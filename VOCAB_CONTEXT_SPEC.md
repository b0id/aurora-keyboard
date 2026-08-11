# Vocabulary, Context & Headless Testing Architecture Specification

**Document Version:** 1.1.0
**Target Subsystem:** Aurora Keyboard Swipe & Inference Subsystem
**Status:** Approved Architecture & Sequenced Implementation Plan

> **Revision note (v1.1.0, 2026-08-10):** v1.0.0 was written before the current
> codebase was audited against it. That audit found a live bug and several
> unstated architectural gaps (see §5.1). This revision corrects the spec's
> numeric claims to match what's actually true today, reorders the milestones
> so the cheapest/highest-value fix comes first and a measurement harness
> exists before any tuning work, and adds §9 codifying how this work gets
> built without risking the user's only working input method. No content
> below should be read as already-shipped unless it's explicitly labeled
> "current state" — everything else is a target, not a fact.

---

## 1. Executive Summary & Core Objectives

Aurora Touch Keyboard currently features a functioning Wayland layer-shell interface, custom gesture trail overlays, and an ExecuTorch-based neural swipe inference daemon (`futo_daemon.py`). While shorter high-frequency words resolve accurately, complex multi-syllable vocabulary (4–5 syllables in common parlance, professional discourse, and technical writing) frequently fails to resolve or gets overshadowed by short unigram matches.

### Key Tenets
1. **Zero UI Regression**: No modifications to the visual presentation, themes, animations, touch responsiveness, or layout sizing of the keyboard.
2. **Prioritize 4–5 Syllable Common Parlance**: Elevate recognition for expressive vocabulary (e.g., *sophisticated, infrastructure, implementation, vulnerability, characteristic, sustainability, communication, unprecedented*).
3. **Stateless Workaround via Ephemeral Rolling Context**: Bridge the Wayland application isolation gap using an internal rolling token state machine with robust punctuation and cursor boundary handling.
4. **Fix Truncation Before Chasing Scale**: Restore access to the vocabulary already downloaded and paid for before curating anything new, and index it with a fast letter-bucketed structure so latency stays low as it grows. See §5 — the honest starting point is smaller than v1.0.0 assumed, and the growth path is staged, not a single jump to 70,000.
5. **Portable by Default, Not Just by Architecture**: Every vocabulary/context improvement must reach the zero-dependency geometric fallback (what a first-time GitHub user gets with no container install), not only the neural daemon path. See §5.2.
6. **Autonomous Agentic & CI/CD Ready**: Provide a fully headless, synthetic trajectory benchmark harness that AI agents and CI/CD pipelines can run in isolation with zero display/Wayland dependencies — built *before* tuning work starts, so every later milestone is measured against real numbers instead of estimated ones.

---

## 2. Problem Analysis: Multi-Syllable Words in Gesture Keyboards

### Root Causes for 4–5 Syllable Degradation
1. **Unigram Frequency Penalty**: Standard language models heavily skew toward 1–2 syllable words (*the, in, of, that*). In a pure unigram scoring formula:
   $$\text{Score}(w) = -2.8 \cdot \text{Dist}(w) - 0.5 \cdot \ln(\text{Rank}(w))$$
   A 4-syllable word ranked at #12,000 incurs a severe penalty compared to a 1-syllable word ranked at #50.
2. **Cumulative Kinematic Path Drift**: Longer words require longer continuous gestures. Slight corner-cutting across 4–5 inflection points leads to higher Levenshtein/spatial drift.
3. **Lexicon Truncation — CONFIRMED and FIXED in Milestone 0 (2026-08-10)**: `futo_daemon.py:158` read `pool = _VOCAB[:15000]`. The vocabulary actually downloaded from `futo-org/futo-swipe` (`hungry_jellyfish/vocab.txt`) contains **32,768 words**, frequency-ordered — 2,551 of them length ≥11 (a proxy for 4–5 syllables) sat entirely beyond the old cutoff and were structurally unreachable no matter how good the trajectory match was. Fixed by removing the slice (now `pool = _VOCAB`).
   **Empirical before/after** (synthetic straight-line trails through key centers, live daemon, see `git log` for the change): all 4 sampled beyond-cutoff words (`longstanding`, `navigational`, `originality`, `probabilities`) went from a hard MISS (word not in searchable pool at all) to top-1 HIT after the fix, with zero regression on 4 control words and the spec's own named examples. **Important correction to the original hypothesis**: 3 of this spec's 4 named example words (`characteristic`, `sustainability`, `unprecedented`) were already ranked well inside the old 15,000 cap and already resolved correctly both before and after — this bug was not why those specific words failed for the user. `infrastructure` (rank 2,704, also inside the old cap) still misses on a synthetic straight path both before and after the fix, resolving to `inmate`/`immature` instead — that's a scoring/matching issue, not a vocabulary coverage issue, and is carried forward as an open item for Milestone 3's scoring calibration rather than something this fix addresses.
4. **Lack of Preceding Context**: Long words are often predictable given the preceding word (e.g., *"critical"* $\to$ *"infrastructure"*, *"artificial"* $\to$ *"intelligence"*). Without bigram context, the decoder cannot disambiguate borderline trajectories.

---

## 3. Architecture & Zero-Interference System Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AURORA CLIENT (Host)                             │
│                                                                             │
│  ┌──────────────────────────┐             ┌──────────────────────────────┐  │
│  │   AuroraKeyboardWindow   │             │   CandidateBar (UI Untouched)│  │
│  │                          │             │   [ ✓ infrastructure ]       │  │
│  │ ┌──────────────────────┐ │             │   [ implementation ]         │  │
│  │ │ RollingTokenContext  │ │             └──────────────▲───────────────┘  │
│  │ │ FIFO [ "critical" ]  │ │                            │                  │
│  │ └──────────┬───────────┘ │                            │                  │
│  └────────────┼─────────────┘                            │                  │
│               │ (raw_trail, key_positions,               │ candidates       │
│               │  context=["critical"])                   │                  │
│               ▼                                          │                  │
│  ┌──────────────────────────┐                            │                  │
│  │      FutoSwipeClient     │────────────────────────────┘                  │
│  └────────────┬─────────────┘                                               │
│               │                                                             │
│  ┌────────────▼─────────────┐   shared import, no container needed         │
│  │  aurora_keyboard/swipe/  │◄──────────────────────────────────┐          │
│  │  lexicon.py (NEW, §5.2)  │                                    │          │
│  │  LetterBucketIndex +     │                                    │          │
│  │  merged wordlist         │                                    │          │
│  └────────────┬──────────────┘                                    │          │
│               │ used by BOTH backends, so the fallback below     │          │
│               │ benefits without needing the daemon at all       │          │
│  ┌────────────▼─────────────┐                                    │          │
│  │  decoder.py (Geometric   │────────────────────────────────────┘          │
│  │  Fallback — no container │                                               │
│  │  or network required)    │                                               │
│  └───────────────────────────┘                                              │
└───────────────┼─────────────────────────────────────────────────────────────┘
                │ Unix Domain Socket: /tmp/futo_swipe.sock (JSON IPC)
┌───────────────┼─────────────────────────────────────────────────────────────┐
│               ▼                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                  FUTO NEURAL DAEMON (futo_daemon.py)                  │  │
│  │                                                                       │  │
│  │  1. Spatial Encoder (Honorable Sturgeon 1D-CNN) ──► Greedy CTC        │  │
│  │                                                          │            │  │
│  │  2. lexicon.py LetterBucketIndex (shared, see above) ◄───┤            │  │
│  │     • Fast (start_char, end_char, length) Candidate Sieve│            │  │
│  │                                                          ▼            │  │
│  │  3. Multi-Factor Contextual Scorer                       │            │  │
│  │     • CTC Edit Distance + Length Prior                   │            │  │
│  │     • Unigram Frequency (Rank-scaled)                    │            │  │
│  │     • Pruned Bigram LM Context Table (log P(w|w_prev))   │            │  │
│  │     • Dynamic User Lexicon Boost                         │            │  │
│  │                                                          ▼            │  │
│  │  4. Top-5 Ranked Word Output ────────────────────────────┘            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                       ISOLATED / SANDBOX INFERENCE LAYER                    │
│           (runs in ydotool-box distrobox container — a crash here          │
│            never touches the live AuroraKeyboardWindow process)            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**What changed from v1.0.0**: the 70k-word bucket index was originally drawn living entirely inside the daemon box. It now lives in a shared `lexicon.py` module imported by both the daemon's scorer *and* the geometric fallback decoder. Without this, every vocabulary improvement in this spec would only reach users who've installed the ~5GB executorch/distrobox container — which is not "available to all people," it's available to people who did a heavy optional install. See §5.2.

### Zero-Interference Guarantees
- **No GUI Layout Alterations**: `CandidateBar`, `SwipeTrailOverlay`, `KeyButton`, and keyboard geometry managers remain completely unchanged.
- **Protocol Backward-Compatibility**: The IPC JSON contract retains `raw_trail`, `key_positions`, and `top_n`. The new `context` and `session_meta` parameters are strictly optional. If omitted, the daemon behaves as a standard unigram decoder.
- **Fallback Integrity**: If the daemon is unreachable, the fallback `SwipeDecoder` operates transparently with its expanded local wordlist (post-§5.2, this is no longer a stub 1,200-word list — see below).

---

## 4. Working Around Wayland Statelessness: Ephemeral Rolling Token Machine

### The Wayland Constraint
Under Wayland security protocols (e.g., `zwp_input_method_v2` / `wlr-layer-shell`), an on-screen keyboard is prohibited from inspecting foreign window contents or querying the focused cursor's surrounding text.

### The Solution: Internal Deterministic Token Tracker
Aurora will track an internal **5-token rolling FIFO queue** inside `AuroraKeyboardWindow` with automatic boundary detection. This is application-level state only — it reads events the app already sees, doesn't touch any new system API, and has no UI surface, which is why it's the lowest-risk piece of this whole spec.

```python
class RollingTokenContext:
    """Manages ephemeral preceding text context within the current input session."""
    def __init__(self, max_tokens: int = 3, idle_timeout_sec: float = 25.0):
        self.max_tokens = max_tokens
        self.idle_timeout_sec = idle_timeout_sec
        self._tokens: list[str] = []
        self._last_event_time: float = 0.0

    def push_word(self, word: str):
        self._tokens.append(word.strip().lower())
        if len(self._tokens) > self.max_tokens:
            self._tokens.pop(0)

    def handle_key(self, keycode_or_char: str):
        # Reset boundary on punctuation or navigation
        if keycode_or_char in [".", "!", "?", "ENTER", "TAB", "ESC"]:
            self.reset()
        elif keycode_or_char == "BACKSPACE":
            self.pop_char_or_token()

    def get_context(self) -> list[str]:
        # Expire stale context after user pause
        if time.time() - self._last_event_time > self.idle_timeout_sec:
            self.reset()
        return list(self._tokens)
```

#### Boundary Reset Rules
1. **Sentence Terminators**: Typing `.`, `!`, `?` or pressing `ENTER` resets the context buffer to `["<s>"]` (sentence start).
2. **Navigation Events**: Pressing cursor keys (`LEFT`, `RIGHT`, `UP`, `DOWN`) or `TAB` clears the buffer, avoiding incorrect context associations when the user clicks elsewhere.
3. **One-Tap Candidate Replacements**: If candidate chip #2 is tapped, `CandidateBar` replaces the last word in the rolling context queue before dispatching the key events.

#### Confirmed integration points (found by code audit, not yet wired)
- `keyboard_window.py:669` — `self.candidate_bar.set_candidates(candidates, backend)` is called immediately after every swipe decode and already knows the committed word (`candidate_bar.py`'s `set_candidates` auto-commits `candidates[0]` via `self.parent_window.engine.type_text(...)`). This is the natural call site for `RollingTokenContext.push_word()` — no new event hook needed.
- `keyboard_window.py:673` (`handle_key_click`) already branches on `ktype in {"char", "key"}` for every keystroke, including punctuation and navigation. This is the natural call site for `RollingTokenContext.handle_key()`.
- Both hook points mean `RollingTokenContext` can be added as pure new code with two single-line call insertions into `keyboard_window.py`, rather than restructuring existing logic there. Keeping the diff in that file minimal is deliberate — see §9.

---

## 5. Lexicon & Search Optimization

### 5.1 Current State (confirmed by code audit, 2026-08-10)

| Component | Current State |
| :--- | :--- |
| FUTO daemon vocab (downloaded from HF, frequency-ordered) | 32,768 words |
| FUTO daemon candidate pool actually searched | **capped at 15,000** by the `_VOCAB[:15000]` bug (§2.3) |
| Geometric fallback wordlist (`swipe/wordlist.txt`) | 1,200 words, entirely separate from the daemon's vocab |
| Daemon process supervision | **none** — started manually via `./aurora-futo-daemon &`, no systemd unit, no auto-restart, no auto-launch from `main.py` |
| CI/CD | none — no `.github/` directory exists yet |
| Headless test coverage | `tests/test_swipe_e2e.py`, `aurora_keyboard/swipe/selftest.py` — real prior art to extend, not a green field |

v1.0.0 framed the target as "scale from 15,000 to 70,000+ words," which conflated the truncation bug with a genuine curation goal. The honest sequence is:

1. **Milestone 0**: fix the truncation bug. This alone raises the daemon's searchable pool from 15,000 to the full 32,768 already on disk — more than doubling it — for a one-line change and zero new data.
2. **Measure** (Milestone 1 harness) whether 32,768 words, once the length-prior and bigram terms (§6) are in place, already clears the accuracy gates in §7.
3. **Only then** decide whether curating an additional word set (v1.0.0's proposed 25k expressive + 10k technical corpus) is worth the maintenance cost. Bloating the pool with low-quality entries is a real risk, not a hypothetical one — `wordlist.py`'s existing docstring already notes this exact failure mode from an earlier decision to avoid `/usr/share/dict/words`. Scale is not free; every extra low-frequency word is a false-positive risk for shorter/mid-length words too.

This turns "scale to 70,000" from a committed deliverable into a **staged, evidence-gated goal** — which is what "achievable and realistic" means in practice here.

### 5.2 Shared Lexicon Module (new in v1.1.0)

Create `aurora_keyboard/swipe/lexicon.py` as the single source of truth for vocabulary and indexing, imported by both:
- `futo_daemon.py`'s contextual scorer (runs in the container), and
- `decoder.py`'s geometric fallback (runs in-process, no container, no network) — currently stuck on a 1,200-word list that none of this spec's improvements would otherwise reach.

```
lexicon.py responsibilities:
  - Merge base wordlist + any curated additions into one ordered vocabulary.
  - Build the LetterBucketIndex (see below) once, expose it to both callers.
  - Own custom_words.txt loading/hot-reload (§6) so both backends see user boosts.
  - Validate and sanitize every entry before it enters the pool (see below).
  - Reload atomically so an in-flight decode never sees a half-updated pool.
```

This is the change that makes the spec's "available to all people, not just Aurora users" goal actually true: a first-time GitHub user who never installs the executorch container still gets the expanded, bucket-indexed vocabulary through the geometric decoder — not just the 1,200-word placeholder list it ships with today.

#### Data Integrity (new in v1.1.0, added 2026-08-11)

Neither the current `_VOCAB`/`_VOCAB_RANKS` loading in `futo_daemon.py` nor the planned `custom_words.txt` hot-reload (§6) has a validation or concurrency plan today — this closes that gap before Milestone 2 builds on it:

1. **Validate on load, for every source (downloaded vocab, bundled `wordlist.txt`, `custom_words.txt`)**: strip whitespace, lowercase, reject empty strings and any character not present in the active `key_positions` layout (catches emoji, accents, stray punctuation, blank lines). A malformed `custom_words.txt` entry — user-edited, so the least trustworthy input in this pipeline — must be dropped with a logged reason, never allowed to crash the scorer or silently corrupt the bucket index.
2. **Deduplicate deliberately, not incidentally.** Today `_VOCAB_RANKS = {w: i for i, w in enumerate(_VOCAB)}` (`futo_daemon.py:49`) lets the last occurrence of a duplicate silently win. `lexicon.py` makes this an explicit rule: first occurrence (highest frequency-rank source) wins, later duplicates are dropped, not silently overwritten.
3. **Reload atomically.** `handle_client` (`futo_daemon.py:207`) runs each connection in its own thread, so a `custom_words.txt` hot-reload landing mid-decode is a real race, not a hypothetical one. `lexicon.py` builds the new merged vocabulary + bucket index fully off to the side, then swaps a single module-level reference — never mutates the live structures in place. Any decode already in flight finishes against the pool it started with.

### 5.3 Spatial Pre-Filtering (Letter-Bucket Inverted Index)

To prevent the latency spike associated with linear Levenshtein checks as the pool grows, words are partitioned into an inverted index by `(start_char, end_char)` and length bands:

```
Index Structure:
  _BUCKETS[(start_char, end_char)] -> list of words
```

Given detected gesture endpoints (e.g., gesture begins near `c` and ends near `n`):
1. The engine checks neighboring start/end key clusters (e.g., `c/v/x` to `n/m/b`).
2. Candidate pool shrinks substantially — the exact ratio depends on the final vocab size chosen per §5.1's staged process, and will be measured, not assumed.
3. Target: sub-millisecond Levenshtein + score computation in pure Python at the current 32,768-word scale. **To be verified empirically in Milestone 1 before being treated as met.**

---

## 6. Syllable-Aware & Bigram Scoring Formulation

The final candidate ranking uses a balanced multi-factor scoring function:

$$\text{FinalScore}(w) = \text{Spatial}(w) + \text{LenPrior}(w) + \lambda_{\text{uni}} \ln P(w) + \lambda_{\text{bi}} \ln P(w \mid w_{t-1}) + \text{UserBoost}(w)$$

Where:
- **$\text{Spatial}(w)$**: $-2.8 \cdot \text{Levenshtein}(\text{CTC\_greedy}, w)$ — existing constant, carried over from the current scorer.
- **$\text{LenPrior}(w)$**: Compensates for the inherent unigram frequency bias against long words. Starting hypothesis: if raw trail duration $\ge 400\text{ms}$ and character count $\ge 9$, apply $+1.8 \cdot \ln(\text{length})$. **This constant is a starting point, not a tuned value** — it must be calibrated against the Milestone 1 harness's real accuracy numbers, since nothing in this system has been tuned against measured data yet.
- **$\text{Bigram}(w \mid w_{t-1})$**: Log-probability from a compact top-bigram table. **Open scope item**: v1.0.0 specified "a 4MB pruned table covering 300,000 high-frequency transitions" without naming a data source. That number was aspirational, not sourced. Building this requires an actual offline bigram frequency corpus (e.g., derived from the `wordfreq` package's bundled data, which is pip-installable and has no network dependency at runtime) — table size and transition count will be whatever that source actually yields after pruning to the shared lexicon's vocabulary, not a pre-committed figure. This is real, scoped work (Milestone 3), not a one-line addition.
- **$\text{UserBoost}(w)$**: Dynamic weight bonus for words in `~/.config/aurora-keyboard/custom_words.txt`.

### Dynamic User Lexicon (`custom_words.txt`)
- Stored in standard plain-text / JSONL format at `~/.config/aurora-keyboard/custom_words.txt`.
- Loaded through the shared `lexicon.py` module (§5.2) so both backends honor it, subject to the same validate-on-load and atomic-reload rules (§5.2 Data Integrity) — this file is user-edited, so it's the least trustworthy input source in the pipeline and gets no exception from those rules.
- Users or automated tooling can add custom domain terms.
- Whenever a user selects a suggestion from the candidate bar, its local frequency counter increments.

---

## 7. Headless Agentic Testing & CI/CD Framework

The entire gesture recognition and contextual ranking pipeline must be testable headlessly without requiring a Wayland compositor, X11 server, or GPU. **This is now Milestone 1 — built immediately after the Milestone 0 bugfix and before any scoring/lexicon tuning — so every later milestone is validated against real measurements on this hardware instead of the target numbers below being trusted blind.**

### Architecture of the Test Suite

```
tests/
├── test_geometry_manager.py     (Existing Qt geometry tests)
├── test_keyboard_window.py      (Existing UI lifecycle tests)
├── test_swipe_e2e.py            (Existing basic socket tests — extend, don't duplicate)
├── test_context_token_buffer.py (NEW: Unit tests for RollingTokenContext)
├── test_multisyllable_eval.py   (NEW: Headless synthetic trajectory benchmark)
└── test_bigram_scoring.py       (NEW: Disambiguation & context ranking tests)
```

`aurora_keyboard/swipe/selftest.py` already establishes the pattern this extends: no pytest dependency required to run, synthetic jittered paths, pass/fail against a fixed word list. The new multisyllable/bigram tests follow the same shape at a larger scale.

### Synthetic Kinematic Trajectory Generator
To test 4–5 syllable words reliably, a mathematical gesture synthesizer creates realistic resampled $(x, y, t)$ trajectories:

```python
def synthesize_swipe(word: str, key_positions: dict, jitter: float = 0.12, t_step_ms: int = 25) -> list[tuple[float, float, int]]:
    """Synthesizes a continuous, kinematically smooth swipe trail with natural corner-rounding."""
    # 1. Map key centers for word characters
    # 2. Apply Catmull-Rom or cubic spline interpolation between key centers
    # 3. Inject Gaussian coordinate noise and variable timing
    # 4. Return formatted (x, y, t) tuples
```

### Benchmark Metric Gates (CI/CD Quality Gates)

**Methodology change from v1.0.0**: rather than asserting these numbers as pre-known facts, Milestone 1 runs the harness against the *current* system (post-Milestone-0 bugfix, pre-tuning) to establish a real baseline. The table below is the **target direction**; the actual pass/fail gates committed to CI are whatever Milestone 1 measures plus "no regression," tightened only as later milestones prove they can hit tighter numbers without violating Zero UI Regression (§1) or daemon stability (§9).

| Metric | Target Direction | Description |
| :--- | :--- | :--- |
| **4–5 Syllable Accuracy (Exact Path)** | as high as achievable, aim $\ge 95\%$ | Top-1 candidate matches target word on ideal path. |
| **4–5 Syllable Accuracy (Jittered Path)** | aim $\ge 85\%$ | Target word appears in Top-3 on noisy/curved path. |
| **Context Disambiguation Rate** | aim $\ge 90\%$ | Given preceding context (e.g. *"sustainable"*), target multi-syllable (*"agriculture"*) beats unigram distractor (*"age"*). |
| **P95 Inference Latency** | $\le 4.0\text{ ms}$ pure-Python decode loop | Time spent in `futo_daemon.py`/`lexicon.py` decode path, excluding neural encoder inference itself. |
| **Memory Footprint** | $\le 60\text{ MB}$ daemon RSS | Total daemon memory including ExecuTorch + lexicon + bigram table. |

### Measured Baseline (Milestone 1, 2026-08-11)

Produced by `tests/test_multisyllable_eval.py` against 31 named multisyllable words (`aurora_keyboard/swipe/trajectory.py`'s `synthesize_swipe()` — centripetal Catmull-Rom trails, not the earlier straight-line M0 spot-check), on this hardware, live daemon, post-Milestone-0:

| Metric | Geometric fallback | FUTO neural daemon |
| :--- | :--- | :--- |
| Words evaluable | 6/31 (25 absent from `wordlist.txt` — a coverage gap, not a decode failure; see Milestone 2) | 31/31 |
| Exact-path Top-1 | 100% (n=6) | **35.5%** (n=31) |
| Jittered-path Top-3 | 100% (n=6) | **45.2%** (n=31) |
| Latency (client round trip) | n/a (in-process) | p95 = 319.8ms, mean = 241.5ms — a superset of the narrower "pure decode loop" target above; encoder-only vs. scorer-only isn't separately instrumented yet |

**This baseline is far below the ≥95%/≥85% target direction.** Two distinct causes, not one:
1. **Vocabulary coverage** (geometric path): 25/31 words aren't in the fallback's 1,200-word list at all — expected, this is exactly what Milestone 2's shared `lexicon.py` exists to fix, not a regression.
2. **Scoring/matching quality** (neural path): even with the full 32,768-word pool searchable (post-M0) and every word technically reachable, only ~35% resolve to Top-1 on an *ideal* synthetic path. This confirms the `infrastructure`-still-misses finding from Milestone 0 (§2) was not a one-off — the unigram-heavy scoring formula (§2 root cause #1, §6) is a real, separate problem from vocabulary coverage. Milestone 3's bigram/length-prior calibration is the fix; there is no scoring/tuning work landed yet, so this number is expected to be low right now.

**Regression found and fixed by this harness**: running the existing suite alongside the new one surfaced a live failure in `test_swipe_e2e.py::test_futo_daemon_live_if_active`. Root cause: `FutoSwipeClient`'s default timeout (0.15s, used by the live app's `SwipeManager`) was tuned against the old 15,000-word pool's speed. Milestone 0's fix made the daemon search the larger 32,768-word pool, pushing real decode latency to ~240ms mean / ~320ms p95 — past the old default timeout, meaning **swipes on the live keyboard were silently falling back to the 1,200-word geometric decoder more often than before Milestone 0**, undoing part of the intended benefit. Confirmed directly (same trail returns `[]` at 150ms timeout, real candidates at 3s). Fixed as a stopgap: `futo_client.py`'s default `timeout` raised from 0.15s to 0.5s. The real fix is the letter-bucket index (§5.3, Milestone 2), which is meant to make the scan fast at this vocab size instead of just waiting longer for it.

---

## 8. (reserved)

*Section intentionally left as a placeholder — v1.0.0's §8 (milestones) has moved to §10 below to sit after the new §9 safety section, since the workflow guarantees in §9 apply to how every milestone gets executed.*

---

## 9. Zero-Disruption Development & Sandbox/Agentic Workflow (new in v1.1.0)

This section exists because Aurora is the user's **only working input method** on this tablet. Every rule below exists to make that fact structurally hard to violate, not just something to remember.

1. **Container-isolated daemon work stays container-isolated.** All lexicon, bucket-index, and bigram scoring changes to `futo_daemon.py` are developed and tested inside the `ydotool-box` distrobox container, driven over the existing `/tmp/futo_swipe.sock` JSON protocol. A daemon crash during this work is a killed container process — it cannot take down `AuroraKeyboardWindow`, which is exactly the isolation the existing dual-backend architecture already provides (§3). This is a guarantee to preserve, not something new to build.
2. **New logic is headlessly unit-tested before it is wired into the live UI file.** `RollingTokenContext` (§4) and `lexicon.py` (§5.2) are plain Python classes with no Qt/Wayland dependency — they get `tests/test_context_token_buffer.py`-style coverage and pass standalone *before* either is imported into `keyboard_window.py`.
3. **Changes to `keyboard_window.py`/`key_engine.py` are minimized and checked before every restart.** Per the confirmed hook points in §4, wiring `RollingTokenContext` in requires exactly two call-site insertions, not a restructure. Any edit to these two files gets a syntax check (`python3 -m py_compile`) and, where the change is import-only or call-site-only, a `python3 -c "import aurora_keyboard.keyboard_window"` smoke check before the app is restarted for the user to try.
4. **No live input simulation for verification.** `ydotool key`/`click` or equivalent are not used to test changes on the real desktop session. Verification uses the Milestone 1 synthetic trajectory harness, direct method calls against the swipe modules, and log/socket inspection — the same approach already validated as effective and non-disruptive on this project.
5. **Each milestone lands as its own small, revertable commit**, verified headlessly first, before the next milestone starts. If a milestone requires a live-app restart to confirm (e.g., the two `keyboard_window.py` call sites in Milestone 3), that restart happens as a single isolated step with a clear rollback (`git revert`) available, not bundled with unrelated changes.
6. **Visual/on-screen confirmation is handed back to the user once they're at the machine** — screenshots and tool-based checks are used for what can't otherwise be verified (log files, decode output, process state), not for "does this look right," which the user can just look at.

---

## 10. Milestone Implementation Plan

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ MILESTONE 0: Fix Lexicon Truncation Bug — DONE 2026-08-10                   │
│ • futo_daemon.py:158 — removed the [:15000] cap, now searches the full      │
│   32,768-word downloaded vocab.                                             │
│ • Restarted daemon in ydotool-box (container-isolated, live keyboard never  │
│   touched), spot-checked against controls + spec examples + words beyond    │
│   the old cutoff. See §2 root cause #3 for the full before/after data.      │
│ • Result: fixes real MISSes for longer/rarer words (e.g. longstanding,      │
│   navigational, originality, probabilities), zero regressions. Does NOT     │
│   fix `infrastructure` specifically (separate scoring issue, not vocab      │
│   coverage — deferred to Milestone 3). Existing test suite                  │
│   (selftest.py, test_swipe_e2e.py) still passes clean.                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 1: Headless Synthetic Trajectory Harness — DONE 2026-08-11        │
│ • Built aurora_keyboard/swipe/trajectory.py (synthesize_swipe(), Catmull-   │
│   Rom smooth trails) + tests/test_multisyllable_eval.py (31-word suite,     │
│   no pytest dependency, matches selftest.py's pattern).                     │
│ • Measured real baseline: geometric 100%/100% but only 6/31 words in        │
│   vocab (coverage gap → Milestone 2); FUTO neural 35.5% exact-top1 /        │
│   45.2% jittered-top3 (scoring gap → Milestone 3). See §7 for full table.   │
│ • Caught and fixed a live regression from Milestone 0: the larger           │
│   32,768-word pool made real decode latency (~240ms mean) exceed the live   │
│   app's default 150ms client timeout, silently increasing fallback-to-      │
│   geometric frequency. Stopgap fix: futo_client.py default timeout          │
│   0.15s → 0.5s. Real fix is Milestone 2's letter-bucket index.              │
│ • Existing suite (selftest.py, test_swipe_e2e.py) verified clean after.     │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 2: Shared Lexicon Module + Letter-Bucket Indexer                  │
│ • New aurora_keyboard/swipe/lexicon.py (§5.2), used by BOTH futo_daemon.py  │
│   and decoder.py — the fallback path stops being stuck at 1,200 words.      │
│ • Implements §5.2's Data Integrity rules: validate/sanitize every source    │
│   on load (incl. custom_words.txt, the least-trusted input), deliberate    │
│   dedup (first occurrence wins), atomic reload (build off to the side,     │
│   swap one reference) so a hot-reload can't race an in-flight decode.       │
│ • Only curate words beyond the existing 32,768 if Milestone 1's numbers     │
│   show it's still needed after Milestone 0 (§5.1).                          │
│ • Re-run Milestone 1 harness, compare against baseline.                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 3: Bigram Scoring + Rolling Token Context + Dynamic User Lexicon  │
│ • Source and prune an offline bigram frequency table (§6) into lexicon.py.  │
│ • Add RollingTokenContext to keyboard_window.py at the two confirmed hook   │
│   points (§4) — candidate_bar.set_candidates() and handle_key_click().      │
│ • Hook custom_words.txt hot-reloading through lexicon.py.                   │
│ • Add test_bigram_scoring.py + test_context_token_buffer.py.                │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 4: Reliability & CI/CD                                            │
│ • User-level systemd unit for futo_daemon.py: auto-start, Restart=on-failure│
│   — closes the "daemon silently never started/crashed" gap found in §5.1.   │
│ • GitHub Actions workflow running the headless suite (geometric-decoder     │
│   path only — no container/GPU needed), for the "traction" audience.        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Verification & Review Checklist

- [ ] Does this specification satisfy all requirements without touching UI styling or layouts?
- [ ] Are the 4–5 syllable vocabulary requirements thoroughly addressed?
- [ ] Is the Wayland stateless context tracking clear and robust against edge cases?
- [ ] Can AI agents and CI systems execute the test harness 100% headlessly?
- [ ] Does every numeric claim in this document say whether it's measured (with a source) or a target (not yet verified)? *(new in v1.1.0)*
- [ ] Does every vocabulary/scoring improvement reach the geometric fallback, not just the neural daemon path? *(new in v1.1.0 — see §5.2)*
- [ ] Can each milestone be verified without live input simulation and without disrupting the tablet's only working input method? *(new in v1.1.0 — see §9)*
- [ ] Does every vocabulary source (downloaded, bundled, user-edited) get validated on load, and does hot-reload swap atomically instead of mutating a pool an in-flight decode might be reading? *(added 2026-08-11 — see §5.2 Data Integrity)*
