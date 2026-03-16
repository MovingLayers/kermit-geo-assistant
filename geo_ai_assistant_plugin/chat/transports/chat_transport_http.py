import requests
import re

from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtCore import pyqtSignal, QThread


class ChatTransportHttp(QThread):
    """
    ChatTransportHttp is a QThread that handles communication with the HTTP-based chat API. 
    It sends user messages, processes responses, and emits signals for new messages, completion, and errors. 
    The ChatConnectionTester class is a one-shot thread that validates credentials by sending a test request to the API.
    """

    # Signals to communicate with the main thread
    message = pyqtSignal(str)  # signal emitted when a chunk of data is received
    finished = pyqtSignal()  # signal emitted when streaming is finished
    error = pyqtSignal(str)  # signal emitted when an error occurs
    connection_error = pyqtSignal(str)  # unused for HTTP, declared for interface compatibility
    
    def __init__(self, url, api_key, model, mcp_tools, parent=None):
        """Initialize the thread with API credentials and model information."""
        super().__init__(parent)
        self.url = url
        self.api_key = api_key
        self.model = model
        self.mcp_tools = mcp_tools
        self.payload = None

    def send(self, conversation):
        """Prepare the payload with the latest user message and start the thread to send the API request."""
        self.payload = {
            "model": self.model,
            "input": conversation[-1]["content"],  # Send only the latest user message
            "integrations": [self.mcp_tools]
        }
        self.start() # Start the thread, which will call run() method

    def run(self):
        """Execute the API request in a separate thread, handle the response, and emit signals for messages and completion."""
        try:
            # Send the POST request to the chat API and get response
            response = requests.post(
                url=self.url + "/api/v1/chat",
                headers={
                   "Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"
                },
                json=self.payload,
                timeout=120
            )
            response.raise_for_status()
            data = response.json()

            # Extract the whole response message
            if "output" in data:
                for item in data["output"]:
                    if item.get("type") == "message":
                        content = item.get("content")
                        if content:
                            content = re.sub(r"\[.*?\]\<\|tool_call_end\|\>", "", content)
                            content = content.strip()
                            if content:
                                self.message.emit(content)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        """Terminate the thread if it's still running."""
        if self.isRunning():
            self.terminate()
            self.wait()

class ChatConnectionTester(QThread):
    """One-shot thread that sends a ping request to validate all credentials."""
    success = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, url, api_key, model, mcp_tools, parent=None):
        super().__init__(parent)
        self.url = url
        self.api_key = api_key
        self.model = model
        self.mcp_tools = mcp_tools

    def run(self):
        try:
            response = requests.post(
                url=self.url + "/api/v1/chat",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "input": "ping",
                    "integrations": [self.mcp_tools]
                },
                timeout=30
            )
            response.raise_for_status()
            self.success.emit()
        except Exception as e:
            self.error.emit(str(e))