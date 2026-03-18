import os

from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon

from .ui.dock_widget import DockWidget

class GeoAIAssistantPlugin:
    """Main plugin class for GeoAI Assistant"""
    
    def __init__(self, iface):
        self.iface = iface
        self.dock_widget = None
        self.action = None
    
    def initGui(self):
        """Initialize GUI"""
        # Create action with icon and text
        self.action = QAction(
            QIcon(os.path.join(os.path.dirname(__file__), "ui", "icons", "plugin_logo.png")),
            "GeoAI Assistant",
            self.iface.mainWindow()
        )
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)

        # Add to plugins menu and toolbar
        self.iface.addPluginToMenu("GeoAI Assistant", self.action)
        self.iface.addToolBarIcon(self.action)

        # Show icon + text on the toolbar button
        toolbar = self.iface.pluginToolBar()
        btn = toolbar.widgetForAction(self.action)
        if btn:
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    
    def toggle_dock(self, checked):
        """Toggle dock widget visibility"""
        if checked:
            # Create dock widget if it doesn't exist
            if not self.dock_widget:
                self.dock_widget = DockWidget(self.iface, parent=self.iface.mainWindow())
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
                # Connect close event
                self.dock_widget.closed.connect(self.dock_closed)
            else:
                # Show existing dock widget
                self.dock_widget.show()
        else:
            # Hide dock widget
            if self.dock_widget:
                self.dock_widget.hide()
    
    def dock_closed(self):
        """Handle dock widget closed event"""
        if self.action:
            self.action.setChecked(False)
    
    def unload(self):
        """Unload plugin and clean up"""
        # Disconnect and remove dock widget
        if self.dock_widget:
            self.dock_widget.disconnect()
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None
            
        # Remove plugin menu item and toolbar icon
        self.iface.removePluginMenu("GeoAI Assistant", self.action)
        self.iface.removeToolBarIcon(self.action)

# Plugin entry point
def classFactory(iface):
    return GeoAIAssistantPlugin(iface)
