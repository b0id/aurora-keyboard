# KDE Plasma Window Rules — Badge, Keyboard & View Profile System

## Why this exists

On Wayland, an application cannot arbitrarily warp its own top-level window positions — unlike X11, the compositor (KWin) owns window placement. While Qt's Wayland protocol supports interactive resizing (`startSystemResize`) and moving (`startSystemMove`), initial positioning and compositor-level properties (such as always-on-top stacking and focus isolation) are managed via **KWin Window Rules**.

This document details the configuration for Aurora Touch Keyboard, how the dual-orientation **View Profile System** works, and how programmatic placement sampling solves KWin's lack of screen orientation awareness.

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

## The Rule Strength Dichotomy: Force (2) vs Apply-Once (3)

KWin rules define property rule strengths:
- **`2` (Force):** Reasserted continuously by KWin at every frame.
- **`3` (Apply):** Applied once when the window maps/launches, but permits the user to drag or resize freely afterwards.

### Main Keyboard Window Rules
- `positionrule=3` (Apply): Allows the user to freely drag the keyboard anywhere on the screen with touch/mouse (`startSystemMove`).
- `sizerule=3` (Apply): Allows dynamic corner-grip dragging (`TouchResizeGrip`), scale preset buttons, and 25%–125% zoom stepping.
- `aboverule=2` (Force): Keeps the keyboard floating above all target applications.
- `acceptfocusrule=2` (Force, `acceptfocus=false`): Prevents focus stealing from active text input fields.

### Floating Badge Rules
- `positionrule=2` (Force): Locks the badge to the bottom-right corner with taskbar clearance buffer.

---

## Orientation View Profiles & Programmatic Sampling

KWin rules store static `(x, y)` and `(width, height)` pixel values with no awareness of tablet rotation.

Aurora Keyboard solves this via [`GeometryManager`](file:///var/home/b0id/Documents/AI/keyboard/aurora_keyboard/geometry_manager.py):

1. **Independent View Profiles:**
   - **Landscape Profile:** Stores dedicated `(x, y)`, `(width, height)`, and dock modes for landscape aspect ratios.
   - **Portrait Profile:** Stores dedicated `(x, y)`, `(width, height)`, and dock modes for portrait aspect ratios.
2. **Programmatic Placement Sampling:**
   - Drag or resize the keyboard to your ideal location.
   - Tap **"📌 Set Default"** in the top action bar (or call `sample_current_placement()`).
   - The app instantly records the live coordinates into that orientation's profile in `~/.config/aurora-keyboard/config.json`, synchronizes the active KWin rule, and triggers `qdbus-qt6 org.kde.KWin /KWin org.kde.KWin.reconfigure`.
3. **Seamless Rotation Handling:**
   - Watches `QScreen.geometryChanged` and `availableGeometryChanged` (with a 400ms debounce).
   - On rotation, loads the target orientation's profile, updates geometry, clamps to screen bounds, adjusts responsive typography, and updates KWin rules.

---

## Troubleshooting & Verification

To verify that KWin is honoring the rules:

```bash
# Check stored rules
cat ~/.config/kwinrulesrc

# Force KWin to reload configuration
qdbus-qt6 org.kde.KWin /KWin org.kde.KWin.reconfigure
```
