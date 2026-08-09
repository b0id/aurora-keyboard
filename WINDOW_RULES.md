# KDE Plasma Window Rules — Badge, Keyboard & View Profile System

## Why this exists

On Wayland, an application cannot arbitrarily warp its own top-level window positions — unlike X11, the compositor (KWin) owns window placement. While Qt's Wayland protocol supports interactive resizing (`startSystemResize`) and moving (`startSystemMove`), initial positioning and compositor-level properties (such as always-on-top stacking, focus isolation, and anti-centering placement) are managed via **KWin Window Rules** and direct compositor scripting.

This document details the configuration for Aurora Touch Keyboard, how the dual-orientation **View Profile System** works, and how direct KWin Wayland compositor positioning solves Wayland's global coordinate limitations.

---

## Current Known-Good Configuration

Two windows, one process: the main keyboard and the floating badge share the same application (`wmclass=aurora-keyboard`). They are distinguished by **window title** in [`keyboard_window.py`](file:///var/home/b0id/Documents/AI/keyboard/aurora_keyboard/keyboard_window.py) and [`widgets/badge.py`](file:///var/home/b0id/Documents/AI/keyboard/aurora_keyboard/widgets/badge.py):

- Main Keyboard: `Aurora Touch Keyboard Main`
- Floating Badge: `Aurora Touch Keyboard Badge`

`~/.config/kwinrulesrc` configuration:

```ini
[3d7bb26c-6247-43d3-b27c-a8f7d9676d1c]
Description=Badge
above=true
aboverule=2
acceptfocus=false
acceptfocusrule=2
placement=1
placementrule=2
position=1416,852
positionrule=2
skipswitcher=true
skipswitcherrule=2
skiptaskbar=true
skiptaskbarrule=2
title=Aurora Touch Keyboard Badge
titlematch=1
wmclass=aurora-keyboard
wmclassmatch=1

[498c3a9e-7b5f-42b3-8a5a-46e47e67ef2a]
Description=Window settings for Aurora Touch Keyboard
above=true
aboverule=2
acceptfocus=false
acceptfocusrule=2
placement=1
placementrule=2
position=10,482
positionrule=3
size=765,443
sizerule=3
skipswitcher=true
skipswitcherrule=2
skiptaskbar=true
skiptaskbarrule=2
title=Aurora Touch Keyboard Main
titlematch=1
wmclass=aurora-keyboard
wmclassmatch=1

[General]
count=2
rules=498c3a9e-7b5f-42b3-8a5a-46e47e67ef2a,3d7bb26c-6247-43d3-b27c-a8f7d9676d1c
```

---

## Rule Properties & Stacking Options

### Main Keyboard Window Rules
- `placement=1` & `placementrule=2` (Force): Bypasses KWin's automatic window centering algorithm on map/show, preserving the exact docked or custom coordinates.
- `positionrule=3` (Apply): Allows the user to freely drag the keyboard anywhere on the screen with touch/mouse (`startSystemMove`).
- `sizerule=3` (Apply): Allows dynamic corner-grip dragging (`TouchResizeGrip`), scale preset buttons, and 25%–125% zoom stepping.
- `above=true` & `aboverule=2` (Force): Keeps the keyboard floating above all target applications.
- `acceptfocus=false` & `acceptfocusrule=2` (Force): Prevents focus stealing from active text input fields.

### Floating Badge Rules
- `placement=1` & `placementrule=2` (Force): Keeps the badge anchored in its designated corner.
- `positionrule=2` (Force): Locks the badge to the bottom-right corner with taskbar clearance buffer.

---

## Orientation View Profiles & Live Placement Sampling

KWin rules store static `(x, y)` and `(width, height)` pixel values with no awareness of tablet rotation.

Aurora Keyboard solves this via [`GeometryManager`](file:///var/home/b0id/Documents/AI/keyboard/aurora_keyboard/geometry_manager.py):

1. **Auto-Dock Default**:
   - On fresh launch, the keyboard starts in `Auto-Dock` mode (`position_mode = "default"`), centered at the bottom of the screen with taskbar clearance.
2. **Independent View Profiles**:
   - **Landscape Profile:** Stores dedicated `(x, y)`, `(width, height)`, and dock modes for landscape aspect ratios.
   - **Portrait Profile:** Stores dedicated `(x, y)`, `(width, height)`, and dock modes for portrait aspect ratios.
3. **Live KWin $(x, y)$ Sampling (`get_window_geometry_kwin`)**:
   - On Wayland, when a user moves a window using `startSystemMove()`, the compositor moves the surface without updating Qt's client-side `pos()`.
   - Aurora Keyboard queries KWin's Wayland compositor over DBus (`/Scripting`) for the **true, live physical $(x, y)$** coordinates on screen whenever you tap **`📌 Set Default`** or release a drag.
4. **Compositor-Side Positioning (`set_window_geometry_kwin`)**:
   - When rotating the tablet, restoring from the badge, or launching, the app directly instructs KWin's compositor to set `win.frameGeometry = {x, y, width, height}` in <20ms, ensuring immediate placement without screen centering or visual glitches.

---

## Troubleshooting & Verification

To verify that KWin is honoring the rules:

```bash
# Check stored rules
cat ~/.config/kwinrulesrc

# Force KWin to reload configuration
qdbus-qt6 org.kde.KWin /KWin org.kde.KWin.reconfigure
```
