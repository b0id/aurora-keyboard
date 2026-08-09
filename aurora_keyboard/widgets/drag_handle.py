"""
Drag handle and touch corner resize grip for Wayland KWin window management.
"""

from PyQt6.QtWidgets import QLabel, QApplication
from PyQt6.QtCore import Qt


class DragHandleLabel(QLabel):
    """Custom Label for initiating Wayland KWin system move via touch/mouse."""

    def __init__(self, text, parent_window):
        super().__init__(text)
        self.parent_window = parent_window
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("""
            color: #38bdf8;
            font-weight: bold;
            font-size: 13px;
            padding: 2px 8px;
            background: rgba(56, 189, 248, 0.2);
            border: 1px solid rgba(56, 189, 248, 0.5);
            border-radius: 6px;
        """)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_start_global = None
        self._window_start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            wh = self.parent_window.windowHandle()
            if wh and hasattr(wh, 'startSystemMove'):
                wh.startSystemMove()
                event.accept()
            else:
                self._drag_start_global = event.globalPosition().toPoint()
                self._window_start_pos = self.parent_window.pos()
                event.accept()

    def mouseMoveEvent(self, event):
        if getattr(self, '_drag_start_global', None) is not None and getattr(self, '_window_start_pos', None) is not None:
            delta = event.globalPosition().toPoint() - self._drag_start_global
            new_x = self._window_start_pos.x() + delta.x()
            new_y = self._window_start_pos.y() + delta.y()
            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                new_x, new_y = self.parent_window.geometry_mgr.clamp_position(
                    new_x, new_y, self.parent_window.width(), self.parent_window.height(), geom
                )
            self.parent_window.move(new_x, new_y)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_start_global = None
        self._window_start_pos = None
        if self.parent_window.isVisible():
            self.parent_window.on_user_drag_finished()
        event.accept()


class TouchResizeGrip(QLabel):
    """Touch-friendly corner grip for resizing the keyboard with a finger drag."""

    def __init__(self, parent_window):
        super().__init__("◢ Resize")
        self.parent_window = parent_window
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Drag with finger to resize keyboard")
        self.setStyleSheet("""
            color: #38bdf8;
            font-size: 13px;
            font-weight: bold;
            padding: 4px 10px;
            background: rgba(56, 189, 248, 0.2);
            border: 1px solid rgba(56, 189, 248, 0.5);
            border-radius: 6px;
        """)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self._start_pos = None
        self._start_size = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            wh = self.parent_window.windowHandle()
            if wh and hasattr(wh, 'startSystemResize'):
                wh.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
                event.accept()
            else:
                self._start_pos = event.globalPosition().toPoint()
                self._start_size = self.parent_window.size()
                event.accept()

    def mouseMoveEvent(self, event):
        if getattr(self, '_start_pos', None) is not None and getattr(self, '_start_size', None) is not None:
            delta = event.globalPosition().toPoint() - self._start_pos
            new_w = self._start_size.width() + delta.x()
            new_h = self._start_size.height() + delta.y()
            self.parent_window.resize(new_w, new_h)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._start_pos = None
        self._start_size = None
        event.accept()
