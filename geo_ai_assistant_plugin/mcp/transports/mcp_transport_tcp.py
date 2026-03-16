import socket
import json
from qgis.core import QgsMessageLog, Qgis
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal


class McpTransportTcp(QObject):
    """TCP transport implementation for MCP server"""
    # Signals to notify about connection status
    connected = pyqtSignal(int)
    disconnected = pyqtSignal()

    def __init__(self, host, port, execute_command, parent=None):
        """Initialize TCP transport"""
        super().__init__(parent)
        self.host = host
        self.port = port
        self.execute_command = execute_command

        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b''
        self.timer = None

    def connect(self):
        """Establish a TCP connection to the MCP server."""
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.socket.setblocking(False)
            
            self.timer = QTimer()
            self.timer.timeout.connect(self.process_server)
            self.timer.start(100)  # 100ms interval
            
            QgsMessageLog.logMessage(f"Connection opened on {self.host}:{self.port}", "GeoAI Assistant")
            self.connected.emit(self.port)
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Failed to open connection: {str(e)}", "GeoAI Assistant", Qgis.Critical)
            self.disconnect()
            return False
            
    def disconnect(self):
        """Close the TCP connection and clean up resources."""
        self.running = False
        
        if self.timer:
            self.timer.stop()
            self.timer = None
            
        if self.socket:
            self.socket.close()
        if self.client:
            self.client.close()
            
        self.socket = None
        self.client = None
        QgsMessageLog.logMessage("Connection closed", "GeoAI Assistant")
        self.disconnected.emit()
        
    def process_server(self):
        """Process server operations (called by timer)"""
        if not self.running:
            return

        if not self.client and self.socket:
            self.accept_connection()

        if self.client:
            self.process_client_data()

    def accept_connection(self):
        """Try to accept new connection"""
        try:
            self.client, address = self.socket.accept() # type: ignore
            self.client.setblocking(False)
            QgsMessageLog.logMessage(f"Connected to client: {address}", "GeoAI Assistant")
        except BlockingIOError:
            pass
        except Exception as e:
            QgsMessageLog.logMessage(f"Error accepting connection: {str(e)}", "GeoAI Assistant", Qgis.Warning)
    
    def process_client_data(self):
        """Process data from connected client"""
        try:
            data = self.client.recv(8192) # type: ignore
            if not data:
                QgsMessageLog.logMessage("Client disconnected", "GeoAI Assistant")
                self.cleanup_client()
                return
                
            self.buffer += data
            
            try:
                command = json.loads(self.buffer.decode('utf-8'))
                self.buffer = b''
                response = self.execute_command(command)
                self.client.sendall(json.dumps(response).encode('utf-8')) # type: ignore
            except json.JSONDecodeError:
                pass  # Incomplete data, keep buffering
                
        except BlockingIOError:
            pass
        except Exception as e:
            QgsMessageLog.logMessage(f"Error processing client data: {str(e)}", "GeoAI Assistant", Qgis.Warning)
            self.cleanup_client()

    def cleanup_client(self):
        """Close client connection and clear buffer"""
        if self.client:
            self.client.close()
            self.client = None
        self.buffer = b''