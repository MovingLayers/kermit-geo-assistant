"""One worker thread for the WebSocket connections to Kermit.

QGIS runs all its code, the plugin's and the user's PyQGIS commands included, on the main thread.
While a long command runs there, the main thread cannot answer the WebSocket pings of the server
and the server closes the connection. The sockets therefore live in this thread, which only moves
network traffic: it answers pings at any time and hands QGIS commands to the main thread.
"""

from qgis.PyQt.QtCore import QObject, QThread, Qt, pyqtSignal
from qgis.core import QgsApplication

STOP_WAIT_MS = 5000

_thread = None
_stopper = None


class _Stopper(QObject):
    """Lives in the worker thread and ends its event loop when asked."""

    request = pyqtSignal()

    def stop_thread(self):
        QThread.currentThread().quit()


def network_thread() -> QThread:
    """The worker thread; started on first use."""
    global _thread, _stopper
    if _thread is None:
        _thread = QThread()
        _thread.setObjectName("kermit-network")
        _stopper = _Stopper()
        _stopper.moveToThread(_thread)
        _stopper.request.connect(_stopper.stop_thread, Qt.QueuedConnection)
        _thread.start()
        app = QgsApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(stop_network_thread)
    return _thread


def move_to_network_thread(obj: QObject) -> None:
    """Let obj, and the sockets it creates later, live in the worker thread."""
    obj.moveToThread(network_thread())


def stop_network_thread() -> None:
    """End the worker thread. Requests queued before this call (closing the sockets) run first."""
    global _thread, _stopper
    if _thread is None:
        return
    _stopper.request.emit()
    _thread.wait(STOP_WAIT_MS)
    _thread = None
    _stopper = None
