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
recalculate for a different resolution.

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
