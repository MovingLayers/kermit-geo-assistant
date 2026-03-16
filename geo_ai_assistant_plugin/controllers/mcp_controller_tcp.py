from qgis.PyQt.QtCore import QObject, pyqtSignal, QSettings

from ..mcp.qgis_command_handler import QgisCommandHandler
from ..mcp.transports.mcp_transport_tcp import McpTransportTcp

class McpControllerTcp(QObject):
    """Controller for managing MCP connection over TCP."""
    # Signals to notify about connection status changes
    connected = pyqtSignal(int)
    disconnected = pyqtSignal()

    def __init__(self, iface, parent=None):
        """Initialize the MCP Controller with the QGIS interface."""
        super().__init__(parent)
        self.iface = iface
        self.settings = QSettings()
        self.transport = None
        self.qgis_command_handler = None

    @property
    def saved_url(self): return self.settings.value("geo_ai_assistant/llm_url", "")
    @property
    def saved_api_key(self): return self.settings.value("geo_ai_assistant/llm_api_key", "")
    @property
    def saved_model(self): return self.settings.value("geo_ai_assistant/llm_model", "")
    @property
    def saved_mcp_tools(self): return self.settings.value("geo_ai_assistant/llm_mcp_tools", "mcp/qgis")
    @property
    def saved_port(self): return int(self.settings.value("geo_ai_assistant/llm_port", "9876"))


    def connect(self, url, api_key, model, mcp_tools, port):
        """Establish a TCP connection to the MCP server."""
        if self.transport:
            return
        # Save settings for future sessions
        self.settings.setValue("geo_ai_assistant/llm_url", url)
        self.settings.setValue("geo_ai_assistant/llm_api_key", api_key)
        self.settings.setValue("geo_ai_assistant/llm_model", model)
        self.settings.setValue("geo_ai_assistant/llm_mcp_tools", mcp_tools)
        self.settings.setValue("geo_ai_assistant/llm_port", port)

        # Initialize the command handler and transport
        self.qgis_command_handler = QgisCommandHandler(iface=self.iface, parent=self)
        self.transport = McpTransportTcp(host="localhost",port=port,execute_command=self.qgis_command_handler.execute_command,parent=self)
        
        # Connect signals for connection status
        self.transport.connected.connect(self.connected)
        self.transport.disconnected.connect(self.disconnected)
        self.transport.connect()

    def disconnect(self):
        """Disconnect from the MCP server and clean up resources."""
        if not self.transport:
            return
        self.transport.connected.disconnect(self.connected)
        self.transport.disconnected.disconnect(self.disconnected)
        self.transport.disconnect()
        self.transport = None
        self.qgis_command_handler = None
        self.disconnected.emit()

    def _on_disconnected(self):
        """Handle cleanup when the transport is disconnected."""
        self.transport = None
        self.qgis_command_handler = None
        self.disconnected.emit()