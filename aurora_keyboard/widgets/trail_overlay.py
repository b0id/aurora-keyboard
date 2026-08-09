"""
Swipe gesture glowing trail overlay widget for Aurora Touch Keyboard.
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen


class SwipeTrailOverlay(QWidget):
    """Transparent overlay that paints a glowing anti-aliased swipe gesture trail."""

    THEME_COLORS = {
        "Aurora Glass": "#38bdf8",
        "Cyber Neon": "#f43f5e",
        "OLED Dark": "#ffffff",
        "Light Velvet": "#0284c7"
    }

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.points = []
        self.alpha = 1.0
        self.glow_color = QColor("#38bdf8")

        self.fade_timer = QTimer(self)
        self.fade_timer.setInterval(16)  # ~60 fps
        self.fade_timer.timeout.connect(self._fade_step)

    def set_theme(self, theme_name: str):
        hex_color = self.THEME_COLORS.get(theme_name, "#38bdf8")
        self.glow_color = QColor(hex_color)

    def add_point(self, global_pos):
        local_pos = self.mapFromGlobal(global_pos)
        self.points.append(QPointF(float(local_pos.x()), float(local_pos.y())))
        self.alpha = 1.0
        self.fade_timer.stop()
        self.update()

    def start_fade(self):
        if not self.points:
            return
        self.alpha = 1.0
        self.fade_timer.start()

    def _fade_step(self):
        self.alpha -= 0.12
        if self.alpha <= 0.0:
            self.alpha = 0.0
            self.points = []
            self.fade_timer.stop()
        self.update()

    def clear_trail(self):
        self.fade_timer.stop()
        self.points = []
        self.alpha = 0.0
        self.update()

    def paintEvent(self, event):
        if not self.points or len(self.points) < 2 or self.alpha <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        path = QPainterPath()
        path.moveTo(self.points[0])
        for p in self.points[1:]:
            path.lineTo(p)

        # 1. Subtle soft outer neon glow
        glow = QColor(self.glow_color)
        glow.setAlphaF(min(1.0, 0.28 * self.alpha))
        glow_pen = QPen(glow, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(glow_pen)
        painter.drawPath(path)

        # 2. Sleek, refined inner core line
        core = QColor(255, 255, 255)
        core.setAlphaF(min(1.0, 0.78 * self.alpha))
        core_pen = QPen(core, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(core_pen)
        painter.drawPath(path)
