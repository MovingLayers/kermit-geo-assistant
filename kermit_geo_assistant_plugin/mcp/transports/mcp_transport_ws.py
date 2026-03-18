import json

from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from PyQt5.QtWebSockets import QWebSocket
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsMessageLog, Qgis

from ..tools_catalog import QGIS_TOOLS_CATALOG

class McpTransportWs(QObject):
    """MCP transport implementation using WebSockets to communicate with the server on Kermit"""
    # Define signals for connection status and errors
    connected = pyqtSignal()
    disconnected = pyqtSignal()       
    error = pyqtSignal(str)  
    
    def __init__(self, url, execute_command, parent=None):
        """Initialize the WebSocket transport with the backend URL and command execution"""
        super().__init__(parent)
        self.url = url
        self.execute_command = execute_command

        self.client = None
        self.running = False
        self.tools_sent = False

    def connect(self):
        """Connect to server"""
        # Create WebSocket client
        self.client = QWebSocket()
        self.tools_sent = False
        
        # Connect signals
        self.client.connected.connect(self._on_connected)
        self.client.disconnected.connect(self._on_disconnected)
        self.client.error.connect(self._on_error)
        self.client.textMessageReceived.connect(self._on_message_received)
        
        # Connect to backend WebSocket server
        request = QNetworkRequest(QUrl(self.url))
        self.client.open(request)
        self.running = True
        return True

    def disconnect(self):
        """Disconnect from server and clean up resources"""
        self.running = False
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
                        
            # Handle command execution: tools/call
            req_id = message_dict.get("id")
            command = {
                "type": message_dict["params"]["name"],
                "params": message_dict["params"]["input"]
            }
            result = self.execute_command(command)

            # Send the result back to the backend
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }
            if self.client and self.client.isValid():
                self.client.sendTextMessage(json.dumps(response))

        except json.JSONDecodeError:
            QgsMessageLog.logMessage("Invalid JSON received from backend", "GeoAI Assistant",Qgis.Warning)

        except Exception as e:
            QgsMessageLog.logMessage(f"Error processing message: {str(e)}", "GeoAI Assistant", Qgis.Warning)
            
    def _on_connected(self):
        """Handle successful connection to backend"""
        QgsMessageLog.logMessage(f"Connected to backend WebSocket: {self.url}", "GeoAI Assistant")
        self.connected.emit()
    
    def _on_disconnected(self):
        """Handle disconnection from backend"""
        QgsMessageLog.logMessage(f"Disconnected from backend WebSocket: {self.url}", "GeoAI Assistant")
        self.tools_sent = False
        self.disconnected.emit()  

    def _on_error(self, error_code, error_msg=None):
        """Handle WebSocket errors"""
        if error_msg is None:
            error_msg = self.client.errorString() if self.client else "Unknown error"
        QgsMessageLog.logMessage(f"WebSocket error: {error_msg}", "GeoAI Assistant", Qgis.Critical)
        self.error.emit(error_msg)
    