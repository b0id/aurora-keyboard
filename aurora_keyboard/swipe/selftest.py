"""
Standalone correctness check for the swipe decoder. No pytest dependency -
run directly:

    python3 -m aurora_keyboard.swipe.selftest

Proves the decoder resolves swipe paths to the right word before any of
this touches the live keyboard UI (see SWIPE_SPEC.md milestone M1).
"""

import random

from .decoder import SwipeDecoder, standard_qwerty_key_positions, _word_path
from .wordlist import load_wordlist


def _jitter(points, amount, rng):
    return [(x + rng.uniform(-amount, amount), y + rng.uniform(-amount, amount)) for x, y in points]


def run() -> bool:
    key_positions = standard_qwerty_key_positions()
    wordlist = load_wordlist()
    decoder = SwipeDecoder(key_positions, wordlist)
    rng = random.Random(42)

    test_words = ["hello", "the", "keyboard", "swipe", "quick", "brown", "world", "type"]
    failures = []

    for word in test_words:
        path = _word_path(word, key_positions)
        if path is None:
            failures.append(f"{word!r}: not representable on the test grid")
            continue

        # Exact ideal path should resolve to the word itself, top choice.
        results = decoder.decode(path, top_n=5)
        top_words = [w for w, _ in results]
        if not top_words or top_words[0] != word:
            failures.append(f"{word!r}: exact path -> top candidate {top_words[:3]!r}, expected {word!r} first")
            continue

        # Jittered path (simulating an imprecise real swipe) should still
        # rank the word in the top 5.
        noisy = _jitter(path, amount=0.15, rng=rng)
        noisy_results = decoder.decode(noisy, top_n=5)
        noisy_words = [w for w, _ in noisy_results]
        if word not in noisy_words:
            failures.append(f"{word!r}: jittered path -> top 5 {noisy_words!r}, expected {word!r} present")

    print(f"Wordlist size: {len(wordlist)}")
    print(f"Words tested: {len(test_words)}")
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return False

    print("PASS - decoder resolves exact and jittered swipe paths correctly.")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
