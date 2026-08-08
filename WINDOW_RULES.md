# KDE Plasma Window Rules — Badge & Keyboard Positioning

## Why this exists

On Wayland, an application cannot reliably position its own top-level windows —
unlike X11, the compositor (KWin) owns window placement, not the client. This app's
`QWidget.move()`/`setGeometry()` calls are largely ineffective for this reason (see
`ARCHITECTURE.md` for the app-side history of that discovery). **KWin Window Rules**
are the correct, sanctioned way to force position and stacking despite this — they're
compositor-side, so they can't destabilize the app itself, and they're the same
mechanism KDE's own panels/docks rely on.

This doc covers what the rules need to say, how to set them up, and — this is the
part worth actually reading — four non-obvious failure modes that made this take far
longer to get working than it should have.

## Current known-good configuration

Two windows, one process: the main keyboard and the floating badge share the same
application (same `wmclass`/app id, `aurora-keyboard`), so they need to be
distinguished by **window title** instead — each is given an explicit, distinct title
in code (`keyboard_window.py`):

- `AuroraKeyboardWindow.setWindowTitle("Aurora Touch Keyboard Main")`
- `FloatingBadge.setWindowTitle("Aurora Touch Keyboard Badge")`

`~/.config/kwinrulesrc`, as of this setup:

```ini
[3d7bb26c-6247-43d3-b27c-a8f7d9676d1c]
Description=Badge
above=true
aboverule=2
position=1400,800
positionrule=2
title=Aurora Touch Keyboard Badge
titlematch=1
wmclass=aurora-keyboard
wmclassmatch=1

[498c3a9e-7b5f-42b3-8a5a-46e47e67ef2a]
Description=Window settings for Aurora Touch Keyboard
above=true
aboverule=2
position=40,600
positionrule=2
size=1520,409
sizerule=3
title=Aurora Touch Keyboard Main
titlematch=1
wmclass=aurora-keyboard
wmclassmatch=1

[General]
count=2
rules=498c3a9e-7b5f-42b3-8a5a-46e47e67ef2a,3d7bb26c-6247-43d3-b27c-a8f7d9676d1c
```

`position=1400,800` for the badge and `position=40,600` / `size=1520,409` for the
main window are specific to this device's screen (a 1920×1280 tablet display) —
recalculate for a different resolution. As of the rotation fix below, the app
recalculates and rewrites these values itself, so treat them as a live cache
rather than a value to hand-tune.

## Rotation / resolution changes are handled automatically

KWin rules are just stored pixel values — they have no idea the screen exists,
let alone that it rotated. Left alone, a portrait/landscape flip on this tablet
put the badge's forced `position` past the new (narrower) screen edge entirely,
and left the main window's forced `size` wider than the display, because its
`sizerule` was `3` (**Apply** — only takes effect once, at initial mapping) rather
than `2` (**Force** — reapplies continuously). That's also why position "fixed
itself" on rotation but size didn't: Force live-updates, Apply doesn't.

`keyboard_window.py` now watches `QScreen.geometryChanged` (with a 400ms debounce,
since rotation fires several intermediate geometry events while it animates) and,
on any change:

1. Recomputes badge and main-window position/size from the *current*
   `screen.availableGeometry()`, using the same anchor formulas as
   `position_badge()`/`position_bottom()` (bottom-right corner for the badge,
   95%-width bottom-docked for the main window) — see `_badge_geometry()` /
   `_dock_geometry()`.
2. Writes the new values into `~/.config/kwinrulesrc` via `kwriteconfig6`,
   locating the right rule groups by `title=` match (not by hardcoded UUID, since
   those can change if the rules are ever rebuilt).
3. Forces `sizerule=2` on the main rule every time, so a stale `Apply` value
   left over from a GUI edit doesn't quietly reintroduce this bug.
4. Calls `qdbus-qt6 ... reconfigure` so the rewritten rule takes effect
   immediately, without waiting for the windows to unmap/remap.

This also runs once at startup (`_sync_kwin_rules_to_screen()` in `__init__`),
so relaunching the app while already in portrait self-heals the rule file instead
of inheriting whatever orientation it was last written for.

Two more bugs surfaced once rotation testing made the rule geometry live instead
of static, both fixed in the same anchor formulas:

**Height was a guessed constant, not the real content height.** `position_bottom()`
computed height as `360` (or `330` for NUMPAD) — a stale placeholder that never
mattered while `sizerule` was `3` (Apply-once), because the *actual* size on screen
stayed whatever the hand-tuned rule (`409`) applied at first launch. Once rotation
required `sizerule=2` (Force, so it can live-update), that guess started actively
overwriting the correct height on every sync — including at plain landscape
startup, no rotation needed. Measured directly (`self.sizeHint().height()`): `409`
for QWERTY/NUMPAD, `353` for DEV/TERM (a case the old constant didn't even
distinguish). `_dock_geometry()` now reads `self.sizeHint().height()` instead of
guessing.

**The bottom margin didn't clear the taskbar.** Both anchor formulas left only a
10–24px gap above the bottom of `screen.availableGeometry()`, on the assumption
that `availableGeometry()` already excludes the panel. It doesn't — not reliably,
for a `Force`-positioned `Tool`-flagged window like these. Confirmed by screenshot
pixel-sampling: the taskbar's top edge sits at physical `y=1226` (of `1280`), and
the forced window was landing with its bottom ~35 logical px past that, hiding the
last key row behind the panel. Fixed with an explicit `BOTTOM_CLEARANCE = 55`
(logical px) constant used by both `_badge_geometry()` and `_dock_geometry()`,
derived from that measurement plus a small buffer — not from trusting
`availableGeometry()`'s own panel accounting.

## Setting this up via the GUI (normal path)

1. **System Settings → Window Management → Window Rules → Add New**.
2. Click **Detect Window Properties**, then click the actual running window — do this
   **separately for the main keyboard and the badge**, since detection needs to
   happen per-window.
3. Enable and set to **Force**:
   - **Position** → the x,y you want
   - **Keep above others** → Yes
   - **Size** (main window only, if you want a fixed size)
4. Apply. Then see "The step everyone misses" below — it likely won't work yet.

## The four gotchas that actually mattered

These are listed in the order they blocked progress, since each one masked the next.

**1. "Detect Window Properties" can silently fail to read the window class off the
badge.** Clicking the picker on the badge captured its title correctly but left
`wmclass` completely empty — no error, just a blank field. Since the match mode was
still "Exact," an empty match value means the rule can never match anything. Suspect
cause: the badge's `Qt.WindowType.Tool | WindowDoesNotAcceptFocus` flags make it
behave differently to whatever introspection the picker uses, compared to a normal
focusable window (the main keyboard's class detection worked fine).
*Fix*: since both windows share the same app id anyway, just type `aurora-keyboard`
into the Window class field manually if detection leaves it blank - or edit the file
directly (see below).

**2. Without a distinct title, KDE cannot tell the badge and main window apart at
all.** Neither window set an explicit title originally, so both fell back to the
app-level name — meaning even a perfectly-formed rule had no way to target one
without the other. Fixed at the code level (see "Current known-good configuration").

**3. Rule "strength" is not just on/off — the wrong one looks like it's saved
correctly but doesn't behave persistently.** KWin's internal enum
(`src/options.h`, `PlacementPolicy`-adjacent rule-strength values):

| Value | Name | Behavior |
|---|---|---|
| 0 | Unused | — |
| 1 | DontAffect | Rule ignored for this property |
| 2 | **Force** | Persistently overrides KWin's own decision, every time the window (re)maps |
| 3 | Apply | Only applied once, at initial mapping |
| 4 | Remember | Restores whatever value the window last had when closed - not a fixed value |
| 5 | ApplyNow | Applies once immediately, **then deletes itself from the rule** (and un-registers the whole rule from the active list if nothing else in it persists) |
| 6 | ForceTemporarily | Force, but only until the window closes |

`ApplyNow` (5) is genuinely useful for live-testing a value before committing to it
(that's how the correct badge position was found - visually confirmed via ApplyNow,
then locked in via Force), but it is **not** a permanent setting - using it is what
made an entire rule appear to "disappear" from System Settings after use. Only
**Force (2)** persists reliably across every minimize/restore cycle.

**4. This is the one that actually mattered most: editing `kwinrulesrc` outside the
GUI does not take effect until KWin is told to reload it.** The System Settings KCM
sends a reload signal automatically when you click Apply; hand-editing the file (or
scripting it, e.g. with `kwriteconfig6`) does not trigger that signal on its own.
Every other fix in this document could be perfectly correct on disk and *still
silently do nothing* without this:

```bash
qdbus-qt6 org.kde.KWin /KWin org.kde.KWin.reconfigure
```

This was root-caused by testing with a minimal, zero-app-logic throwaway window
(same title/flags as the badge, no positioning code at all) - it also ignored the
rule until `reconfigure()` was called, which proved the issue was KWin-side, not
anything in this app's own code.

## Reproducing this from scratch

If the rules ever get reset (reinstall, corrupted config, etc.), the fastest path is
direct file edits plus an explicit reload, rather than fighting the GUI picker again:

```bash
RULESFILE=~/.config/kwinrulesrc
BADGE_ID=$(uuidgen)   # or reuse an existing group name
MAIN_ID=$(uuidgen)

kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key wmclass "aurora-keyboard"
kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key wmclassmatch 1
kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key title "Aurora Touch Keyboard Badge"
kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key titlematch 1
kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key position "1400,800"
kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key positionrule 2
kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key above "true"
kwriteconfig6 --file "$RULESFILE" --group "$BADGE_ID" --key aboverule 2

kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key wmclass "aurora-keyboard"
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key wmclassmatch 1
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key title "Aurora Touch Keyboard Main"
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key titlematch 1
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key position "40,600"
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key positionrule 2
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key size "1520,409"
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key sizerule 2
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key above "true"
kwriteconfig6 --file "$RULESFILE" --group "$MAIN_ID" --key aboverule 2

kwriteconfig6 --file "$RULESFILE" --group General --key count 2
kwriteconfig6 --file "$RULESFILE" --group General --key rules "${MAIN_ID},${BADGE_ID}"

qdbus-qt6 org.kde.KWin /KWin org.kde.KWin.reconfigure
```

Then relaunch `aurora-keyboard` to verify.
