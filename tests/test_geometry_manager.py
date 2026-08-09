"""
Unit & integration tests for GeometryManager and OrientationProfile view system.
"""

import os
import sys
import unittest
import tempfile
import json
from unittest.mock import patch, MagicMock

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect

from aurora_keyboard.geometry_manager import (
    GeometryManager, OrientationProfile, BOTTOM_CLEARANCE,
    MIN_WIDTH_FLOOR, MIN_HEIGHT_FLOOR
)


class TestGeometryManager(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.mgr = GeometryManager()

    def test_orientation_detection(self):
        # Landscape: width >= height
        landscape_geom = QRect(0, 0, 1600, 1000)
        self.assertEqual(self.mgr.get_orientation_key(landscape_geom), "landscape")

        # Portrait: width < height
        portrait_geom = QRect(0, 0, 1000, 1600)
        self.assertEqual(self.mgr.get_orientation_key(portrait_geom), "portrait")

    def test_size_bounds_and_clamping(self):
        geom = QRect(0, 0, 1600, 1000)
        min_w, min_h, max_w, max_h = self.mgr.get_size_bounds(geom)
        self.assertGreaterEqual(min_w, MIN_WIDTH_FLOOR)
        self.assertGreaterEqual(min_h, MIN_HEIGHT_FLOOR)
        self.assertEqual(max_w, 1600 - 20)
        self.assertEqual(max_h, 1000 - BOTTOM_CLEARANCE - 20)

        # Clamping
        w, h = self.mgr.clamp_size(100, 50, geom)
        self.assertEqual(w, min_w)
        self.assertEqual(h, min_h)

        w, h = self.mgr.clamp_size(2000, 1500, geom)
        self.assertEqual(w, max_w)
        self.assertEqual(h, max_h)

    def test_sample_and_profiles(self):
        self.mgr.sample_and_set_profile("landscape", 40, 600, 1520, 400, "bottom")
        prof = self.mgr.profiles["landscape"]
        self.assertIsNotNone(prof)
        self.assertEqual(prof.pos, (40, 600))
        self.assertEqual(prof.size, (1520, 400))
        self.assertEqual(prof.dock_position, "bottom")

        self.mgr.sample_and_set_profile("portrait", 20, 800, 960, 350, "top")
        prof_p = self.mgr.profiles["portrait"]
        self.assertIsNotNone(prof_p)
        self.assertEqual(prof_p.pos, (20, 800))
        self.assertEqual(prof_p.size, (960, 350))
        self.assertEqual(prof_p.dock_position, "top")

    def test_config_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_config_file = os.path.join(tmpdir, "config.json")
            with patch("aurora_keyboard.geometry_manager.CONFIG_PATH", test_config_file):
                self.mgr.sample_and_set_profile("landscape", 50, 500, 1400, 400)
                self.mgr.sample_and_set_profile("portrait", 10, 900, 800, 320)
                self.mgr.current_theme = "Cyber Neon"
                self.mgr.current_layout = "DEV"
                self.mgr.save_config()

                # Verify file was written
                self.assertTrue(os.path.exists(test_config_file))

                # Load into fresh manager
                new_mgr = GeometryManager()
                new_mgr.load_config()
                self.assertIsNotNone(new_mgr.profiles["landscape"])
                self.assertEqual(new_mgr.profiles["landscape"].pos, (50, 500))
                self.assertEqual(new_mgr.profiles["landscape"].size, (1400, 400))
                self.assertEqual(new_mgr.current_theme, "Cyber Neon")
                self.assertEqual(new_mgr.current_layout, "DEV")

    def test_badge_geometry(self):
        geom = QRect(0, 0, 1600, 1000)
        bx, by = self.mgr.compute_badge_geometry(geom, badge_w=160, badge_h=160)
        self.assertEqual(bx, 1600 - 160 - 24)
        self.assertEqual(by, 1000 - 160 - BOTTOM_CLEARANCE)


if __name__ == "__main__":
    unittest.main()
