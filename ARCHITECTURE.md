# Aurora Touch Keyboard — Architecture & Design Spec

A floating, draggable, glassmorphic on-screen keyboard for KDE Plasma 6 /
Wayland tablets (built and tested on Aurora Blue OS, a Bazzite/uBlue-style
Fedora Atomic image, on a Dell Latitude 7320 Detachable). It injects real
kernel-level key events via `evdev`/`uinput`, so it works in any application —
terminal, browser, editor — exactly like a physical keyboard.

## 1. Design Goals

1. **App-agnostic input.** Don't rely on any per-application text-injection
   API (X11 `XTestFakeKeyEvent`, IBus, etc.) that only some apps honor.
   Instead, create a virtual kernel input device so every application sees
   identical physical-keyboard events.
2. **Never steal focus.** The keyboard must not interfere with whatever the
   user is typing into (`Qt.WindowType.WindowDoesNotAcceptFocus`).
3. **Full modifier support.** Ctrl, Alt, AltGr, Super/Meta, Shift, and Caps
   all compose with normal key presses (e.g. `Ctrl+Shift+Esc`), not just emit bare characters.
4. **Touch-first UX.** Draggable (`startSystemMove`), corner-resizable (`startSystemResize`),
   collapsible to a floating badge, multiple layouts (QWERTY / DEV / NUMPAD),
   scale presets (25% Mini to 125% Large), and four glassmorphic themes.
5. **Independent Orientation View Profiles.** Dedicated geometry, scale, and layout presets
   for Landscape vs. Portrait views with programmatic placement sampling and KWin sync.

## 2. Module Map

```
aurora_keyboard/
├── main.py                  Entry point, CLI args, single-instance IPC socket
├── keyboard_window.py       Main window coordinator (UI layout, events, actions)
├── geometry_manager.py      Orientation profiles, screen watcher, bounds clamping, KWin sync
├── key_engine.py            uinput virtual keyboard device + key/combo emission
├── layouts.py               Declarative key-grid definitions for QWERTY / DEV / NUMPAD
├── styles.py                QSS glassmorphic theme stylesheets (4 themes)
├── widgets/
│   ├── candidate_bar.py     Swipe word suggestion bar & auto-commit chips
│   ├── trail_overlay.py     Anti-aliased neon gesture trail overlay
│   ├── drag_handle.py       DragHandleLabel & TouchResizeGrip (Wayland move/resize)
│   ├── badge.py             FloatingBadge & BadgeButton touch launcher
│   └── key_button.py        SwipeKeyButton (discrete taps vs swipe paths)
└── swipe/
    ├── manager.py           SwipeManager (FUTO neural primary + geometric fallback)
    ├── futo_client.py       IPC client connecting to local neural swipe daemon
    ├── futo_daemon.py       FUTO Python neural inference server
    ├── decoder.py           SHARK² geometric trajectory decoder
    └── wordlist.txt         Embedded high-frequency word dictionary
```

## 3. View Profile Architecture (`geometry_manager.py`)

KDE Plasma 6 / Wayland uses static window rules in `~/.config/kwinrulesrc`.
To support tablets that rotate between Landscape (wide) and Portrait (tall) aspects:

- **`OrientationProfile`**: Encapsulates `(pos, size, dock_position)` for a specific orientation.
- **`GeometryManager`**:
  - Automatically identifies active aspect ratio via `get_orientation_key(geom)`.
  - Enforces minimum touch target limits (`MIN_WIDTH_FLOOR=240`, `MIN_HEIGHT_FLOOR=220`, `BOTTOM_CLEARANCE=55`).
  - Provides `sample_and_set_profile()` to lock current window coordinates programmatically.
  - Synchronizes active rules into `kwinrulesrc` (`positionrule=3`, `sizerule=3`) and sends `reconfigure` via DBus.

## 4. `key_engine.py` — The Kernel UInput Layer

- Creates a virtual keyboard `/dev/input/eventX` via `evdev.UInput`.
- Filters keycodes to `<= e.KEY_MAX` (767) to prevent kernel `EINVAL` (errno 22).
- Composes multi-key chords (`send_combo`) by pressing modifiers in order and releasing them in reverse order.

## 5. UI Widgets & Interactions

- **`DragHandleLabel`**: Calls `windowHandle().startSystemMove()` for native Wayland compositor window repositioning.
- **`TouchResizeGrip`**: Calls `windowHandle().startSystemResize(RightEdge | BottomEdge)` for touch finger resizing.
- **`CandidateBar`**: Displays top predictions with immediate auto-commit on top chip and replacement on secondary clicks.
- **`SwipeTrailOverlay`**: Transparent 60fps overlay rendering layered glowing stroke paths.
- **`FloatingBadge`**: 160×160 touch icon with drop shadow staying anchored in screen corner.

## 6. Deployment & Autostart

- `install.sh`: Creates desktop launcher and autostart entry with `--badge-only` to launch minimized.
- `main.py`: Single-instance guard using `QLocalServer` prevents duplicate processes.
