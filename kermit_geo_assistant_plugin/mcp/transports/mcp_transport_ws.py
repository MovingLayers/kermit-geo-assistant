import json

from qgis.PyQt.QtCore import QObject, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtWebSockets import QWebSocket
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsMessageLog, Qgis

from ...network_thread import move_to_network_thread
from ..tools_catalog import QGIS_TOOLS_CATALOG

# The signals the worker passes on to the transport
RELAYED = ("connected", "disconnected", "error")


class McpSocketWorker(QObject):
    """
    The WebSocket to the QGIS side of Kermit. It lives in the network thread (see network_thread.py), so
    the socket answers the pings of the server while the QGIS main thread runs a long command. It sends
    the tools catalog itself and hands every command to the main thread; the result comes back through
    send_result.
    """
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    command_requested = pyqtSignal(object, object)   # request id, command: to be run by the main thread

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.log_url = url.split("?", 1)[0]  # the query holds the API key and the session id: never logged
        self.client = None
        self.tools_sent = False

    @pyqtSlot()
    def start(self):
        """Create the WebSocket in this thread, connect its signals and open it."""
        self.client = QWebSocket()
        self.tools_sent = False

        self.client.connected.connect(self._on_connected)
        self.client.disconnected.connect(self._on_disconnected)
        self.client.error.connect(self._on_error)
        self.client.textMessageReceived.connect(self._on_message_received)

        request = QNetworkRequest(QUrl(self.url))
        self.client.open(request)

    @pyqtSlot()
    def stop(self):
        """Close the connection and clean up resources"""
        if self.client:
            client = self.client
            self.client = None
            # Disconnect all client signals first to prevent re-entrant callbacks
            client.connected.disconnect()
            client.disconnected.disconnect()
            client.error.disconnect()
            client.textMessageReceived.disconnect()
            client.close()
            client.deleteLater()
        self.deleteLater()

    @pyqtSlot(object, object)
    def send_result(self, req_id, result):
        """Send the result of a command back to the backend"""
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result
        }
        if self.client and self.client.isValid():
            self.client.sendTextMessage(json.dumps(response))

    def _send_tools(self, message: dict):
        """Send the initial tools/list message to backend"""
        # Guard against duplicate tools/list messages - log and ignore if already sent
        if self.tools_sent:
            QgsMessageLog.logMessage("Tools already sent, ignoring duplicate tools/list", "GeoAI Assistant", Qgis.Warning)
            return

        # Validate that the message is the expected tools/list request
        if message.get("method") != "tools/list":
            raise ValueError("Expected tools/list request")

        # Send the list of available tools back to the backend
        id = message.get("id")
        response = {
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "tools": QGIS_TOOLS_CATALOG
            }
        }
        if self.client and self.client.isValid():
            self.client.sendTextMessage(json.dumps(response))
        self.tools_sent = True
        QgsMessageLog.logMessage("Tools catalog sent", "GeoAI Assistant")

    def _on_message_received(self, message):
        """Process incoming message from backend"""
        try:
            message_dict = json.loads(message)

            # Handle error message
            if message_dict.get("error") is not None:
                msg = message_dict["error"].get("message", "Unknown error from server")
                self._on_error(None, msg)
                return

            # Send tools catalog: tools/list
            if not self.tools_sent:
                self._send_tools(message_dict)
                return

            # After tools catalog is sent, only support tools/call method - validate and process
            if message_dict.get("method") != "tools/call":
                raise ValueError(f"Unsupported method: {message_dict.get('method')}")

            # Handle command execution: tools/call. The main thread runs it, QGIS objects live there.
            req_id = message_dict.get("id")
            command = {
                "type": message_dict["params"]["name"],
                "params": message_dict["params"]["input"]
            }
            self.command_requested.emit(req_id, command)

        except json.JSONDecodeError:
            QgsMessageLog.logMessage("Invalid JSON received from backend", "GeoAI Assistant",Qgis.Warning)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error processing message: {str(e)}", "GeoAI Assistant", Qgis.Warning)

    def _on_connected(self):
        """Handle successful connection to backend"""
        QgsMessageLog.logMessage(f"Connected to backend WebSocket: {self.log_url}", "GeoAI Assistant")
        self.connected.emit()

    def _on_disconnected(self):
        """Handle disconnection from backend"""
        QgsMessageLog.logMessage(f"Disconnected from backend WebSocket: {self.log_url}", "GeoAI Assistant")
        self.tools_sent = False
        self.disconnected.emit()

    def _on_error(self, error_code, error_msg=None):
        """Handle WebSocket errors"""
        if error_msg is None:
            error_msg = self.client.errorString() if self.client else "Unknown error"
        QgsMessageLog.logMessage(f"WebSocket error: {error_msg}", "GeoAI Assistant", Qgis.Critical)
        self.error.emit(error_msg)


class McpTransportWs(QObject):
    """
    MCP transport implementation using WebSockets to communicate with the server on Kermit.
    The socket lives in the network thread (McpSocketWorker). This object stays in the main thread:
    it runs the commands of the server there, because QGIS only allows its objects to be used in the
    main thread, and it relays the connection signals.
    """
    # Define signals for connection status and errors
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    # Requests to the worker
    _start = pyqtSignal()
    _stop = pyqtSignal()
    _result = pyqtSignal(object, object)

    def __init__(self, url, execute_command, parent=None):
        """Initialize the WebSocket transport with the backend URL and command execution"""
        super().__init__(parent)
        self.url = url
        self.execute_command = execute_command
        self.running = False

        self.worker = McpSocketWorker(url)
        move_to_network_thread(self.worker)
        for name in RELAYED:
            getattr(self.worker, name).connect(getattr(self, name), Qt.QueuedConnection)
        self.worker.command_requested.connect(self._run_command, Qt.QueuedConnection)
        self._start.connect(self.worker.start, Qt.QueuedConnection)
        self._stop.connect(self.worker.stop, Qt.QueuedConnection)
        self._result.connect(self.worker.send_result, Qt.QueuedConnection)

    def connect(self):
        """Connect to server"""
        self.running = True
        self._start.emit()
        return True

    def disconnect(self):
        """Disconnect from server and clean up resources"""
        self.running = False
        self._stop.emit()
        for name in RELAYED:
            try:
                getattr(self, name).disconnect()
            except TypeError:
                pass  # no receiver

    def _run_command(self, req_id, command):
        """Run a command of the server in the main thread and send its result back."""
        if not self.running:
            return
        try:
            result = self.execute_command(command)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error processing message: {str(e)}", "GeoAI Assistant", Qgis.Warning)
            return
        self._result.emit(req_id, result)
