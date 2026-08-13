"""
Integration tests for AuroraKeyboardWindow UI, widgets, and layout switching.
"""

import sys
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QEvent, QPointF
from PyQt6.QtGui import QMouseEvent

from aurora_keyboard.keyboard_window import AuroraKeyboardWindow


class TestAuroraKeyboardWindow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.window = AuroraKeyboardWindow()

    def tearDown(self):
        self.window.badge.hide()
        self.window.hide()
        self.window.deleteLater()

    def test_window_initialization(self):
        self.assertIsNotNone(self.window.engine)
        self.assertIsNotNone(self.window.swipe_manager)
        self.assertIsNotNone(self.window.candidate_bar)
        self.assertIsNotNone(self.window.badge)
        self.assertIsNotNone(self.window.trail_overlay)
        self.assertEqual(self.window.windowTitle(), "Aurora Touch Keyboard Main")
        self.assertEqual(self.window.badge.windowTitle(), "Aurora Touch Keyboard Badge")

    def test_layout_switching(self):
        # QWERTY
        self.window.change_layout("QWERTY")
        self.assertEqual(self.window.current_layout_name, "QWERTY")
        qwerty_keys = len(self.window.key_buttons)
        self.assertGreater(qwerty_keys, 40)

        # DEV
        self.window.change_layout("DEV")
        self.assertEqual(self.window.current_layout_name, "DEV")
        dev_keys = len(self.window.key_buttons)
        self.assertGreater(dev_keys, 40)

        # NUM
        self.window.change_layout("NUM")
        self.assertEqual(self.window.current_layout_name, "NUM")
        num_keys = len(self.window.key_buttons)
        self.assertLess(num_keys, 30)

    def test_theme_application(self):
        for theme in ["Aurora Glass", "Cyber Neon", "OLED Dark", "Light Velvet"]:
            self.window.apply_theme(theme)
            self.assertEqual(self.window.current_theme, theme)

    def test_shift_and_caps_toggle(self):
        # Initial
        self.assertFalse(self.window.shift_active)
        self.assertFalse(self.window.caps_active)

        # Find a char button (e.g. 'a')
        char_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('type') == 'char'), None)
        self.assertIsNotNone(char_btn)

        # Toggle Shift
        self.window.shift_active = True
        self.window.update_key_labels()
        self.window.shift_active = False
        self.window.update_key_labels()

    def test_sample_current_placement(self):
        from unittest.mock import patch
        with patch.object(self.window.geometry_mgr, "get_window_geometry_kwin", return_value=(50, 400, 1000, 350)):
            self.window.resize(1000, 350)
            self.window.move(50, 400)
            self.window.sample_current_placement()

            orient = self.window._orientation_key()
            prof = self.window.geometry_mgr.profiles.get(orient)
            self.assertIsNotNone(prof)
            self.assertEqual(prof.size, (1000, 350))
            self.assertEqual(prof.pos, (50, 400))

    def test_drag_lock_prevents_background_click_drag(self):
        # A click on window background starts a full window drag via
        # mousePressEvent unless locked.
        self.assertFalse(self.window._drag_locked)

        self.window.set_drag_locked(True)
        self.assertTrue(self.window._drag_locked)
        self.assertFalse(self.window.drag_lock_btn.icon().isNull())
        self.assertFalse(self.window.drag_label.isEnabled())

        pos = QPointF(50, 50)
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress, pos, pos,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
        self.window.mousePressEvent(event)
        self.assertIsNone(getattr(self.window, "_drag_pos", None))

    def test_drag_lock_toggle_restores_normal_behavior(self):
        self.window.set_drag_locked(True)
        self.window.set_drag_locked(False)
        self.assertFalse(self.window._drag_locked)
        self.assertFalse(self.window.drag_lock_btn.icon().isNull())
        self.assertTrue(self.window.drag_label.isEnabled())

    def test_modifier_tri_state_and_double_tap_lock(self):
        from aurora_keyboard.keyboard_window import MOD_STATE_OFF, MOD_STATE_LATCHED, MOD_STATE_LOCKED

        # 1. Single tap -> LATCHED
        self.window.toggle_modifier("LEFTCTRL")
        self.assertEqual(self.window.modifier_states.get("LEFTCTRL"), MOD_STATE_LATCHED)
        self.assertIn("LEFTCTRL", self.window.get_active_modifiers())

        # 2. Quick tap within double-tap window -> LOCKED
        self.window.toggle_modifier("LEFTCTRL")
        self.assertEqual(self.window.modifier_states.get("LEFTCTRL"), MOD_STATE_LOCKED)
        self.assertIn("LEFTCTRL", self.window.get_active_modifiers())

        # 3. Simulate typing a character while locked -> stays LOCKED
        char_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('type') == 'char'), None)
        self.assertIsNotNone(char_btn)
        self.window.handle_key_click(char_btn.key_info, char_btn)
        self.assertEqual(self.window.modifier_states.get("LEFTCTRL"), MOD_STATE_LOCKED)

        # 4. Single tap while locked -> transitions to OFF (single tap to escape lock)
        self.window.toggle_modifier("LEFTCTRL")
        self.assertEqual(self.window.modifier_states.get("LEFTCTRL"), MOD_STATE_OFF)
        self.assertNotIn("LEFTCTRL", self.window.get_active_modifiers())

    def test_multi_modifier_and_latched_auto_release(self):
        from aurora_keyboard.keyboard_window import MOD_STATE_LATCHED

        # Tap Ctrl then tap Shift (both active)
        self.window.toggle_modifier("LEFTCTRL")
        self.window.toggle_modifier("LEFTSHIFT")
        self.assertEqual(self.window.modifier_states.get("LEFTCTRL"), MOD_STATE_LATCHED)
        self.assertEqual(self.window.modifier_states.get("LEFTSHIFT"), MOD_STATE_LATCHED)
        active = self.window.get_active_modifiers()
        self.assertIn("LEFTCTRL", active)
        self.assertIn("LEFTSHIFT", active)

        # Typing a character consumes both latched modifiers
        char_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('type') == 'char'), None)
        self.window.handle_key_click(char_btn.key_info, char_btn)
        self.assertEqual(len(self.window.get_active_modifiers()), 0)

    def test_escape_clears_all_modifiers_and_caps(self):
        from aurora_keyboard.keyboard_window import MOD_STATE_LOCKED

        # Lock Ctrl, latch Shift, turn on Caps
        self.window.modifier_states["LEFTCTRL"] = MOD_STATE_LOCKED
        self.window.modifier_states["LEFTSHIFT"] = MOD_STATE_LOCKED
        self.window.caps_active = True
        self.window.update_key_labels()
        self.window.update_modifier_buttons_visual()

        # Find Esc button or call handle_key_click with escape
        esc_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('type') == 'escape'), None)
        if esc_btn:
            self.window.handle_key_click(esc_btn.key_info, esc_btn)
        else:
            self.window.clear_all_modifiers()

        self.assertEqual(len(self.window.get_active_modifiers()), 0)
        self.assertFalse(self.window.caps_active)
        self.assertFalse(self.window.shift_active)

    def test_left_column_action_buttons(self):
        # Verify action buttons exist in QWERTY layout
        labels = [b.key_info.get("label") for b in self.window.key_buttons if hasattr(b, 'key_info')]
        self.assertIn("Esc", labels)
        self.assertIn("All", labels)
        self.assertIn("Copy", labels)
        self.assertIn("Paste", labels)

    def test_auto_repeat_enabled_for_char_and_navigation_keys(self):
        char_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('type') == 'char'), None)
        self.assertIsNotNone(char_btn)
        self.assertTrue(char_btn.autoRepeat())
        self.assertEqual(char_btn.autoRepeatDelay(), 380)
        self.assertEqual(char_btn.autoRepeatInterval(), 50)

        nav_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('type') == 'key'), None)
        self.assertIsNotNone(nav_btn)
        self.assertTrue(nav_btn.autoRepeat())

        # Modifiers should NOT auto-repeat
        mod_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('type') == 'toggle_modifier'), None)
        self.assertIsNotNone(mod_btn)
        self.assertFalse(mod_btn.autoRepeat())

    def test_super_key_pulses_application_menu(self):
        from unittest.mock import patch
        with patch.object(self.window.engine, "send_keycode") as mock_send:
            super_btn = next((b for b in self.window.key_buttons if getattr(b, 'key_info', {}).get('mod') == 'LEFTMETA'), None)
            self.assertIsNotNone(super_btn)
            self.window.handle_key_click(super_btn.key_info, super_btn)
            # Verify send_keycode was called with LEFTMETA keycode (125)
            mock_send.assert_called_with(125)

    def test_minimize_and_restore(self):
        self.window.show()
        self.window.hide_to_badge()
        self.assertTrue(self.window.badge.isVisible())
        self.assertFalse(self.window.isVisible())

        self.window.bring_to_front()
        self.assertFalse(self.window.badge.isVisible())
        self.assertTrue(self.window.isVisible())

    def test_rotation_preserves_distinct_presets_without_corruption(self):
        # Set distinct Landscape and Portrait presets
        self.window.geometry_mgr.sample_and_set_profile("landscape", 400, 500, 800, 450, "bottom")
        self.window.geometry_mgr.sample_and_set_profile("portrait", 50, 1100, 960, 400, "bottom")
        self.window.geometry_mgr.position_mode = "remember"

        # Simulate resize events (which happen during screen transition)
        from PyQt6.QtGui import QResizeEvent
        from PyQt6.QtCore import QSize
        resize_ev = QResizeEvent(QSize(1067, 1600), QSize(1600, 1067))
        self.window.resizeEvent(resize_ev)

        # Verify Landscape preset was NOT corrupted by the resize
        land_prof = self.window.geometry_mgr.profiles["landscape"]
        self.assertEqual(land_prof.pos, (400, 500))
        self.assertEqual(land_prof.size, (800, 450))

        # Verify Portrait preset was NOT corrupted
        port_prof = self.window.geometry_mgr.profiles["portrait"]
        self.assertEqual(port_prof.pos, (50, 1100))
        self.assertEqual(port_prof.size, (960, 400))


if __name__ == "__main__":
    unittest.main()
