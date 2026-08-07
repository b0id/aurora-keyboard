# Swipe-to-Type — Spec & Plan

## Current State (as of Aug 2026)

Two things exist, at very different levels of completeness. Read this section first —
everything below it is either background for how we got here, or the plan forward.

**1. Geometric decoder — built, tested, wired into the live app, not yet visible to you.**
- Gesture detection is live in `keyboard_window.py`: dragging across letter keys
  (past a movement threshold) is correctly distinguished from a normal tap. Tap-typing
  is provably unaffected — verified by real use, not just review.
- Each detected swipe is decoded by `aurora_keyboard/swipe/decoder.py` against a
  ~1,175-word bundled dictionary, using the keyboard's real on-screen key positions
  (not a synthetic grid) — this is scale/orientation-aware, so it stays correct across
  window resizes, docking, and redocking.
- Result: **nothing visible happens yet.** The decoded word currently only goes to a
  log line (`[Swipe] path=... -> [...]`) — there's no candidate bar, no trail, no way
  to actually use a swipe result yet. This is why swiping "feels like nothing happens"
  right now: correct, expected, not a bug.
- Accuracy on real swipes: modest. It got 1 of the 4 words in the head-to-head test
  below right; it's a pure geometry match with no learning, no frequency weighting, no
  timing signal.

**2. FUTO Swipe — feasibility spike only, not part of the app.**
- Proven to work: FUTO's tiny encoder model genuinely loads and runs via `executorch`,
  in an isolated container, on real captured swipe data, producing correctly-shaped,
  accurate-looking output (3/4 correct on the same real-swipe test, with zero lexicon
  constraint applied).
- This is 100% separate from the running app. No FUTO code, model, or dependency is
  loaded by `aurora-keyboard` — the spike ran standalone Python scripts inside the
  `ydotool-box` container. If that container disappeared, the live keyboard would be
  completely unaffected.
- Full details, the actual numbers, and how to reproduce it: see "FUTO Spike" section
  below.

**3. Temporary diagnostic code still in `keyboard_window.py`** (flagging for clarity,
not urgency — it's inert unless a swipe happens, and does nothing but write a file):
- `swipe_raw_start` / `swipe_raw_sample` / the raw-trail JSON dump in `swipe_end()` —
  added purely to capture real `(x, y, t_ms)` swipe data for the FUTO comparison.
  Writes to `scratchpad/swipe_captures/*.json` on every swipe. Harmless, but not
  meant to be permanent - remove once no longer needed for FUTO experiments, or
  formalize it if we decide it's useful ongoing (e.g. for tuning later).

## Goal

Add optional swipe-to-type on top of the existing tap keyboard, without touching or
risking the tap-typing path. Tap-typing is the only working input method right now —
every step below must leave it byte-for-byte unchanged if swipe is never engaged.
This has held throughout: every milestone so far was verified not to regress typing
before moving on.

## Why a custom decoder, not a library

Checked for a well-supported, pre-built swipe-to-type system before writing any code:

- Google/Gboard's real gesture engine is proprietary — not available.
- FUTO Swipe and CleverKeys are the only credible open options, but both ship as
  models built primarily for Android (ExecuTorch/ONNX, C++ inference libs), not as
  a Python/Qt library. The FUTO spike (below) confirmed the models *can* run outside
  Android via Python `executorch` — but it needed an isolated container, a dependency
  version fix, and real debugging to get there. Still not a drop-in.

No drop-in library exists for this stack. So what's actually built (v1) is a small,
dependency-free geometric decoder — the SHARK²-style approach classic gesture
keyboards (Swype, etc.) used before neural models: compare the user's swipe path
against each dictionary word's "ideal" path through its letters' key centers, pick the
closest match. No ML, no model downloads, no new dependencies, fully offline.

## Module layout

`aurora_keyboard/swipe/`
- `decoder.py` — `SwipeDecoder`. Pure geometry, no Qt import. Takes key positions
  as a plain `{letter: (x, y)}` dict rather than hardcoding a layout, so it works
  identically against a synthetic test grid and against the live keyboard's actual
  button centers - same code either way. Scale-aware: pruning distance derives from
  the actual key spacing it's given, not a fixed constant, so it works correctly at
  any window size/orientation.
- `wordlist.py` + `wordlist.txt` — bundled common-English word list (offline, no
  system dictionary dependency). Not frequency-ranked yet (see Plan).
- `selftest.py` — standalone correctness check (no pytest dependency, run with
  `python3 -m aurora_keyboard.swipe.selftest`).

Gesture capture and wiring live directly in `keyboard_window.py`:
- `SwipeKeyButton` — the char-key button class. Distinguishes tap from drag itself
  (it's the widget that actually receives mouse events, not its parent), so a plain
  tap is completely unaffected below the movement threshold.
- `AuroraKeyboardWindow.swipe_begin/swipe_update/swipe_end` — accumulates the
  key-crossing path during a drag and runs it through `SwipeDecoder` on release.
  Currently logs the result; does not yet act on it (no candidate bar exists).
- `_build_key_positions()` — reads live button geometry fresh on every swipe, which
  is what makes this correct across resize/redock without any special-casing.

## FUTO Spike

A feasibility spike (Aug 2026) tested whether FUTO Swipe's actual models could run at
all on this system, and how they'd compare to the geometric decoder on real data.

### Design considerations learned, regardless of whether FUTO itself ever gets integrated

- **Time-aware sampling.** FUTO resamples the trajectory at even *time* intervals
  (60Hz) before matching. `decoder.py`'s `_resample()` resamples by even *arc length*
  only — no timing signal at all, so pauses/dwell (which usually mark an intended
  key) are invisible to it. `keyboard_window.py` already captures the dense raw
  `(x, y, t_ms)` trail during a swipe (the temporary diagnostic capture noted above);
  using it to weight or select points before geometric matching is a real, non-neural
  improvement path.
- **Layout supplied at inference time, not hardcoded.** This is FUTO's "layout-agnostic"
  design: key coordinates + a validity mask are model inputs, not baked-in assumptions.
  `SwipeDecoder` already does this — no change needed here.
- **Frequency-ranked vocabulary.** FUTO's dictionary/context-LM weight by word
  frequency; `wordlist.py` currently does not — every word is equally likely. Cheap to
  add later, doesn't require any model.
- **Confidence/intention gating.** FUTO's encoder emits a per-step "intention gate" -
  a learned signal for which trajectory points are real intended key presses vs.
  in-between motion. The geometric decoder has no equivalent. A heuristic stand-in
  (weight points near direction changes more heavily) is worth exploring without
  needing the actual model.
- **Backend should be swappable, not hardcoded.** If FUTO integration is ever pursued
  for real, it should sit behind the same "key_positions in, word scores out"
  interface `SwipeDecoder` already exposes, so the UI (trail rendering, candidate bar)
  doesn't need to know or care which backend answered.

### Head-to-head result

Same real, messy human swipes (raw captured trail, not synthetic) fed to both
decoders. FUTO here is *just* the single encoder model with naive greedy CTC
decoding — no lexicon, no beam search, no context-LM — closer to FUTO's own worst
case than its real one.

| Intended word | Path crossed | Geometric decoder | FUTO encoder (greedy) |
|---|---|---|---|
| good | ghuiopoiuytfd | type ✗ | gppf ✗ (plausible near-miss, not noise) |
| well | werfghjkl | who ✗ | well ✓ |
| bad | bvfdsasd | bad ✓ | bad ✓ |
| apple | asdfghjklplkjuytre | swipe ✗ | apple ✓ |

FUTO's bare encoder, with no lexicon constraint at all, got 3/4 exactly right on real
sloppy swipes, including two the geometric decoder missed outright. The one miss is
consistent with FUTO's own documented caveat that greedy decoding alone is "fairly
inaccurate" — expected to improve with a lexicon constraint, which this spike
deliberately didn't build yet. This is a real, material accuracy gap in FUTO's favor,
not a marginal one — worth weighing against the integration cost (container/runtime
complexity, ~5GB of container-local dependencies, still-unbuilt beam search layer).

### Key implementation gotcha

FUTO expects trajectory *and* key coordinates normalized to `[0,1]` relative to the
keyboard's own bounding box — not raw pixels. Feeding raw screen coordinates produced
pure noise output with no error at all; this is easy to get wrong silently. Any future
FUTO code must normalize both trajectory and key positions through the same transform
before calling the encoder.

### Spike environment (for reproducing or extending)

- Container: `ydotool-box` (existing distrobox, Fedora 41, Python 3.13.9) — reused
  rather than creating a new one, since `executorch` doesn't ship wheels for this
  system's default Python 3.14.
- `pip install executorch` pulls torch unpinned, which resolved to an incompatible
  version (ABI mismatch, `undefined symbol` on import) — had to force
  `torch==2.12.0` to match what executorch 1.3.1 was actually built against (see
  `install_requirements.py` in the executorch repo for the current pin — this will
  drift as both projects release new versions).
- Model used: `futo-org/futo-swipe`, file `honorable_sturgeon/model_fp32.pte` (the
  encoder only — 2.65MB). Loaded and run via `executorch.runtime.Runtime`.
- Installing pulled ~5.2GB into the container (full torch + CUDA libs for a 2.65MB
  CPU model) — contained to the container, doesn't touch the host or the main app's
  environment, but worth knowing before repeating this.
- License: FUTO Model Weights License 1.0 — genuinely permissive (personal and
  commercial use both fine), the only real requirement is a visible "powered by FUTO
  Swipe" attribution notice if shipped.

## Plan Going Forward

Two independent tracks. Track A is safe, small, and ships visible value on what
already works. Track B is the higher-ceiling, higher-cost path. They don't block each
other — A doesn't need to wait on B, and B's early steps (lexicon scoring) don't touch
the live app at all.

### Track A — make the geometric decoder actually usable (low risk, builds on what's live)

1. **Swipe-path trail rendering** — visual feedback while dragging, so the feature is
   legible instead of invisible mid-swipe. Pure paint overlay, no behavior change.
2. **Candidate bar + word insertion** — surface the top few results, tap to insert via
   the existing `KeyEngine.type_text()`. This is what turns the current log-only
   diagnostic into an actual feature.
3. **Frequency-weight the wordlist** — cheap, no new dependency, directly improves
   real accuracy (ties currently resolve arbitrarily; common words should win).
4. **Tune pruning/threshold constants** against real usage once the above exist.

### Track B — evaluate FUTO further (higher potential accuracy, real cost)

1. **Lexicon-constrained scoring using the encoder already proven working** — instead
   of naive greedy CTC, score each dictionary word against the encoder's output
   directly (forced-alignment style). No new models, no new integration architecture,
   same container. Directly targets the one failure mode seen above ("good" → "gppf").
   This is the next concrete FUTO step, not yet started.
2. **Chain in the other two models** (layout-specific decoder + context-LM) for
   FUTO's real intended pipeline, once step 1 shows the approach is worth it.
3. **Design the runtime bridge**: the main app runs Python 3.14; `executorch` needs
   3.10-3.13. Any real integration needs a deliberate answer for how they talk to each
   other (subprocess call per swipe, small persistent local daemon in the container,
   etc.) — not decided yet.
4. **Only after 1-3**, consider wiring a FUTO backend into the live UI, behind the same
   swappable interface `SwipeDecoder` already exposes — geometric decoder remains the
   safe fallback throughout.

### Suggested order

Track A first for visible progress (low risk, makes the already-built decoder
actually usable), Track B step 1 (lexicon scoring) alongside or after — it's cheap
and answers the real open question ("how good can FUTO get without the full 3-model
pipeline") before committing to the bigger, riskier steps 2-4.

## Non-goals (still true)

- No personalization or learning from usage
- No autocorrect blending with tap-typing
- No multi-language support
- No GPU dependency (both the geometric decoder and the FUTO spike run CPU-only)

## Milestone log

| # | Scope | Status |
|---|---|---|
| M1 | Decoder + wordlist, standalone-tested | Done |
| M2 | Swipe-vs-tap gesture detection on the key grid, wired live | Done |
| — | Scale/orientation-awareness fix (pruning radius was a hardcoded constant) | Done |
| — | FUTO feasibility spike (encoder-only, greedy decode, container-isolated) | Done |
| M3 | Trail rendering + candidate bar UI + word insertion (Track A) | Done |
| M4 | Wordlist frequency weighting + threshold tuning (Track A) | Done |
| — | FUTO Neural IPC Daemon (`futo_daemon.py`) + Host Client (`FutoSwipeClient`) | Done |
| — | Unified `SwipeManager` (FUTO Neural Primary + Geometric Fallback) | Done |
