"""
Floating minimize badge widget for restoring the keyboard.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor


class BadgeButton(QPushButton):
    """Badge's tap and drag target."""

    DRAG_THRESHOLD = 8

    def __init__(self, text, badge):
        super().__init__(text)
        self.badge = badge
        self._press_pos = None
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and not self._dragging:
            moved = event.globalPosition().toPoint() - self._press_pos
            if moved.manhattanLength() > self.DRAG_THRESHOLD:
                self._dragging = True
                self.setDown(False)
                wh = self.badge.windowHandle()
                if wh and hasattr(wh, 'startSystemMove'):
                    wh.startSystemMove()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._press_pos = None
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)


class FloatingBadge(QWidget):
    """Small floating widget that stays on screen corner to re-open keyboard."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setObjectName("floating_badge")
        # Distinct title so KWin Window Rules can target the badge separately from the main keyboard
        self.setWindowTitle("Aurora Touch Keyboard Badge")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(160, 160)
        self.setToolTip("Open Aurora Touch Keyboard")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.btn = BadgeButton("⌨", self)
        self.btn.setObjectName("badge_btn")
        self.btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.btn.clicked.connect(self.on_click)
        layout.addWidget(self.btn)

    def on_click(self):
        self.parent_window.bring_to_front()
