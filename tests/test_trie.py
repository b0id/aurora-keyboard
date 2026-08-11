"""
Headless unit tests for aurora_keyboard/swipe/trie.py (VOCAB_CONTEXT_SPEC.md
Milestone 3a). No Qt/Wayland/ExecuTorch dependency - run directly:

    python3 -m unittest tests.test_trie
"""

import unittest

from aurora_keyboard.swipe.trie import Trie, build_trie, zipf_log_frequency


class TestTrieInsertLookup(unittest.TestCase):
    def test_insert_and_contains(self):
        trie = Trie()
        trie.insert("cat", 100.0)
        self.assertTrue(trie.contains("cat"))
        self.assertFalse(trie.contains("ca"))
        self.assertFalse(trie.contains("cats"))

    def test_prefix_is_not_a_word_unless_inserted(self):
        trie = Trie()
        trie.insert("cats", 100.0)
        self.assertFalse(trie.contains("cat"))
        self.assertTrue(trie.contains("cats"))

    def test_both_prefix_and_extension_can_be_words(self):
        trie = Trie()
        trie.insert("cat", 100.0)
        trie.insert("cats", 90.0)
        self.assertTrue(trie.contains("cat"))
        self.assertTrue(trie.contains("cats"))

    def test_rejects_characters_outside_alphabet(self):
        trie = Trie(letters="abc")
        inserted = trie.insert("cad", 100.0)
        self.assertFalse(inserted)
        self.assertFalse(trie.contains("cad"))

    def test_word_count(self):
        trie = Trie()
        trie.insert("a", 1.0)
        trie.insert("ab", 1.0)
        trie.insert("a", 2.0)  # duplicate insert, same word - count shouldn't double
        self.assertEqual(trie.word_count, 2)

    def test_node_stores_word_and_frequency(self):
        trie = Trie()
        trie.insert("dog", 42.0)
        node = trie.root
        for ch in "dog":
            node = node.children[trie.char_to_idx[ch]]
        self.assertTrue(node.is_word)
        self.assertEqual(node.word, "dog")
        self.assertEqual(node.log_frequency, 42.0)
        self.assertEqual(node.depth, 3)

    def test_repeated_insert_keeps_max_frequency(self):
        trie = Trie()
        trie.insert("dog", 10.0)
        trie.insert("dog", 50.0)
        trie.insert("dog", 20.0)
        node = trie.root
        for ch in "dog":
            node = node.children[trie.char_to_idx[ch]]
        self.assertEqual(node.log_frequency, 50.0)


class TestZipfLogFrequency(unittest.TestCase):
    def test_rank_zero_is_max(self):
        self.assertAlmostEqual(zipf_log_frequency(0, 1000), 255.0, places=3)

    def test_monotonically_decreasing_with_rank(self):
        freqs = [zipf_log_frequency(r, 10000) for r in (0, 10, 100, 1000, 9999)]
        self.assertEqual(freqs, sorted(freqs, reverse=True))

    def test_never_below_floor(self):
        self.assertGreaterEqual(zipf_log_frequency(999999, 1000), 1.0)


class TestBuildTrie(unittest.TestCase):
    def test_builds_from_vocab_and_ranks(self):
        vocab = ["the", "of", "and", "infrastructure"]
        ranks = {w: i for i, w in enumerate(vocab)}
        trie = build_trie(vocab, ranks)
        for word in vocab:
            self.assertTrue(trie.contains(word))
        self.assertEqual(trie.word_count, len(vocab))

    def test_higher_rank_word_gets_lower_frequency(self):
        vocab = ["the", "infrastructure"]
        ranks = {"the": 0, "infrastructure": 5000}
        trie = build_trie(vocab, ranks)

        def freq_of(word):
            node = trie.root
            for ch in word:
                node = node.children[trie.char_to_idx[ch]]
            return node.log_frequency

        self.assertGreater(freq_of("the"), freq_of("infrastructure"))


if __name__ == "__main__":
    unittest.main()
