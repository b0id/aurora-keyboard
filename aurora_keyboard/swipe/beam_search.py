"""
Trie-constrained CTC beam search (VOCAB_CONTEXT_SPEC.md sec6.2, Milestone 3a).

Python port of FUTO's own reference implementation
(gitlab.futo.org/keyboard/swipe-library, src/beam_search.cpp) - same three
per-timestep transitions (emit blank, emit a new trie-child character,
repeat the current character without an intervening blank), same dedup-by-
trie-node rule, same length-aware beam pruning, same final Equation 3
scoring (technical report sec2.3, arXiv:2606.25247). Simplified to
single-stream decoding only - FUTO's version also supports two-finger
swipe typing (a "left"/"right" trail pair), which Aurora doesn't use.

Replaces the greedy-CTC-string + Levenshtein-distance approach in
futo_daemon.py: that approach collapses the encoder's per-timestep output
to one string before matching, discarding the graded probability
information beam search uses directly. Milestone 1's measured 35.5%
top-1 accuracy was largely this gap, not a vocabulary or tuning problem
(see VOCAB_CONTEXT_SPEC.md sec2.1).
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from .trie import Trie, TrieNode
except ImportError:
    # futo_daemon.py imports this module as a direct script (no package
    # context) - see trie.py/lexicon.py for the same fallback pattern.
    from trie import Trie, TrieNode


@dataclass
class ScoringParams:
    """Mirrors FUTO's ScoringParams (model_metadata.hpp). Defaults are the
    published encoder-only constants (scoring.json); alpha is unused until
    Milestone 3b's context LM term is wired in."""
    gamma: float = 0.1017        # length normalization exponent
    lam: float = 0.0373          # frequency bonus weight
    beta: float = 2.1745         # length bonus weight
    alpha: float = 1.0           # context LM weight (Milestone 3b, unused for now)
    gamma_prune: float = 0.4234  # length-aware beam pruning exponent
    beta_prune: float = 1.0382   # length-aware beam pruning bonus


class _Hyp:
    __slots__ = ("score", "prune_score", "node", "blank_ended")

    def __init__(self, score: float, prune_score: float, node: TrieNode, blank_ended: bool):
        self.score = score
        self.prune_score = prune_score
        self.node = node
        self.blank_ended = blank_ended


def _length_prune_score(score: float, depth: int, gamma_prune: float, beta_prune: float) -> float:
    if gamma_prune == 0.0 and beta_prune == 0.0:
        return score
    d_eff = max(depth, 1)
    return score / (d_eff ** gamma_prune) + beta_prune * depth


def decode(
    log_probs,
    trie: Trie,
    scoring: ScoringParams,
    beam_width: int = 100,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Decode CTC log-probabilities into (word, score) pairs, best first.

    log_probs: sequence of per-timestep arrays, each of length
    len(trie.letters) + 1 (the trailing slot is the CTC blank class),
    indexed in the same character order as trie.char_to_idx.
    """
    blank_idx = len(trie.letters)
    beam = [_Hyp(0.0, 0.0, trie.root, False)]

    for probs_t in log_probs:
        new_beam: dict[tuple[int, bool], _Hyp] = {}

        def offer(key, score, prune_score, node, blank_ended):
            existing = new_beam.get(key)
            if existing is None or existing.score < score:
                new_beam[key] = _Hyp(score, prune_score, node, blank_ended)

        for hyp in beam:
            node = hyp.node
            depth = node.depth

            # Emit blank: stay at the same trie node.
            blank_score = hyp.score + probs_t[blank_idx]
            blank_prune = _length_prune_score(blank_score, depth, scoring.gamma_prune, scoring.beta_prune)
            offer((id(node), True), blank_score, blank_prune, node, True)

            # Emit a new character: move to a trie child.
            for char_idx, child in node.children.items():
                char_score = hyp.score + probs_t[char_idx]
                child_depth = depth + 1
                char_prune = _length_prune_score(char_score, child_depth, scoring.gamma_prune, scoring.beta_prune)
                offer((id(child), False), char_score, char_prune, child, False)

            # Repeat the current character without an intervening blank.
            if not hyp.blank_ended and node.parent_char is not None:
                same_score = hyp.score + probs_t[node.parent_char]
                same_prune = _length_prune_score(same_score, depth, scoring.gamma_prune, scoring.beta_prune)
                offer((id(node), False), same_score, same_prune, node, False)

        candidates = list(new_beam.values())
        if len(candidates) > beam_width:
            candidates.sort(key=lambda h: -h.prune_score)
            candidates = candidates[:beam_width]
        beam = candidates
        if not beam:
            break

    results = []
    for hyp in beam:
        node = hyp.node
        if not node.is_word:
            continue
        length = max(node.depth, 1)
        freq_score = scoring.lam * node.log_frequency
        final_score = hyp.score / (length ** scoring.gamma) + scoring.beta * length + freq_score
        results.append((node.word, final_score))

    results.sort(key=lambda pair: -pair[1])
    seen = set()
    out = []
    for word, score in results:
        if word not in seen:
            seen.add(word)
            out.append((word, score))
        if len(out) >= top_k:
            break
    return out
