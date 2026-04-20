from qgis.PyQt.QtCore import QObject, pyqtSignal, QUrl
from PyQt5.QtWebSockets import QWebSocket
import json

class ChatTransportWs(QObject):
    """
    ChatTransportWs is a QObject that manages a WebSocket connection to a chat server. 
    It handles sending messages, receiving streaming responses, and emitting signals for the ChatInterfaceWidget to update the UI accordingly. 
    It also manages connection state and error handling.
    """
    # Signals to communicate with the ChatInterfaceWidget
    message = pyqtSignal(str)       # streaming chunks
    finished = pyqtSignal()         # message fully received
    error = pyqtSignal(str)         # error messages
    connection_error = pyqtSignal(str)  # separate signal for connection errors
    session_created = pyqtSignal(str)   # emitted with session_id once server confirms session

    def __init__(self, url: str, parent=None):
        """Initialize the WebSocket connection to the given URL."""
        super().__init__(parent)
        self.url = url
        self.ws: QWebSocket = None  # type: ignore
        self.connected = False
        self.queue = []   # pending messages to send
        self.sending = False
        self.cancelled = False

        # Create and connect WebSocket immediately
        self.init_websocket()

    def init_websocket(self):
        """Initialize the WebSocket and connect signals."""
        self.ws = QWebSocket()
        # Connect WebSocket signals to local handler methods
        self.ws.textMessageReceived.connect(self._on_message) # incoming text
        self.ws.error.connect(self._on_error) # connection errors
        self.ws.connected.connect(self._on_connected) # connection established
        self.ws.disconnected.connect(self._on_disconnected) # connection closed
        # Open the WebSocket connection
        self.ws.open(QUrl(self.url))

    def send(self, conversation):
        """Send a conversation to the Kermit."""
        if not conversation:
            return
        query = conversation[-1]["content"]  # Send only the latest user message
        self.queue.append(query)
        self.try_send_next()

    def close(self):
        """Close the WebSocket when plugin is closed"""
        if self.ws:
            self.ws.close()
            self.ws = None
            self.connected = False

    def try_send_next(self):
        """Send next message in queue if connection is ready."""
        if not self.connected or self.sending or not self.queue:
            return
        self.sending = True
        query = self.queue.pop(0)
        request = {
            "type": "query",
            "content": query
        }
        # Send the query as a JSON string
        self.ws.sendTextMessage(json.dumps(request))

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
                # Add extra newline before phase messages
                if m_type == "phase":
                    content = "\n" + content
                self.message.emit(content + "\n")   
        elif msg_type == "response":
            content = event.get("content", "")
            if content:
                self.message.emit(content)
            # Emit finished after response is complete
            self.finished.emit()
            self.finish_sending()
        elif msg_type == "error":
            content = event.get("content", "")
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
        """Handle WebSocket disconnection."""
        self.connected = False

    def _on_error(self, code):
        """Handle WebSocket errors."""
        self.connection_error.emit(f"WebSocket error: {code}")
        self.finish_sending()
