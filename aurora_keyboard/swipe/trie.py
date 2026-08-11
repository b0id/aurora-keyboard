"""
Prefix trie for trie-constrained CTC beam search (VOCAB_CONTEXT_SPEC.md
Milestone 3a). Python port of FUTO's own reference implementation
(gitlab.futo.org/keyboard/swipe-library, include/swipe_decoder/trie.hpp) -
same node layout and word-frequency convention, adapted to plain Python
objects instead of a flat array (this vocabulary is ~30K words, not the
scale that array-of-structs optimization exists for).

No Qt/Wayland dependency - built once per Lexicon (lexicon.py) and shared
by both the neural daemon and (in principle) the geometric fallback.
"""

from __future__ import annotations

import math

DEFAULT_LETTERS = "abcdefghijklmnopqrstuvwxyz"


class TrieNode:
    __slots__ = ("children", "is_word", "log_frequency", "depth", "word", "parent_char")

    def __init__(self, depth: int = 0, parent_char: int | None = None):
        self.children: dict[int, "TrieNode"] = {}
        self.is_word = False
        self.log_frequency = -100.0
        self.depth = depth
        self.word: str | None = None
        self.parent_char = parent_char


class Trie:
    """Vocabulary trie for constrained beam search. `letters` fixes the
    character-index mapping that beam search's log-probability arrays must
    use the same order for (see beam_search.py)."""

    def __init__(self, letters: str = DEFAULT_LETTERS):
        self.letters = letters
        self.char_to_idx = {c: i for i, c in enumerate(letters)}
        self.root = TrieNode(depth=0)
        self.word_count = 0

    def insert(self, word: str, log_frequency: float) -> bool:
        """Insert word with an AOSP-style 1-255 log-frequency value. Returns
        False (no-op) if any character isn't in this trie's alphabet."""
        node = self.root
        for ch in word:
            idx = self.char_to_idx.get(ch)
            if idx is None:
                return False
            child = node.children.get(idx)
            if child is None:
                child = TrieNode(depth=node.depth + 1, parent_char=idx)
                node.children[idx] = child
            node = child
        if not node.is_word:
            self.word_count += 1
        node.is_word = True
        node.log_frequency = max(node.log_frequency, log_frequency)
        node.word = word
        return True

    def contains(self, word: str) -> bool:
        node = self.root
        for ch in word:
            idx = self.char_to_idx.get(ch)
            if idx is None:
                return False
            node = node.children.get(idx)
            if node is None:
                return False
        return node.is_word


def zipf_log_frequency(rank: int, vocab_size: int) -> float:
    """AOSP-style 1-255 log-frequency from an ordinal frequency rank
    (rank 0 = most frequent). Zipf's law says raw frequency is
    approximately proportional to 1/rank, so log(frequency) is
    approximately proportional to -log(rank) - this maps that relationship
    onto the 1-255 range FUTO's trie format expects (itrie.h: "It should be
    1 to 255, similar to the word frequencies in the AOSP dictionaries")."""
    log_n = math.log(vocab_size + 1)
    if log_n == 0:
        return 255.0
    return max(1.0, 255.0 * (1.0 - math.log(rank + 1) / log_n))


def build_trie(vocabulary: list[str], ranks: dict[str, int], letters: str = DEFAULT_LETTERS) -> Trie:
    trie = Trie(letters)
    n = len(vocabulary)
    for word in vocabulary:
        rank = ranks.get(word, n)
        trie.insert(word, zipf_log_frequency(rank, n))
    return trie
