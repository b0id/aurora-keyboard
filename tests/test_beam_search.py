"""
Headless unit tests for aurora_keyboard/swipe/beam_search.py
(VOCAB_CONTEXT_SPEC.md Milestone 3a). No Qt/Wayland/ExecuTorch dependency -
uses hand-built log-probability arrays instead of a real encoder, so this
tests the beam search algorithm itself in isolation. Run directly:

    python3 -m unittest tests.test_beam_search
"""

import unittest

from aurora_keyboard.swipe.beam_search import ScoringParams, decode
from aurora_keyboard.swipe.trie import Trie

NEG = -100.0  # "effectively zero probability" for a peaked synthetic distribution


def _peaked_step(num_classes, hot_idx):
    row = [NEG] * num_classes
    row[hot_idx] = 0.0
    return row


class TestBeamSearchBasics(unittest.TestCase):
    def setUp(self):
        self.trie = Trie(letters="abc")
        self.trie.insert("ab", 200.0)
        self.trie.insert("ac", 100.0)
        self.trie.insert("b", 150.0)
        self.blank_idx = 3  # len("abc")
        self.scoring = ScoringParams(gamma=0.0, lam=0.0, beta=0.0, gamma_prune=0.0, beta_prune=0.0)

    def test_decodes_exact_spike_sequence(self):
        # a, blank, b -> "ab"
        log_probs = [
            _peaked_step(4, 0),
            _peaked_step(4, self.blank_idx),
            _peaked_step(4, 1),
        ]
        results = decode(log_probs, self.trie, self.scoring, beam_width=10, top_k=5)
        words = [w for w, _ in results]
        self.assertIn("ab", words)
        self.assertEqual(words[0], "ab")

    def test_no_word_reached_returns_empty(self):
        # A trie with only 2+ character words - one timestep can't land on
        # an is_word node yet, regardless of which branch the beam explores.
        trie = Trie(letters="abc")
        trie.insert("ab", 100.0)
        trie.insert("ac", 100.0)
        log_probs = [_peaked_step(4, 0)]
        results = decode(log_probs, trie, self.scoring, beam_width=10, top_k=5)
        self.assertEqual(results, [])

    def test_repeat_character_without_blank(self):
        trie = Trie(letters="ab")
        trie.insert("aa", 100.0)
        blank_idx = 2
        scoring = ScoringParams(gamma=0.0, lam=0.0, beta=0.0, gamma_prune=0.0, beta_prune=0.0)
        # 'a' spiked twice in a row, no blank between - only reachable via the
        # "repeat same character" transition, not "emit new character" (there's
        # no second edge out of the 'a' node back to itself in a trie).
        log_probs = [_peaked_step(3, 0), _peaked_step(3, 0)]
        results = decode(log_probs, trie, scoring, beam_width=10, top_k=5)
        words = [w for w, _ in results]
        self.assertIn("aa", words)

    def test_beam_width_one_still_finds_the_only_viable_path(self):
        log_probs = [
            _peaked_step(4, 0),
            _peaked_step(4, self.blank_idx),
            _peaked_step(4, 1),
        ]
        results = decode(log_probs, self.trie, self.scoring, beam_width=1, top_k=5)
        self.assertEqual([w for w, _ in results], ["ab"])

    def test_top_k_truncates(self):
        log_probs = [_peaked_step(4, 0), _peaked_step(4, 1)]
        results = decode(log_probs, self.trie, self.scoring, beam_width=10, top_k=1)
        self.assertLessEqual(len(results), 1)

    def test_no_duplicate_words_in_results(self):
        log_probs = [
            _peaked_step(4, 0),
            _peaked_step(4, self.blank_idx),
            _peaked_step(4, 1),
        ]
        results = decode(log_probs, self.trie, self.scoring, beam_width=50, top_k=10)
        words = [w for w, _ in results]
        self.assertEqual(len(words), len(set(words)))


class TestScoringEffects(unittest.TestCase):
    def test_higher_frequency_word_ranks_above_lower_frequency_on_tied_path(self):
        # Two single-letter words reachable by the same one-step path (blank
        # doesn't discriminate between them) - only frequency should differ
        # if the CTC path score up to a fork is identical isn't representable
        # for two different letters, so instead test via direct score
        # comparison using decode()'s output ordering on a real fork.
        trie = Trie(letters="ab")
        trie.insert("a", 255.0)
        trie.insert("b", 1.0)
        scoring = ScoringParams(gamma=0.0, lam=1.0, beta=0.0, gamma_prune=0.0, beta_prune=0.0)
        # Equal probability on 'a' and 'b' at the one timestep - CTC path
        # score ties, so ranking must come entirely from frequency.
        log_probs = [[0.0, 0.0, NEG]]
        results = decode(log_probs, trie, scoring, beam_width=10, top_k=5)
        words = [w for w, _ in results]
        self.assertEqual(words[0], "a")

    def test_length_bonus_can_favor_longer_word(self):
        trie = Trie(letters="ab")
        trie.insert("a", 1.0)
        trie.insert("ab", 1.0)
        blank_idx = 2
        log_probs = [_peaked_step(3, 0), _peaked_step(3, 1)]

        no_bonus = ScoringParams(gamma=0.0, lam=0.0, beta=0.0, gamma_prune=0.0, beta_prune=0.0)
        results_no_bonus = decode(log_probs, trie, no_bonus, beam_width=10, top_k=5)

        with_bonus = ScoringParams(gamma=0.0, lam=0.0, beta=50.0, gamma_prune=0.0, beta_prune=0.0)
        results_with_bonus = decode(log_probs, trie, with_bonus, beam_width=10, top_k=5)

        # With a large enough length bonus, "ab" should outrank "a" even
        # though "a" alone is also a fully-supported path.
        self.assertEqual(results_with_bonus[0][0], "ab")
        self.assertIn("a", [w for w, _ in results_no_bonus])


if __name__ == "__main__":
    unittest.main()
