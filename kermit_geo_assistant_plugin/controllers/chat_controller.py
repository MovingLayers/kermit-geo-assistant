from qgis.PyQt.QtCore import QObject, pyqtSignal, QSettings

from ..chat.transports.chat_transport_http import ChatTransportHttp
from ..chat.transports.chat_transport_ws import ChatTransportWs


class ChatController(QObject):
    """
    Controller for managing chat state and transport. 
    The transport is created on demand when the user clicks Connect, and is cleaned up when the plugin is unloaded or when a new connection is made."""
    # Signals to communicate with the widget
    message = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    connection_error = pyqtSignal(str)
    connected = pyqtSignal() # emitted when connection is established
    disconnected = pyqtSignal() # emitted when connection is closed
    session_created = pyqtSignal(str)  # emitted with server-assigned session_id (ws transport only)

    def __init__(self, transport_type: str, parent=None):
        """Initialize the controller with the specified transport type."""
        super().__init__(parent)
        self.transport_type = transport_type
        self.settings = QSettings()
        self.conversation = []
        self.transport = None

    def send(self, user_text: str):
        """Called by the widget when the user submits a message. Appends the user message to the conversation and sends it via the transport."""
        self.conversation.append({"role": "user", "content": user_text})
        if self.transport is not None:
            self.transport.send(self.conversation)

    def add_assistant_reply(self, text: str):
        """Called by the widget once a full response has been streamed."""
        self.conversation.append({"role": "assistant", "content": text})

    def cancel(self):
        """Called by the widget when the user cancels the current message."""
        if self.transport is not None:
            self.transport.cancel()
        # Roll back the user message whose response was cancelled
        if self.conversation and self.conversation[-1]["role"] == "user":
            self.conversation.pop()
    
    def clear_conversation(self):
        """Called by the widget to clear the conversation history."""
        self.conversation.clear()

    def close(self):
        """Clean up transport on plugin unload."""
        if self.transport is not None and self.transport_type == 'ws':
            self.transport.close()
        self.transport = None
        self.disconnected.emit()

    def connect(self, url: str, api_key: str, model: str = "", mcp_tools: str = ""):
        """Called by the widget when the user clicks Connect. Cleans up any existing transport and creates a new one based on the specified transport type and URL."""
        self.close()
        if self.transport_type == 'ws':
            url = url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
            self.transport = ChatTransportWs(url=f"{url}/chat?api_key={api_key}", parent=self)
        else:
            self.transport = ChatTransportHttp(url, api_key, model, mcp_tools, parent=self)
        self.wire_transport()
        self.connected.emit()

    def wire_transport(self):
        """Connect transport signals to controller signals."""
        self.transport.message.connect(self.message)
        self.transport.finished.connect(self.finished)
        self.transport.error.connect(self.error)
        self.transport.connection_error.connect(self.connection_error)
        if self.transport_type == 'ws':
            self.transport.session_created.connect(self.session_created)