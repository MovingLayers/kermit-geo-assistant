from urllib.parse import quote

from qgis.PyQt.QtCore import QObject, pyqtSignal, QSettings

from ..chat.file_upload import AllowedTypesFetcher, FileUploader
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
    connection_lost = pyqtSignal()  # an established connection was closed without the user asking (ws transport only)
    notice = pyqtSignal(str)  # a message of the plugin itself for the chat, e.g. after a restored connection
    connected = pyqtSignal() # emitted when connection is established
    disconnected = pyqtSignal() # emitted when connection is closed
    session_created = pyqtSignal(str)  # emitted with server-assigned session_id (ws transport only)
    allowed_types = pyqtSignal(list)  # file extensions the server accepts; emitted after session_created
    allowed_types_failed = pyqtSignal(str)
    upload_done = pyqtSignal(dict)  # file path -> error message; empty when all files were stored

    def __init__(self, transport_type: str, parent=None):
        """Initialize the controller with the specified transport type."""
        super().__init__(parent)
        self.transport_type = transport_type
        self.settings = QSettings()
        self.conversation = []
        self.transport = None
        self.base_url = ""
        self.api_key = ""
        self.session_id = ""
        self.types_worker = None
        self.upload_worker = None

    def send(self, user_text: str):
        """Called by the widget when the user submits a message. Appends the user message to the conversation and sends it via the transport."""
        self.conversation.append({"role": "user", "content": user_text})
        if self.transport is not None:
            self.transport.send(self.conversation)

    def send_files_attached(self, names: list):
        """Called by the widget when files were attached without a text."""
        self.conversation.append({"role": "user", "content": "Angehängt: " + ", ".join(names)})
        if self.transport is not None and hasattr(self.transport, "send_files_attached"):
            self.transport.send_files_attached()

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

    def upload_files(self, paths: list):
        """Upload the files to the session; upload_done reports the failures."""
        self.upload_worker = FileUploader(self.base_url, self.api_key, self.session_id, paths, parent=self)
        self.upload_worker.done.connect(self.upload_done)
        self.upload_worker.start()

    def on_session_created(self, session_id: str):
        """Remember the session and ask the server which file types it accepts."""
        self.session_id = session_id
        self.types_worker = AllowedTypesFetcher(self.base_url, self.api_key, parent=self)
        self.types_worker.fetched.connect(self.allowed_types)
        self.types_worker.failed.connect(self.allowed_types_failed)
        self.types_worker.start()

    def close(self):
        """Clean up transport on plugin unload."""
        self.session_id = ""
        if self.transport is not None and self.transport_type == 'ws':
            self.transport.close()
        self.transport = None
        self.disconnected.emit()

    def connect(self, url: str, api_key: str, model: str = "", mcp_tools: str = ""):
        """Called by the widget when the user clicks Connect. Cleans up any existing transport and creates a new one based on the specified transport type and URL."""
        self.close()
        self.base_url = url.rstrip("/")
        self.api_key = api_key
        if self.transport_type == 'ws':
            url = url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
            self.transport = ChatTransportWs(url=f"{url}/chat?api_key={quote(api_key, safe='')}", parent=self)
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
            self.transport.connection_lost.connect(self.connection_lost)
            self.transport.session_created.connect(self.session_created)
            self.transport.session_created.connect(self.on_session_created)