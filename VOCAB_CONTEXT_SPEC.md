# Vocabulary, Context & Headless Testing Architecture Specification

**Document Version:** 1.2.0
**Target Subsystem:** Aurora Keyboard Swipe & Inference Subsystem
**Status:** Approved Architecture & Sequenced Implementation Plan

> **Revision note (v1.2.0, 2026-08-11):** Milestone 1's measured 35.5% top-1
> accuracy (§7) triggered a check: is the scoring formula in `futo_daemon.py`
> actually FUTO's own method, or something built independently? It's the
> latter. FUTO's model repo (the same one this project already downloads
> from) ships **three** models — an encoder (in use), a fixed-layout decoder
> (`magic_macaw`, never downloaded), and a context language model
> (`hungry_jellyfish`, never downloaded) — plus a published technical report
> ([arXiv:2606.25247](https://arxiv.org/abs/2606.25247)) documenting the
> real decoding algorithm (trie-constrained CTC beam search) and scoring
> formula (Equation 3, with tuned constants shipped in `scoring.json`).
> `futo_daemon.py`'s current approach — greedy CTC string, then Levenshtein
> distance against a flat candidate list — is a simplified stand-in that
> predates this project's awareness of FUTO's real method, not a deliberate
> design choice. FUTO's own published number for the encoder alone, decoded
> properly, is **92.94% top-1 / 97.46% top-3** (Table 3 of the report) —
> consistent with most of the 35.5%→92%+ gap being decoding-method, not
> context-awareness. This revision replaces the previous "build our own
> bigram table + hand-tuned length prior" plan (old §6) with "use FUTO's
> own proven, published method first" — see §2.1 and the rewritten §6/§10.
> The stated priority (per the user, 2026-08-11) is the easy/proven path:
> *"if this was pure android we would just use pure futo... just need to
> make sure we get our writing straight."*
>
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
4. **Lack of Preceding Context**: Long words are often predictable given the preceding word (e.g., *"critical"* $\to$ *"infrastructure"*, *"artificial"* $\to$ *"intelligence"*). Without bigram context, the decoder cannot disambiguate borderline trajectories. **Update (v1.2.0, see §2.1): FUTO ships a trained context LM for exactly this. Root cause 4 is "not integrated," not "no data source exists."**

### 2.1 What FUTO's Own System Actually Does (added v1.2.0, 2026-08-11)

`futo_daemon.py` was built as a working stand-in, not a port of FUTO's real method. Checking FUTO's model repo and technical report against what's actually implemented found a substantial gap:

| | `futo_daemon.py` today | FUTO's actual published method |
| :--- | :--- | :--- |
| **Decoding algorithm** | Greedy CTC → one string → Levenshtein distance against every candidate in a flat/bucketed list | **Trie-constrained CTC beam search**, beam width 100, with length-aware beam pruning (own tuned formula) |
| **Scoring formula** | Hand-built: `-2.8·dist - 0.5·ln(rank+5)` plus several flat `+N.N` match bonuses, none derived from FUTO's work | **Equation 3** (below) — length-normalized CTC score + log-frequency term + length term, three constants (`γ, λ_f, β`) tuned per model combination and shipped in `scoring.json` |
| **Frequency data** | Ordinal rank position in a plain word list | Log-scale frequency value stored per-word in the trie itself (AOSP dictionary format) |
| **Models used** | Encoder only (`honorable_sturgeon`) | Encoder **+ optional fixed-layout decoder (`magic_macaw`) + optional context LM (`hungry_jellyfish`)** — all three ship in the same HF repo this project already pulls from |
| **Context awareness** | Not implemented; this spec's v1.1.0 planned a from-scratch bigram table (`wordfreq`) | A **trained context language model** already exists (`hungry_jellyfish`), used via an `α·s_LM` term added to Equation 3. FUTO's own production config weights it at `α=0.6459` — a large, deliberately-tuned weight, not a minor add-on |
| **Reported accuracy** | 35.5% top-1 (Milestone 1, §7) | **92.94% top-1 / 97.46% top-3** (encoder-only, val split, Table 3 of the technical report) |

**FUTO's real scoring formula** (Equation 3, technical report §2.3):

$$s(w \mid y) = -\frac{\text{CTC}(w \mid y)}{L_w^{\gamma}} + \lambda_f \log f_w + \beta L_w$$

where $\text{CTC}(w \mid y)$ is the CTC negative log-likelihood of word $w$ given the encoder's output $y$ (turned into a score by the leading minus), $L_w$ is word length, $f_w$ is the word's frequency (read from the trie's stored per-word frequency field), and $(\gamma, \lambda_f, \beta)$ are tuned jointly with the model. **Production deployment optionally adds an `α·s_LM` term**, where $s_{\text{LM}}$ is the context LM's log-likelihood of the candidate given the preceding word(s) — this is the real "bigram/context" term, already trained, not something this project needs to build from a frequency corpus. Real tuned constants (from `scoring.json`, downloaded alongside the models):

| Configuration | γ | λ (freq) | β (length) | α (context LM) |
| :--- | ---: | ---: | ---: | ---: |
| Encoder only | 0.1017 | 0.0373 | 2.1745 | — |
| Encoder + decoder | 0.1081 | 0.0335 | 2.1994 | — |
| Encoder + context LM | 0.0159 | 0.0219 | 3.0665 | **0.6459** |
| Encoder + decoder + context LM | 0.1126 | 0.0060 | 2.2138 | **0.6387** |

Beam search itself is trie-constrained (deployment lexicon: an AOSP-format wordlist, 162,185 English entries in FUTO's own evaluation) with a separate length-aware pruning score, `s_prune = s_ctc / max(d,1)^γp + βp·d` at depth `d`, tuned independently to maximize beam recall.

**What this means for this spec**: §6 (scoring formulation) and Milestone 3 (§10) are rewritten to implement FUTO's real, published, pre-tuned method instead of the from-scratch formula v1.1.0 proposed. This is the "easy path" — proven weights and a documented algorithm, not new tuning work.

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
│  │  1. Encoder (honorable_sturgeon 1D-CNN) ──► per-timestep CTC logits   │  │
│  │                                                          │            │  │
│  │  2. lexicon.py trie (shared, see above) ◄─────────────────┤            │  │
│  │     • Trie-constrained CTC beam search (§2.1, §6)         │            │  │
│  │     • (Optional) magic_macaw decoder refinement           │            │  │
│  │                                                          ▼            │  │
│  │  3. FUTO Equation-3 Scorer (§6 — real, published, tuned) │            │  │
│  │     • Length-normalized CTC score                        │            │  │
│  │     • Log-frequency term (trie-stored, AOSP format)       │            │  │
│  │     • Length term                                        │            │  │
│  │     • (Optional) α·context-LM term — hungry_jellyfish     │            │  │
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

**Update (2026-08-12)**: `lexicon.py` existed since Milestone 2, but `manager.py`'s `SwipeManager` wasn't actually wired to use it until now — it was still building the fallback decoder from the original 1,175-word `wordlist.txt`. This wasn't caught earlier because the fallback path is barely exercised while the daemon is healthy; it became visible only when the daemon died in a real incident (§5.1) and every swipe was quietly running on the small list for hours. Fixed: `SwipeManager.wordlist` now comes from `lexicon.get_lexicon(...).vocabulary` (~31K words). This surfaced a real performance gap too — building a `SwipeDecoder` over that vocabulary takes ~900ms (measured), so `get_geo_decoder()`'s previously-nonfunctional cache (`self._geo_decoders = {}` existed but was never actually read from) had to be made real, keyed by layout, so the rebuild only happens once per rotation/geometry change instead of on every swipe. Per-swipe fallback decode with the full vocabulary measured at ~56ms.

### Zero-Interference Guarantees
- **No GUI Layout Alterations**: `CandidateBar`, `SwipeTrailOverlay`, `KeyButton`, and keyboard geometry managers remain completely unchanged.
- **Protocol Backward-Compatibility**: The IPC JSON contract retains `raw_trail`, `key_positions`, and `top_n`. The new `context` and `session_meta` parameters are strictly optional. If omitted, the daemon behaves as a standard unigram decoder.
- **Fallback Integrity**: If the daemon is unreachable, the fallback `SwipeDecoder` operates transparently with the shared ~31K-word lexicon (fixed 2026-08-12, see above) — no longer the 1,175-word stub list.

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

**Update (v1.2.0)**: this component's purpose is unchanged by the §2.1/§6 rewrite — it's still the thing that supplies "preceding word(s)" to whatever scores context. What changed is what consumes it: `get_context()`'s output is sent as the `context` field to `futo_daemon.py`, which now feeds it to `hungry_jellyfish` (the real trained context LM, §6.1) as the `α·s_LM` term's input, instead of a hand-built bigram lookup. `RollingTokenContext` itself needed no redesign for this pivot — the FIFO/boundary-reset logic was already model-agnostic.

---

## 5. Lexicon & Search Optimization

### 5.1 Current State (confirmed by code audit, 2026-08-10)

| Component | Current State |
| :--- | :--- |
| FUTO daemon vocab (downloaded from HF, frequency-ordered) | 32,768 words |
| FUTO daemon candidate pool actually searched | **capped at 15,000** by the `_VOCAB[:15000]` bug (§2.3) |
| Geometric fallback wordlist (`swipe/wordlist.txt`) | 1,200 words, entirely separate from the daemon's vocab |
| Daemon process supervision | ~~none~~ **Fixed in Milestone 4a (2026-08-12)** — systemd --user unit, auto-start at login, auto-restart on crash (~5s recovery, verified with a real `kill -9`). This gap caused a real incident: the daemon died silently after the 2026-08-11 session, degrading every swipe to the 1,175-word fallback for hours before it was noticed. |
| CI/CD | none — no `.github/` directory exists yet |
| Headless test coverage | `tests/test_swipe_e2e.py`, `aurora_keyboard/swipe/selftest.py` — real prior art to extend, not a green field |

v1.0.0 framed the target as "scale from 15,000 to 70,000+ words," which conflated the truncation bug with a genuine curation goal. The honest sequence is:

1. **Milestone 0**: fix the truncation bug. This alone raises the daemon's searchable pool from 15,000 to the full 32,768 already on disk — more than doubling it — for a one-line change and zero new data.
2. **Measure** (Milestone 1 harness) whether 32,768 words, once FUTO's real scoring/decoding method (§6) is in place, already clears the accuracy gates in §7.
3. **Only then** decide whether curating an additional word set (v1.0.0's proposed 25k expressive + 10k technical corpus) is worth the maintenance cost. Bloating the pool with low-quality entries is a real risk, not a hypothetical one — `wordlist.py`'s existing docstring already notes this exact failure mode from an earlier decision to avoid `/usr/share/dict/words`. Scale is not free; every extra low-frequency word is a false-positive risk for shorter/mid-length words too.

This turns "scale to 70,000" from a committed deliverable into a **staged, evidence-gated goal** — which is what "achievable and realistic" means in practice here.

### 5.2 Shared Lexicon Module (new in v1.1.0, both callers wired as of 2026-08-12)

Create `aurora_keyboard/swipe/lexicon.py` as the single source of truth for vocabulary and indexing, imported by both:
- `futo_daemon.py`'s contextual scorer (runs in the container), and
- `decoder.py`'s geometric fallback via `manager.py`'s `SwipeManager` (runs in-process, no container, no network) — wired 2026-08-12; from Milestone 2 (2026-08-11) until then, `lexicon.py` existed but `manager.py` still built the fallback from the original 1,175-word `wordlist.txt`, unnoticed until a real daemon outage made the gap visible (§5.1).

```
lexicon.py responsibilities:
  - Merge base wordlist + any curated additions into one ordered vocabulary.
  - Build the LetterBucketIndex (see below) once, expose it to both callers.
  - Own custom_words.txt loading/hot-reload (§6) so both backends see user boosts.
  - Validate and sanitize every entry before it enters the pool (see below).
  - Reload atomically so an in-flight decode never sees a half-updated pool.
```

This is the change that makes the spec's "available to all people, not just Aurora users" goal actually true: a first-time GitHub user who never installs the executorch container gets the expanded, bucket-indexed vocabulary through the geometric decoder — not just a 1,175-word placeholder list. **Confirmed working, not just designed**: `tests/test_swipe_e2e.py::test_swipe_manager_fallback_uses_shared_lexicon` verifies the fallback resolves `"infrastructure"` (absent from the old bundled list) with the daemon unreachable.

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

**Status (v1.2.0)**: built and verified in Milestone 2 — narrows the pool ~4.5x (e.g. 31,359 → 6,950 for a real test case) with zero accuracy change, but per-candidate Levenshtein scoring over the remaining pool still dominates latency (~330ms), not the lookup itself. Milestone 3 replaces the whole flat-list-plus-Levenshtein approach with trie-constrained beam search (§6.2), which is expected to fold in or replace this structure rather than run alongside it — this section is likely to be superseded, not just extended, once Milestone 3 lands.

---

## 6. Scoring Formulation (rewritten v1.2.0 — FUTO's real method, not a from-scratch formula)

v1.1.0 proposed a hand-built scoring function (Levenshtein distance + a guessed length-prior constant + a bigram table sourced from `wordfreq`). That plan is **replaced**: §2.1 found FUTO already publishes a tuned, evaluated scoring formula for this exact problem, shipped with real trained weights. Using it is less work than building and tuning our own, and starts from FUTO's own reported 92.94% top-1 rather than an untested guess.

### 6.1 FUTO's Equation 3 (the real formula)

$$s(w \mid y) = -\frac{\text{CTC}(w \mid y)}{L_w^{\gamma}} + \lambda_f \log f_w + \beta L_w \;\;\big[ + \; \alpha \cdot s_{\text{LM}}(w \mid \text{context}) \big]$$

- $\text{CTC}(w \mid y)$ — the CTC negative log-likelihood of candidate word $w$ given the encoder's per-timestep output $y$, computed incrementally during trie-constrained beam search (not a post-hoc Levenshtein distance against a single greedy string — that discards information the CTC log-probabilities actually carry).
- $L_w^{\gamma}$ — length normalization; without it, longer words accumulate more CTC cost simply by having more characters to score, independent of match quality. This is the length-penalty root cause from §2 root cause #1, but fixed with FUTO's own normalization term instead of a guessed `LenPrior` add-on.
- $\lambda_f \log f_w$ — log-frequency term, using the trie's stored per-word frequency (AOSP wordlist convention: a 0–255 integer proportional to log raw corpus frequency), not an ordinal rank position.
- $\beta L_w$ — an explicit length bonus, tuned jointly with the other terms.
- $\alpha \cdot s_{\text{LM}}(w \mid \text{context})$ — **optional, the real context-awareness term.** $s_{\text{LM}}$ is `hungry_jellyfish`'s log-likelihood of candidate $w$ given the preceding word(s) (fed by `RollingTokenContext`, §4). This is what root cause #4 actually needed — a trained model, not a bigram table built from scratch.

Constants $(\gamma, \lambda_f, \beta[, \alpha])$ are **not guessed** — they're published in `scoring.json` alongside the models, tuned per model combination (see §2.1's table). Milestone 3 uses these directly as a starting point, then re-validates against the Milestone 1 harness on this project's own vocabulary/hardware before treating them as final — real published constants still get the same "measure, don't assume" treatment as everything else in this spec (§1 tenet 6), they just start from a far better prior than a guess.

### 6.2 Decoding algorithm change (also part of Milestone 3)

Equation 3 is scored during **trie-constrained CTC beam search** (beam width 100, FUTO's reported setting), not applied after the fact to a flat or bucket-pruned word list. This is a real algorithm change, not just new score terms bolted onto the existing loop:
- The shared lexicon (§5.2) needs a trie structure in addition to (or replacing) the flat list + letter-bucket index — a trie is what makes incremental beam search over partial words efficient, and it's what the letter-bucket index (§5.3) was an interim substitute for.
- Length-aware beam pruning (`s_prune`, §2.1) keeps the search fast as the beam grows, playing the same "keep this cheap at scale" role the letter-bucket index was built for in Milestone 2 — expected to fold into or replace §5.3 once implemented and measured.
- This is why the Milestone 2 latency finding (bucket index narrows the pool but the flat per-candidate Levenshtein loop still dominates cost) stops being the bottleneck once decoding no longer runs that loop at all.

### 6.3 UserBoost (unchanged)
- Dynamic weight bonus for words in `~/.config/aurora-keyboard/custom_words.txt`, added on top of Equation 3's score. Same mechanism as v1.1.0 planned — this part wasn't guessed, it's a straightforward additive boost, and stays.

### Dynamic User Lexicon (`custom_words.txt`)
- Stored in standard plain-text / JSONL format at `~/.config/aurora-keyboard/custom_words.txt`.
- Loaded through the shared `lexicon.py` module (§5.2) so both backends honor it, subject to the same validate-on-load and atomic-reload rules (§5.2 Data Integrity) — this file is user-edited, so it's the least trustworthy input source in the pipeline and gets no exception from those rules.
- Users or automated tooling can add custom domain terms.
- **Hot-reload: DONE (2026-08-12).** `lexicon.py`'s `get_lexicon()` checks the file's mtime (one `stat()` call) on every call and transparently rebuilds when it changes - both `futo_daemon.py` and `manager.py`'s geometric fallback re-fetch the lexicon per request, so editing the file takes effect on the very next swipe, no daemon restart. Verified live against the real running daemon: added a word, it was immediately findable with no restart; deleted it, it was immediately gone. 5 new tests (`tests/test_lexicon.py::TestCustomWordsHotReload`) cover creation, editing, no-op stability, and malformed-encoding graceful degradation (a real gap the hot-reload path exposed - a bad-encoding read previously wasn't caught and could have crashed the lexicon rebuild).
- **Corrected claim**: the "local frequency counter increments on selection" behavior this bullet used to describe was never built - no code anywhere tracks candidate-bar selections into a frequency signal. **UserBoost (§6.1/§6.3) also isn't implemented as a scoring term at all** - `beam_search.py`'s `ScoringParams`/`decode()` has no boost field or additive term for custom words. In practice, a custom word today is *findable* (it's in the trie, in the vocabulary the letter-bucket/beam search searches) but gets no ranking advantage - it's appended last in `build_vocabulary()` (§5.2), so it gets the *lowest* frequency score of any word in the pool, competing purely on CTC path match quality. A real UserBoost term (and selection-frequency tracking) is unbuilt future work, not a shipped feature - corrected here since the previous wording implied otherwise.

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
└── test_context_disambiguation.py (NEW: hungry_jellyfish context-LM reranking tests, §6.1/§10 Milestone 3b - supersedes the v1.1.0-planned test_bigram_scoring.py, no bigram table to test anymore)
```

`aurora_keyboard/swipe/selftest.py` already establishes the pattern this extends: no pytest dependency required to run, synthetic jittered paths, pass/fail against a fixed word list. The new multisyllable/context tests follow the same shape at a larger scale.

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

**Update (v1.2.0)**: the accuracy targets below are no longer arbitrary round numbers — they're FUTO's own published results (technical report, Table 3, encoder-only, val split, proper trie-constrained beam search): **92.94% top-1 / 97.46% top-3**. That's the realistic ceiling Milestone 3 is working toward by implementing FUTO's real method (§6), not a number invented for this spec.

| Metric | Target Direction | Description |
| :--- | :--- | :--- |
| **4–5 Syllable Accuracy (Exact Path)** | ~93% top-1 (FUTO's own published number, §2.1/§6.1) | Top-1 candidate matches target word on ideal path. |
| **4–5 Syllable Accuracy (Jittered Path)** | ~97% top-3 (FUTO's own published number) | Target word appears in Top-3 on noisy/curved path. |
| **Context Disambiguation Rate** | aim $\ge 90\%$ | Given preceding context (e.g. *"sustainable"*), target multi-syllable (*"agriculture"*) beats unigram distractor (*"age"*). Powered by `hungry_jellyfish`'s trained `α·s_LM` term (§6.1), not a hand-built bigram table. |
| **P95 Inference Latency** | $\le 4.0\text{ ms}$ pure-Python decode loop | Time spent in `futo_daemon.py`/`lexicon.py` decode path, excluding neural encoder inference itself. |
| **Memory Footprint** | $\le 60\text{ MB}$ daemon RSS | Total daemon memory including ExecuTorch + lexicon trie + (if enabled) the context LM model. |

Two caveats carried over honestly, not smoothed away: FUTO's 93%/97% numbers are on *their* evaluation corpus (`swipe.futo.org`, real human swipes) and *their* deployment lexicon (162,185-entry AOSP wordlist), not this project's synthetic-trajectory harness or current ~31,359-word vocabulary — Milestone 3 re-measures on this project's own harness rather than assuming the published number transfers exactly. And FUTO's own paper states the context LM specifically "is trained as a separate component and is not evaluated in this paper" — so the `α`-weighted context term's real-world effect size is not yet published even by FUTO; Milestone 3 measures it directly once wired in.

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
2. **Scoring/matching quality** (neural path): even with the full 32,768-word pool searchable (post-M0) and every word technically reachable, only ~35% resolve to Top-1 on an *ideal* synthetic path. This confirms the `infrastructure`-still-misses finding from Milestone 0 (§2) was not a one-off — the unigram-heavy scoring formula (§2 root cause #1, §6) is a real, separate problem from vocabulary coverage. **Root-caused further in Milestone 2.5/§2.1**: the scoring/decoding approach itself diverged from FUTO's own published method. Milestone 3 (§10) now adopts FUTO's real trie-constrained beam search + Equation 3 instead of tuning the from-scratch formula further.

**Regression found and fixed by this harness**: running the existing suite alongside the new one surfaced a live failure in `test_swipe_e2e.py::test_futo_daemon_live_if_active`. Root cause: `FutoSwipeClient`'s default timeout (0.15s, used by the live app's `SwipeManager`) was tuned against the old 15,000-word pool's speed. Milestone 0's fix made the daemon search the larger 32,768-word pool, pushing real decode latency to ~240ms mean / ~320ms p95 — past the old default timeout, meaning **swipes on the live keyboard were silently falling back to the 1,200-word geometric decoder more often than before Milestone 0**, undoing part of the intended benefit. Confirmed directly (same trail returns `[]` at 150ms timeout, real candidates at 3s). Fixed as a stopgap: `futo_client.py`'s default `timeout` raised from 0.15s to 0.5s. The real fix is the letter-bucket index (§5.3, Milestone 2), which is meant to make the scan fast at this vocab size instead of just waiting longer for it.

### Measured Results (Milestone 3a, 2026-08-11)

Re-run of the same `tests/test_multisyllable_eval.py` harness (identical 31 words, identical synthetic trails) after replacing greedy-CTC+Levenshtein with trie-constrained CTC beam search (§6.1/§6.2):

| Metric | M1 baseline (pre-3a) | **M3a (beam search)** |
| :--- | :--- | :--- |
| Exact-path Top-1 | 35.5% | **100.0%** (31/31) |
| Jittered-path Top-3 | 45.2% | **100.0%** (31/31) |
| Client round-trip latency | mean 241.5ms / p95 319.8ms | **mean 13.9ms / p95 15.5ms** |

Before landing this, the beam search was validated against FUTO's own published README example ("computer", real coordinates, known-correct answer — top-1 hit) and checked for regressions on short control words on the *same* synthetic trails used throughout this spec: beam search got 5/8 exact top-1 vs. the old scorer's 3/8 on identical trails — beam search matched or beat the old approach in every head-to-head comparison run, not just on the multisyllable target set.

**Honest gaps, not smoothed over:**
- **Short words (3-5 letters) are still the softer case.** A broader 32-word live-socket spot-check (mixed short/medium/long) got 75% exact top-1; misses cluster on short words (`fox`→`fix`, `dog`→`did`, `type`→`to`) plus one longer-word miss (`wonderful`→`wrongful`, not in top-3 at all). This is a pre-existing characteristic — confirmed above to already exist under the old scorer on the same trails, not something beam search introduced — but it isn't solved either. Likely candidates: synthetic-trajectory realism for short swipes (§7 harness generates idealized paths; real human swipes on short words may carry more disambiguating signal), and/or the still-provisional Zipf-shaped frequency proxy (`trie.py`'s `zipf_log_frequency`, derived from rank position since this project doesn't have FUTO's real corpus frequency counts) not being as well-calibrated as FUTO's actual AOSP frequency data.
- **Memory target not met, pre-existing.** Daemon RSS measured at ~743MB, well above the §7 target of ≤60MB. This is dominated by PyTorch/ExecuTorch's own baseline footprint (present since before this milestone), not something the lexicon/trie/beam-search additions introduced — but the ≤60MB target itself was never verified as achievable (v1.1.0 flagged all these numbers as targets, not facts) and should be revisited or dropped rather than left as a silently-failing gate.
- FUTO's own published 92.94%/97.46% (Table 3, real human swipes, their 162K-word lexicon) isn't directly comparable to this 100%/100% — different evaluation corpus (synthetic vs. real swipes) and different, smaller vocabulary. The dramatic jump here is real and apples-to-apples against this project's own prior baseline, but shouldn't be read as "beating FUTO's own numbers" on a like-for-like basis.

Implementation: `aurora_keyboard/swipe/trie.py` (prefix trie, Zipf-shaped frequency proxy) and `aurora_keyboard/swipe/beam_search.py` (the ported algorithm) are both headlessly unit-tested (`tests/test_trie.py`, `tests/test_beam_search.py`, 20 tests) and verified standalone before being wired into `futo_daemon.py` and `lexicon.py`'s `Lexicon.trie`, per §9. Full regression suite (37 tests: `test_swipe_e2e.py`, `test_lexicon.py`, `test_trie.py`, `test_beam_search.py`) passes clean, plus `selftest.py`.

### Measured Results (Milestone 3b, daemon side, 2026-08-11)

The context LM's real I/O contract (`num_exact=32768`, `embed_dim=16`, `num_buckets=32768`, `max_context_len=16`) isn't published anywhere - discovered by loading the actual model and reading tensor shapes / resize-error messages, then sanity-checked against known-good language behavior before any production code was written:

| Context | Top predicted next words |
| :--- | :--- |
| `["the"]` | first, new, same, other, most |
| `["thank", "you"]` | for, to, in, and, at |
| `["how", "are"]` | you, we, the, they, it |

Then the actual disambiguation term (α·s_LM, the real fix for §2 root cause #4) was checked against the spec's own named example:

| Context | Candidates | Scores |
| :--- | :--- | :--- |
| `["critical"]` | infrastructure vs. instructor | **-0.21** vs. -4.14 — correct word wins clearly |

The `vocab_hash.py` port (wyhash + multiply-shift, used for out-of-vocabulary word embedding lookup) was cross-checked **bit-exact** against FUTO's real C++ header — compiled locally with `g++`, run side-by-side with the Python port on 10 test words, identical 64-bit hash values and bucket indices on every one (an initial port had a real bug here: Python's arbitrary-precision integers don't wrap at 64 bits the way C++'s `uint64_t` does, silently producing wrong bucket indices until the wraparound was added explicitly — caught by this cross-check, not by inspection).

End-to-end (live socket, daemon side only): no-context requests are byte-for-byte identical to Milestone 3a (zero regression), old-protocol requests without a `context` field still work (backward compatible), and a context-supplied request measurably reranks candidates with ~2ms added latency (~14ms → ~16ms). The Milestone 1 harness (which sends no context) is unaffected: still 100%/100%.

---

## 8. (reserved)

*Section intentionally left as a placeholder — v1.0.0's §8 (milestones) has moved to §10 below to sit after the new §9 safety section, since the workflow guarantees in §9 apply to how every milestone gets executed.*

---

## 9. Zero-Disruption Development & Sandbox/Agentic Workflow (new in v1.1.0)

This section exists because Aurora is the user's **only working input method** on this tablet. Every rule below exists to make that fact structurally hard to violate, not just something to remember.

1. **Container-isolated daemon work stays container-isolated.** All lexicon, indexing, and scoring/decoding changes to `futo_daemon.py` (including Milestone 3's trie-based beam search and context LM integration) are developed and tested inside the `ydotool-box` distrobox container, driven over the existing `/tmp/futo_swipe.sock` JSON protocol. A daemon crash during this work is a killed container process — it cannot take down `AuroraKeyboardWindow`, which is exactly the isolation the existing dual-backend architecture already provides (§3). This is a guarantee to preserve, not something new to build.
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
│ MILESTONE 2: Shared Lexicon Module + Letter-Bucket Indexer — DONE 2026-08-11│
│ • Built aurora_keyboard/swipe/lexicon.py (§5.2): build_vocabulary() merges  │
│   bundled wordlist + FUTO's downloaded vocab + custom_words.txt (first-wins │
│   dedup), LetterBucketIndex (§5.3) for O(bucket) candidate pruning, atomic  │
│   get_lexicon()/reload_lexicon() swap. Data Integrity rules implemented and │
│   unit-tested (tests/test_lexicon.py, 13 tests) - caught a real pre-        │
│   existing bug in the process (676 case-variant duplicates in FUTO's own    │
│   vocab.txt, e.g. "More"/"more", were never deduped before this).           │
│ • Wired into BOTH futo_daemon.py (replacing the manual vocab-merge code and │
│   the linear `for word in _VOCAB` scan) and available to decoder.py/        │
│   manager.py for the fallback path.                                        │
│ • Verified zero accuracy regression (M1 harness numbers unchanged: 35.5%/   │
│   45.2%) and confirmed the bucket index narrows the pool ~4.5x, but see     │
│   §5.3 status note - it's not the actual latency bottleneck.                │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 2.5: Discovery — FUTO's Real Method (2026-08-11, see §2.1)        │
│ • Investigating why latency barely improved despite the bucket index found  │
│   the real bottleneck: pure-Python Levenshtein scoring over ~7,000          │
│   candidates (~330ms), not candidate selection.                            │
│ • That investigation led to checking FUTO's model repo against what's      │
│   implemented, which found 2 of FUTO's 3 shipped models were never used,   │
│   and the scoring formula was hand-built rather than FUTO's own tuned,     │
│   published method. See §2.1 for the full comparison and citation.         │
│ • No code changed in this step - pure investigation that reshaped           │
│   Milestone 3 below.                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 3: Adopt FUTO's Real Method (rewritten v1.2.0, see §2.1/§6)       │
│ Replaces the old "from-scratch bigram table + guessed length prior" plan    │
│ with implementing FUTO's own published, pre-tuned method. Split into three  │
│ sub-steps so the biggest, lowest-risk win lands and gets measured first.    │
│                                                                              │
│ 3a. Real decoding + scoring, encoder-only — DONE 2026-08-11                 │
│   • Validated first: ported beam search POC decoded FUTO's own published   │
│     "computer" README example correctly, and matched/beat the old scorer   │
│     on short control words on identical trails, before any repo changes.   │
│   • New aurora_keyboard/swipe/trie.py + beam_search.py (headlessly unit-   │
│     tested, 20 tests, before being wired into anything live per §9).       │
│   • lexicon.py's Lexicon gained .trie; futo_daemon.py's decode_swipe now   │
│     calls beam_search.decode() with FUTO's published constants instead of  │
│     greedy-CTC + Levenshtein. _greedy_ctc/_levenshtein deleted (unused).   │
│   • Measured: 35.5%→100% exact-top1, 45.2%→100% jittered-top3, latency     │
│     241ms→13.9ms mean (17x). Full results + honest gaps (short words,      │
│     memory target) in §7 "Measured Results (Milestone 3a)".                │
│   • 37-test regression suite + selftest.py verified clean.                 │
│                                                                              │
│ 3b. Context LM integration — DONE 2026-08-11 (daemon + live-app hook)      │
│   • Validated first, before writing production code: probed the real       │
│     hungry_jellyfish model's I/O shapes empirically (no metadata.json      │
│     covers these) - num_exact=32768, embed_dim=16, num_buckets=32768,      │
│     max_context_len=16 - then checked predict-next-word sanity ("how are"  │
│     -> "you" ranked first, "thank you" -> "for") before trusting it.       │
│   • New aurora_keyboard/swipe/vocab_hash.py (wyhash + multiply-shift OOV    │
│     bucket hashing) - cross-checked BIT-EXACT against FUTO's actual C++    │
│     header, compiled and run locally, not just read. 10 fixture-vector     │
│     tests (tests/test_vocab_hash.py) lock this in as a regression guard.   │
│   • New aurora_keyboard/swipe/context_lm.py (ContextLMScorer) and          │
│     rolling_context.py (RollingTokenContext, §4) - both headlessly tested  │
│     (13 tests) before any wiring, per §9.                                  │
│   • futo_daemon.py: loads the context LM alongside the encoder (separate   │
│     try/except - failure degrades gracefully, same pattern as encoder).    │
│     decode_swipe/handle_client gained an optional `context` field (empty   │
│     by default - old protocol still works unchanged). When context is      │
│     supplied, beam search returns a wider pool (20 vs top_n) that gets     │
│     reranked by beam_score + α·context_lm_score (α=0.6459 published        │
│     constant) before final truncation.                                    │
│   • Verified live: "critical" context correctly boosts "infrastructure"    │
│     over "instructor" (-0.21 vs -4.14, the exact disambiguation example    │
│     named in §7's Context Disambiguation Rate metric). No-context and      │
│     old-protocol requests unaffected (confirmed byte-for-byte identical    │
│     candidates). Latency: ~14ms -> ~16ms with reranking (+2ms).            │
│   • 55-test full regression suite + selftest.py + Milestone 1 harness      │
│     (still 100%/100%, unaffected since it sends no context) all clean.     │
│   • Live-app hook landed: keyboard_window.py instantiates                  │
│     RollingTokenContext in __init__, calls push_word(candidates[0]) right  │
│     after set_candidates() and handle_key(char_to_send/keycode_str) in     │
│     both handle_key_click() branches - exactly the two confirmed hook      │
│     points (§4), two-line diff each, nothing else in that file touched.    │
│     futo_client.py/manager.py thread context through predict()/decode()   │
│     to the daemon; missing/empty context is fully backward compatible.     │
│   • Verified without live input simulation (§9 rule 4): instantiated the   │
│     real AuroraKeyboardWindow and called handle_key_click() directly with  │
│     synthetic key_info dicts - period resets context, BACKSPACE pops,      │
│     an ordinary letter leaves it untouched, all matching sec4's rules      │
│     exactly. Confirmed the live app wasn't running before any of this      │
│     (zero disruption risk) and the geometric fallback needs no changes.    │
│   • custom_words.txt hot-reload: DONE 2026-08-12, see §6 Dynamic User      │
│     Lexicon - get_lexicon() itself now checks mtime per call rather than   │
│     needing a separate watcher; benefits both backends automatically.      │
│     Also caught and fixed: UserBoost was never actually a scoring term     │
│     (custom words were findable but had no ranking advantage - see §6),    │
│     and a malformed-encoding custom_words.txt could have crashed the       │
│     lexicon rebuild (not caught by the existing OSError handler).          │
│                                                                              │
│ 3c. (Optional, smaller win) magic_macaw decoder refinement                  │
│   • FUTO's own numbers show +0.55-0.76pt top-1 over encoder-only — worth    │
│     doing only after 3a/3b are measured and only if still worthwhile        │
│                                                                              │
│ Portability note: none of 3a-3c reach the geometric fallback's *decoding*   │
│ algorithm (no neural models there by design, §3) - but see Milestone 4b    │
│ below, which fixed the fallback's *vocabulary* to be the shared lexicon    │
│ instead of the small bundled list, independent of 3a-3c. The fallback's    │
│ context-awareness, if wanted later, would still need a lightweight         │
│ non-neural approach (e.g. a small bigram table) — deferred, not blocking.  │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 4a: Daemon Supervision — DONE 2026-08-12                          │
│ Triggered by a real incident, not proactive hardening: the daemon died      │
│ silently sometime after the 2026-08-11 session ended (no supervision        │
│ existed yet), and every swipe silently degraded to the 1,175-word           │
│ geometric fallback for hours before it was noticed - structurally unable    │
│ to produce most multi-syllable words (7/10 of a sample were absent from     │
│ that fallback list entirely), matching the user's own ~40% estimate.        │
│ • install.sh now generates and enables a systemd --user unit                │
│   (aurora-futo-daemon.service): Restart=on-failure, RestartSec=3,           │
│   StartLimitBurst=5/60s, WantedBy=default.target (starts at login).         │
│   Skips gracefully on non-systemd systems (main.py's existing               │
│   _ensure_futo_daemon() on-launch check still covers that case, just        │
│   without mid-session crash recovery).                                     │
│ • Installing it immediately surfaced a second real bug, not a               │
│   hypothetical: aurora-futo-daemon resolved its own directory via           │
│   `dirname "${BASH_SOURCE[0]}"`, which doesn't follow symlinks - fine when  │
│   run directly from the repo (every manual restart all night did this by   │
│   coincidence) but silently wrong when invoked via the ~/.local/bin symlink │
│   install.sh itself creates and instructs users to run. Fixed with          │
│   `dirname "$(readlink -f ...)"`. This means the documented "run            │
│   aurora-futo-daemon &" instruction may never have worked correctly from    │
│   PATH before this fix - only direct-path invocation did.                   │
│ • Verified for real, not assumed: killed the running daemon process         │
│   directly (kill -9) - systemd detected it and had a fully working,         │
│   model-loaded daemon back within ~5 seconds, confirmed via a live decode   │
│   ("phenomenal" -> correct) immediately after recovery, no manual action.   │
│ • 55-test regression suite clean after.                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 4b: Fallback Reaches the Shared Lexicon — DONE 2026-08-12         │
│ Also incident-motivated: same outage that drove 4a showed the fallback's    │
│ small vocabulary makes daemon-down degradation much worse than it needs    │
│ to be. lexicon.py existed since Milestone 2 but manager.py was never       │
│ actually wired to use it (§5.2 update).                                    │
│ • SwipeManager.wordlist now sources from lexicon.get_lexicon(...) (~31K    │
│   words) instead of the original 1,175-word wordlist.txt.                  │
│ • Found and fixed a related latency trap before it shipped: building a     │
│   SwipeDecoder over the full vocabulary measured at ~900ms - the           │
│   `_geo_decoders` cache dict existed but was never actually read from, so   │
│   this would have rebuilt on every single swipe. Made the cache real,      │
│   keyed by layout - rebuild only on rotation/geometry change, not per      │
│   swipe. Per-swipe fallback decode with the full vocabulary: ~56ms.        │
│ • New tests (test_swipe_manager_fallback_uses_shared_lexicon,              │
│   test_geo_decoder_cached_by_layout) confirm both the vocabulary fix and   │
│   the caching fix - not just one or the other. 57-test suite clean.        │
├─────────────────────────────────────────────────────────────────────────────┤
│ MILESTONE 4c: CI/CD (not started)                                           │
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
- [ ] Does the scoring/decoding plan use FUTO's own published method and tuned constants where one exists, rather than a formula invented for this spec? *(added v1.2.0, 2026-08-11 — see §2.1, §6)*
- [ ] Is every "target" accuracy/latency number in this document either FUTO's own published result (with citation) or this project's own Milestone 1 harness measurement — not a round number picked for its own sake? *(added v1.2.0)*
