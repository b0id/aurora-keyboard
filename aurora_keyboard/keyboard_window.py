"""
Main PyQt6 Window for Aurora Touch Keyboard with evdev.UInput and KWin Wayland dragging.
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QScreen

from .key_engine import KeyEngine
from .layouts import QWERTY_ROWS, DEV_ROWS, NUMPAD_ROWS
from .styles import THEMES


class DragHandleLabel(QLabel):
    """Custom Label for initiating Wayland KWin system move via touch/mouse."""

    def __init__(self, text, parent_window):
        super().__init__(text)
        self.parent_window = parent_window
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("""
            color: #38bdf8;
            font-weight: bold;
            font-size: 14px;
            padding: 4px 12px;
            background: rgba(56, 189, 248, 0.2);
            border: 1px solid rgba(56, 189, 248, 0.5);
            border-radius: 6px;
        """)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            wh = self.parent_window.windowHandle()
            if wh and hasattr(wh, 'startSystemMove'):
                wh.startSystemMove()
                event.accept()
            else:
                self.parent_window._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and getattr(self.parent_window, '_drag_pos', None) is not None:
            self.parent_window.move(event.globalPosition().toPoint() - self.parent_window._drag_pos)
            event.accept()


class FloatingBadge(QWidget):
    """Small floating widget that stays on screen corner to re-open keyboard."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setObjectName("floating_badge")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(56, 56)
        self.setToolTip("Open Aurora Touch Keyboard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn = QPushButton("⌨", self)
        self.btn.setObjectName("badge_btn")
        self.btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.btn.clicked.connect(self.on_click)
        layout.addWidget(self.btn)

        self._drag_pos = None

    def on_click(self):
        self.parent_window.bring_to_front()

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
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


class AuroraKeyboardWindow(QWidget):
    """Main Frameless On-Screen Keyboard Window."""

    def __init__(self):
        super().__init__()
        self.setObjectName("keyboard_root")
        self.engine = KeyEngine()
        
        self.shift_active = False
        self.caps_active = False
        self.active_modifiers = set()
        
        self.current_layout_name = "QWERTY"
        self.current_theme = "Aurora Glass"
        self.dock_position = "bottom"
        
        self.badge = FloatingBadge(self)
        self._drag_pos = None

        self.apply_flags()
        self.init_ui()
        self.position_bottom()
        self.apply_theme(self.current_theme)

    def apply_flags(self):
        """Set window flags for stay-on-top, frameless, and non-focusing."""
        # Note: BypassWindowManagerHint is deliberately omitted. It has no
        # real equivalent in the Wayland protocol (unlike X11 override-redirect),
        # and on KWin/Wayland it can leave the surface uncomposited/invisible,
        # including on re-show after hide_to_badge(). Dragging is handled via
        # windowHandle().startSystemMove() instead, which doesn't need it.
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
        self.main_layout.setSpacing(6)

        # Top Drag & Action Bar
        self.action_bar = QFrame(self)
        self.action_bar.setObjectName("action_bar")
        bar_layout = QHBoxLayout(self.action_bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(6)

        # Drag Handle Grip Button
        self.drag_label = DragHandleLabel("❖ Drag Keyboard", self)
        bar_layout.addWidget(self.drag_label)

        # Quick Actions
        actions = [
            ("All", lambda: self.engine.send_combo(self.get_active_modifiers() or ["LEFTCTRL"], "a")),
            ("Copy", lambda: self.engine.send_combo(self.get_active_modifiers() or ["LEFTCTRL"], "c")),
            ("Paste", lambda: self.engine.send_combo(self.get_active_modifiers() or ["LEFTCTRL"], "v")),
            ("Undo", lambda: self.engine.send_combo(self.get_active_modifiers() or ["LEFTCTRL"], "z")),
            ("Esc", lambda: self.engine.send_keycode(self.engine.get_keycode("ESC"))),
            ("Tab", lambda: self.engine.send_keycode(self.engine.get_keycode("TAB"))),
        ]
        for name, callback in actions:
            btn = QPushButton(name)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedHeight(34)
            btn.setStyleSheet("padding: 0 8px; font-size: 13px;")
            btn.clicked.connect(callback)
            bar_layout.addWidget(btn)

        bar_layout.addStretch()

        # Dock Toggle Button (Bottom / Top)
        self.dock_btn = QPushButton("⬇ Dock")
        self.dock_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dock_btn.setFixedHeight(34)
        self.dock_btn.clicked.connect(self.toggle_dock)
        bar_layout.addWidget(self.dock_btn)

        # Layout Selector
        self.layout_box = QComboBox()
        self.layout_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.layout_box.addItems(["QWERTY", "DEV/TERM", "NUMPAD"])
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
        min_btn.setFixedSize(34, 34)
        min_btn.clicked.connect(self.hide_to_badge)
        bar_layout.addWidget(min_btn)

        # Close Button
        close_btn = QPushButton("✕")
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setFixedSize(34, 34)
        close_btn.setObjectName("close_btn")
        close_btn.setStyleSheet("background: rgba(239, 68, 68, 0.4); color: white;")
        close_btn.clicked.connect(QApplication.instance().quit)
        bar_layout.addWidget(close_btn)

        self.main_layout.addWidget(self.action_bar)

        # Keyboard Keys Container
        self.keys_container = QWidget()
        self.keys_layout = QVBoxLayout(self.keys_container)
        self.keys_layout.setContentsMargins(0, 0, 0, 0)
        self.keys_layout.setSpacing(6)

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
            self.dock_btn.setText("⬆ Dock Top")
        else:
            self.dock_position = "bottom"
            y = geom.y() + geom.height() - height - 10
            self.dock_btn.setText("⬇ Dock Bot")
        
        self.move(x, y)

    def build_keys(self, layout_name):
        while self.keys_layout.count():
            item = self.keys_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if layout_name == "QWERTY":
            rows = QWERTY_ROWS
        elif layout_name == "DEV/TERM":
            rows = DEV_ROWS
        else:
            rows = NUMPAD_ROWS

        self.key_buttons = []

        for row_data in rows:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            for key_info in row_data:
                btn = QPushButton()
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.key_info = key_info
                
                label = key_info.get("label", "")
                if self.shift_active or self.caps_active:
                    label = key_info.get("shift_label", label.upper() if len(label) == 1 else label)
                btn.setText(label)

                span = key_info.get("span", 1.0)
                btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Fixed
                )
                btn.setMinimumWidth(int(40 * span))

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
        """Return list of active modifier keycodes including shift if active."""
        mods = list(self.active_modifiers)
        if self.shift_active and "LEFTSHIFT" not in mods:
            mods.append("LEFTSHIFT")
        return mods

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
                self.clear_modifiers()
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
                    btn.setText(info.get("shift_label", base_label.upper() if len(base_label) == 1 else base_label))
                else:
                    btn.setText(base_label)

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

    def position_badge(self):
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            bw = self.badge.width()
            bh = self.badge.height()
            x = geom.x() + geom.width() - bw - 24
            y = geom.y() + geom.height() - bh - 24
            self.badge.move(x, y)

    def position_bottom(self):
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            width = int(geom.width() * 0.95)
            height = 320 if self.current_layout_name != "NUMPAD" else 300
            x = geom.x() + int((geom.width() - width) / 2)
            y = geom.y() + geom.height() - height - 10
            self.setGeometry(x, y, width, height)
            self.position_badge()

    def hide_to_badge(self):
        self.hide()
        self.position_badge()
        self.badge.show()
        self.position_badge()

    def show_keyboard(self):
        self.show()
        self.position_bottom()

    def bring_to_front(self):
        """Restore the keyboard regardless of current state (badge or hidden)."""
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
