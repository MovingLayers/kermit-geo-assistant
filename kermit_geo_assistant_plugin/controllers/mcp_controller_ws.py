from qgis.PyQt.QtCore import QObject, pyqtSignal, QSettings

from ..mcp.qgis_command_handler import QgisCommandHandler
from ..mcp.transports.mcp_transport_ws import McpTransportWs


class McpControllerWs(QObject):
    """Controller for managing the MCP WebSocket connection and command handling."""
    # Signals to notify about connection status and errors
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, iface, parent=None):
        """Initialize the MCP Controller with the QGIS interface."""
        super().__init__(parent)
        self.iface = iface
        self.settings = QSettings()
        self.qgis_command_handler = None
        self.transport = None

    @property
    def saved_url(self):
        return self.settings.value("geo_ai_assistant/kermit_url", "")

    @property
    def saved_api_key(self):
        return self.settings.value("geo_ai_assistant/kermit_api_key", "")

    def connect(self, url: str, api_key: str):
        """Establish a WebSocket connection to the MCP server on Kermit."""
        # Guard against multiple connections - log and ignore if already connected
        if self.transport:
            return
        
        # Initialize the QGIS command handler
        self.qgis_command_handler = QgisCommandHandler(iface=self.iface, parent=self)

        # Save the URL and API key to settings for future use
        self.settings.setValue("geo_ai_assistant/kermit_url", url)
        self.settings.setValue("geo_ai_assistant/kermit_api_key", api_key)
        
        # Convert the URL to a WebSocket URL and append the API key as a query parameter
        url = url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        url = f"{url}/ws/mcp?api_key={api_key}"

        # Create the transport and pass the qgis_command_handler's execute_command method to it
        self.transport = McpTransportWs(url=url,execute_command=self.qgis_command_handler.execute_command,parent=self)

        # Connect signals for connection status and errors
        self.transport.connected.connect(self.connected)
        self.transport.disconnected.connect(self._on_disconnected)
        self.transport.error.connect(self._on_error)
        self.transport.connect()

    def disconnect(self):
        """Disconnect from the MCP server on Kermit and clean up resources."""
        if not self.transport:
            return
        self.transport.connected.disconnect(self.connected)
        self.transport.disconnected.disconnect(self._on_disconnected)
        self.transport.error.disconnect(self._on_error)
        self.transport.disconnect()
        self.transport = None
        self.qgis_command_handler = None
        self.disconnected.emit()

    def _on_disconnected(self):
        """Handle disconnection events by cleaning up resources and emitting the disconnected signal."""
        self.disconnect()

    def _on_error(self, msg: str):
        """Handle error events by cleaning up resources and emitting the error signal."""
        if not self.transport:
            return
        self.transport.connected.disconnect(self.connected)
        self.transport.disconnected.disconnect(self._on_disconnected)
        self.transport.error.disconnect(self._on_error)
        self.transport.disconnect()
        self.transport = None
        self.qgis_command_handler = None
        self.error.emit(msg)