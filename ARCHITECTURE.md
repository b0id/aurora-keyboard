# Aurora Touch Keyboard — Architecture & Design Spec

A floating, draggable, glassmorphic on-screen keyboard for KDE Plasma 6 /
Wayland tablets (built and tested on Aurora Blue OS, a Bazzite/uBlue-style
Fedora Atomic image, on a Dell Latitude 7320 Detachable). It injects real
kernel-level key events via `evdev`/`uinput`, so it works in any application —
terminal, browser, editor — exactly like a physical keyboard.

## 1. Design goals

1. **App-agnostic input.** Don't rely on any per-application text-injection
   API (X11 `XTestFakeKeyEvent`, IBus, etc.) that only some apps honor.
   Instead, create a virtual kernel input device so every application, from
   `xterm` to a Wayland-native editor, sees identical, indistinguishable
   physical-keyboard events.
2. **Never steal focus.** The keyboard must not interfere with whatever the
   user is typing into. It should not become the active window, must not
   accept keyboard focus itself, and must not appear in window-switchers.
3. **Full modifier support.** Ctrl, Alt, AltGr, Super/Meta, Shift, and Caps
   all need to compose with normal key presses (e.g. `Ctrl+Shift+Esc`), not
   just emit bare characters.
4. **Touch-first UX.** Draggable, dockable (top/bottom), collapsible to a
   small reopenable badge, multiple layouts (QWERTY / dev-terminal / numpad),
   multiple visual themes.
5. **Wayland-native, not X11-ported.** Dragging uses KWin's
   `startSystemMove()` protocol request rather than X11-style manual
   window-position hacking, since the process has no permission to warp its
   own position arbitrarily under Wayland.

## 2. Module map

```
aurora_keyboard/
├── main.py             Entry point, CLI args, single-instance guard
├── keyboard_window.py  Qt widgets: main window, drag handle, floating badge
├── key_engine.py        uinput virtual keyboard device + key/combo emission
├── layouts.py           Declarative key-grid data for QWERTY / DEV / NUMPAD
├── styles.py            QSS theme stylesheets (4 themes)
└── __init__.py          Package version marker

install.sh               Installs launcher, .desktop entry, autostart entry
pyproject.toml           PyQt6 + evdev dependency, console-script entry point
```

Dependency direction is strictly one-way:
`main.py → keyboard_window.py → key_engine.py`, with `layouts.py` and
`styles.py` as pure data consumed by `keyboard_window.py`. `key_engine.py`
has no Qt dependency at all — it's a standalone input-injection module that
could be reused headlessly (e.g. from a script or a different UI toolkit).

## 3. `key_engine.py` — the uinput layer

This is the part of the app that actually talks to the kernel. Everything
above it is "what button did the user press"; this module is "how do we make
the kernel believe a real key was pressed."

### 3.1 Why uinput instead of alternatives

| Approach | Problem |
|---|---|
| Wayland virtual-keyboard protocol (`zwp_virtual_keyboard_v1`) | Compositor-specific, not guaranteed present, requires a Wayland client library binding not bundled with PyQt6 |
| `ydotool` / `wtype` subprocess calls | Extra runtime dependency, process-spawn overhead per keystroke, and `ydotool` itself is usually just a uinput wrapper anyway |
| IBus / input-method injection | Only reaches apps that are IBus/input-method aware; terminals and many native apps ignore it |
| **`/dev/uinput` via `python-evdev`** (chosen) | Kernel-level, universally seen by every app, X11 and Wayland alike, because it looks exactly like a real `/dev/input/eventN` keyboard to everything above the kernel |

The trade-off is that uinput requires device permissions (see §6.1) and,
because it fabricates *all* possible key codes up front, is sensitive to
exactly which codes get registered (see §6.2 — this was the source of one of
the two startup bugs fixed in this project).

### 3.2 `CHAR_MAP`

A static `dict[str, (keycode, needs_shift)]` covering the full ASCII
printable set. `type_text()` walks a string char-by-char, looks up each
character, and emits a shift-down → key-down → key-up → shift-up sequence
per character (`_emit_key`). Characters outside the map fall back to
`get_keycode()`, which upper-cases the input and prefixes `KEY_` to resolve
against `evdev.ecodes` directly (this is how raw keycode names like `"ESC"`
or `"F5"` get resolved without needing an explicit map entry).

### 3.3 Combo emission (`send_combo`)

Modifier keys are pressed down (in order), then the target key is
pressed-and-released, then modifiers are released in *reverse* order. This
ordering matters: releasing modifiers in reverse mirrors how a real hand
would lift fingers off a chord, and avoids emitting a modifier-release event
before the key that depends on it has actually gone down — some
applications' key-event state machines are sensitive to this.

### 3.4 The uinput device registration bug (fixed)

```python
events = {e.EV_KEY: [code for code in e.KEY.keys() if code <= e.KEY_MAX]}
```

`evdev.ecodes.KEY` is a `{code: name}` dict covering every `KEY_*`
constant — including `KEY_CNT = 768`, a sentinel meaning "one past the last
valid key," not a real key. `KEY_MAX` is `767`. Originally the code passed
*all* 514 entries straight to `UInput()`, including code `768`. The kernel's
`UI_SET_KEYBIT` ioctl rejects any code beyond `KEY_MAX` — the key bitmap only
has slots `0..767` — with `EINVAL` (errno 22), which aborts `UInput.__init__`
entirely. The engine's `self.ui` then silently stayed `None` and every
subsequent key call was a no-op, indistinguishable from an untouched UI on
the surface. The fix filters the code list to `<= KEY_MAX` before handing it
to `UInput()`.

### 3.5 The `/dev/uinput` permission requirement (fixed, deployment-side)

`/dev/uinput` is `root:input`, mode `0660`. A user not in the `input` group
gets a `PermissionError` at the exact same `UInput()` call, caught by the
same broad `except Exception`, printed only to stderr — invisible when
launched from a `.desktop` file with no attached terminal. Fixed by either:
adding the user to the `input` group, or a udev rule tagging the device
`uaccess` for the active logind seat (see install notes in §7).

Both failures above share a root shape worth remembering: **`UInput()`
failing is silent by design in this codebase.** `_init_uinput()` catches,
prints to stderr, and moves on; nothing downstream ever checks `self.ui`
except to no-op. That's why "the UI looks great but nothing types" was the
symptom for two completely unrelated causes. If a future change touches this
path, consider surfacing failure visibly (e.g., a Qt error dialog on
init failure) rather than only a stderr print.

## 4. `keyboard_window.py` — the UI layer

### 4.1 Window flags and why each one is there

```python
Qt.WindowType.WindowStaysOnTopHint |
Qt.WindowType.FramelessWindowHint |
Qt.WindowType.Tool |
Qt.WindowType.WindowDoesNotAcceptFocus
```

- `WindowStaysOnTopHint` — keyboard must float above the app being typed into.
- `FramelessWindowHint` — no titlebar; this is a keyboard, not a document window.
- `Tool` — signals "utility window," excluded from Alt-Tab.
- `WindowDoesNotAcceptFocus` — the single most important flag: it's what lets
  the keyboard sit on top and be clicked without ever stealing the text
  cursor away from whatever app the user is actually typing into.

Combined with `Qt.WidgetAttribute.WA_ShowWithoutActivating`, this gives the
"floats above everything, never takes focus" behavior the whole app depends
on.

**`Qt.WindowType.BypassWindowManagerHint` was removed (fixed — see §6.3).**
It used to be included here on the theory that it would make dragging and
always-on-top placement more reliable. On this KWin/Wayland stack it did the
opposite: it made the window fail to composite at all, especially on
re-show after `hide_to_badge()`. It is an X11 concept (override-redirect)
that Wayland's protocol model has no equivalent for; Qt's Wayland QPA plugin
does not handle it predictably. Removing it does not regress dragging,
because dragging is implemented separately via `startSystemMove()` (§4.2),
which needs no such flag.

### 4.2 Dragging

Two independent drag paths exist, layered for robustness:

1. **Primary (Wayland-correct):** `windowHandle().startSystemMove()`,
   triggered from `mousePressEvent` on the window itself, the dedicated
   `DragHandleLabel`, and the `FloatingBadge`. This delegates the actual
   move to the compositor — the only way to reposition a toplevel on
   Wayland, since a client can't just set its own global (x, y) the way it
   could on X11.
2. **Fallback:** manual `move()` calls tracking `_drag_pos` across
   `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`, used only if
   `startSystemMove` isn't available on the current windowing system.

### 4.3 Docking and positioning

`position_bottom()` computes geometry from `QScreen.availableGeometry()` —
95% of screen width, docked to the bottom by default, with `toggle_dock()`
flipping between a bottom dock and a top dock. Height is 320px normally, 300px
for the numpad layout (fewer rows).

### 4.4 The floating badge and the "disappears forever" bug (fixed)

`FloatingBadge` is a small always-on-top 56×56 circular button
(`hide_to_badge()` hides the main window and shows it; clicking it used to
call `self.hide()` then `parent_window.show_keyboard()` directly).

The user-visible symptom — minimizing the keyboard made it vanish with no
way back short of killing the process — traced to §4.1's
`BypassWindowManagerHint` bug, not to the badge itself. `hide_to_badge()` →
later → `show_keyboard()` re-shows the *same* window instance that carries
the broken flag, so the re-map attempt hit the same Wayland compositing
failure. Confirmed by a live A/B test on the actual desktop: identical code,
window flags with `BypassWindowManagerHint` present → invisible; same code
with it removed → renders correctly, every time.

While fixing this, the badge's click handler was consolidated into a new
`AuroraKeyboardWindow.bring_to_front()` method:

```python
def bring_to_front(self):
    if self.badge.isVisible():
        self.badge.hide()
    self.show_keyboard()
```

This exists so there is exactly one code path for "make the keyboard visible
regardless of current state," rather than duplicating hide/show logic between
the badge's click handler and (as of the fix below) the single-instance IPC
handler.

### 4.5 Key click handling and modifier state machine

`handle_key_click()` branches on the key's declared `type`
(`char` / `key` / `shift` / `caps` / `toggle_modifier`):

- **`char`** — resolves to a shifted or unshifted character depending on
  `shift_active`/`caps_active`, then either `type_text()`s it directly or,
  if any modifiers are toggled on, routes through `send_combo()` and clears
  the modifiers afterward (one-shot modifier behavior, like a physical
  keyboard chord).
- **`key`** — non-printable keys (Backspace, Enter, arrows, F-keys, etc.),
  same combo-vs-direct branching.
- **`shift`** — toggles one-shot shift; auto-clears after the next `char`
  press unless Caps Lock is also active.
- **`caps`** — toggles persistent caps state.
- **`toggle_modifier`** — Ctrl/Super/Alt/AltGr latch on/off; releasing Super
  specifically also emits a bare `KEY_LEFTMETA` tap on toggle-off, since many
  window managers bind bare-Meta-tap to the application launcher and this
  preserves that behavior when Super is used as a "hold-then-release"
  modifier rather than as part of a chord.

## 5. `layouts.py` and `styles.py` — declarative data

Both are intentionally free of any Qt or engine imports. A "layout" is a
list of rows, each a list of key-dicts with `label`, optional `shift_label`,
`type`, and rendering hints (`span` for relative width, `class` for QSS
styling). `keyboard_window.py`'s `build_keys()` is a generic renderer over
this data — adding a new layout or a new key is a pure-data change, no UI
code required.

Three layouts ship: `QWERTY_ROWS` (full text entry incl. nav cluster),
`DEV_ROWS` (F-keys, Esc, Del, terminal-heavy symbol row, Home/End/PgUp/PgDn),
`NUMPAD_ROWS` (compact numeric entry).

`styles.py` holds four QSS theme strings (`Aurora Glass`, `Cyber Neon`,
`OLED Dark`, `Light Velvet`) keyed in the `THEMES` dict, applied wholesale via
`setStyleSheet()` — theming is a stylesheet swap, not a code path change.

## 6. Bugs found and fixed this project (chronological)

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | Nothing typed anywhere, UI fully functional | `/dev/uinput` is `root:input 0660`; user not in `input` group → `PermissionError` on `UInput()`, silently caught | Add user to `input` group (or udev `uaccess` rule) |
| 2 | `[KeyEngine Error] ... [Errno 22] Invalid argument` on startup | `KEY_CNT` (768) included in the keybit list passed to `UInput()`, exceeds `KEY_MAX` (767), kernel `EINVAL`s the whole registration | Filter registered codes to `<= e.KEY_MAX` in `key_engine.py` |
| 3 | Minimizing to the badge makes the keyboard vanish permanently | `Qt.WindowType.BypassWindowManagerHint` breaks surface compositing on KWin/Wayland re-show | Remove the flag from `apply_flags()`; dragging is unaffected since it uses `startSystemMove()` |
| 4 | Taskbar icon spawns a new overlapping keyboard instead of restoring the existing one | No single-instance guard; every launch (autostart, `.desktop` launcher, taskbar click) started an independent process, each grabbing its own uinput device | `QLocalServer`/`QLocalSocket` single-instance guard in `main.py` — a second launch pings the first instance via `bring_to_front()` and exits instead of starting a competing process |

Bugs 1–2 were diagnosed from `key_engine.py` alone and confirmed by direct
Python reproduction. Bugs 3–4 were diagnosed by actually launching the app on
the live desktop, screenshotting before/after each candidate fix, and
cross-checking `journalctl`/`ps` for the systemd-scoped duplicate-process
evidence — not just code reading — since both were compositor/process-
lifecycle issues that don't show up from source alone.

### 6.1 Single-instance guard design (`main.py`)

```python
IPC_SERVER_NAME = "aurora-touch-keyboard-singleton"

def _notify_running_instance() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(IPC_SERVER_NAME)
    if socket.waitForConnected(200):
        socket.write(b"show")
        ...
        return True
    return False
```

On launch, the app first tries to connect to a well-known local socket name.
If that succeeds, another instance is already running — write a one-byte
"show" ping and exit immediately, never touching `KeyEngine`/`UInput` or
building any UI. If the connect fails (times out in 200ms), this *is* the
first instance: remove any stale socket file a crashed prior run might have
left (`QLocalServer.removeServer`), start listening, and proceed to build the
window as normal. The listening instance's `newConnection` handler calls
`window.bring_to_front()` on every ping received, which is the same method
the floating badge uses — so "restore from taskbar" and "restore from badge"
are the same code path.

This was verified live: launching a second process while the first was
running exited cleanly (`exit code 0`) with no new process left in `ps aux`,
where previously three independent `aurora-keyboard` processes were
observed to accumulate from repeated taskbar activation
(`journalctl` showed three separate `app-aurora-keyboard@<uuid>.service`
transient units).

## 7. Deployment (`install.sh`)

Symlinks the launcher script to `~/.local/bin`, writes a `.desktop` launcher
to `~/.local/share/applications` (for the app grid / taskbar pin), and an
autostart entry to `~/.config/autostart` that launches with `--badge-only`
(collapsed) so the keyboard doesn't cover the screen on every login. None of
`install.sh` sets up `/dev/uinput` access — that's a one-time manual step
(§3.5) not currently automated by the installer; a future revision could add
a udev rule drop-in as part of install.

Also not automated: forcing the badge/main-window screen position via KDE Window
Rules (Wayland gives the app itself no reliable way to do this - see the drag/position
history in §4). This is compositor-side config, external to the app, covered fully
in `WINDOW_RULES.md` - including four non-obvious failure modes (silent detection
failures, one-shot vs. persistent rule strength, and a required manual
`reconfigure()` call after any non-GUI edit) that make it worth reading before
attempting this by hand again.

## 8. Roadmap

### Swipe-to-type (in progress — see SWIPE_SPEC.md)

Gesture-based word input: drag a continuous path across letters instead of
discrete taps, matched against a dictionary to produce word candidates. This
moved past the design-sketch stage — gesture detection and a geometric
(SHARK²-style) decoder are built and live in `keyboard_window.py` /
`aurora_keyboard/swipe/`, plus a feasibility spike into using FUTO Swipe's
neural models as a higher-accuracy backend. Full current status, the
FUTO comparison data, and the forward plan (trail rendering, candidate bar,
lexicon-constrained FUTO scoring, etc.) live in `SWIPE_SPEC.md` — that file
is now the source of truth for this feature rather than this section.
