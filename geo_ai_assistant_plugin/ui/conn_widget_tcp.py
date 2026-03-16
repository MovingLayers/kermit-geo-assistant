from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget, QSizePolicy, QLineEdit, QFormLayout
from qgis.PyQt.QtGui import QIcon

from ..chat.transports.chat_transport_http import ChatConnectionTester

class ConnWidgetTcp(QWidget):
    """Widget for managing TCP connection to the MCP server."""

    # Icons for show/hide API key
    HIDE_ICON = ":/images/themes/default/mActionHideAllLayers.svg"
    SHOW_ICON = ":/images/themes/default/mActionShowAllLayers.svg"

    def __init__(self, controller, chat_controller, parent=None):
        """Initialize the connection widget."""
        super().__init__(parent)

        # Controllers and their signals to update the UI
        self.controller = controller
        self.controller.connected.connect(self._on_connected)
        self.controller.disconnected.connect(self._on_disconnected)
        self.chat_controller = chat_controller
        self.chat_controller.error.connect(self._on_error)

        # Tester thread for validating connection parameters
        self.tester = None

        self.setup_ui()

    def setup_ui(self):
        """Set up the user interface."""

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Main layout
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Input fields for connection parameters
        self.url_input = QLineEdit(self.controller.saved_url)
        self.url_input.setPlaceholderText("Enter url (e.g., http://localhost:1234)")

        self.api_key_input = QLineEdit(self.controller.saved_api_key)
        self.api_key_input.setPlaceholderText("Enter API key for authentication")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_hide_action = self.api_key_input.addAction(QIcon(self.HIDE_ICON), QLineEdit.TrailingPosition)
        self.api_key_hide_action.setCheckable(True)
        self.api_key_hide_action.toggled.connect(self.set_api_key_visibility)

        self.model_input = QLineEdit(self.controller.saved_model)
        self.model_input.setPlaceholderText("Enter model name (e.g., liquid/lfm2.5-1.2b)")

        self.mcp_tools_input = QLineEdit(self.controller.saved_mcp_tools)
        self.mcp_tools_input.setPlaceholderText("Enter tool integration string (e.g., mcp/qgis)")

        self.port_spin = QSpinBox()
        self.port_spin.setMinimum(1024)
        self.port_spin.setMaximum(65535)
        self.port_spin.setValue(self.controller.saved_port)

        # Connect/Disconnect button
        self.start_button = QPushButton("Connect")
        self.start_button.clicked.connect(self.toggle_connection)

        # Status label
        self.status_label = QLabel("Status: Disconnected")

        # Layout for credential inputs
        form_layout = QFormLayout()
        form_layout.addRow("URL:", self.url_input)
        form_layout.addRow("API Key:", self.api_key_input)
        form_layout.addRow("Model:", self.model_input)
        form_layout.addRow("MCP tools:", self.mcp_tools_input)

        # Layout for connection controls
        conn_layout = QHBoxLayout()
        conn_layout.addWidget(QLabel("Port:"))
        conn_layout.addWidget(self.port_spin)
        conn_layout.addWidget(self.start_button)

        # Add all layouts to the main layout
        layout.addLayout(form_layout)
        layout.addLayout(conn_layout)
        layout.addWidget(self.status_label)
        layout.addStretch()

    def set_api_key_visibility(self, visible):
        """Toggle the visibility of the API key input."""
        self.api_key_input.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.api_key_hide_action.setIcon(QIcon(self.SHOW_ICON if visible else self.HIDE_ICON))

    def toggle_connection(self):
        """Handle connect/disconnect button click."""
        if self.start_button.text() == "Disconnect":
            self.controller.disconnect()
        else:
            # Get input values
            url = self.url_input.text().strip()
            api_key = self.api_key_input.text().strip()
            model = self.model_input.text().strip()
            mcp_tools = self.mcp_tools_input.text().strip()
            port = self.port_spin.value()

            # Basic validation
            if not url or not api_key or not model or not mcp_tools:
                self._on_error("All fields are required.")
                return

            # Test the connection parameters
            self.tester = ChatConnectionTester(url, api_key, model, mcp_tools, parent=self)
            self.tester.success.connect(lambda: self._on_test_success(url, api_key, model, mcp_tools, port))
            self.tester.error.connect(self._on_error)
            self.status_label.setText("Status: Testing connection...")
            self.start_button.setEnabled(False)
            self.tester.start()

    def disconnect(self):
        """Called by dock_widget on close."""
        self.controller.disconnect()
        self.chat_controller.close()

    def _on_test_success(self, url, api_key, model, mcp_tools, port):
        """Called when connection test succeeds."""
        self.tester = None
        self.start_button.setEnabled(True)
        self.controller.connect(url, api_key, model, mcp_tools, port)
        self.chat_controller.connect(url, api_key, model, mcp_tools) 

    def _on_error(self, msg: str):
        """Called when an error occurs during connection testing."""
        self.tester = None
        self.status_label.setText(f"Status: Error — {msg}")
        self.start_button.setText("Connect")
        self.start_button.setEnabled(True)
        self.set_fields_enabled(True)

    def _on_connected(self, port: int):
        """Called when successfully connected to the MCP server."""
        self.status_label.setText(f"Status: Connected on port {port}")
        self.start_button.setText("Disconnect")
        self.set_fields_enabled(False)

    def _on_disconnected(self):
        """Called when disconnected from the MCP server."""
        self.status_label.setText("Status: Disconnected")
        self.start_button.setText("Connect")
        self.set_fields_enabled(True)

    def set_fields_enabled(self, enabled: bool):
        """Enable or disable input fields based on connection status."""
        self.port_spin.setEnabled(enabled)
        self.url_input.setEnabled(enabled)
        self.api_key_input.setEnabled(enabled)
        self.api_key_hide_action.setEnabled(enabled)
        self.model_input.setEnabled(enabled)
        self.mcp_tools_input.setEnabled(enabled)