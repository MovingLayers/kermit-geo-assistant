import os

from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtCore import pyqtSignal, QSize
from qgis.PyQt.QtWidgets import QDockWidget, QVBoxLayout, QWidget, QTabWidget, QStackedWidget, QSizePolicy

from ..controllers.mcp_controller_tcp import McpControllerTcp
from ..controllers.mcp_controller_ws import McpControllerWs
from ..controllers.chat_controller import ChatController
from .conn_widget_tcp import ConnWidgetTcp
from .conn_widget_ws import ConnWidgetWs
from .chat_widget import ChatWidget


class AdaptiveTabWidget(QTabWidget):
    """A QTabWidget that adapts its size to the content of the current tab."""
    
    def sizeHint(self):
        """Calculate size hint based on the current tab's content."""
        w = self.currentWidget()
        if w is None:
            return super().sizeHint()
        tab_bar_h = self.tabBar().sizeHint().height()
        return QSize(w.sizeHint().width(), w.sizeHint().height() + tab_bar_h)

    def minimumSizeHint(self):
        """Calculate minimum size hint based on the current tab's content."""
        w = self.currentWidget()
        if w is None:
            return super().minimumSizeHint()
        tab_bar_h = self.tabBar().minimumSizeHint().height()
        return QSize(w.minimumSizeHint().width(), w.minimumSizeHint().height() + tab_bar_h)


class DockWidget(QDockWidget):
    """Main dock widget for the GeoAI Assistant plugin, containing tabs for different connection types and their respective chat interfaces."""
    closed = pyqtSignal()

    def __init__(self, iface, parent=None):
        """Initialize the dock widget."""
        super().__init__("GeoAI Assistant", parent)
        self.iface = iface
        self.setObjectName("GeoAI_Assistant_Dock")
        self.tab_widgets = [] 

        self.setup_ui()

    def setup_ui(self):
        """Set up the dock widget UI"""
        self.load_stylesheet()

        # Main widget
        main_widget = QWidget()
        self.setWidget(main_widget)

        # Collapsible group wrapping tabs + connection settings
        connection_group = QgsCollapsibleGroupBox("Connection Settings")
        connection_group.setCollapsed(False)

        # Adaptive tab widget that resizes based on content, containing connection settings for each tab
        self.tabs = AdaptiveTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.tabs.tabBar().setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)

        # Chat area below, outside the collapsible group
        self.chat_stack = QStackedWidget()
        self.chat_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Create two tabs for each mode
        self._add_tab(title="Kermit")
        self._add_tab(title="Local LLMs")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tab_index = 0

        # Layout for connection group
        group_layout = QVBoxLayout()
        group_layout.addWidget(self.tabs)
        connection_group.setLayout(group_layout)

        # Layout for main widget
        main_layout = QVBoxLayout(main_widget)
        main_layout.addWidget(connection_group, 0) # connection group takes minimum space needed
        main_layout.addWidget(self.chat_stack, 1) # chat takes remaining space
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

    def _add_tab(self, title):
        """Create a tab with its own connection + chat widgets"""
        if title == "Local LLMs":
            mcp_controller = McpControllerTcp(self.iface, parent=self)
            chat_controller = ChatController(transport_type='http', parent=self)
            conn_widget = ConnWidgetTcp(mcp_controller, chat_controller, parent=self)
            chat_widget = ChatWidget(chat_controller, parent=self)
            mcp_controller.disconnected.connect(chat_widget.clear_chat)
        else:
            mcp_controller = McpControllerWs(self.iface, parent=self)
            chat_controller = ChatController(transport_type='ws', parent=self)
            conn_widget = ConnWidgetWs(mcp_controller, chat_controller, parent=self)
            chat_widget = ChatWidget(chat_controller, parent=self)

        # Set size policies to ensure proper resizing behavior
        conn_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        chat_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Create a container widget for the tab content (connection settings) and add the connection widget to it
        tab = QWidget()
        tab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        # Layout for the tab content, containing the connection widget
        layout = QVBoxLayout(tab)
        layout.addWidget(conn_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Add tab and chat to their respective stacks
        self.tabs.addTab(tab, title)
        self.chat_stack.addWidget(chat_widget)  # index matches tab index
        self.tab_widgets.append({"connection": conn_widget, "chat": chat_widget})

    def _on_tab_changed(self, new_index):
        """Handle tab change: stop old connection and clear old chat when switching tabs"""
        old_index = self.tab_index
        if old_index != new_index:
            old = self.tab_widgets[old_index]
            old["connection"].disconnect()
            old["chat"].clear_chat()
            old["chat"].controller.close()
        self.tab_index = new_index
        self.chat_stack.setCurrentIndex(new_index)
        self.tabs.updateGeometry()

    def current_tab_widgets(self):
        """Return widgets of the currently active tab"""
        index = self.tabs.currentIndex()
        return self.tab_widgets[index]

    def disconnect(self):
        """Stop connection of active tab only"""
        current = self.current_tab_widgets()
        current["connection"].disconnect()

    def load_stylesheet(self):
        """Load QSS stylesheet for the dock widget"""
        qss_path = os.path.join(os.path.dirname(__file__), "styles.qss")
        with open(qss_path, "r") as f:
            self.setStyleSheet(f.read())

    def closeEvent(self, event):
        """Handle dock widget close event"""
        if self.tab_widgets:
            self.disconnect()

        self.closed.emit()
        super().closeEvent(event)