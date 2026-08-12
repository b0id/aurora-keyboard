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
        # A click on window background (not a key, not the drag handle -
        # e.g. padding or a gap between keys) starts a full window drag via
        # mousePressEvent unless locked. Verified by calling the handler
        # directly with a constructed event, not live input simulation.
        self.assertFalse(self.window._drag_locked)

        self.window.set_drag_locked(True)
        self.assertTrue(self.window._drag_locked)
        self.assertEqual(self.window.drag_lock_btn.text(), "🔒")
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
        self.assertEqual(self.window.drag_lock_btn.text(), "🔓")
        self.assertTrue(self.window.drag_label.isEnabled())

    def test_minimize_and_restore(self):
        self.window.show()
        self.window.hide_to_badge()
        self.assertTrue(self.window.badge.isVisible())
        self.assertFalse(self.window.isVisible())

        self.window.bring_to_front()
        self.assertFalse(self.window.badge.isVisible())
        self.assertTrue(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
