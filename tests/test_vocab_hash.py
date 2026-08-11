"""
Headless unit tests for aurora_keyboard/swipe/vocab_hash.py
(VOCAB_CONTEXT_SPEC.md Milestone 3b). No ExecuTorch dependency - run
directly:

    python3 -m unittest tests.test_vocab_hash

Fixture values below were cross-checked bit-for-bit against FUTO's actual
C++ reference (gitlab.futo.org/keyboard/swipe-library,
include/swipe_decoder/vocab_hash.hpp), compiled and run locally
(2026-08-11) - not just visually compared to the header. This matters
because a Python port that "looks right" but differs even slightly from
the reference silently hashes out-of-vocabulary words into the wrong
embedding bucket, with no error to catch it.
"""

import unittest

from aurora_keyboard.swipe.vocab_hash import compute_hash_indices, wyhash

# word -> (hash64, bucket0, bucket1) at num_buckets=32768, num_hashes=2,
# verified against a compiled run of FUTO's own vocab_hash.hpp.
KNOWN_VECTORS = {
    "": (1471106076447886454, 4969, 26474),
    "a": (1336536464068998331, 14655, 4630),
    "hi": (18254057817958058607, 6411, 20796),
    "the": (5933384505577477024, 31603, 14789),
    "swipe": (18343642538961247545, 616, 5198),
    "infrastructure": (14043887300348505345, 25636, 18836),
    "xyzzy123notaword": (15444241080444017064, 21687, 19535),
    "aurora": (8257154445338998606, 11664, 4367),
    "keyboard": (4892815952855719275, 4719, 18392),
    "z": (7561784998454347237, 47, 3509),
}


class TestAgainstReferenceVectors(unittest.TestCase):
    def test_wyhash_matches_cpp_reference(self):
        for word, (expected_hash, _, _) in KNOWN_VECTORS.items():
            with self.subTest(word=word):
                self.assertEqual(wyhash(word.encode("utf-8")), expected_hash)

    def test_bucket_indices_match_cpp_reference(self):
        for word, (_, b0, b1) in KNOWN_VECTORS.items():
            with self.subTest(word=word):
                self.assertEqual(compute_hash_indices(word, 32768, 2), [b0, b1])


class TestBucketProperties(unittest.TestCase):
    def test_buckets_within_range(self):
        for word in ("hello", "world", "aurora", "keyboard", ""):
            indices = compute_hash_indices(word, 32768, 2)
            for idx in indices:
                self.assertGreaterEqual(idx, 0)
                self.assertLess(idx, 32768)

    def test_deterministic(self):
        a = compute_hash_indices("consistent", 32768, 2)
        b = compute_hash_indices("consistent", 32768, 2)
        self.assertEqual(a, b)

    def test_different_words_usually_differ(self):
        words = ["apple", "banana", "cherry", "date", "elderberry", "fig"]
        results = {w: tuple(compute_hash_indices(w, 32768, 2)) for w in words}
        self.assertGreater(len(set(results.values())), 1)


if __name__ == "__main__":
    unittest.main()
