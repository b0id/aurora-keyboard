"""
Headless unit tests for aurora_keyboard/swipe/lexicon.py (VOCAB_CONTEXT_SPEC.md
Milestone 2). No Qt/Wayland dependency, no daemon/container required - pure
unittest, run directly:

    python3 -m unittest tests.test_lexicon
"""

import unittest

from aurora_keyboard.swipe import lexicon
from aurora_keyboard.swipe.decoder import standard_qwerty_key_positions


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.key_positions = standard_qwerty_key_positions()

    def test_rejects_non_layout_characters(self):
        lines = ["hello", "i'll", "café", "", "   ", "world's", "42", "OK\n"]
        out = lexicon._sanitize_lines(lines, self.key_positions)
        self.assertEqual(out, ["hello", "ok"])

    def test_lowercases(self):
        out = lexicon._sanitize_lines(["Hello", "WORLD"], self.key_positions)
        self.assertEqual(out, ["hello", "world"])

    def test_empty_and_whitespace_dropped(self):
        out = lexicon._sanitize_lines(["", "  ", "\n", "ok"], self.key_positions)
        self.assertEqual(out, ["ok"])


class TestBuildVocabulary(unittest.TestCase):
    def test_contains_bundled_words(self):
        key_positions = standard_qwerty_key_positions()
        vocab = lexicon.build_vocabulary(key_positions)
        self.assertIn("swipe", vocab)
        self.assertIn("the", vocab)

    def test_no_duplicates(self):
        key_positions = standard_qwerty_key_positions()
        vocab = lexicon.build_vocabulary(key_positions)
        self.assertEqual(len(vocab), len(set(vocab)))

    def test_first_occurrence_wins_order(self):
        # "the" appears in both the bundled wordlist and (if present) the
        # FUTO vocab; whichever source is authoritative for ordering, it
        # must not appear twice.
        key_positions = standard_qwerty_key_positions()
        vocab = lexicon.build_vocabulary(key_positions)
        self.assertEqual(vocab.count("the"), 1)


class TestLetterBucketIndex(unittest.TestCase):
    def setUp(self):
        self.vocab = ["apple", "avocado", "banana", "cherry", "date", "elderberry"]
        self.index = lexicon.LetterBucketIndex(self.vocab)

    def test_start_match(self):
        result = self.index.candidates({"a"}, set())
        self.assertEqual(set(result), {"apple", "avocado"})

    def test_end_match(self):
        result = self.index.candidates(set(), {"y"})
        self.assertEqual(set(result), {"cherry", "elderberry"})

    def test_union_no_duplicates(self):
        # "apple" ends in 'e' and starts with 'a' - asking for both must
        # not return it twice.
        result = self.index.candidates({"a"}, {"e"})
        self.assertEqual(result.count("apple"), 1)

    def test_no_match_returns_empty(self):
        result = self.index.candidates({"z"}, {"z"})
        self.assertEqual(result, [])

    def test_matches_full_scan_on_real_vocabulary(self):
        # The index must return exactly the same candidate set as a naive
        # linear scan (the thing it's replacing for speed) - this is the
        # accuracy-preserving invariant, not just a speed check.
        key_positions = standard_qwerty_key_positions()
        vocab = lexicon.build_vocabulary(key_positions)
        index = lexicon.LetterBucketIndex(vocab)

        start_chars, end_chars = {"s"}, {"g"}
        expected = {w for w in vocab if w[0] in start_chars or w[-1] in end_chars}
        actual = set(index.candidates(start_chars, end_chars))
        self.assertEqual(actual, expected)


class TestReloadAtomicity(unittest.TestCase):
    def test_get_lexicon_returns_same_instance_until_reload(self):
        key_positions = standard_qwerty_key_positions()
        lexicon._lexicon_ref = None
        first = lexicon.get_lexicon(key_positions)
        second = lexicon.get_lexicon(key_positions)
        self.assertIs(first, second)

        third = lexicon.reload_lexicon(key_positions)
        self.assertIsNot(first, third)
        self.assertIs(lexicon.get_lexicon(key_positions), third)

    def test_in_flight_reference_unaffected_by_reload(self):
        # A caller holding an old Lexicon snapshot keeps seeing consistent
        # data even after reload_lexicon() swaps the module-level ref.
        key_positions = standard_qwerty_key_positions()
        lexicon._lexicon_ref = None
        held = lexicon.get_lexicon(key_positions)
        held_vocab_len = len(held.vocabulary)

        lexicon.reload_lexicon(key_positions)

        self.assertEqual(len(held.vocabulary), held_vocab_len)


if __name__ == "__main__":
    unittest.main()
