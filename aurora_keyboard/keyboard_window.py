"""
Main PyQt6 Window for Aurora Touch Keyboard with evdev.UInput, KWin Wayland dragging,
glowing gesture trail overlay, FUTO neural swipe-to-type, and orientation view profiles.
"""

import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QScreen, QCloseEvent

from .key_engine import KeyEngine
from .layouts import QWERTY_ROWS, DEV_ROWS, NUMPAD_ROWS
from .styles import THEMES
from .swipe import SwipeManager
from .geometry_manager import (
    GeometryManager, OrientationProfile, BOTTOM_CLEARANCE,
    MIN_WIDTH_FRACTION, MIN_WIDTH_FLOOR, MIN_HEIGHT_FLOOR
)
from .widgets import (
    SwipeTrailOverlay, CandidateBar, DragHandleLabel,
    TouchResizeGrip, FloatingBadge, SwipeKeyButton
)


class AuroraKeyboardWindow(QWidget):
    """Main Frameless On-Screen Keyboard Window."""

    # Toolbar density threshold: below this width, hide non-essential action buttons
    TOOLBAR_DENSITY_THRESHOLD = 580

    _SCALE_PRESETS = (
        ("25% (Mini)", 0.25),
        ("50% (1/4 Tile)", 0.50),
        ("75% (Compact)", 0.75),
        ("100% (Standard)", 1.0),
        ("125% (Large)", 1.25),
    )

    def __init__(self):
        super().__init__()
        self.setObjectName("keyboard_root")
        self.setWindowTitle("Aurora Touch Keyboard Main")

        self.geometry_mgr = GeometryManager()
        self.geometry_mgr.load_config()

        self.engine = KeyEngine()
        self.swipe_manager = SwipeManager()

        self.shift_active = False
        self.caps_active = False
        self.active_modifiers = set()

        self.current_layout_name = self.geometry_mgr.current_layout or "QWERTY"
        self.current_theme = self.geometry_mgr.current_theme or "Aurora Glass"
        self.dock_position = "bottom"
        self._programmatic_geometry = False
        self._natural_height = 360

        self.badge = FloatingBadge(self)
        self._drag_pos = None

        # Swipe gesture state
        self._swipe_points = []
        self._swipe_letters = []
        self._swipe_raw = []

        # Debounced save/sync timer
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_config_and_sync)

        self.apply_flags()
        self.init_ui()

        # Swipe Trail Overlay
        self.trail_overlay = SwipeTrailOverlay(self)
        self.trail_overlay.setGeometry(self.rect())
        self.trail_overlay.show()

        # Apply initial theme & measure natural height
        self.apply_theme(self.current_theme)

        # Apply initial geometry
        self.apply_orientation_geometry()

        # Rotation & screen watcher
        self._rotation_timer = QTimer(self)
        self._rotation_timer.setSingleShot(True)
        self._rotation_timer.timeout.connect(self._handle_screen_change)
        self._watch_screen(QApplication.primaryScreen())

        app = QApplication.instance()
        if app:
            app.primaryScreenChanged.connect(self._on_primary_screen_changed)
            app.aboutToQuit.connect(self._on_about_to_quit)

        # Initial KWin rule synchronization
        self.geometry_mgr.sync_kwin_rules(self.geometry(), self._natural_height)

    # --- Property bridges for backward compatibility ---
    @property
    def position_mode(self) -> str:
        return self.geometry_mgr.position_mode

    @position_mode.setter
    def position_mode(self, val: str):
        self.geometry_mgr.position_mode = val

    @property
    def orientation_presets(self) -> dict:
        return {k: (v.to_dict() if v else None) for k, v in self.geometry_mgr.profiles.items()}

    def _orientation_key(self, geom=None) -> str:
        return self.geometry_mgr.get_orientation_key(geom)

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

        # Drag Handle Grip
        self.drag_label = DragHandleLabel("❖ Drag", self)
        bar_layout.addWidget(self.drag_label)

        # Quick Actions
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

        # Calibration / Lock Placement Button
        self.lock_preset_btn = QPushButton("📌 Set Default")
        self.lock_preset_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lock_preset_btn.setFixedHeight(28)
        self.lock_preset_btn.setToolTip("Lock current placement as default preset for this orientation")
        self.lock_preset_btn.setStyleSheet("""
            QPushButton {
                background: rgba(56, 189, 248, 0.2);
                border: 1px solid rgba(56, 189, 248, 0.5);
                color: #38bdf8;
                font-size: 11px;
                font-weight: bold;
                padding: 0 6px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.4);
                color: #ffffff;
            }
        """)
        self.lock_preset_btn.clicked.connect(self.sample_current_placement)
        bar_layout.addWidget(self.lock_preset_btn)

        # Touch Zoom Out Button
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        zoom_out_btn.setFixedSize(26, 28)
        zoom_out_btn.setToolTip("Shrink keyboard width (-10%)")
        zoom_out_btn.setStyleSheet("font-size: 15px; font-weight: bold;")
        zoom_out_btn.clicked.connect(lambda: self.scale_keyboard(0.90))
        bar_layout.addWidget(zoom_out_btn)

        # Scale Presets
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
        zoom_in_btn.setToolTip("Enlarge keyboard width (+10%)")
        zoom_in_btn.setStyleSheet("font-size: 15px; font-weight: bold;")
        zoom_in_btn.clicked.connect(lambda: self.scale_keyboard(1.10))
        bar_layout.addWidget(zoom_in_btn)

        # Touch Corner Resize Grip
        self.resize_grip = TouchResizeGrip(self)
        bar_layout.addWidget(self.resize_grip)

        # Size / Position Mode Selector
        self.size_mode_box = QComboBox()
        self.size_mode_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.size_mode_box.addItems(["Remember", "Auto-Dock"])
        if self.geometry_mgr.position_mode == "default":
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
        if self.current_layout_name in ["DEV/TERM", "DEV"]:
            self.layout_box.setCurrentText("DEV")
        elif self.current_layout_name in ["NUMPAD", "NUM"]:
            self.layout_box.setCurrentText("NUM")
        else:
            self.layout_box.setCurrentText("QWERTY")
        self.layout_box.currentTextChanged.connect(self.change_layout)
        bar_layout.addWidget(self.layout_box)

        # Theme Selector
        self.theme_box = QComboBox()
        self.theme_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.theme_box.addItems(list(THEMES.keys()))
        self.theme_box.setCurrentText(self.current_theme)
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
        close_btn.clicked.connect(self.close)
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
        self.build_keys(self.current_layout_name)

    def _apply_min_max_size(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        min_w, min_h, max_w, max_h = self.geometry_mgr.get_size_bounds(screen.availableGeometry())
        self.setMinimumSize(min_w, min_h)
        self.setMaximumSize(max_w, max_h)

    def apply_orientation_geometry(self):
        """Applies target geometry for the current orientation view and moves the window via KWin."""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        orient = self.geometry_mgr.get_orientation_key(geom)
        self._apply_min_max_size()

        x, y, w, h = self.geometry_mgr.get_geometry_for_orientation(orient, geom, self._natural_height)
        self._programmatic_geometry = True
        self.setGeometry(x, y, w, h)
        self._programmatic_geometry = False

        # Directly move on KWin Wayland compositor
        self.geometry_mgr.set_window_geometry_kwin("Aurora Touch Keyboard Main", x, y, w, h)
        self.position_badge()

    def position_bottom(self):
        self.apply_orientation_geometry()

    def position_badge(self):
        screen = QApplication.primaryScreen()
        if screen:
            x, y = self.geometry_mgr.compute_badge_geometry(screen.availableGeometry())
            self.badge.move(x, y)
            self.geometry_mgr.set_window_geometry_kwin("Aurora Touch Keyboard Badge", x, y, 160, 160)

    def sample_current_placement(self):
        """Programmatically samples the current geometry as the preset for this orientation view."""
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None
        orient = self.geometry_mgr.get_orientation_key(geom)
        p = self.pos()
        self.geometry_mgr.sample_and_set_profile(orient, p.x(), p.y(), self.width(), self.height(), self.dock_position)
        self.save_config_and_sync()
        if hasattr(self, 'candidate_bar'):
            self.candidate_bar.show_toast(f"✓ Locked {orient.capitalize()} preset ({self.width()}×{self.height()} at {p.x()},{p.y()})")

    def save_config_and_sync(self):
        self.geometry_mgr.current_theme = self.current_theme
        self.geometry_mgr.current_layout = self.current_layout_name
        self.geometry_mgr.save_config()
        self.geometry_mgr.sync_kwin_rules(self.geometry(), self._natural_height)

    def on_user_drag_finished(self):
        """Called immediately after a touch/mouse drag releases."""
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None
        orient = self.geometry_mgr.get_orientation_key(geom)
        p = self.pos()
        self.geometry_mgr.sample_and_set_profile(orient, p.x(), p.y(), self.width(), self.height(), self.dock_position)
        self._save_timer.stop()
        self.save_config_and_sync()

    def _watch_screen(self, screen):
        if screen:
            screen.geometryChanged.connect(self._on_screen_geometry_changed)
            screen.availableGeometryChanged.connect(self._on_screen_geometry_changed)

    def _on_primary_screen_changed(self, screen):
        self._watch_screen(screen)
        self._rotation_timer.start(400)

    def _on_screen_geometry_changed(self, *_args):
        self._rotation_timer.start(400)

    def _handle_screen_change(self):
        """Handles tablet orientation or resolution switch seamlessly."""
        self._apply_min_max_size()
        self.apply_orientation_geometry()
        self._update_responsive_typography()
        self._update_toolbar_density()
        self.geometry_mgr.sync_kwin_rules(self.geometry(), self._natural_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.setGeometry(self.rect())
        self._update_responsive_typography()
        self._update_toolbar_density()
        self._sync_scale_preset_label()

        if self.isVisible() and not getattr(self, '_programmatic_geometry', False):
            screen = QApplication.primaryScreen()
            geom = screen.availableGeometry() if screen else None
            orient = self.geometry_mgr.get_orientation_key(geom)
            p = self.pos()
            self.geometry_mgr.sample_and_set_profile(orient, p.x(), p.y(), self.width(), self.height(), self.dock_position)
            self._save_timer.start(500)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible() and not getattr(self, '_programmatic_geometry', False):
            screen = QApplication.primaryScreen()
            geom = screen.availableGeometry() if screen else None
            orient = self.geometry_mgr.get_orientation_key(geom)
            p = self.pos()
            self.geometry_mgr.sample_and_set_profile(orient, p.x(), p.y(), self.width(), self.height(), self.dock_position)
            self._save_timer.start(500)

    def closeEvent(self, event: QCloseEvent):
        """Ensures active window geometry is saved and synced upon closing."""
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None
        orient = self.geometry_mgr.get_orientation_key(geom)
        p = self.pos()
        self.geometry_mgr.sample_and_set_profile(orient, p.x(), p.y(), self.width(), self.height(), self.dock_position)
        self.save_config_and_sync()
        event.accept()
        QApplication.instance().quit()

    def _on_about_to_quit(self):
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None
        orient = self.geometry_mgr.get_orientation_key(geom)
        p = self.pos()
        if p.x() > 0 or p.y() > 0:
            self.geometry_mgr.sample_and_set_profile(orient, p.x(), p.y(), self.width(), self.height(), self.dock_position)
        self.geometry_mgr.save_config()

    def _update_responsive_typography(self):
        if not hasattr(self, 'keys_container') or not getattr(self, 'key_buttons', None):
            return
        total_h = self.keys_container.height()
        num_rows = self.keys_layout.count()
        if total_h > 20 and num_rows > 0:
            spacing_total = self.keys_layout.spacing() * max(0, num_rows - 1)
            row_h = (total_h - spacing_total) / num_rows
            font_px = max(8, min(int(row_h * 0.42), 22))
            padding_px = 0 if row_h < 25 else 2
            min_h_px = max(14, int(row_h) - 2)
            style = f"font-size: {font_px}px; padding: {padding_px}px 0px;"
            for btn in self.key_buttons:
                btn.setStyleSheet(style)
                btn.setFixedHeight(min_h_px)

    def _update_toolbar_density(self):
        if not all(hasattr(self, attr) for attr in ('dock_btn', 'layout_box', 'theme_box', 'lock_preset_btn')):
            return
        roomy = self.width() >= self.TOOLBAR_DENSITY_THRESHOLD
        self.dock_btn.setVisible(roomy)
        self.layout_box.setVisible(roomy)
        self.theme_box.setVisible(roomy)
        self.lock_preset_btn.setVisible(roomy)

    def _sync_scale_preset_label(self):
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
            self.geometry_mgr.position_mode = "default"
            self.position_bottom()
        else:
            self.geometry_mgr.position_mode = "remember"
            self.sample_current_placement()
        self.save_config_and_sync()

    def _apply_custom_geometry(self, x, y, w, h):
        screen = QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else None
        if geom:
            w, h = self.geometry_mgr.clamp_size(w, h, geom)
            x, y = self.geometry_mgr.clamp_position(x, y, w, h, geom)
        self._programmatic_geometry = True
        self.setGeometry(x, y, w, h)
        self._programmatic_geometry = False
        self.geometry_mgr.set_window_geometry_kwin("Aurora Touch Keyboard Main", x, y, w, h)
        orient = self.geometry_mgr.get_orientation_key(geom)
        self.geometry_mgr.sample_and_set_profile(orient, x, y, w, h, self.dock_position)
        self._save_timer.start(500)

    def scale_keyboard(self, factor: float):
        cur_pos = self.pos()
        new_w = int(self.width() * factor)
        natural_h = self._natural_height
        self._apply_custom_geometry(cur_pos.x(), cur_pos.y(), new_w, natural_h)

    def on_scale_preset_selected(self, text: str):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geom = screen.availableGeometry()
        base_w = int(geom.width() * 0.95)
        natural_h = self._natural_height

        fraction = next((f for label, f in self._SCALE_PRESETS if text.startswith(label.split()[0])), 1.0)
        target_w = int(base_w * fraction)

        cur_pos = self.pos()
        self._apply_custom_geometry(cur_pos.x(), cur_pos.y(), target_w, natural_h)

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
            y = geom.y() + geom.height() - height - BOTTOM_CLEARANCE
            self.dock_btn.setText("⬇ Dock")

        self._apply_custom_geometry(x, y, width, height)

    def build_keys(self, layout_name: str):
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
                    label = key_info.get("shift_label", label.upper() if len(base_label := label) == 1 else label)

                display_label = label.replace("&", "&&") if ("&" in label and "&&" not in label) else label
                btn.setText(display_label)

                span = key_info.get("span", 1.0)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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

    def change_layout(self, layout_name: str):
        self.current_layout_name = layout_name
        self.build_keys(layout_name)
        self.apply_theme(self.current_theme)

    def apply_theme(self, theme_name: str):
        self.current_theme = theme_name
        css = THEMES.get(theme_name, THEMES["Aurora Glass"])
        self.setStyleSheet(css)
        self.badge.setStyleSheet(css)
        if hasattr(self, 'trail_overlay'):
            self.trail_overlay.set_theme(theme_name)
        if hasattr(self, 'key_buttons'):
            self._natural_height = max(MIN_HEIGHT_FLOOR, self.sizeHint().height())

    def hide_to_badge(self):
        self.hide()
        self.position_badge()
        self.badge.show()
        self.position_badge()

    def show_keyboard(self):
        self.show()
        self.apply_orientation_geometry()

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
        if self.isVisible():
            self.on_user_drag_finished()
        event.accept()
