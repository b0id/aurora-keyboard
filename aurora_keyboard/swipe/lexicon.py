"""
Shared vocabulary + letter-bucket index (VOCAB_CONTEXT_SPEC.md sec5.2/sec5.3).

Single source of truth for both futo_daemon.py's neural scorer (runs in the
ydotool-box container) and decoder.py's geometric fallback (runs in-process,
no container, no network) - so vocabulary growth reaches both backends
instead of only the one a user happened to install the container for. No
Qt/Wayland dependency: plain data structures, importable and testable on
either side of the container boundary.

Word validity only depends on whether every character is a normal a-z
letter, not on any particular keyboard's live pixel geometry (every QWERTY
layout has all 26 letters). So callers validate against a canonical
reference layout (standard_qwerty_key_positions()), not whatever real
on-screen coordinates a given swipe used.
"""

from __future__ import annotations

import glob
import os
import threading
from pathlib import Path

try:
    from .wordlist import load_wordlist
except ImportError:
    # futo_daemon.py runs as a direct script (no package context) inside
    # the container, and imports this module the same way - fall back to
    # a plain top-level import, which works because Python auto-adds the
    # running script's own directory (this file's directory too) to
    # sys.path.
    from wordlist import load_wordlist

KeyPositions = dict[str, tuple[float, float]]

CUSTOM_WORDS_PATH = Path(os.path.expanduser("~/.config/aurora-keyboard/custom_words.txt"))

# huggingface_hub's cache layout. distrobox shares the host's $HOME with the
# ydotool-box container by default, so if the FUTO daemon has ever run and
# downloaded its vocab, this file is reachable from plain host Python too -
# no torch/executorch/huggingface_hub import needed here, just a text read.
_FUTO_VOCAB_GLOB = os.path.expanduser(
    "~/.cache/huggingface/hub/models--futo-org--futo-swipe/snapshots/*/hungry_jellyfish/vocab.txt"
)

# Missing bundled words are inserted at this rank when a real frequency-
# ordered vocab (FUTO's) is available, matching futo_daemon.py's existing
# behavior before this module existed (words_set.insert(500, bw)) - not a
# new choice, just relocated so both backends share it.
_BUNDLED_INSERT_RANK = 500


def _valid_word(word: str, key_positions: KeyPositions) -> bool:
    return bool(word) and all(ch in key_positions for ch in word)


def _sanitize_lines(lines: list[str], key_positions: KeyPositions) -> list[str]:
    """Validate/sanitize raw lines from any source (downloaded vocab,
    bundled wordlist, or user-edited custom_words.txt) before they can
    enter the shared pool. custom_words.txt is user-edited, so it's the
    least trustworthy input here and gets no exception from this.

    Deduplicates within the source itself (first occurrence wins) - the
    downloaded FUTO vocab alone has 676 case-variant duplicates once
    lowercased (e.g. "More"/"more"), a pre-existing data quality issue in
    the upstream file that a naive dedupe-only-across-sources check would
    have missed entirely.
    """
    seen = set()
    out = []
    for raw in lines:
        w = raw.strip().lower()
        if _valid_word(w, key_positions) and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _load_futo_vocab(key_positions: KeyPositions) -> list[str]:
    matches = sorted(glob.glob(_FUTO_VOCAB_GLOB))
    if not matches:
        return []
    try:
        with open(matches[-1], "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    return _sanitize_lines(lines, key_positions)


def _load_custom_words(key_positions: KeyPositions) -> list[str]:
    if not CUSTOM_WORDS_PATH.exists():
        return []
    try:
        with open(CUSTOM_WORDS_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    return _sanitize_lines(lines, key_positions)


def build_vocabulary(key_positions: KeyPositions) -> list[str]:
    """Ordered, deduplicated vocabulary merging all three sources.
    First occurrence wins (deliberate dedup, not incidental) - later
    duplicate sources never silently shadow an earlier, more-trusted one.

    Ordering: if the downloaded FUTO vocab is present, it's the base
    (it's the actual frequency-ordered source) and any bundled word it's
    missing gets inserted at a fixed modest rank rather than reordering
    everything. If it's absent (no container ever run - the "portable to
    a first-time GitHub user" case), the bundled wordlist is the entire
    vocabulary. Custom words are appended last; their boost comes from
    UserBoost in the scoring formula (sec6), not from rank position.
    """
    bundled = _sanitize_lines(load_wordlist(), key_positions)
    futo = _load_futo_vocab(key_positions)
    custom = _load_custom_words(key_positions)

    if futo:
        merged = list(futo)
        seen = set(merged)
        insert_at = min(_BUNDLED_INSERT_RANK, len(merged))
        for w in bundled:
            if w not in seen:
                merged.insert(insert_at, w)
                seen.add(w)
    else:
        merged = list(dict.fromkeys(bundled))
        seen = set(merged)

    for w in custom:
        if w not in seen:
            merged.append(w)
            seen.add(w)

    return merged


class LetterBucketIndex:
    """Inverted index by first/last letter (VOCAB_CONTEXT_SPEC.md sec5.3).
    Lets a caller find "words starting or ending with any of these
    letters" in O(bucket size) instead of scanning the whole vocabulary -
    the exact fix for the linear `for word in pool` scan in
    futo_daemon.py's decode_swipe that Milestone 1 found was blowing past
    the live app's client timeout at 32,768-word scale."""

    def __init__(self, vocabulary: list[str]):
        self._by_start: dict[str, list[str]] = {}
        self._by_end: dict[str, list[str]] = {}
        for word in vocabulary:
            if not word:
                continue
            self._by_start.setdefault(word[0], []).append(word)
            self._by_end.setdefault(word[-1], []).append(word)

    def candidates(self, start_chars, end_chars) -> list[str]:
        """Union of words matching ANY start_chars as first letter OR ANY
        end_chars as last letter. Mirrors the OR-gate futo_daemon.py's
        scorer already applies (word[0] == start_letter or word[0] ==
        greedy_str[0] or the equivalent on the end) - same candidate set
        as today's linear scan, just found fast."""
        seen = set()
        out = []
        for c in start_chars:
            for w in self._by_start.get(c, ()):
                if w not in seen:
                    seen.add(w)
                    out.append(w)
        for c in end_chars:
            for w in self._by_end.get(c, ()):
                if w not in seen:
                    seen.add(w)
                    out.append(w)
        return out


class Lexicon:
    """One immutable snapshot: a merged vocabulary, its frequency ranks,
    and its letter-bucket index. Built once, read many times."""

    def __init__(self, key_positions: KeyPositions):
        self.vocabulary = build_vocabulary(key_positions)
        self.ranks = {w: i for i, w in enumerate(self.vocabulary)}
        self.index = LetterBucketIndex(self.vocabulary)


_lexicon_ref: Lexicon | None = None
_reload_lock = threading.Lock()


def get_lexicon(key_positions: KeyPositions) -> Lexicon:
    """The current shared Lexicon, built on first call. A single module-
    level reference assignment is atomic under CPython's GIL, so a caller
    that grabs this reference and uses it for one decode never sees a
    partially-rebuilt vocabulary, even if reload_lexicon() runs
    concurrently on another thread - it just keeps using the snapshot it
    already has until its own next call to get_lexicon()."""
    global _lexicon_ref
    if _lexicon_ref is None:
        with _reload_lock:
            if _lexicon_ref is None:
                _lexicon_ref = Lexicon(key_positions)
    return _lexicon_ref


def reload_lexicon(key_positions: KeyPositions) -> Lexicon:
    """Build a brand new Lexicon fully off to the side, then atomically
    swap it in. Never mutates the live vocabulary/ranks/index in place -
    a decode already in flight keeps the snapshot it captured."""
    global _lexicon_ref
    new_lexicon = Lexicon(key_positions)
    with _reload_lock:
        _lexicon_ref = new_lexicon
    return new_lexicon
