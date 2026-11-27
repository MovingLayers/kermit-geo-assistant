import os
import re

from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtCore import Qt, QEvent, QPointF, QRect, QSize, QTimer
from qgis.PyQt.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QWidget, QScrollArea, QSizePolicy, QTextEdit, QTextBrowser, QToolButton, QFileDialog, QFrame
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QFont

from .flow_layout import FlowLayout

QWIDGETSIZE_MAX = 16777215   # Qt's value for "no maximum size"
from qgis.PyQt.QtGui import QTextTable, QTextFrameFormat, QBrush
from qgis.PyQt.QtWidgets import QApplication


HEADER_COLOR = "#eef0f4"
LINE_COLOR = "#dcdee4"


class AutoHeightBrowser(QTextBrowser):
    """A message bubble whose height follows its text, also when the window width changes."""

    PADDING = 20

    def fit_height(self):
        """Set the height to what the text needs at the current width."""
        width = self.viewport().width()
        if width <= 0:
            return
        self.document().setTextWidth(width)
        height = int(self.document().size().height()) + self.PADDING
        if self.height() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()


class UserBubble(QLabel):
    """A user message bubble that fits its text and grows up to a share of the chat width."""

    SHARE = 0.85
    PADDING_X = 8
    PADDING_Y = 4
    BORDER = 1
    ROOM = 24   # a word-wrapped label needs more than the width of its text to keep it on one line
    FONT_FAMILY = "Arial"
    FONT_SIZE = 13

    def __init__(self, text):
        super().__init__(text)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.setObjectName("chatMsgUser")
        self.setWordWrap(True)
        self.setContentsMargins(self.PADDING_X, self.PADDING_Y, self.PADDING_X, self.PADDING_Y)
        # The font is set here and not only by the stylesheet: the bubble is measured before the stylesheet applies to it
        font = QFont(self.FONT_FAMILY)
        font.setPixelSize(self.FONT_SIZE)
        self.setFont(font)

    def fit(self, available):
        """Set width and height for a chat area of the given width.

        The width is the text on one line plus a little room, up to a share of the chat width. The height is what the
        label itself needs for that width, so wrapped text is never cut off.
        """
        inner = int(available * self.SHARE) - 2 * (self.PADDING_X + self.BORDER)
        if inner <= 0:
            return
        # The size set by an earlier fit would change what the label reports as its height
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        metrics = self.fontMetrics()
        one_line = metrics.boundingRect(QRect(0, 0, 100000, 100000), Qt.TextWordWrap, self.text()).width()
        width = min(one_line + self.ROOM, inner) + 2 * (self.PADDING_X + self.BORDER)
        self.setFixedWidth(width)
        self.setFixedHeight(self.heightForWidth(width))


def style_tables(browser):
    """Give the tables of a rendered Markdown message a light look: a tinted header, thin lines between the rows, no grid.

    Qt ignores a stylesheet for the tables it makes from Markdown, so the formats of the table and its cells are set.
    """
    for frame in browser.document().rootFrame().childFrames():
        if not isinstance(frame, QTextTable):
            continue
        table_format = frame.format()
        table_format.setBorder(0)
        table_format.setCellSpacing(0)
        table_format.setCellPadding(5)
        frame.setFormat(table_format)
        for row in range(frame.rows()):
            for column in range(frame.columns()):
                cell = frame.cellAt(row, column)
                cell_format = cell.format().toTableCellFormat()
                if row == 0:
                    cell_format.setBackground(QBrush(QColor(HEADER_COLOR)))
                cell_format.setBottomBorder(1)
                cell_format.setBottomBorderStyle(QTextFrameFormat.BorderStyle_Solid)
                cell_format.setBottomBorderBrush(QBrush(QColor(LINE_COLOR)))
                cell.setFormat(cell_format)


def plus_icon(size=14, scale=4):
    """A centred "+" icon, drawn at a higher resolution so it stays sharp: grey enabled, light grey disabled."""
    icon = QIcon()
    pixels = size * scale
    for mode, color in ((QIcon.Normal, "#555555"), (QIcon.Disabled, "#b5b4b8")):
        pixmap = QPixmap(pixels, pixels)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(color), 1.6, Qt.SolidLine, Qt.FlatCap))
        middle, reach = size / 2, size * 0.32
        painter.drawLine(QPointF(middle - reach, middle), QPointF(middle + reach, middle))
        painter.drawLine(QPointF(middle, middle - reach), QPointF(middle, middle + reach))
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


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
        self.controller.notice.connect(self.append_notice)
        self.controller.connected.connect(lambda: self.prompt_input.setEnabled(True))
        self.controller.connected.connect(self.show_welcome_message)
        self.controller.disconnected.connect(lambda: self.prompt_input.setEnabled(False))
        self.controller.disconnected.connect(self.reset_stream)
        self.controller.disconnected.connect(self.show_placeholder)
        self.controller.disconnected.connect(self.reset_attachments)
        self.controller.allowed_types.connect(self.on_allowed_types)
        self.controller.allowed_types_failed.connect(self.on_allowed_types_failed)
        self.controller.upload_done.connect(self.on_upload_done)

        # State for the in-progress assistant message
        self.assistant_msg = None
        self.assistant_text = ""
        self.pending_response_text = "Processing your request..."

        # Files attached to the next message: file name -> path; names whose upload failed
        self.attachments = {}
        self.failed_attachments = {}
        self.allowed_extensions = []
        self.pending_prompt = ""

        # Whether the user was working in this chat; the prompt gets the focus back only then
        self.focus_here = False
        self.focus_before_upload = False
        QApplication.instance().focusChanged.connect(self.on_focus_changed)

        self.setup_ui()

    def on_focus_changed(self, old, new):
        """Remember whether the focus is inside this chat. A window that lost the focus altogether keeps the last answer."""
        if new is not None:
            self.focus_here = new is self or self.isAncestorOf(new)

    def focus_prompt(self):
        """Give the focus back to the prompt, but only if the user was working in this chat and not elsewhere in QGIS."""
        if self.focus_here and self.prompt_input.isEnabled():
            self.prompt_input.setFocus()

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
        self.chat_layout.setContentsMargins(5, 0, 5, 0)
        self.chat_layout.setSpacing(2)
        self.chat_container.setLayout(self.chat_layout)
        self.scroll_area.setWidget(self.chat_container)
        main_layout.addWidget(self.scroll_area, 1)

        # Clear chat button
        self.clear_button = QToolButton()
        self.clear_button.setObjectName("clearChatButton")
        self.clear_button.setText("Clear chat")
        self.clear_button.setIcon(QIcon(os.path.join(os.path.dirname(__file__), "icons", "clear_chat.png")))
        self.clear_button.setVisible(False)
        self.clear_button.clicked.connect(self.clear_chat)
        main_layout.addWidget(self.clear_button, alignment=Qt.AlignRight)

        # Input box: attached files (chips) above the text, "+" and cancel below it
        self.input_box = QFrame()
        self.input_box.setObjectName("inputBox")
        self.input_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        box_layout = QVBoxLayout(self.input_box)
        box_layout.setContentsMargins(8, 6, 8, 4)
        box_layout.setSpacing(2)

        self.attachments_container = QWidget()
        self.attachments_container.setObjectName("attachmentsContainer")
        self.attachments_layout = FlowLayout(self.attachments_container, spacing=6)
        self.attachments_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.attachments_container.setVisible(False)
        box_layout.addWidget(self.attachments_container)

        self.prompt_input = QTextEdit()
        self.prompt_input.setObjectName("promptInput")
        self.prompt_input.setPlaceholderText("Ask the assistant…")
        self.prompt_input.setFrameStyle(QFrame.NoFrame)
        self.prompt_input.setFixedHeight(48)
        self.prompt_input.installEventFilter(self)
        self.prompt_input.setEnabled(False)
        box_layout.addWidget(self.prompt_input)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        # "+" opens the file picker; enabled once the server told which file types it accepts
        self.attach_button = QToolButton()
        self.attach_button.setObjectName("attachButton")
        self.attach_button.setIcon(plus_icon())
        self.attach_button.setIconSize(QSize(14, 14))
        self.attach_button.setToolTip("Dateien anhängen")
        self.attach_button.setFixedSize(24, 24)
        self.attach_button.setEnabled(False)
        self.attach_button.clicked.connect(self.pick_files)
        bottom_row.addWidget(self.attach_button)
        bottom_row.addStretch()
        self.cancel_button = QToolButton()
        self.cancel_button.setObjectName("cancelStreamButton")
        self.cancel_button.setIcon(QgsApplication.getThemeIcon("/mActionStop.svg"))
        self.cancel_button.setToolTip("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_stream)
        bottom_row.addWidget(self.cancel_button)
        box_layout.addLayout(bottom_row)
        main_layout.addWidget(self.input_box)

        self.scroll_area.viewport().installEventFilter(self)

        # Show placeholder content until connected
        self.show_placeholder()

    def eventFilter(self, obj, event):
        # Refit the user bubbles when the chat area changes its width
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self.fit_user_bubbles)
        # Handle Enter key for sending prompts
        if obj == self.prompt_input:
            if event.type() == QEvent.KeyPress:
                if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    if not event.modifiers() & Qt.ShiftModifier:
                        self.send_prompt()
                        return True
        return super().eventFilter(obj, event)
    
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
        msg = AutoHeightBrowser()
        msg.setOpenExternalLinks(False)
        msg.setReadOnly(True)
        msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        msg.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        msg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        msg.setFrameStyle(0)
        msg.document().setDocumentMargin(0)
        msg.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        msg.setPlainText("Hallo! Ich bin Ihr GeoAI-Assistent. Wie kann ich Ihnen heute helfen?")
        msg.setFixedHeight(40)

        self.chat_layout.addWidget(msg)
        self.scroll_to_bottom()
        self.update_clear_button_visibility()

    def append_notice(self, text):
        """Show a message of the plugin itself in the chat, below what is there."""
        msg = AutoHeightBrowser()
        msg.setOpenExternalLinks(False)
        msg.setReadOnly(True)
        msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        msg.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        msg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        msg.setFrameStyle(0)
        msg.document().setDocumentMargin(0)
        msg.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        msg.setPlainText(text)
        msg.setFixedHeight(40)
        self.chat_layout.addWidget(msg)
        self.scroll_to_bottom()
        self.update_clear_button_visibility()

    def send_prompt(self):
        """Send the user's prompt to the controller and prepare the UI for the assistant's response."""
        prompt = self.prompt_input.toPlainText().strip()
        if (not prompt and not self.attachments) or not self.prompt_input.isEnabled():
            return
        if self.attachments:
            self.set_sending_enabled(False)
            self.failed_attachments = {}
            self.render_attachments()
            self.controller.upload_files(list(self.attachments.values()))
            return
        self.deliver_prompt(prompt)

    def deliver_prompt(self, prompt):
        """Show the user's message and send it."""
        self.add_user_message(prompt)
        self.prompt_input.clear()
        self.start_assistant_stream()
        self.controller.send(prompt)   # controller owns conversation + transport
        self.focus_prompt()

    def deliver_files_attached(self, names):
        """Show the attached file names as the user's message and tell Kermit the files are there."""
        text = "Angehängt: " + ", ".join(names)
        self.add_user_message(text)
        self.start_assistant_stream()
        self.controller.send_files_attached(names)
        self.focus_prompt()

    def on_upload_done(self, failures):
        """Send the message when all files are stored; otherwise keep it and mark the failed files."""
        if self.controller.transport is None:
            return  # the connection closed during the upload: the input stays off until the user connects again
        self.set_sending_enabled(True)
        self.focus_prompt()
        if not failures:
            names = list(self.attachments)
            self.attachments = {}
            self.render_attachments()
            prompt = self.prompt_input.toPlainText().strip()
            if prompt:
                self.deliver_prompt(prompt)
            else:
                self.deliver_files_attached(names)
            return
        self.failed_attachments = {os.path.basename(path): text for path, text in failures.items()}
        self.render_attachments()
        lines = "\n".join(f"{name}: {text}" for name, text in self.failed_attachments.items())
        self.append_error(f"Die Nachricht wurde nicht gesendet. Diese Dateien konnten nicht angehängt werden:\n{lines}")

    def set_sending_enabled(self, enabled):
        """Block the input and the attach button while files are uploading."""
        if not enabled:
            self.focus_before_upload = self.focus_here   # disabling the prompt moves the focus away
        else:
            self.focus_here = self.focus_before_upload
        self.prompt_input.setEnabled(enabled)
        self.attach_button.setEnabled(enabled and bool(self.allowed_extensions))

    def on_allowed_types(self, extensions):
        """The server told which file types a session accepts."""
        self.allowed_extensions = [e.lower() for e in extensions]
        self.attach_button.setEnabled(bool(self.allowed_extensions))
        self.attach_button.setToolTip("Dateien anhängen")

    def on_allowed_types_failed(self, text):
        """The server did not tell the accepted file types: files cannot be attached."""
        self.allowed_extensions = []
        self.attach_button.setEnabled(False)
        self.attach_button.setToolTip(f"Dateien anhängen ist nicht verfügbar: {text}")

    def pick_files(self):
        """Let the user choose files; a file with the name of a listed file replaces it."""
        patterns = " ".join(f"*{e}" for e in self.allowed_extensions)
        focus_before = self.focus_here   # the file dialog takes the focus
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach files", "", f"Supported files ({patterns})")
        self.focus_here = focus_before
        for path in paths:
            name = os.path.basename(path)
            self.attachments[name] = path
            self.failed_attachments.pop(name, None)
        self.render_attachments()
        self.focus_prompt()

    def remove_attachment(self, name):
        """Remove a file from the list; nothing was uploaded yet."""
        self.attachments.pop(name, None)
        self.failed_attachments.pop(name, None)
        self.render_attachments()

    def render_attachments(self):
        """One chip per attached file: name, size, remove button; a failed file is marked red with the reason."""
        self.clear_layout(self.attachments_layout)
        for name, path in self.attachments.items():
            try:
                size = f"{os.path.getsize(path) / 1024:.0f} KB"
            except OSError:
                size = ""
            reason = self.failed_attachments.get(name)
            chip = QFrame()
            chip.setObjectName("attachmentChip")
            chip.setProperty("failed", bool(reason))
            chip.setToolTip(f"{name} ({size})" + (f"\n{reason}" if reason else ""))
            label = QLabel()
            shown = label.fontMetrics().elidedText(name, Qt.ElideMiddle, 150)
            label.setText(f"{shown}  {size}".strip())
            remove = QToolButton()
            remove.setObjectName("removeAttachment")
            remove.setText("✕")
            remove.setToolTip("Entfernen")
            remove.setAutoRaise(True)
            remove.clicked.connect(lambda _=False, n=name: self.remove_attachment(n))
            row = QHBoxLayout(chip)
            row.setContentsMargins(8, 2, 2, 2)
            row.setSpacing(4)
            row.addWidget(label)
            row.addWidget(remove)
            self.attachments_layout.addWidget(chip)
        self.attachments_container.setVisible(bool(self.attachments))
        self.attachments_container.updateGeometry()

    def reset_stream(self):
        """Forget the conversation and the reply that was streaming when the connection closed: the session is gone."""
        self.assistant_msg = None
        self.assistant_text = ""
        self.cancel_button.setVisible(False)
        self.controller.clear_conversation()

    def reset_attachments(self):
        """Forget the attached files when the connection closes."""
        self.attachments = {}
        self.failed_attachments = {}
        self.allowed_extensions = []
        self.attach_button.setEnabled(False)
        self.render_attachments()

    def add_user_message(self, text):
        """Add a user message to the chat layout."""
        msg = UserBubble(text)
        msg.fit(self.chat_width())
        QTimer.singleShot(0, self.fit_user_bubbles)  # the chat area may still change its width
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(msg)
        self.chat_layout.addLayout(layout)
        self.scroll_to_bottom()

    def chat_width(self):
        """The width available for messages."""
        return self.scroll_area.viewport().width() - self.chat_layout.contentsMargins().left() - self.chat_layout.contentsMargins().right()

    def fit_user_bubbles(self):
        """Fit the user bubbles to the chat area's current width."""
        for bubble in self.chat_container.findChildren(UserBubble):
            bubble.fit(self.chat_width())

    def start_assistant_stream(self):
        """Prepare the UI for a new assistant response stream."""
        self.assistant_text = ""
        self.assistant_msg = AutoHeightBrowser()
        self.assistant_msg.setOpenExternalLinks(False)
        self.assistant_msg.setReadOnly(True)
        self.assistant_msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.assistant_msg.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.assistant_msg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.assistant_msg.setFrameStyle(0)
        self.assistant_msg.document().setDocumentMargin(0)
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
        # A single newline is a space in Markdown; keep it as a line break (blank lines stay paragraph breaks)
        self.assistant_msg.setMarkdown(re.sub(r"(?<!\n)\n(?!\n)", "  \n", self.assistant_text))
        style_tables(self.assistant_msg)
        self.assistant_msg.fit_height()
        self.scroll_to_bottom()

    def on_stream_finished(self):
        """Finalize the assistant's message when the stream is finished."""
        self.cancel_button.setVisible(False)
        self.focus_prompt()
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
        self.focus_prompt()
        if self.assistant_msg:
            # Reuse the in-progress bubble
            self.assistant_msg.setPlainText(f"Error: {text}")
            self.assistant_msg = None
            self.assistant_text = ""
        else:
            # No bubble in progress — create a new one
            msg = AutoHeightBrowser()
            msg.setOpenExternalLinks(False)
            msg.setReadOnly(True)
            msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            msg.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            msg.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            msg.setFrameStyle(0)
            msg.document().setDocumentMargin(0)
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