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
    """Sleek suggestion bar displaying word candidates with instant auto-commit and responsive touch chips."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setObjectName("candidate_bar")
        self.setMinimumHeight(24)
        self.setMaximumHeight(36)

        self.auto_commit = True
        self.last_inserted_word = None

        self.bar_layout = QHBoxLayout(self)
        self.bar_layout.setContentsMargins(6, 2, 6, 2)
        self.bar_layout.setSpacing(4)
        self.chip_buttons = []

        self._placeholder_label = QLabel("✦ Swipe across keys to type")
        self._placeholder_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 11px; font-style: italic; padding: 1px 4px;")
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
            self._placeholder_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 11px; font-style: italic; padding: 1px 4px;")
            self.bar_layout.addWidget(self._placeholder_label)
            self.bar_layout.addStretch()
            return

        # Engine Badge
        tag = "⚡ FUTO" if "futo" in backend else "✦ Swipe"
        badge = QLabel(tag)
        badge.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: bold; padding: 2px 4px; background: rgba(56, 189, 248, 0.15); border-radius: 4px;")
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
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            btn.setMinimumHeight(20)
            btn.setStyleSheet("font-size: 12px; padding: 1px 6px;")
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
        # moveEvent already tracks custom_pos live during the drag; sync it to
        # the KWin rule IMMEDIATELY here rather than through the usual
        # debounced path (positionrule is Force - see _sync_kwin_rules_to_
        # screen - so as soon as the rule's stored position matches wherever
        # this drag actually ended, there's nothing left for KWin to visibly
        # snap back to; a 500ms-debounced sync would leave a window where the
        # rule still points at the OLD position and Force would visibly
        # snap back to it before catching up).
        if self.parent_window.isVisible():
            self.parent_window._save_timer.stop()
            self.parent_window.save_config_and_sync()
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
            # No manual clamping here - the window's own minimumSize/maximumSize
            # (see AuroraKeyboardWindow._apply_min_max_size) bound resize() the
            # same way regardless of what triggered it, so there's one set of
            # limits instead of a second copy that could drift out of sync.
            self.parent_window.resize(new_w, new_h)
            event.accept()

    def mouseReleaseEvent(self, event):
        # No explicit finalize needed: AuroraKeyboardWindow.resizeEvent already
        # switches to "remember" mode and persists on any non-programmatic
        # resize, which covers both this drag and a native startSystemResize
        # (which bypasses this widget's mouseMoveEvent entirely).
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

    # Must be able to shrink to a quarter of the screen's width in either
    # orientation (tiling use case) while staying tappable. Height floor is
    # about touch-target legibility, not tiling, so it's a flat value instead
    # of a fraction. These are the ONLY place size limits are defined - every
    # resize path (grip, zoom buttons, presets, remembered geometry, the KWin
    # rule sync) reads them via _size_bounds()/_clamp_size(), instead of each
    # keeping its own copy that can silently drift out of agreement.
    MIN_WIDTH_FRACTION = 0.25
    MIN_WIDTH_FLOOR = 240
    # 95 (the original value) let a manual grip-drag squash 5 key rows into
    # illegible overlapping mush - measured what 5 rows actually need to stay
    # tappable/legible and raised the floor accordingly. The scale presets no
    # longer shrink height at all (see on_scale_preset_selected), so this floor
    # now mainly guards a manual resize-grip drag rather than everyday use.
    MIN_HEIGHT_FLOOR = 220

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
        self._programmatic_geometry = False

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

    def _orientation_key(self, geom=None):
        """Landscape/portrait presets are kept separate because a single
        remembered position/size doesn't translate well between them - a
        spot picked for a wide-short window doesn't suit a narrow-tall one,
        and vice versa. Determined by aspect, not a fixed rotation angle, so
        it works the same regardless of which way the screen actually turns."""
        if geom is None:
            screen = QApplication.primaryScreen()
            geom = screen.availableGeometry() if screen else None
        if geom is None or geom.height() <= 0:
            return "landscape"
        return "landscape" if geom.width() >= geom.height() else "portrait"

    def load_config(self):
        self.position_mode = "default"
        self.custom_size = None
        self.custom_pos = None
        self.orientation_presets = {"landscape": None, "portrait": None}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.position_mode = data.get("position_mode", "default")
                    presets = data.get("orientation_presets")
                    if presets:
                        for key in ("landscape", "portrait"):
                            entry = presets.get(key)
                            if entry and entry.get("pos") and entry.get("size"):
                                self.orientation_presets[key] = {"pos": entry["pos"], "size": entry["size"]}
                    else:
                        # Migrating from the old single-preset format: seed
                        # whichever orientation is currently active, since
                        # that's presumably where this position/size came from.
                        legacy_size = data.get("custom_size")
                        legacy_pos = data.get("custom_pos")
                        if legacy_size and legacy_pos:
                            self.orientation_presets[self._orientation_key()] = {"pos": legacy_pos, "size": legacy_size}
                    current = self.orientation_presets.get(self._orientation_key())
                    if current:
                        self.custom_pos = list(current["pos"])
                        self.custom_size = list(current["size"])
                    if "theme" in data and data["theme"] in THEMES:
                        self.current_theme = data["theme"]
            except Exception as e:
                print(f"[Config] Error loading: {e}", file=sys.stderr)

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            # self.custom_pos/custom_size are always "whatever's live right
            # now" (every drag/resize writes here - see resizeEvent,
            # moveEvent, _apply_custom_geometry, on_size_mode_changed); saving
            # buckets that snapshot into whichever orientation is currently
            # active, leaving the OTHER orientation's preset untouched.
            if self.custom_pos and self.custom_size:
                self.orientation_presets[self._orientation_key()] = {
                    "pos": self.custom_pos, "size": self.custom_size,
                }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "position_mode": self.position_mode,
                    "orientation_presets": self.orientation_presets,
                    "theme": self.current_theme,
                    "layout": self.current_layout_name
                }, f, indent=2)
        except Exception as e:
            print(f"[Config] Error saving: {e}", file=sys.stderr)

    def save_config_and_sync(self):
        self.save_config()
        self._sync_kwin_rules_to_screen()

    # Below this width, the action bar's ~16 controls physically can't fit -
    # hide the least essential ones rather than let them overlap/clip.
    TOOLBAR_DENSITY_THRESHOLD = 560

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.setGeometry(self.rect())
        self._update_responsive_typography()
        self._update_toolbar_density()
        self._sync_scale_preset_label()
        # Any resize that isn't this app's own programmatic geometry application
        # (docking, a rotation reposition, _apply_custom_geometry) is a live user
        # drag - including a native startSystemResize, which bypasses
        # TouchResizeGrip's own mouseMoveEvent entirely and resizes the window
        # directly via the compositor. Treat it the same way _apply_custom_geometry
        # does: switch to "remember" so it sticks instead of reverting on the next
        # reposition, and persist (debounced).
        if self.isVisible() and not getattr(self, '_programmatic_geometry', False):
            self.position_mode = "remember"
            self.custom_size = [self.width(), self.height()]
            p = self.pos()
            self.custom_pos = [p.x(), p.y()]
            self._save_timer.start(500)

    def moveEvent(self, event):
        super().moveEvent(event)
        # Same rationale as resizeEvent above: any move that isn't this app's
        # own programmatic geometry application is a live user drag - via the
        # drag handle's startSystemMove(), its manual-fallback path, or
        # clicking the window body directly - and should stick instead of
        # reverting on the next reposition (positionrule is intentionally
        # Apply-once, not Force - see _sync_kwin_rules_to_screen - so nothing
        # else keeps a drag from being silently discarded).
        if self.isVisible() and not getattr(self, '_programmatic_geometry', False):
            self.position_mode = "remember"
            p = self.pos()
            self.custom_pos = [p.x(), p.y()]
            self._save_timer.start(500)

    def _update_responsive_typography(self):
        if not hasattr(self, 'keys_container') or not getattr(self, 'key_buttons', None):
            return
        total_h = self.keys_container.height()
        num_rows = self.keys_layout.count()
        if total_h > 20 and num_rows > 0:
            # Subtract inter-row spacing before dividing - treating the full
            # container height as available to the rows (ignoring the 4px gaps
            # between them) overestimated each row's real budget, so the
            # min-height set below could exceed what a row actually had to give
            # it. The button was then taller than its own parent row widget,
            # which clips it - the visible symptom was rounded top corners but
            # flat-cut bottom ones, where the clip line fell.
            spacing_total = self.keys_layout.spacing() * max(0, num_rows - 1)
            row_h = (total_h - spacing_total) / num_rows
            font_px = max(8, min(int(row_h * 0.42), 22))
            padding_px = 0 if row_h < 25 else 2
            # Every theme's base QPushButton rule fixes min-height at 48px
            # (styles.py). At small scales the window is shorter than 5 rows *
            # 48px, so without overriding it here the layout can't satisfy every
            # button's minimum and rows overlap/clip - which is what made key
            # labels disappear entirely at 50%/25%. Apply to ALL keys, not just
            # "char" ones - Tab/Shift/Enter/Ctrl/Space/arrows are still fixed at
            # 48px otherwise and don't shrink with everything else.
            #
            # Height is set via setFixedHeight(), NOT the "min-height" QSS
            # property above - QSS min-height turned out to be a hint the native
            # widget style can still override with its own font-metrics-based
            # content minimum, so the button ended up taller than its own parent
            # row widget and got clipped by it (rounded top corners, flat-cut
            # bottom ones, since that's where the clip line fell). setFixedHeight
            # is a hard Qt-level constraint the style can't override.
            min_h_px = max(14, int(row_h) - 2)
            style = f"font-size: {font_px}px; padding: {padding_px}px 0px;"
            for btn in self.key_buttons:
                btn.setStyleSheet(style)
                btn.setFixedHeight(min_h_px)

    def _update_toolbar_density(self):
        """Below TOOLBAR_DENSITY_THRESHOLD, the action bar's ~16 controls can't
        all fit - hide the ones that are safe to lose (dock toggle, layout
        picker, theme picker) rather than let them overlap illegibly. Resize
        grip, drag handle, zoom controls, size mode, and minimize/close always
        stay - explicitly requested, since those are needed at any size."""
        if not all(hasattr(self, attr) for attr in ('dock_btn', 'layout_box', 'theme_box')):
            return
        roomy = self.width() >= self.TOOLBAR_DENSITY_THRESHOLD
        self.dock_btn.setVisible(roomy)
        self.layout_box.setVisible(roomy)
        self.theme_box.setVisible(roomy)

    _SCALE_PRESETS = (
        ("25% (Mini)", 0.25), ("50% (1/4 Tile)", 0.50), ("75% (Compact)", 0.75),
        ("100% (Standard)", 1.0), ("125% (Large)", 1.25),
    )

    def _sync_scale_preset_label(self):
        """Keep the preset dropdown showing whatever percentage the current
        width actually is, regardless of how it got there (+/- buttons, the
        resize grip, or the dropdown itself) - otherwise the dropdown shows a
        stale label the moment any other control changes the size."""
        screen = QApplication.primaryScreen()
        if not screen or not hasattr(self, 'scale_preset_box'):
            return
        base_w = int(screen.availableGeometry().width() * 0.95)
        if base_w <= 0:
            return
        fraction = self.width() / base_w
        closest_label = min(self._SCALE_PRESETS, key=lambda p: abs(p[1] - fraction))[0]
        if self.scale_preset_box.currentText() != closest_label:
            self.scale_preset_box.blockSignals(True)
            self.scale_preset_box.setCurrentText(closest_label)
            self.scale_preset_box.blockSignals(False)

    def on_size_mode_changed(self, text):
        if "Auto-Dock" in text:
            self.position_mode = "default"
            self.position_bottom()
        else:
            self.position_mode = "remember"
            self.custom_size = [self.width(), self.height()]
            p = self.pos()
            self.custom_pos = [p.x(), p.y()]
        self.save_config_and_sync()

    def _size_bounds(self, geom):
        """Single source of truth for min/max keyboard size, in terms of the
        given available-screen rect. Everything that constrains size - Qt's own
        minimumSize/maximumSize, the remembered-geometry clamp, and the KWin
        rule sync - reads from here instead of keeping its own copy."""
        min_w = max(self.MIN_WIDTH_FLOOR, int(geom.width() * self.MIN_WIDTH_FRACTION))
        min_h = self.MIN_HEIGHT_FLOOR
        max_w = max(min_w, geom.width() - 20)
        max_h = max(min_h, geom.height() - BOTTOM_CLEARANCE - 20)
        return min_w, min_h, max_w, max_h

    def _clamp_size(self, w, h, geom):
        min_w, min_h, max_w, max_h = self._size_bounds(geom)
        return max(min_w, min(max_w, w)), max(min_h, min(max_h, h))

    def _clamp_position(self, x, y, w, h, geom):
        x = max(geom.x() + 10, min(geom.x() + geom.width() - w - 10, x))
        y = max(geom.y() + 10, min(geom.y() + geom.height() - h - BOTTOM_CLEARANCE, y))
        return x, y

    def _apply_min_max_size(self):
        """Set real Qt/Wayland min/max size hints so the bounds hold even for a
        native compositor-driven resize (startSystemResize), which bypasses
        this app's own drag math entirely and would otherwise ignore it."""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        min_w, min_h, max_w, max_h = self._size_bounds(screen.availableGeometry())
        self.setMinimumSize(min_w, min_h)
        self.setMaximumSize(max_w, max_h)

    def _apply_custom_geometry(self, x, y, w, h):
        """Single entry point for every manual resize (grip, zoom buttons,
        presets): clamps to the current screen, switches to 'remember' mode so
        the change actually sticks instead of reverting on the next reposition,
        and persists via the debounced save+sync."""
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None
        if geom:
            w, h = self._clamp_size(w, h, geom)
            x, y = self._clamp_position(x, y, w, h, geom)
        self._programmatic_geometry = True
        self.setGeometry(x, y, w, h)
        self._programmatic_geometry = False
        self.position_mode = "remember"
        self.custom_size = [self.width(), self.height()]
        p = self.pos()
        self.custom_pos = [p.x(), p.y()]
        self._save_timer.start(500)

    def scale_keyboard(self, factor: float):
        """The +/- buttons and the preset dropdown must agree on what "size"
        means, or picking a preset then nudging with +/- (or vice versa)
        produces a size that matches neither - which is what made the two
        controls look disconnected. Same rule as presets: only width changes,
        height stays natural."""
        cur_pos = self.pos()
        new_w = int(self.width() * factor)
        natural_h = getattr(self, '_natural_height', None) or self.sizeHint().height()
        self._apply_custom_geometry(cur_pos.x(), cur_pos.y(), new_w, natural_h)

    def on_scale_preset_selected(self, text: str):
        """These presets are about fitting into a narrower tiled column, not
        about shrinking every direction - the keyboard's natural height already
        comfortably fits within half of either orientation's screen height, so
        there's nothing to gain by shrinking it too. Only width scales with the
        selected percentage; height stays at its natural size regardless (still
        manually adjustable with the resize grip, which has its own floor)."""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        base_w = int(geom.width() * 0.95)
        natural_h = getattr(self, '_natural_height', None) or self.sizeHint().height()

        # startswith, not "in" - "25%" is a substring of "125% (Large)" too
        fraction = next((f for label, f in self._SCALE_PRESETS if text.startswith(label.split()[0])), 1.0)
        target_w = int(base_w * fraction)

        cur_pos = self.pos()
        self._apply_custom_geometry(cur_pos.x(), cur_pos.y(), target_w, natural_h)

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
        self.main_layout.setContentsMargins(8, 4, 8, 8)
        self.main_layout.setSpacing(3)

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

        # Scale Presets (including 25% Mini and 50% 1/4 Tile)
        self.scale_preset_box = QComboBox()
        self.scale_preset_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scale_preset_box.addItems(["25% (Mini)", "50% (1/4 Tile)", "75% (Compact)", "100% (Standard)", "125% (Large)"])
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
            row_layout.setSpacing(2)

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
                btn.setMinimumWidth(int(8 * span))

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
        # Cache the natural (unshrunk) height now that the theme's real font
        # size / min-height CSS is actually applied to the current buttons -
        # measuring any earlier (e.g. right after build_keys(), before any
        # stylesheet exists) would capture Qt's bare default button metrics
        # instead of the real themed size. Used as the "100%" reference by
        # on_scale_preset_selected/_dock_geometry instead of a live sizeHint(),
        # which would otherwise drift smaller every time a shrink already
        # applied a smaller min-height override to these same button objects.
        if hasattr(self, 'key_buttons'):
            self._natural_height = self.sizeHint().height()

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
        within an available-screen rect. 'remember' replays whichever
        orientation preset (see _orientation_key) matches this geom - landscape
        and portrait are remembered independently, since a position/size that
        suits one doesn't suit the other - clamped to the current screen via
        the same _clamp_size/_clamp_position every other resize path uses.
        Otherwise this is the original default: 95%-width, sizeHint()-height,
        bottom-docked and centered - unchanged from before the resize/toggle
        features existed."""
        if getattr(self, 'position_mode', None) == "remember":
            preset = getattr(self, 'orientation_presets', {}).get(self._orientation_key(geom))
            if preset:
                width, height = self._clamp_size(preset["size"][0], preset["size"][1], geom)
                x, y = self._clamp_position(preset["pos"][0], preset["pos"][1], width, height, geom)
                return x, y, width, height

        width = int(geom.width() * 0.95)
        height = getattr(self, '_natural_height', None) or self.sizeHint().height()
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
            self._apply_min_max_size()
            x, y, width, height = self._dock_geometry(screen.availableGeometry())
            self._programmatic_geometry = True
            self.setGeometry(x, y, width, height)
            self._programmatic_geometry = False
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
        # positionrule is Apply-once (3), not Force - dragging needs Apply-
        # once (see _sync_kwin_rules_to_screen), which costs us live position
        # updates on rotation: Wayland lets a client set its own SIZE
        # directly regardless of rule strength, so that still follows a
        # rotation correctly via the hide()+show() remap below, but POSITION
        # is exclusively the compositor's call and Apply-once doesn't
        # reliably re-fire on that remap - it falls back to KWin's own
        # default (centered) placement instead. Known limitation for now;
        # dragging matters more day to day. The correct per-orientation
        # target is still written into the rule file below either way (via
        # _dock_geometry's per-orientation preset lookup), so a manual drag
        # right after rotating, or the next full relaunch, lands correctly.
        self._sync_kwin_rules_to_screen()
        self._apply_min_max_size()
        # Refresh the live custom_pos/custom_size to whatever preset matches
        # the NEW orientation, so a drag/resize right after rotating updates
        # that orientation's preset instead of overwriting it with stale
        # values carried over from the orientation just left.
        preset = getattr(self, 'orientation_presets', {}).get(self._orientation_key())
        if preset:
            self.custom_pos = list(preset["pos"])
            self.custom_size = list(preset["size"])
        if self.isVisible():
            self.hide()
            self.position_bottom()
            self.show()
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
                # Apply-once (3), not Force (2). Force was tried twice this
                # session to make rotation reposition the window live - it
                # does, reliably (confirmed via an isolated test window, see
                # WINDOW_RULES.md) - but a Force position rule also appears to
                # block KWin's interactive move grab outright, not just snap
                # back after a drag: syncing the rule to match on every
                # drag-release (still done below, in DragHandleLabel/
                # AuroraKeyboardWindow.mouseReleaseEvent - harmless and still
                # useful for the next remap) did not bring dragging back.
                # Dragging is the more load-bearing feature, so this stays
                # Apply-once; a rotation currently only reliably updates SIZE
                # live (Wayland lets a client set that directly regardless of
                # rule strength) and falls back to KWin's own default
                # placement for position. Revisit with a heavier fix (fully
                # recreating the window on rotation, forcing a genuine new
                # xdg_toplevel mapping) in a future session if needed.
                kwrite(main_section, "positionrule", "3")
                kwrite(main_section, "size", f"{main_w},{main_h}")
                # sizerule deliberately stays Apply-once (3), not Force (2): a
                # continuously-reasserted Force *size* rule caused the main
                # window to intermittently steal input focus while typing -
                # this app's only input method, so that regression outweighs
                # live-resizing on rotation. Size only catches up at the next
                # real (re)map: minimize-to-badge-and-restore, or a relaunch.
                kwrite(main_section, "sizerule", "3")

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
        # Same immediate (non-debounced) sync as DragHandleLabel.mouseReleaseEvent
        # - see the comment there for why this needs to happen right away
        # rather than through the usual debounced path.
        if self.isVisible():
            self._save_timer.stop()
            self.save_config_and_sync()
        event.accept()
