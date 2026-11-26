from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtWidgets import QVBoxLayout, QLabel, QPushButton, QLineEdit, QWidget, QSizePolicy, QFormLayout
import time

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon

# Shown when the server or the network closed the connection and the user did not ask for it.
# A new connection is a new session: attached files and a run in progress are gone.
CONNECTION_LOST_TEXT = "Verbindung zum Server verloren. Bitte neu verbinden."
RECONNECTING_TEXT = "Verbindung verloren. Verbindung wird wiederhergestellt …"
RECONNECTED_TEXT = "Verbindung wiederhergestellt. Die bisherige Unterhaltung ist beendet. Bitte schreiben Sie Ihre Anfrage erneut."
RECONNECT_FAILED_TEXT = "Verbindung zum Server verloren. Die Wiederherstellung ist fehlgeschlagen. Bitte neu verbinden."

# A lost connection is restored in a few attempts, and only when it had held for a while: a server that
# closes every new connection at once must not make the plugin loop. The pauses before the attempts grow
# (2, 5, 10 and 20 s: a restart of the server is covered); an attempt gives up after the timeout.
MIN_CONNECTED_SECONDS = 10
RECONNECT_DELAYS_MS = (2000, 5000, 10000, 20000)
RECONNECT_TIMEOUT_MS = 15000

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
        self._reconnecting = False   # one automatic attempt to restore a lost connection is running
        self._attempt = 0   # counts attempts, so an old timeout does not stop a newer one
        self._tries = 0   # attempts made in the running reconnect
        self._generation = 0   # counts the closings of the connections: a loss report of an old connection is stale
        self._connected_at = None   # when the QGIS connection came up (monotonic seconds)
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
            self._user_close()
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
        self._user_close()

    def _user_close(self):
        """The user closed the connection: no reconnect attempt is pending any more."""
        was_reconnecting = self._reconnecting
        self._reconnecting = False
        self._attempt += 1
        self._close_both()
        if was_reconnecting:
            # The QGIS connection was not up yet, so it sent no disconnect signal to reset the widget
            self.status_label.setText("Status: Disconnected")
            self.start_button.setText("Connect")
            self.set_fields_enabled(True)

    def _close_both(self):
        """Close the QGIS connection and the chat connection on purpose."""
        self._closing = True
        self._generation += 1
        self._connected_at = None
        try:
            self.controller.disconnect()
            self.chat_controller.close()
        finally:
            self._closing = False

    def _on_connection_lost(self):
        """The chat connection was closed by the server or the network: close the rest and say so.
        Deferred, because the chat socket is still inside its own disconnect signal."""
        self._schedule_connection_lost()

    def _schedule_connection_lost(self, text=None):
        """Handle a lost connection right after the current signal. The server usually closes the chat and
        the QGIS connection together, so two reports come in for one loss: the first one is handled, the
        second one finds the connections closed again (or already restored) and is dropped."""
        generation = self._generation
        QTimer.singleShot(0, lambda: self._handle_connection_lost(text, generation))

    def _handle_connection_lost(self, text=None, generation=None):
        """The connection closed without the user asking: close both connections, so the chat shows the
        disconnected state, then try to connect again, or show the reason."""
        if generation is not None and generation != self._generation:
            return  # stale: a loss of a connection that was closed since
        if self.chat_controller.transport is None:
            return  # already closed
        was_up = self._connected_at is not None and time.monotonic() - self._connected_at >= MIN_CONNECTED_SECONDS
        retry = was_up and text is None and not self._reconnecting and bool(self._pending_url)
        self._close_both()
        if retry:
            self._start_reconnect()
        else:
            self._fail(text or CONNECTION_LOST_TEXT)

    def _start_reconnect(self):
        """Connect again with the credentials of the last connection, in up to four attempts."""
        self._reconnecting = True
        self._tries = 0
        self._next_attempt()

    def _next_attempt(self):
        """Wait, then connect again; the pause grows with every attempt."""
        delay = RECONNECT_DELAYS_MS[self._tries]
        self._tries += 1
        self._attempt += 1
        attempt = self._attempt
        self.status_label.setText(f"Status: {RECONNECTING_TEXT} (Versuch {self._tries} von {len(RECONNECT_DELAYS_MS)})")
        self.start_button.setText("Disconnect")
        self.set_fields_enabled(False)
        QTimer.singleShot(delay, lambda: self._try_connect(attempt))

    def _try_connect(self, attempt):
        """Connect again. It is a new session. Nothing happens when the user closed the connection meanwhile."""
        if not self._reconnecting or attempt != self._attempt:
            return
        self.chat_controller.connect(self._pending_url, self._pending_api_key)
        QTimer.singleShot(RECONNECT_TIMEOUT_MS, lambda: self._reconnect_timeout(attempt))

    def _reconnect_timeout(self, attempt):
        """Give up when the attempt did not finish in time."""
        if self._reconnecting and attempt == self._attempt:
            self._fail("")

    def _fail(self, text):
        """End the connection with an error. During a reconnect the next attempt follows; after the last one
        the widget says that the restore failed instead of the single cause."""
        reconnecting = self._reconnecting
        self._attempt += 1   # the timeout of the failed attempt does not count any more
        if self.chat_controller.transport is not None:
            self._close_both()
        if reconnecting and self._tries < len(RECONNECT_DELAYS_MS):
            self._next_attempt()
            return
        self._reconnecting = False
        self._show_error(RECONNECT_FAILED_TEXT if reconnecting else text)

    def _on_mcp_error(self, msg):
        """The QGIS connection failed: the chat connection is of no use without it, close it too."""
        if self._reconnecting:
            self._fail(msg)
            return
        self._show_error(msg)
        if not self._closing and self.chat_controller.transport is not None:
            self._schedule_connection_lost(msg)

    def _on_connected(self):
        """Called when successfully connected to the Kermit."""
        self._connected_at = time.monotonic()
        self.status_label.setText("Status: Connected to Kermit")
        self.start_button.setText("Disconnect")
        self.set_fields_enabled(False)
        if self._reconnecting:
            # The lost connection is restored; the chat says that the session is a new one
            self._reconnecting = False
            self._attempt += 1
            self.chat_controller.notice.emit(RECONNECTED_TEXT)

    def _on_disconnected(self):
        """Called when disconnected from the Kermit."""
        self.status_label.setText("Status: Disconnected")
        self.start_button.setText("Connect")
        self.set_fields_enabled(True)
        if not self._closing and self.chat_controller.transport is not None:
            # The QGIS connection closed while the chat connection is still open
            self._schedule_connection_lost()

    def _on_error(self, msg):
        """Called when the chat connection reports an error."""
        if self._reconnecting:
            self._fail(msg)
            return
        self._show_error(msg)

    def _show_error(self, msg):
        """Show an error in the status line and offer Connect again."""
        self.status_label.setText(f"Status: Error — {msg}")
        self.start_button.setText("Connect")
        self.set_fields_enabled(True)

    def set_fields_enabled(self, enabled: bool):
        """Enable or disable input fields and buttons based on connection status."""
        self.url_input.setEnabled(enabled)
        self.api_key_input.setEnabled(enabled)
        self.api_key_hide_action.setEnabled(enabled)