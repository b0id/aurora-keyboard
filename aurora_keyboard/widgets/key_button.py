"""
Key button widgets distinguishing discrete taps from continuous swipe drags.
"""

from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import Qt


class SwipeKeyButton(QPushButton):
    """Char-key button that distinguishes discrete taps from continuous swipe drags."""

    DRAG_THRESHOLD = 16

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self._press_pos = None
        self._press_time = None
        self._swiping = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_time = event.timestamp()
            self._swiping = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None:
            pos = event.globalPosition().toPoint()
            if not self._swiping and (pos - self._press_pos).manhattanLength() > self.DRAG_THRESHOLD:
                self._swiping = True
                self.setDown(False)
                self.parent_window.swipe_begin(self)
                self.parent_window.swipe_raw_start(self._press_pos, self._press_time)
            if self._swiping:
                self.parent_window.swipe_update(pos)
                self.parent_window.swipe_raw_sample(pos, event.timestamp())
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._swiping:
            self._swiping = False
            self._press_pos = None
            self.parent_window.swipe_end()
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)
