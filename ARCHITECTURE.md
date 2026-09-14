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
- **`AURORA_NO_UINPUT` safety interlock**: when this environment variable is set, no virtual device is created and every emit no-ops. The device is system-wide, so a keystroke emitted from a test lands in whatever window the user currently has focused. All test modules that construct `AuroraKeyboardWindow` or `KeyEngine` set it at import time.

### 4.1 Modifier semantics (`keyboard_window.py`)

Modifiers are tri-state: **OFF → LATCHED** (single tap, applies to the next keystroke) **→ LOCKED** (second tap within `DOUBLE_TAP_INTERVAL` = 400 ms) **→ OFF**. `consume_latched_modifiers()` retires latched modifiers after each keystroke; locked ones persist until tapped off or Esc clears everything.

Two rules exist specifically to stop a modifier leaking into a later keystroke — the failure mode where Enter silently became Shift/Super+Enter and appeared not to work at all:

- **Super defers its launcher press.** A tapped Super only latches; the bare `KEY_LEFTMETA` pulse that opens the desktop launcher is scheduled `META_PULSE_DELAY_MS` (600 ms) later and is cancelled by any following keystroke. So `Super+D` works from a *single* tap, and tapping Super alone still opens the launcher. Previously the tap pulsed *and* latched, leaving Meta armed over the next key.
- **Swipe commits retire one-shot modifiers.** Swipe words and candidate chips go through `AuroraKeyboardWindow.commit_text()`, not `engine.type_text()` directly, so a latched modifier can't survive a whole swiped sentence.

Auto-repeat on hold is limited to `AUTO_REPEAT_KEYCODES` (backspace, delete, space, tab, arrows, home/end/page) plus character keys — never Enter, the F-keys or Insert.

## 5. UI Widgets & Interactions

- **`DragHandleLabel`**: Calls `windowHandle().startSystemMove()` for native Wayland compositor window repositioning.
- **`TouchResizeGrip`**: Calls `windowHandle().startSystemResize(RightEdge | BottomEdge)` for touch finger resizing.
- **`CandidateBar`**: Displays top predictions with immediate auto-commit on top chip and replacement on secondary clicks. Commits route through `AuroraKeyboardWindow.commit_text()` (§4.1) and update `RollingTokenContext` via `replace_last_word()` so a chip correction also corrects the context fed to the context LM.
- **`SwipeTrailOverlay`**: Transparent 60fps overlay rendering layered glowing stroke paths.
- **`FloatingBadge`**: 160×160 touch icon with drop shadow staying anchored in screen corner.

## 6. Deployment & Autostart

- `install.sh`: Creates desktop launcher and autostart entry with `--badge-only` to launch minimized, plus a systemd `--user` unit supervising the FUTO daemon.
- **Single daemon ownership**: `futo_daemon.py` probes `/tmp/futo_swipe.sock` before binding and exits if a live daemon already answers (a stale file from a crashed daemon is still cleaned up and re-bound). `main.py`'s `_ensure_futo_daemon()` defers to `systemctl --user start` when the unit is installed, falling back to the launcher script only on non-systemd installs. Both are needed: the unit takes ~20s to load its models at login, so `is_available()` said no and the app spawned a second daemon that then *took the socket over* — leaving the systemd-supervised one stranded on an unlinked inode and the unsupervised one serving swipes, i.e. no auto-restart, the exact failure the systemd unit was added to prevent.
- `main.py`: Single-instance guard using `QLocalServer` prevents duplicate processes.
- **Preference restore**: theme and layout live in `~/.config/aurora-keyboard/config.json` and are applied in `AuroraKeyboardWindow.__init__`. `--theme`/`--layout` default to `None` so that an unspecified flag leaves the saved preference alone; a non-`None` argparse default is always truthy and silently overrode it on every launch. Changing either from the toolbar schedules a debounced write (`_persist_prefs`), so the choice survives a crash rather than only a clean exit.
