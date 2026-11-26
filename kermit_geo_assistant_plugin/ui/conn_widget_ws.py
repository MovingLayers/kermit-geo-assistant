from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtWidgets import QVBoxLayout, QLabel, QPushButton, QLineEdit, QWidget, QSizePolicy, QFormLayout
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon

# Shown when the server or the network closed the connection and the user did not ask for it.
# A new connection is a new session: attached files and a run in progress are gone.
CONNECTION_LOST_TEXT = "Verbindung zum Server verloren. Bitte neu verbinden."

class ConnWidgetWs(QWidget):
    """
    Widget for managing WebSocket connection to Kermit. 
    Contains fields for URL and API key, and a button to connect/disconnect."""

    # Icons for show/hide API key
    HIDE_ICON = ":/images/themes/default/mActionHideAllLayers.svg"
    SHOW_ICON = ":/images/themes/default/mActionShowAllLayers.svg"

    def __init__(self, controller, chat_controller, parent=None):
        """Initialize the connection widget."""
        super().__init__(parent)

        # Controllers for managing connection and chat, and their signals
        self.controller = controller
        self.chat_controller = chat_controller
        self._pending_url = ""
        self._pending_api_key = ""
        self._closing = False   # both connections are being closed on purpose
        self.controller.connected.connect(self._on_connected)
        self.controller.disconnected.connect(self._on_disconnected)
        self.controller.error.connect(self._on_mcp_error)
        self.chat_controller.connection_error.connect(self._on_error)
        self.chat_controller.connection_lost.connect(self._on_connection_lost)
        self.chat_controller.session_created.connect(self._on_session_created)

        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface elements."""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # URL input field
        self.url_input = QLineEdit(self.controller.saved_url)
        self.url_input.setPlaceholderText("Enter url (e.g., http://localhost:8000)")

        # API key input field with show/hide functionality
        self.api_key_input = QLineEdit(self.controller.saved_api_key)
        self.api_key_input.setPlaceholderText("Enter API key for authentication")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_hide_action = self.api_key_input.addAction(QIcon(self.HIDE_ICON), QLineEdit.TrailingPosition)
        self.api_key_hide_action.setCheckable(True)
        self.api_key_hide_action.toggled.connect(self.set_api_key_visibility)

        # Connect/Disconnect button
        self.start_button = QPushButton("Connect")
        self.start_button.clicked.connect(self.toggle_connection)

        # Status label to show connection status
        self.status_label = QLabel("Status: Disconnected")

        # Layout for Iinput fields
        form_layout = QFormLayout()
        form_layout.addRow("URL:", self.url_input)
        form_layout.addRow("API Key:", self.api_key_input)

        # Add all widgets to the main layout
        layout.addLayout(form_layout)
        layout.addWidget(self.start_button)
        layout.addWidget(self.status_label)

    def set_api_key_visibility(self, visible):
        """Toggle the visibility of the API key in the input field."""
        self.api_key_input.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.api_key_hide_action.setIcon(QIcon(self.SHOW_ICON if visible else self.HIDE_ICON))

    def toggle_connection(self):
        """Connect or disconnect based on the current state of the connection."""
        if self.start_button.text() == "Disconnect":
            self._close_both()
        else:
            # Store credentials so _on_session_created can connect MCP once the
            # server sends back the session_id via the chat WebSocket.
            self._pending_url = self.url_input.text()
            self._pending_api_key = self.api_key_input.text()
            self.chat_controller.connect(self._pending_url, self._pending_api_key)

    def _on_session_created(self, session_id: str):
        """Called once the chat WebSocket receives the server-assigned session_id.
        Now connect the MCP WebSocket with the session_id so the server can link them."""
        self.controller.connect(self._pending_url, self._pending_api_key, session_id)

    def disconnect(self):
        """Called by dock_widget on close."""
        self._close_both()

    def _close_both(self):
        """Close the QGIS connection and the chat connection on purpose."""
        self._closing = True
        try:
            self.controller.disconnect()
            self.chat_controller.close()
        finally:
            self._closing = False

    def _on_connection_lost(self):
        """The chat connection was closed by the server or the network: close the rest and say so.
        Deferred, because the chat socket is still inside its own disconnect signal."""
        QTimer.singleShot(0, self._handle_connection_lost)

    def _handle_connection_lost(self, text=CONNECTION_LOST_TEXT):
        """Close both connections, so the chat shows the disconnected state, and show the reason."""
        if self.chat_controller.transport is None:
            return  # already closed
        self._close_both()
        self._on_error(text)

    def _on_mcp_error(self, msg):
        """The QGIS connection failed: the chat connection is of no use without it, close it too."""
        self._on_error(msg)
        if not self._closing and self.chat_controller.transport is not None:
            QTimer.singleShot(0, lambda: self._handle_connection_lost(msg))

    def _on_connected(self):
        """Called when successfully connected to the Kermit."""
        self.status_label.setText("Status: Connected to Kermit")
        self.start_button.setText("Disconnect")
        self.set_fields_enabled(False)

    def _on_disconnected(self):
        """Called when disconnected from the Kermit."""
        self.status_label.setText("Status: Disconnected")
        self.start_button.setText("Connect")
        self.set_fields_enabled(True)
        if not self._closing and self.chat_controller.transport is not None:
            # The QGIS connection closed while the chat connection is still open
            QTimer.singleShot(0, self._handle_connection_lost)

    def _on_error(self, msg):
        """Called when there is an error in connection."""
        self.status_label.setText(f"Status: Error — {msg}")
        self.start_button.setText("Connect")
        self.set_fields_enabled(True)

    def set_fields_enabled(self, enabled: bool):
        """Enable or disable input fields and buttons based on connection status."""
        self.url_input.setEnabled(enabled)
        self.api_key_input.setEnabled(enabled)
        self.api_key_hide_action.setEnabled(enabled)