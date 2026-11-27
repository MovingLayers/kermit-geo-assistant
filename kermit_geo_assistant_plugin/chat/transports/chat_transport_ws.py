from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal, pyqtSlot, QUrl
from PyQt5.QtWebSockets import QWebSocket
import json

from ...network_thread import move_to_network_thread

# A gap between two parts of a reply. A plain blank line shows no gap in the chat bubble (Qt gives
# Markdown paragraphs no spacing), so the gap is a paragraph that holds only a non-breaking space.
GAP = "\n \n\n"

# The signals the worker passes on to the transport (and the transport to the controller)
RELAYED = ("message", "finished", "error", "connection_error", "session_created", "connection_lost")


class ChatSocketWorker(QObject):
    """
    The chat WebSocket. It lives in the network thread (see network_thread.py), so the socket answers
    the pings of the server while the QGIS main thread is busy. It handles sending messages, receiving
    streaming responses and the connection state, and reports to the transport through signals.
    """
    message = pyqtSignal(str)       # streaming chunks
    finished = pyqtSignal()         # message fully received
    error = pyqtSignal(str)         # error messages
    connection_error = pyqtSignal(str)  # separate signal for connection errors
    session_created = pyqtSignal(str)   # emitted with session_id once server confirms session
    connection_lost = pyqtSignal()      # an established connection was closed by the server or the network

    def __init__(self):
        super().__init__()
        self.ws: QWebSocket = None  # type: ignore
        self.connected = False
        self.closing = False   # the plugin closes the socket itself: its disconnect is no loss
        self.has_session = False   # the server confirmed a session: only then a close is a lost connection
        self.queue = []   # pending messages to send
        self.sending = False
        self.cancelled = False
        self.status_shown = False   # status lines were printed in the reply that is streaming

    @pyqtSlot(str)
    def open_socket(self, url: str):
        """Create the WebSocket in this thread, connect its signals and open it."""
        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(self._on_message) # incoming text
        self.ws.error.connect(self._on_error) # connection errors
        self.ws.connected.connect(self._on_connected) # connection established
        self.ws.disconnected.connect(self._on_disconnected) # connection closed
        self.ws.open(QUrl(url))

    @pyqtSlot(object)
    def enqueue(self, request: dict):
        """Queue a request and send it when the connection is ready and no reply is pending."""
        self.queue.append(request)
        self.try_send_next()

    @pyqtSlot()
    def close(self):
        """Close the WebSocket when the connection is closed on purpose."""
        self.closing = True
        if self.ws:
            self.ws.close()
            self.ws = None
        self.connected = False
        self.deleteLater()

    def try_send_next(self):
        """Send next message in queue if connection is ready."""
        if not self.connected or self.sending or not self.queue:
            return
        self.sending = True
        request = self.queue.pop(0)
        # Send the request as a JSON string
        self.ws.sendTextMessage(json.dumps(request))

    @pyqtSlot()
    def cancel(self):
        """Cancel the current message and clear the queue."""
        self.cancelled = True
        self.queue.clear()

    def finish_sending(self):
        """Mark current message as finished and send next if any."""
        self.sending = False
        self.try_send_next()

    def _on_message(self, text: str):
        """Handle incoming WebSocket messages, which are expected to be JSON with a 'type' field."""
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            self.error.emit(f"Invalid JSON: {text}")
            self.finish_sending()
            return

        # Determine message type
        msg_type = event.get("type")

        # If cancelled, ignore all messages until response/error to reset state
        if self.cancelled:
            # drain the stream silently, reset when it ends
            if msg_type in ("response", "error"):
                self.cancelled = False
                self.finish_sending()
            return

        # Handle different message types accordingly
        if msg_type == "session_created":
            self.has_session = True
            self.session_created.emit(event.get("session_id", ""))
            return
        elif msg_type == "status":
            content = event.get("content", "")
            if content:
                self.message.emit(content + "\n")
        elif msg_type == "user_status":
            message = event["data"]["message"]
            icon = event["data"]["icon"]
            m_type = event["data"]["type"] # phase, detail, decision
            # Format the status message with icon
            if message:
                content = f"{icon} {message}" if icon else message
                # A gap before phase messages
                if m_type == "phase":
                    content = GAP + content
                self.message.emit(content + "\n")
                self.status_shown = True
        elif msg_type == "response":
            content = event.get("content", "")
            if content:
                # A gap between the status lines and the reply
                self.message.emit(GAP + content if self.status_shown else content)
            self.status_shown = False
            # Emit finished after response is complete
            self.finished.emit()
            self.finish_sending()
        elif msg_type == "error":
            content = event.get("content", "")
            self.status_shown = False
            self.error.emit(content)
            self.finish_sending()
        else:
            # Ignore unknown message types silently
            pass

    def _on_connected(self):
        """Handle WebSocket connection established."""
        self.connected = True
        self.try_send_next()  # send any queued message

    def _on_disconnected(self):
        """Handle WebSocket disconnection. A close that was not asked for resets the send state and reports the loss."""
        self.connected = False
        if self.closing or not self.has_session:
            return  # closed on purpose, or refused before a session existed (the error message says why)
        self.sending = False
        self.cancelled = False
        self.status_shown = False
        self.queue.clear()
        self.connection_lost.emit()

    def _on_error(self, code):
        """Handle WebSocket errors."""
        self.connection_error.emit(f"WebSocket error: {code}")
        self.finish_sending()


class ChatTransportWs(QObject):
    """
    The chat connection as the controller uses it. The socket itself lives in the network thread
    (ChatSocketWorker); this object stays in the main thread, passes requests to the worker through
    queued signals and relays what the worker reports.
    """
    # Signals to communicate with the ChatInterfaceWidget
    message = pyqtSignal(str)       # streaming chunks
    finished = pyqtSignal()         # message fully received
    error = pyqtSignal(str)         # error messages
    connection_error = pyqtSignal(str)  # separate signal for connection errors
    session_created = pyqtSignal(str)   # emitted with session_id once server confirms session
    connection_lost = pyqtSignal()      # an established connection was closed by the server or the network

    # Requests to the worker
    _open = pyqtSignal(str)
    _enqueue = pyqtSignal(object)
    _cancel = pyqtSignal()
    _close = pyqtSignal()

    def __init__(self, url: str, parent=None):
        """Create the worker in the network thread and open the connection to the given URL."""
        super().__init__(parent)
        self.url = url
        self._closed = False
        self.worker = ChatSocketWorker()
        move_to_network_thread(self.worker)
        for name in RELAYED:
            getattr(self.worker, name).connect(getattr(self, name), Qt.QueuedConnection)
        self._open.connect(self.worker.open_socket, Qt.QueuedConnection)
        self._enqueue.connect(self.worker.enqueue, Qt.QueuedConnection)
        self._cancel.connect(self.worker.cancel, Qt.QueuedConnection)
        self._close.connect(self.worker.close, Qt.QueuedConnection)
        self._open.emit(url)

    def send(self, conversation):
        """Send a conversation to the Kermit."""
        if not conversation or self._closed:
            return
        query = conversation[-1]["content"]  # Send only the latest user message
        self._enqueue.emit({"type": "query", "content": query})

    def send_files_attached(self):
        """Tell Kermit that files were attached and no text was sent."""
        if not self._closed:
            self._enqueue.emit({"type": "files_attached"})

    def cancel(self):
        """Cancel the current message and clear the queue."""
        if not self._closed:
            self._cancel.emit()

    def close(self):
        """Close the connection on purpose. What the worker still reports is dropped."""
        if self._closed:
            return
        self._closed = True
        self._close.emit()
        for name in RELAYED:
            try:
                getattr(self, name).disconnect()
            except TypeError:
                pass  # no receiver
