"""
Main PyQt6 Window for Aurora Touch Keyboard with evdev.UInput, KWin Wayland dragging,
glowing gesture trail overlay, and FUTO neural / geometric swipe-to-type candidate bar.
"""

import sys
import os
import subprocess
import json
import configparser
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QFrame, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QScreen, QColor, QPainter, QPainterPath, QPen

from .key_engine import KeyEngine
from .layouts import QWERTY_ROWS, DEV_ROWS, NUMPAD_ROWS
from .styles import THEMES
from .swipe import SwipeManager

# KDE Window Rules store fixed pixel position/size (see WINDOW_RULES.md) - they
# have no notion of the screen's own dimensions, so a screen rotation or
# resolution change leaves them stale unless something rewrites them.
KWIN_RULES_PATH = os.path.expanduser("~/.config/kwinrulesrc")
KWIN_RULE_TITLE_BADGE = "Aurora Touch Keyboard Badge"
KWIN_RULE_TITLE_MAIN = "Aurora Touch Keyboard Main"
CONFIG_PATH = os.path.expanduser("~/.config/aurora-keyboard/config.json")

# screen.availableGeometry() does not reliably exclude the Plasma taskbar for a
# Force-positioned Tool window - measured directly via screenshot pixel sampling
# (taskbar top at physical y=1226 of 1280, ~45 logical px tall at this device's
# 1.2 scale) rather than trusting availableGeometry()'s own panel accounting.
BOTTOM_CLEARANCE = 55


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


class CandidateBar(QFrame):
    """Sleek suggestion bar displaying word candidates with instant auto-commit and large touch chips."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setObjectName("candidate_bar")
        self.setFixedHeight(44)

        self.auto_commit = True
        self.last_inserted_word = None

        self.bar_layout = QHBoxLayout(self)
        self.bar_layout.setContentsMargins(8, 3, 8, 3)
        self.bar_layout.setSpacing(8)
        self.chip_buttons = []

        self._placeholder_label = QLabel("✦ Swipe across keys to type")
        self._placeholder_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 13px; font-style: italic; padding: 2px 8px;")
        self.bar_layout.addWidget(self._placeholder_label)
        self.bar_layout.addStretch()

    def set_candidates(self, candidates: list, backend: str = "neural"):
        # Clear existing chips
        while self.bar_layout.count():
            item = self.bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.chip_buttons = []

        if not candidates:
            self.last_inserted_word = None
            self._placeholder_label = QLabel("✦ Swipe across keys to type")
            self._placeholder_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 13px; font-style: italic; padding: 2px 8px;")
            self.bar_layout.addWidget(self._placeholder_label)
            self.bar_layout.addStretch()
            return

        # Engine Badge
        tag = "⚡ FUTO" if "futo" in backend else "✦ Swipe"
        badge = QLabel(tag)
        badge.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: bold; padding: 3px 6px; background: rgba(56, 189, 248, 0.15); border-radius: 4px;")
        self.bar_layout.addWidget(badge)

        top_word = candidates[0]
        # Auto-commit top candidate immediately on release if enabled
        if self.auto_commit:
            self.parent_window.engine.type_text(top_word + " ")
            self.last_inserted_word = top_word

        for i, word in enumerate(candidates):
            display_text = f"✓ {word}" if (i == 0 and self.auto_commit) else word
            btn = QPushButton(display_text)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedHeight(34)
            if i == 0:
                btn.setProperty("class", "candidate-chip-top")
            else:
                btn.setProperty("class", "candidate-chip")
            btn.clicked.connect(lambda _, w=word, idx=i: self.on_candidate_clicked(w, idx))
            self.bar_layout.addWidget(btn)
            self.chip_buttons.append(btn)

        self.bar_layout.addStretch()

        # Clear button
        clear_btn = QPushButton("✕")
        clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        clear_btn.setFixedSize(26, 26)
        clear_btn.setStyleSheet("background: transparent; color: rgba(255, 255, 255, 0.5); border: none; font-size: 14px;")
        clear_btn.clicked.connect(self.clear_candidates)
        self.bar_layout.addWidget(clear_btn)

    def on_candidate_clicked(self, word: str, idx: int):
        if self.auto_commit and self.last_inserted_word:
            if idx == 0:
                # Top word is already inserted; clear candidates
                self.clear_candidates()
                return
            # Replace previously auto-inserted word: backspace len(last_word)+1 and type replacement
            backspaces = len(self.last_inserted_word) + 1
            bs_code = self.parent_window.engine.get_keycode("BACKSPACE")
            for _ in range(backspaces):
                self.parent_window.engine.send_keycode(bs_code)
            self.parent_window.engine.type_text(word + " ")
            self.clear_candidates()
        else:
            self.parent_window.engine.type_text(word + " ")
            self.clear_candidates()

    def clear_candidates(self):
        self.set_candidates([], "")


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
                new_x = max(geom.x() + 10, min(geom.x() + geom.width() - self.parent_window.width() - 10, new_x))
                new_y = max(geom.y() + 10, min(geom.y() + geom.height() - self.parent_window.height() - BOTTOM_CLEARANCE, new_y))
            self.parent_window.move(new_x, new_y)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_start_global = None
        self._window_start_pos = None
        if getattr(self.parent_window, 'position_mode', None) == "remember":
            p = self.parent_window.pos()
            self.parent_window.custom_pos = [p.x(), p.y()]
            self.parent_window.save_config()
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
            screen = QApplication.primaryScreen()
            max_w = screen.availableGeometry().width() if screen else 1920
            max_h = screen.availableGeometry().height() if screen else 1280
            new_w = max(380, min(max_w, self._start_size.width() + delta.x()))
            new_h = max(160, min(max_h - 80, self._start_size.height() + delta.y()))
            self.parent_window.resize(new_w, new_h)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._start_pos = None
        self._start_size = None
        event.accept()


class BadgeButton(QPushButton):
    """Badge's tap target."""

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
        # Distinct title so KWin Window Rules can target the badge separately
        # from the main keyboard window - both share the same app id/class
        # since they come from the same process, so title is the only thing
        # that tells them apart for rule matching.
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


class AuroraKeyboardWindow(QWidget):
    """Main Frameless On-Screen Keyboard Window."""

    def __init__(self):
        super().__init__()
        self.setObjectName("keyboard_root")
        self.setWindowTitle("Aurora Touch Keyboard Main")
        self.engine = KeyEngine()
        
        self.shift_active = False
        self.caps_active = False
        self.active_modifiers = set()
        
        self.current_layout_name = "QWERTY"
        self.current_theme = "Aurora Glass"
        self.dock_position = "bottom"
        
        self.load_config()

        self.badge = FloatingBadge(self)
        self._drag_pos = None

        # Swipe Manager (FUTO neural primary + geometric fallback)
        self.swipe_manager = SwipeManager()
        self._swipe_points = []
        self._swipe_letters = []
        self._swipe_raw = []

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_config_and_sync)

        self.apply_flags()
        self.init_ui()
        self.position_bottom()

        # Swipe Trail Overlay
        self.trail_overlay = SwipeTrailOverlay(self)
        self.trail_overlay.setGeometry(self.rect())
        self.trail_overlay.show()

        self.apply_theme(self.current_theme)

        # Rotation / resolution change handling: KWin rules don't auto-scale,
        # so re-derive and re-push their geometry whenever the screen changes.
        self._rotation_timer = QTimer(self)
        self._rotation_timer.setSingleShot(True)
        self._rotation_timer.timeout.connect(self._handle_screen_change)
        self._watch_screen(QApplication.primaryScreen())
        app = QApplication.instance()
        if app:
            app.primaryScreenChanged.connect(self._on_primary_screen_changed)
        # Also correct any rule geometry left stale from a previous orientation
        # (e.g. app was relaunched while already in portrait).
        self._sync_kwin_rules_to_screen()

    def load_config(self):
        self.position_mode = "remember"
        self.custom_size = None
        self.custom_pos = None
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.position_mode = data.get("position_mode", "remember")
                    self.custom_size = data.get("custom_size", None)
                    self.custom_pos = data.get("custom_pos", None)
                    if "theme" in data and data["theme"] in THEMES:
                        self.current_theme = data["theme"]
            except Exception as e:
                print(f"[Config] Error loading: {e}", file=sys.stderr)

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "position_mode": self.position_mode,
                    "custom_size": self.custom_size,
                    "custom_pos": self.custom_pos,
                    "theme": self.current_theme,
                    "layout": self.current_layout_name
                }, f, indent=2)
        except Exception as e:
            print(f"[Config] Error saving: {e}", file=sys.stderr)

    def save_config_and_sync(self):
        self.save_config()
        self._sync_kwin_rules_to_screen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.setGeometry(self.rect())
        self._update_responsive_typography()
        if getattr(self, 'position_mode', None) == "remember" and self.isVisible():
            self.custom_size = [self.width(), self.height()]
            p = self.pos()
            self.custom_pos = [p.x(), p.y()]
            self._save_timer.start(500)

    def _update_responsive_typography(self):
        if not hasattr(self, 'keys_container') or not getattr(self, 'key_buttons', None):
            return
        total_h = self.keys_container.height()
        if total_h > 80:
            row_h = total_h / 5.0
            font_px = max(11, min(int(row_h * 0.36), 22))
            for btn in self.key_buttons:
                info = getattr(btn, 'key_info', None)
                if info and info.get("type") == "char":
                    btn.setStyleSheet(f"font-size: {font_px}px;")

    def on_size_mode_changed(self, text):
        if "Default" in text:
            self.position_mode = "default"
            self.position_bottom()
        else:
            self.position_mode = "remember"
            self.custom_size = [self.width(), self.height()]
            p = self.pos()
            self.custom_pos = [p.x(), p.y()]
        self.save_config_and_sync()

    def scale_keyboard(self, factor: float):
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None
        max_w = geom.width() if geom else 1920
        max_h = geom.height() if geom else 1280
        
        cur_w = self.width()
        cur_h = self.height()
        new_w = max(380, min(max_w - 20, int(cur_w * factor)))
        new_h = max(160, min(max_h - BOTTOM_CLEARANCE - 20, int(cur_h * factor)))
        
        cur_pos = self.pos()
        new_x = max(10, min(max_w - new_w - 10, cur_pos.x()))
        new_y = max(10, min(max_h - new_h - BOTTOM_CLEARANCE, cur_pos.y()))
        
        self.setGeometry(new_x, new_y, new_w, new_h)
        if self.position_mode == "remember":
            self.custom_size = [new_w, new_h]
            self.custom_pos = [new_x, new_y]
            self.save_config()

    def on_scale_preset_selected(self, text: str):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        base_w = int(geom.width() * 0.95)
        base_h = 409
        
        if "50%" in text:
            target_w = int(base_w * 0.50)
            target_h = int(base_h * 0.55)
        elif "65%" in text:
            target_w = int(base_w * 0.65)
            target_h = int(base_h * 0.70)
        elif "75%" in text:
            target_w = int(base_w * 0.75)
            target_h = int(base_h * 0.80)
        elif "125%" in text:
            target_w = min(geom.width() - 20, int(base_w * 1.25))
            target_h = int(base_h * 1.25)
        else:
            target_w = base_w
            target_h = base_h
            
        cur_pos = self.pos()
        target_x = max(geom.x() + 10, min(geom.x() + geom.width() - target_w - 10, cur_pos.x()))
        target_y = max(geom.y() + 10, min(geom.y() + geom.height() - target_h - BOTTOM_CLEARANCE, cur_pos.y()))

        self.setGeometry(target_x, target_y, target_w, target_h)
        if self.position_mode == "remember":
            self.custom_size = [target_w, target_h]
            self.custom_pos = [target_x, target_y]
            self.save_config()

    def apply_flags(self):
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 8, 12, 12)
        self.main_layout.setSpacing(4)

        # 1. Top Drag & Action Bar
        self.action_bar = QFrame(self)
        self.action_bar.setObjectName("action_bar")
        bar_layout = QHBoxLayout(self.action_bar)
        bar_layout.setContentsMargins(6, 2, 6, 2)
        bar_layout.setSpacing(4)

        # Drag Handle Grip Button
        self.drag_label = DragHandleLabel("❖ Drag", self)
        bar_layout.addWidget(self.drag_label)

        # Quick Actions (Compact)
        actions = [
            ("All", lambda: self.engine.send_combo(self.get_active_modifiers() or ["LEFTCTRL"], "a")),
            ("Copy", lambda: self.engine.send_combo(self.get_active_modifiers() or ["LEFTCTRL"], "c")),
            ("Paste", lambda: self.engine.send_combo(self.get_active_modifiers() or ["LEFTCTRL"], "v")),
            ("Esc", lambda: self.engine.send_keycode(self.engine.get_keycode("ESC"))),
            ("Tab", lambda: self.engine.send_keycode(self.engine.get_keycode("TAB"))),
        ]
        for name, callback in actions:
            btn = QPushButton(name)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedHeight(28)
            btn.setStyleSheet("padding: 0 4px; font-size: 11px;")
            btn.clicked.connect(callback)
            bar_layout.addWidget(btn)

        bar_layout.addStretch()

        # Touch Zoom Out Button
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        zoom_out_btn.setFixedSize(26, 28)
        zoom_out_btn.setToolTip("Shrink keyboard size (-10%)")
        zoom_out_btn.setStyleSheet("font-size: 15px; font-weight: bold;")
        zoom_out_btn.clicked.connect(lambda: self.scale_keyboard(0.90))
        bar_layout.addWidget(zoom_out_btn)

        # Scale Presets (including 1/4 Tile Mini)
        self.scale_preset_box = QComboBox()
        self.scale_preset_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scale_preset_box.addItems(["50% (1/4 Tile)", "65% (Compact)", "100% (Standard)", "125% (Large)"])
        self.scale_preset_box.setCurrentText("100% (Standard)")
        self.scale_preset_box.currentTextChanged.connect(self.on_scale_preset_selected)
        bar_layout.addWidget(self.scale_preset_box)

        # Touch Zoom In Button
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        zoom_in_btn.setFixedSize(26, 28)
        zoom_in_btn.setToolTip("Enlarge keyboard size (+10%)")
        zoom_in_btn.setStyleSheet("font-size: 15px; font-weight: bold;")
        zoom_in_btn.clicked.connect(lambda: self.scale_keyboard(1.10))
        bar_layout.addWidget(zoom_in_btn)

        # Touch Finger Resize Grip
        self.resize_grip = TouchResizeGrip(self)
        bar_layout.addWidget(self.resize_grip)

        # Size / Position Mode Selector
        self.size_mode_box = QComboBox()
        self.size_mode_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.size_mode_box.addItems(["Remember", "Auto-Dock"])
        if self.position_mode == "default":
            self.size_mode_box.setCurrentText("Auto-Dock")
        else:
            self.size_mode_box.setCurrentText("Remember")
        self.size_mode_box.currentTextChanged.connect(self.on_size_mode_changed)
        bar_layout.addWidget(self.size_mode_box)

        # Dock Toggle Button (Bottom / Top)
        self.dock_btn = QPushButton("⬇ Dock")
        self.dock_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dock_btn.setFixedHeight(28)
        self.dock_btn.clicked.connect(self.toggle_dock)
        bar_layout.addWidget(self.dock_btn)

        # Layout Selector
        self.layout_box = QComboBox()
        self.layout_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.layout_box.addItems(["QWERTY", "DEV", "NUM"])
        self.layout_box.currentTextChanged.connect(self.change_layout)
        bar_layout.addWidget(self.layout_box)

        # Theme Selector
        self.theme_box = QComboBox()
        self.theme_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.theme_box.addItems(list(THEMES.keys()))
        self.theme_box.currentTextChanged.connect(self.apply_theme)
        bar_layout.addWidget(self.theme_box)

        # Minimize Button
        min_btn = QPushButton("🗕")
        min_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        min_btn.setFixedSize(28, 28)
        min_btn.clicked.connect(self.hide_to_badge)
        bar_layout.addWidget(min_btn)

        # Close Button
        close_btn = QPushButton("✕")
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setFixedSize(28, 28)
        close_btn.setObjectName("close_btn")
        close_btn.setStyleSheet("background: rgba(239, 68, 68, 0.4); color: white;")
        close_btn.clicked.connect(QApplication.instance().quit)
        bar_layout.addWidget(close_btn)

        self.main_layout.addWidget(self.action_bar)

        # 2. Word Candidate & Suggestion Bar
        self.candidate_bar = CandidateBar(self)
        self.main_layout.addWidget(self.candidate_bar)

        # 3. Keyboard Keys Container
        self.keys_container = QWidget()
        self.keys_layout = QVBoxLayout(self.keys_container)
        self.keys_layout.setContentsMargins(0, 0, 0, 0)
        self.keys_layout.setSpacing(4)

        self.main_layout.addWidget(self.keys_container)
        self.build_keys("QWERTY")

    def toggle_dock(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        width = self.width()
        height = self.height()
        x = geom.x() + int((geom.width() - width) / 2)

        if self.dock_position == "bottom":
            self.dock_position = "top"
            y = geom.y() + 10
            self.dock_btn.setText("⬆ Dock")
        else:
            self.dock_position = "bottom"
            y = geom.y() + geom.height() - height - 10
            self.dock_btn.setText("⬇ Dock")
        
        self.move(x, y)

    def build_keys(self, layout_name):
        while self.keys_layout.count():
            item = self.keys_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if layout_name == "QWERTY":
            rows = QWERTY_ROWS
        elif layout_name in ["DEV/TERM", "DEV"]:
            rows = DEV_ROWS
        else:
            rows = NUMPAD_ROWS

        self.key_buttons = []

        for row_data in rows:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            for key_info in row_data:
                if key_info.get("type") == "char":
                    btn = SwipeKeyButton(self)
                else:
                    btn = QPushButton()
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.key_info = key_info
                
                label = key_info.get("label", "")
                if self.shift_active or self.caps_active:
                    label = key_info.get("shift_label", label.upper() if len(label) == 1 else label)
                
                # Escape ampersands so Qt does not hide them as accelerator mnemonics
                display_label = label.replace("&", "&&") if ("&" in label and "&&" not in label) else label
                btn.setText(display_label)

                span = key_info.get("span", 1.0)
                btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Expanding
                )
                btn.setMinimumWidth(int(14 * span))

                cls = key_info.get("class", "")
                if cls:
                    btn.setProperty("class", cls)

                btn.clicked.connect(lambda checked, info=key_info, button=btn: self.handle_key_click(info, button))
                
                if key_info.get("type") in ["shift", "caps", "toggle_modifier"]:
                    btn.setCheckable(True)
                    if key_info.get("type") == "shift":
                        btn.setChecked(self.shift_active)
                    elif key_info.get("type") == "caps":
                        btn.setChecked(self.caps_active)
                    elif key_info.get("type") == "toggle_modifier":
                        btn.setChecked(key_info.get("mod") in self.active_modifiers)

                row_layout.addWidget(btn, int(span * 10))
                self.key_buttons.append(btn)

            self.keys_layout.addWidget(row_widget)

    def get_active_modifiers(self) -> list:
        mods = list(self.active_modifiers)
        if self.shift_active and "LEFTSHIFT" not in mods:
            mods.append("LEFTSHIFT")
        return mods

    def _build_key_positions(self):
        positions = {}
        for btn in self.key_buttons:
            info = getattr(btn, "key_info", None)
            if not info or info.get("type") != "char":
                continue
            label = info.get("label", "")
            if len(label) == 1 and label.isalpha():
                center = btn.mapToGlobal(btn.rect().center())
                positions[label.lower()] = (center.x(), center.y())
        return positions

    def swipe_begin(self, start_btn):
        info = start_btn.key_info
        label = info.get("label", "")
        center = start_btn.mapToGlobal(start_btn.rect().center())
        if len(label) == 1 and label.isalpha():
            self._swipe_letters = [label.lower()]
            self._swipe_points = [center]
        else:
            self._swipe_letters = []
            self._swipe_points = []
        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.add_point(center)

    def swipe_update(self, global_pos):
        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.add_point(global_pos)

        widget = QApplication.widgetAt(global_pos)
        info = getattr(widget, "key_info", None) if widget else None
        if not info or info.get("type") != "char":
            return
        label = info.get("label", "").lower()
        if len(label) != 1 or not label.isalpha():
            return
        if not self._swipe_letters or self._swipe_letters[-1] != label:
            self._swipe_letters.append(label)
            self._swipe_points.append(widget.mapToGlobal(widget.rect().center()))

    def swipe_raw_start(self, pos, t_ms):
        self._swipe_raw = [(pos.x(), pos.y(), t_ms)]

    def swipe_raw_sample(self, pos, t_ms):
        self._swipe_raw.append((pos.x(), pos.y(), t_ms))

    def swipe_end(self):
        letters, points = self._swipe_letters, self._swipe_points
        raw = self._swipe_raw
        self._swipe_letters, self._swipe_points, self._swipe_raw = [], [], []

        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.start_fade()

        if len(letters) < 2 and len(raw) < 5:
            return

        try:
            key_positions = self._build_key_positions()
            raw_points = [(p.x(), p.y()) for p in points]
            candidates, backend = self.swipe_manager.decode(
                raw_points=raw_points,
                raw_trail=raw,
                key_positions=key_positions,
                top_n=5
            )
            if candidates:
                self.candidate_bar.set_candidates(candidates, backend)
        except Exception as err:
            print(f"[Swipe] Decode error: {err}", file=sys.stderr)

    def handle_key_click(self, key_info, btn):
        ktype = key_info.get("type")
        active_mods = self.get_active_modifiers()

        if ktype == "char":
            base_char = key_info.get("label", "")
            shift_char = key_info.get("shift_label", base_char.upper() if len(base_char) == 1 else base_char)
            char_to_send = shift_char if (self.shift_active or self.caps_active) else base_char

            has_non_shift_mods = any(m != "LEFTSHIFT" for m in active_mods)

            if has_non_shift_mods:
                self.engine.send_combo(active_mods, base_char)
                self.clear_modifiers()
            else:
                self.engine.type_text(char_to_send)
                if self.shift_active and not self.caps_active:
                    self.clear_modifiers()

        elif ktype == "key":
            keycode_str = key_info.get("keycode")
            if active_mods:
                self.engine.send_combo(active_mods, keycode_str)
                # Preserve latched toggle_modifiers (Ctrl, Alt, Super) for continuous navigation/scrolling
                # Only clear one-shot shift if it was not explicitly latched
                if self.shift_active and not self.caps_active and "LEFTSHIFT" not in self.active_modifiers:
                    self.shift_active = False
                    self.update_key_labels()
                    for btn in self.key_buttons:
                        info = getattr(btn, 'key_info', None)
                        if info and info.get("type") == "shift":
                            btn.setChecked(False)
            else:
                code = self.engine.get_keycode(keycode_str)
                self.engine.send_keycode(code)

        elif ktype == "shift":
            self.shift_active = not self.shift_active
            btn.setChecked(self.shift_active)
            self.update_key_labels()

        elif ktype == "caps":
            self.caps_active = not self.caps_active
            btn.setChecked(self.caps_active)
            self.update_key_labels()

        elif ktype == "toggle_modifier":
            mod = key_info.get("mod")
            if mod in self.active_modifiers:
                self.active_modifiers.remove(mod)
                btn.setChecked(False)
                if mod == "LEFTMETA":
                    code = self.engine.get_keycode("LEFTMETA")
                    self.engine.send_keycode(code)
            else:
                self.active_modifiers.add(mod)
                btn.setChecked(True)

    def update_key_labels(self):
        for btn in self.key_buttons:
            info = getattr(btn, 'key_info', None)
            if info and info.get("type") == "char":
                base_label = info.get("label", "")
                if self.shift_active or self.caps_active:
                    raw_label = info.get("shift_label", base_label.upper() if len(base_label) == 1 else base_label)
                else:
                    raw_label = base_label
                display_label = raw_label.replace("&", "&&") if ("&" in raw_label and "&&" not in raw_label) else raw_label
                btn.setText(display_label)

    def clear_modifiers(self):
        self.active_modifiers.clear()
        self.shift_active = False
        self.update_key_labels()
        for btn in self.key_buttons:
            info = getattr(btn, 'key_info', None)
            if info and info.get("type") in ["toggle_modifier", "shift"]:
                btn.setChecked(False)

    def change_layout(self, layout_name):
        self.current_layout_name = layout_name
        self.build_keys(layout_name)
        self.apply_theme(self.current_theme)

    def apply_theme(self, theme_name):
        self.current_theme = theme_name
        css = THEMES.get(theme_name, THEMES["Aurora Glass"])
        self.setStyleSheet(css)
        self.badge.setStyleSheet(css)
        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.set_theme(theme_name)

    def _badge_geometry(self, geom):
        """Bottom-right-corner (x, y) for the badge within an available-screen rect.
        Shared by position_badge() and the KWin-rule sync so both agree."""
        bw = self.badge.width()
        bh = self.badge.height()
        x = geom.x() + geom.width() - bw - 24
        y = geom.y() + geom.height() - bh - BOTTOM_CLEARANCE
        return x, y

    def _dock_geometry(self, geom):
        """Derives docked or remembered (x, y, width, height) for the main window
        within an available-screen rect."""
        if getattr(self, 'position_mode', None) == "remember" and getattr(self, 'custom_size', None):
            width, height = self.custom_size
            width = max(380, min(geom.width() - 20, width))
            height = max(160, min(geom.height() - BOTTOM_CLEARANCE - 20, height))
            if getattr(self, 'custom_pos', None):
                raw_x, raw_y = self.custom_pos
                x = max(geom.x() + 10, min(geom.x() + geom.width() - width - 10, raw_x))
                y = max(geom.y() + 10, min(geom.y() + geom.height() - height - BOTTOM_CLEARANCE, raw_y))
            else:
                x = geom.x() + int((geom.width() - width) / 2)
                y = geom.y() + geom.height() - height - BOTTOM_CLEARANCE
            return x, y, width, height

        width = int(geom.width() * 0.95)
        height = self.sizeHint().height()
        x = geom.x() + int((geom.width() - width) / 2)
        y = geom.y() + geom.height() - height - BOTTOM_CLEARANCE
        return x, y, width, height

    def position_badge(self):
        screen = QApplication.primaryScreen()
        if screen:
            x, y = self._badge_geometry(screen.availableGeometry())
            self.badge.move(x, y)

    def position_bottom(self):
        screen = QApplication.primaryScreen()
        if screen:
            x, y, width, height = self._dock_geometry(screen.availableGeometry())
            self.setGeometry(x, y, width, height)
            self.position_badge()

    def _watch_screen(self, screen):
        if screen:
            # geometryChanged covers the raw resolution swap; availableGeometryChanged
            # covers Plasma's panel/strut reflow, which can settle *after* the resolution
            # change and on its own timeline - missing it was why the dock math could
            # run against a stale (pre-reflow) available area.
            screen.geometryChanged.connect(self._on_screen_geometry_changed)
            screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)

    def _on_primary_screen_changed(self, screen):
        self._watch_screen(screen)
        self._rotation_timer.start(400)

    def _on_screen_geometry_changed(self, *_args):
        # Rotation fires several intermediate geometry updates in quick
        # succession while it animates - debounce to act once it settles.
        self._rotation_timer.start(400)

    def _handle_screen_change(self):
        self._sync_kwin_rules_to_screen()
        if self.isVisible():
            self.position_bottom()
        else:
            self.position_badge()

    def _sync_kwin_rules_to_screen(self):
        """Rewrite the badge/main KWin rule geometry to match the current screen
        and ask KWin to reload. Without this, a rotation leaves the rules pointing
        at pixel coordinates computed for the old orientation - the badge can end
        up entirely off-screen and the main window wider than the display."""
        screen = QApplication.primaryScreen()
        if not screen or not os.path.exists(KWIN_RULES_PATH):
            return
        geom = screen.availableGeometry()
        main_x, main_y, main_w, main_h = self._dock_geometry(geom)
        badge_x, badge_y = self._badge_geometry(geom)

        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read(KWIN_RULES_PATH)
            badge_section = main_section = None
            for section in config.sections():
                title = config[section].get("title", "")
                if title == KWIN_RULE_TITLE_BADGE:
                    badge_section = section
                elif title == KWIN_RULE_TITLE_MAIN:
                    main_section = section

            def kwrite(group, key, value):
                subprocess.run(
                    ["kwriteconfig6", "--file", KWIN_RULES_PATH,
                     "--group", group, "--key", key, str(value)],
                    check=False, timeout=5,
                )

            if badge_section:
                kwrite(badge_section, "position", f"{badge_x},{badge_y}")
            if main_section:
                kwrite(main_section, "position", f"{main_x},{main_y}")
                kwrite(main_section, "positionrule", "3")
                kwrite(main_section, "size", f"{main_w},{main_h}")
                kwrite(main_section, "sizerule", "3")
                # Deliberately NOT forcing sizerule to "2" (Force) here. That was
                # tried to make a rotation-driven resize apply live, but a
                # continuously-reasserted Force size rule turned out to cause the
                # main window to intermittently steal input focus while typing -
                # this app's only input method, so that regression outweighs the
                # convenience. Left at whatever it already is (originally "3",
                # Apply-once) - position still updates live (positionrule stays
                # Force, unaffected), but the new size only takes effect at the
                # next real (re)map: minimize-to-badge-and-restore, or a relaunch.

            if badge_section or main_section:
                subprocess.run(
                    ["qdbus-qt6", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"],
                    check=False, timeout=5,
                )
        except Exception as err:
            print(f"[WindowRules] Failed to sync geometry: {err}", file=sys.stderr)

    def hide_to_badge(self):
        self.hide()
        self.position_badge()
        self.badge.show()
        self.position_badge()

    def show_keyboard(self):
        self.show()
        self.position_bottom()

    def bring_to_front(self):
        if self.badge.isVisible():
            self.badge.hide()
        self.show_keyboard()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            wh = self.windowHandle()
            if wh and hasattr(wh, 'startSystemMove'):
                wh.startSystemMove()
                event.accept()
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and getattr(self, '_drag_pos', None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()
