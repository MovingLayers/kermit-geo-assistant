import os

from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtCore import Qt, QEvent
from qgis.PyQt.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QWidget, QScrollArea, QSizePolicy, QTextEdit, QTextBrowser, QToolButton
from qgis.PyQt.QtGui import QIcon


class ChatWidget(QWidget):
    """
    Chat interface for interacting with the assistant. 
    Displays user prompts and assistant responses in a scrollable area, and provides an input box for sending new prompts. 
    Connects to the controller to send prompts and receive streaming responses."""
    
    def __init__(self, controller, parent=None):
        """Initialize the chat widget and connect it to the chat controller."""
        super().__init__(parent)
        self.controller = controller

        # Connect controller signals to widget slots
        self.controller.message.connect(self.append_assistant_stream)
        self.controller.finished.connect(self.on_stream_finished)
        self.controller.error.connect(self.append_error)
        self.controller.connected.connect(lambda: self.prompt_input.setEnabled(True))
        self.controller.connected.connect(self.show_welcome_message)
        self.controller.disconnected.connect(lambda: self.prompt_input.setEnabled(False))
        self.controller.disconnected.connect(self.show_placeholder)

        # State for the in-progress assistant message
        self.assistant_msg = None
        self.assistant_text = ""
        self.pending_response_text = "Processing your request..."

        self.setup_ui()

    def setup_ui(self):
        """Set up the chat widget UI"""

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5)

        # Scroll area for chat messages
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout()
        self.chat_layout.setAlignment(Qt.AlignTop)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(2)
        self.chat_container.setLayout(self.chat_layout)
        self.scroll_area.setWidget(self.chat_container)
        main_layout.addWidget(self.scroll_area)

        # Clear chat button
        self.clear_button = QToolButton()
        self.clear_button.setText("Clear chat")
        self.clear_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "clear_chat.png")))
        self.clear_button.setVisible(False)
        self.clear_button.clicked.connect(self.clear_chat)
        main_layout.addWidget(self.clear_button, alignment=Qt.AlignRight)

        # Prompt input area
        self.prompt_input = QTextEdit()
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setPlaceholderText("Ask the assistant…")
        self.prompt_input.setFixedHeight(90)
        self.prompt_input.installEventFilter(self)
        self.prompt_input.setEnabled(False)
        self.cancel_button = QToolButton(self.prompt_input)   # parent = prompt_input → overlaps it
        self.cancel_button.setObjectName("cancelStreamButton")
        self.cancel_button.setIcon(QgsApplication.getThemeIcon("/mActionStop.svg"))
        self.cancel_button.setToolTip("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_stream)
        self.cancel_button.raise_()
        main_layout.addWidget(self.prompt_input) 

        # Show placeholder content until connected
        self.show_placeholder()

    def eventFilter(self, obj, event):
        # Handle Enter key for sending prompts, and repositioning the cancel button on resize
        if obj == self.prompt_input:
            if event.type() == QEvent.Resize:
                self.reposition_cancel_button()
            elif event.type() == QEvent.KeyPress:
                if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    if not event.modifiers() & Qt.ShiftModifier:
                        self.send_prompt()
                        return True
        return super().eventFilter(obj, event)
    
    def reposition_cancel_button(self):
        """Position the cancel button at the bottom-right corner of the prompt input."""
        margin = 4
        btn = self.cancel_button.sizeHint()
        x = self.prompt_input.width() - btn.width() - margin
        y = self.prompt_input.height() - btn.height() - margin
        self.cancel_button.move(max(0, x), max(0, y))

    def show_placeholder(self):
        """Show a placeholder image and text when not connected."""
        self.clear_layout(self.chat_layout)
        self.chat_layout.setAlignment(Qt.AlignCenter)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        # Image
        image_label = QLabel()
        pixmap = QIcon(os.path.join(os.path.dirname(__file__), "icons", "moving_layers_logo.png")).pixmap(300, 300)
        image_label.setPixmap(pixmap)
        image_label.setAlignment(Qt.AlignCenter)

        # Text
        text_label = QLabel("Shaping our environment by making geodata speak")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setWordWrap(True)

        subtext_label = QLabel("Connect to start chatting with GeoAI Assistant")
        subtext_label.setAlignment(Qt.AlignCenter)
        subtext_label.setWordWrap(True)

        layout.addWidget(image_label)
        layout.addWidget(text_label)
        layout.addWidget(subtext_label)
        self.chat_layout.addWidget(container)

    def show_welcome_message(self):
        """Display a welcome message when the connection is established."""
        self.clear_chat()
        self.chat_layout.setAlignment(Qt.AlignTop)
        msg = QTextBrowser()
        msg.setOpenExternalLinks(False)
        msg.setReadOnly(True)
        msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        msg.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        msg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        msg.setFrameStyle(0)
        msg.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        msg.setPlainText("Hello! I'm your GeoAI assistant. How can I help you today?")
        msg.setFixedHeight(40)

        self.chat_layout.addWidget(msg)
        self.scroll_to_bottom()
        self.update_clear_button_visibility()

    def send_prompt(self):
        """Send the user's prompt to the controller and prepare the UI for the assistant's response."""
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            return
        self.add_user_message(prompt)
        self.prompt_input.clear()
        self.start_assistant_stream()
        self.controller.send(prompt)   # controller owns conversation + transport

    def add_user_message(self, text):
        """Add a user message to the chat layout."""
        msg = QLabel(text)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        msg.setObjectName("chatMsgUser")
        msg.setWordWrap(True)
        msg.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        msg.setMaximumWidth(int(self.scroll_area.width() * 0.8))
        msg.setMinimumWidth(200)
        msg.setContentsMargins(8, 4, 8, 4)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(msg)
        self.chat_layout.addLayout(layout)
        self.scroll_to_bottom()

    def start_assistant_stream(self):
        """Prepare the UI for a new assistant response stream."""
        self.assistant_text = ""
        self.assistant_msg = QTextBrowser()
        self.assistant_msg.setOpenExternalLinks(False)
        self.assistant_msg.setReadOnly(True)
        self.assistant_msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.assistant_msg.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.assistant_msg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.assistant_msg.setFrameStyle(0)
        self.assistant_msg.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.assistant_msg.setPlainText(self.pending_response_text)
        self.assistant_msg.setFixedHeight(40)
        self.chat_layout.addWidget(self.assistant_msg)
        
        self.scroll_to_bottom()
        self.cancel_button.setVisible(True)
        self.update_clear_button_visibility()

    def append_assistant_stream(self, text):
        """Append streaming text from the assistant to the current message bubble."""
        if not self.assistant_msg:
            return
        self.assistant_text += text
        self.assistant_msg.setPlainText(self.assistant_text)
        self.assistant_msg.setFixedHeight(int(self.assistant_msg.document().size().height()) + 20)
        self.scroll_to_bottom()

    def on_stream_finished(self):
        """Finalize the assistant's message when the stream is finished."""
        self.cancel_button.setVisible(False)
        if not self.assistant_text.strip():
            if self.assistant_msg:
                self.assistant_msg.deleteLater()
                self.assistant_msg = None
            return
        self.controller.add_assistant_reply(self.assistant_text)  # tell controller
        self.assistant_msg = None
        self.assistant_text = ""

    def append_error(self, text):
        """Append an error message to the chat layout."""
        self.cancel_button.setVisible(False)
        if self.assistant_msg:
            # Reuse the in-progress bubble
            self.assistant_msg.setPlainText(f"Error: {text}")
            self.assistant_msg = None
            self.assistant_text = ""
        else:
            # No bubble in progress — create a new one
            msg = QTextBrowser()
            msg.setOpenExternalLinks(False)
            msg.setReadOnly(True)
            msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            msg.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            msg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            msg.setFrameStyle(0)
            msg.setPlainText(f"Error: {text}")
            msg.setFixedHeight(40)

            self.chat_layout.addWidget(msg)
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        """Scroll the chat to the bottom to show the latest messages."""
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def update_clear_button_visibility(self):
        """Show the clear button if there are any messages in the chat."""
        self.clear_button.setVisible(self.chat_layout.count() > 0)

    def clear_chat(self):
        """Clear all messages from the chat and reset the controller's conversation when clear button is clicked."""
        self.clear_layout(self.chat_layout)
        self.controller.clear_conversation()   # keep controller in sync
        self.update_clear_button_visibility()
        self.scroll_area.verticalScrollBar().setValue(0)

    def clear_layout(self, layout):
        """Recursively clear all widgets and layouts from the given layout."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())
                item.layout().deleteLater()

    def cancel_stream(self):
        """Cancel the in-progress assistant response stream, when the cancel button is clicked."""
        self.controller.cancel()
        # Clean up the in-progress assistant bubble
        if self.assistant_msg:
            self.assistant_msg.deleteLater()
            self.assistant_msg = None
        self.assistant_text = ""
        self.cancel_button.setVisible(False)