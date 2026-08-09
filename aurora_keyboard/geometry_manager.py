"""
Geometry, View Profiles, and KWin Rule Synchronization Manager for Aurora Touch Keyboard.
Handles screen orientation detection, per-view presets, geometry clamping,
programmatic placement sampling, and KWin Wayland compositor positioning.
"""

import sys
import os
import subprocess
import json
import configparser
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from PyQt6.QtWidgets import QApplication

KWIN_RULES_PATH = os.path.expanduser("~/.config/kwinrulesrc")
KWIN_RULE_TITLE_BADGE = "Aurora Touch Keyboard Badge"
KWIN_RULE_TITLE_MAIN = "Aurora Touch Keyboard Main"
CONFIG_PATH = os.path.expanduser("~/.config/aurora-keyboard/config.json")

# screen.availableGeometry() does not reliably exclude the Plasma taskbar for a
# Tool window - measured directly via screenshot pixel sampling
# (taskbar top at physical y=1226 of 1280, ~45 logical px tall at 1.2 scale).
BOTTOM_CLEARANCE = 55

MIN_WIDTH_FRACTION = 0.25
MIN_WIDTH_FLOOR = 240
MIN_HEIGHT_FLOOR = 220


@dataclass
class OrientationProfile:
    """Stores distinct geometric and layout presets for an orientation view."""
    pos: Tuple[int, int]
    size: Tuple[int, int]
    dock_position: str = "bottom"  # "bottom" or "top"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pos": list(self.pos),
            "size": list(self.size),
            "dock_position": self.dock_position
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrientationProfile":
        pos = tuple(data.get("pos", [0, 0]))
        size = tuple(data.get("size", [800, 300]))
        dock_pos = data.get("dock_position", "bottom")
        return cls(pos=pos, size=size, dock_position=dock_pos)


class GeometryManager:
    """
    Manages screen geometry, orientation view profiles (Landscape / Portrait),
    geometry bounds clamping, KWin compositor placement, and rule synchronization.
    """

    def __init__(self):
        # Default mode is 'default' (Auto-Dock) on fresh initialization
        self.position_mode: str = "default"  # "default" (Auto-Dock) or "remember"
        self.profiles: Dict[str, Optional[OrientationProfile]] = {
            "landscape": None,
            "portrait": None
        }
        self.badge_pos: Optional[Tuple[int, int]] = None
        self.current_theme: str = "Aurora Glass"
        self.current_layout: str = "QWERTY"

    def get_orientation_key(self, geom=None) -> str:
        """Determines orientation ('landscape' vs 'portrait') based on available screen aspect ratio."""
        if geom is None:
            screen = QApplication.primaryScreen()
            geom = screen.availableGeometry() if screen else None
        if geom is None or geom.height() <= 0:
            return "landscape"
        return "landscape" if geom.width() >= geom.height() else "portrait"

    def get_screen_geometry(self):
        screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def get_size_bounds(self, geom) -> Tuple[int, int, int, int]:
        """Calculates min_w, min_h, max_w, max_h for the given screen geometry."""
        min_w = max(MIN_WIDTH_FLOOR, int(geom.width() * MIN_WIDTH_FRACTION))
        min_h = MIN_HEIGHT_FLOOR
        max_w = max(min_w, geom.width() - 20)
        max_h = max(min_h, geom.height() - BOTTOM_CLEARANCE - 20)
        return min_w, min_h, max_w, max_h

    def clamp_size(self, w: int, h: int, geom) -> Tuple[int, int]:
        min_w, min_h, max_w, max_h = self.get_size_bounds(geom)
        return max(min_w, min(max_w, w)), max(min_h, min(max_h, h))

    def clamp_position(self, x: int, y: int, w: int, h: int, geom) -> Tuple[int, int]:
        cx = max(geom.x() + 10, min(geom.x() + geom.width() - w - 10, x))
        cy = max(geom.y() + 10, min(geom.y() + geom.height() - h - BOTTOM_CLEARANCE, y))
        return cx, cy

    def compute_default_geometry(self, geom, natural_height: int = 360) -> Tuple[int, int, int, int]:
        """Computes clean default centered bottom-docked geometry for the screen."""
        width = int(geom.width() * 0.95)
        height = max(MIN_HEIGHT_FLOOR, natural_height)
        width, height = self.clamp_size(width, height, geom)
        x = geom.x() + int((geom.width() - width) / 2)
        y = geom.y() + geom.height() - height - BOTTOM_CLEARANCE
        return x, y, width, height

    def compute_badge_geometry(self, geom, badge_w: int = 160, badge_h: int = 160) -> Tuple[int, int]:
        """Computes bottom-right corner position for the floating badge."""
        x = geom.x() + geom.width() - badge_w - 24
        y = geom.y() + geom.height() - badge_h - BOTTOM_CLEARANCE
        return x, y

    def get_geometry_for_orientation(self, orientation: str, geom, natural_height: int = 360) -> Tuple[int, int, int, int]:
        """
        Retrieves the exact target (x, y, width, height) for a given orientation.
        If in 'remember' mode and a profile exists, clamps and returns the stored profile.
        Otherwise falls back to computing clean default docked geometry.
        """
        if self.position_mode == "remember":
            profile = self.profiles.get(orientation)
            if profile and profile.pos and profile.size:
                w, h = self.clamp_size(profile.size[0], profile.size[1], geom)
                if profile.dock_position == "top":
                    x = profile.pos[0]
                    y = geom.y() + 10
                    x, _ = self.clamp_position(x, y, w, h, geom)
                else:
                    x, y = self.clamp_position(profile.pos[0], profile.pos[1], w, h, geom)
                return x, y, w, h

        return self.compute_default_geometry(geom, natural_height)

    def sample_and_set_profile(self, orientation: str, x: int, y: int, w: int, h: int, dock_pos: str = "bottom"):
        """Programmatically sample and lock the given placement as the profile for an orientation."""
        self.profiles[orientation] = OrientationProfile(
            pos=(int(x), int(y)),
            size=(int(w), int(h)),
            dock_position=dock_pos
        )
        self.position_mode = "remember"

    def get_window_geometry_kwin(self, window_title: str) -> Optional[Tuple[int, int, int, int]]:
        """
        Queries the KWin Wayland compositor directly for the live global (x, y, width, height)
        of the window. Bypasses Wayland limitations where Qt's QWidget.pos() is unaware of
        startSystemMove() repositioning.
        """
        tag = f"AURORA_GEOM_QUERY_{os.getpid()}"
        script = f"""
        var windows = workspace.windowList();
        for (var i = 0; i < windows.length; i++) {{
            var win = windows[i];
            if (win.caption && win.caption.indexOf("{window_title}") !== -1) {{
                console.warn("{tag}:" + Math.round(win.frameGeometry.x) + "," + Math.round(win.frameGeometry.y) + "," + Math.round(win.frameGeometry.width) + "," + Math.round(win.frameGeometry.height));
                break;
            }}
        }}
        """
        script_file = None
        plugin_name = f"aurora_q_{os.getpid()}"
        try:
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
                f.write(script)
                script_file = f.name

            res = subprocess.run(
                ["qdbus-qt6", "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", script_file, plugin_name],
                capture_output=True, text=True, timeout=2
            )
            sid = res.stdout.strip()
            if sid and sid.isdigit():
                subprocess.run(["qdbus-qt6", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script.run"], capture_output=True, timeout=2)
                subprocess.run(["qdbus-qt6", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script.stop"], capture_output=True, timeout=2)
                subprocess.run(["qdbus-qt6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin_name], capture_output=True, timeout=2)

            out = subprocess.run(["journalctl", "--user", "-n", "8", "--no-pager"], capture_output=True, text=True, timeout=2)
            for line in reversed(out.stdout.splitlines()):
                if f"{tag}:" in line:
                    geom_str = line.split(f"{tag}:")[1].strip()
                    parts = [int(v) for v in geom_str.split(",")]
                    if len(parts) == 4:
                        return (parts[0], parts[1], parts[2], parts[3])
        except Exception:
            pass
        finally:
            if script_file and os.path.exists(script_file):
                try:
                    os.remove(script_file)
                except Exception:
                    pass
        return None

    def set_window_geometry_kwin(self, window_title: str, x: int, y: int, w: int, h: int) -> bool:
        """
        Directly instructs the KWin Wayland compositor to reposition and resize the window.
        Bypasses Wayland client limitations where QWidget.move() is ignored.
        """
        script = f"""
        var windows = workspace.windowList();
        for (var i = 0; i < windows.length; i++) {{
            var win = windows[i];
            if (win.caption && win.caption.indexOf("{window_title}") !== -1) {{
                win.frameGeometry = {{ x: {int(x)}, y: {int(y)}, width: {int(w)}, height: {int(h)} }};
            }}
        }}
        """
        script_file = None
        plugin_name = f"aurora_geo_{os.getpid()}_{int(x)}_{int(y)}"
        try:
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f:
                f.write(script)
                script_file = f.name

            res = subprocess.run(
                ["qdbus-qt6", "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", script_file, plugin_name],
                capture_output=True, text=True, timeout=2
            )
            sid = res.stdout.strip()
            if sid and sid.isdigit():
                subprocess.run(["qdbus-qt6", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script.run"], capture_output=True, timeout=2)
                subprocess.run(["qdbus-qt6", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script.stop"], capture_output=True, timeout=2)
                subprocess.run(["qdbus-qt6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin_name], capture_output=True, timeout=2)
                return True
        except Exception:
            pass
        finally:
            if script_file and os.path.exists(script_file):
                try:
                    os.remove(script_file)
                except Exception:
                    pass
        return False

    def import_from_kwin_rules(self, orientation: Optional[str] = None) -> bool:
        """
        Samples coordinates directly from ~/.config/kwinrulesrc if configured by the user via KDE GUI.
        Returns True if a valid rule was found and imported.
        """
        if not os.path.exists(KWIN_RULES_PATH):
            return False

        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read(KWIN_RULES_PATH)
            for section in config.sections():
                if config[section].get("title", "") == KWIN_RULE_TITLE_MAIN:
                    pos_str = config[section].get("position", "")
                    size_str = config[section].get("size", "")
                    if pos_str and size_str and "," in pos_str and "," in size_str:
                        px, py = [int(v.strip()) for v in pos_str.split(",")]
                        sw, sh = [int(v.strip()) for v in size_str.split(",")]
                        target_orient = orientation or self.get_orientation_key()
                        self.sample_and_set_profile(target_orient, px, py, sw, sh)
                        return True
        except Exception as e:
            print(f"[GeometryManager] Could not import KWin rules: {e}", file=sys.stderr)
        return False

    def load_config(self):
        """Loads orientation view profiles and preferences from ~/.config/aurora-keyboard/config.json."""
        if not os.path.exists(CONFIG_PATH):
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.position_mode = data.get("position_mode", "default")
                presets = data.get("orientation_presets", {})
                for key in ("landscape", "portrait"):
                    entry = presets.get(key)
                    if entry and "pos" in entry and "size" in entry:
                        self.profiles[key] = OrientationProfile.from_dict(entry)

                # Legacy fallback migration
                if not any(self.profiles.values()):
                    legacy_pos = data.get("custom_pos")
                    legacy_size = data.get("custom_size")
                    if legacy_pos and legacy_size:
                        active_key = self.get_orientation_key()
                        self.profiles[active_key] = OrientationProfile(
                            pos=tuple(legacy_pos),
                            size=tuple(legacy_size)
                        )

                self.current_theme = data.get("theme", "Aurora Glass")
                self.current_layout = data.get("layout", "QWERTY")
        except Exception as e:
            print(f"[GeometryManager] Config load error: {e}", file=sys.stderr)

    def save_config(self):
        """Persists orientation view profiles and preferences to config.json."""
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            presets_data = {}
            for key, prof in self.profiles.items():
                if prof:
                    presets_data[key] = prof.to_dict()
                else:
                    presets_data[key] = None

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "position_mode": self.position_mode,
                    "orientation_presets": presets_data,
                    "theme": self.current_theme,
                    "layout": self.current_layout
                }, f, indent=2)
        except Exception as e:
            print(f"[GeometryManager] Config save error: {e}", file=sys.stderr)

    def sync_kwin_rules(self, active_geom=None, natural_height: int = 360):
        """
        Synchronizes current orientation geometry and anti-centering placement rules
        into ~/.config/kwinrulesrc and reconfigures KWin.
        """
        if not os.path.exists(KWIN_RULES_PATH):
            return

        screen = QApplication.primaryScreen()
        if not screen:
            return

        geom = screen.availableGeometry()
        orient = self.get_orientation_key(geom)
        main_x, main_y, main_w, main_h = self.get_geometry_for_orientation(orient, geom, natural_height)
        badge_x, badge_y = self.compute_badge_geometry(geom)

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
                    check=False, timeout=5
                )

            if badge_section:
                kwrite(badge_section, "position", f"{badge_x},{badge_y}")
                kwrite(badge_section, "positionrule", "2")  # Force badge corner position
                kwrite(badge_section, "placement", "1")     # No placement policy (bypasses centering)
                kwrite(badge_section, "placementrule", "2")

            if main_section:
                kwrite(main_section, "position", f"{main_x},{main_y}")
                # positionrule is Apply-once (3) to allow free touch dragging
                kwrite(main_section, "positionrule", "3")
                kwrite(main_section, "size", f"{main_w},{main_h}")
                # sizerule is Apply-once (3) to allow dynamic corner resizing
                kwrite(main_section, "sizerule", "3")
                # placement=1 (None) prevents KWin from centering the window on show/remap!
                kwrite(main_section, "placement", "1")
                kwrite(main_section, "placementrule", "2")

            if badge_section or main_section:
                subprocess.run(
                    ["qdbus-qt6", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"],
                    check=False, timeout=5
                )
        except Exception as err:
            print(f"[GeometryManager] KWin sync error: {err}", file=sys.stderr)
