"""
Headless multi-syllable swipe accuracy benchmark (VOCAB_CONTEXT_SPEC.md
Milestone 1). No pytest dependency, no Wayland/Qt/GPU - run directly:

    python3 -m tests.test_multisyllable_eval

This is a MEASUREMENT harness, not a pass/fail gate yet. Per
VOCAB_CONTEXT_SPEC.md sec7's "methodology change from v1.0.0": until a
baseline exists, there's nothing real to gate against, so this prints the
current numbers rather than asserting target thresholds. Once a baseline is
recorded (see the doc's Milestone 1 results), later runs can be compared
against it by hand or a stricter check can be added here.

Tests two independent things, matching the dual-backend architecture:
  1. The geometric fallback decoder (decoder.py) - zero-dependency, but
     only knows the words in its own wordlist.txt (currently 1,200 words,
     pre-Milestone-2 shared lexicon). Words absent from that list are
     reported separately, not counted as decode failures - that's a
     vocabulary-coverage gap (Milestone 2's job), not a matching-algorithm
     failure.
  2. The FUTO neural daemon over its live socket, if running - post-
     Milestone-0, its pool is the full 32,768-word downloaded vocab. Skipped
     cleanly (not failed) if the daemon isn't up, so this suite still runs
     on a machine without the container.
"""

import statistics
import time

from aurora_keyboard.swipe.decoder import SwipeDecoder, standard_qwerty_key_positions
from aurora_keyboard.swipe.wordlist import load_wordlist
from aurora_keyboard.swipe.futo_client import FutoSwipeClient
from aurora_keyboard.swipe.trajectory import synthesize_swipe

# 4-5 syllable words in common/professional/technical parlance, per
# VOCAB_CONTEXT_SPEC.md tenet #2. Not all are strictly 4-5 syllables by a
# formal count (e.g. "sustainability" is 6) - this mirrors the spec's own
# named example list, which uses the same loose framing.
MULTISYLLABLE_WORDS = [
    "infrastructure", "characteristic", "sustainability", "unprecedented",
    "sophisticated", "implementation", "vulnerability", "communication",
    "application", "information", "organization", "responsibility",
    "considerably", "geographical", "mathematical", "technological",
    "particularly", "university", "opportunity", "imagination",
    "environmental", "professional", "administration", "documentation",
    "configuration", "authentication", "availability", "accessibility",
    "compatibility", "functionality", "optimization",
]

JITTER_SEED = 42
JITTER_AMOUNT = 0.12


def _eval_geometric(words: list[str]) -> dict:
    key_positions = standard_qwerty_key_positions()
    wordlist = load_wordlist()
    wordlist_set = set(wordlist)
    decoder = SwipeDecoder(key_positions, wordlist)

    in_vocab = [w for w in words if w in wordlist_set]
    out_of_vocab = [w for w in words if w not in wordlist_set]

    exact_hits, jitter_hits = [], []
    for word in in_vocab:
        exact_trail = synthesize_swipe(word, key_positions, jitter=0.0)
        jitter_trail = synthesize_swipe(word, key_positions, jitter=JITTER_AMOUNT, seed=JITTER_SEED)
        if exact_trail is None or jitter_trail is None:
            continue

        exact_points = [(x, y) for x, y, _ in exact_trail]
        top1 = decoder.decode(exact_points, top_n=1)
        exact_hits.append(bool(top1) and top1[0][0] == word)

        jitter_points = [(x, y) for x, y, _ in jitter_trail]
        top3 = [w for w, _ in decoder.decode(jitter_points, top_n=3)]
        jitter_hits.append(word in top3)

    return {
        "backend": "geometric",
        "in_vocab": in_vocab,
        "out_of_vocab": out_of_vocab,
        "exact_top1_rate": sum(exact_hits) / len(exact_hits) if exact_hits else None,
        "jitter_top3_rate": sum(jitter_hits) / len(jitter_hits) if jitter_hits else None,
        "n_evaluated": len(exact_hits),
    }


def _eval_futo(words: list[str]) -> dict | None:
    client = FutoSwipeClient(timeout=2.0)
    if not client.is_available():
        return None

    key_positions = standard_qwerty_key_positions()
    exact_hits, jitter_hits, latencies_ms = [], [], []

    for word in words:
        exact_trail = synthesize_swipe(word, key_positions, jitter=0.0)
        jitter_trail = synthesize_swipe(word, key_positions, jitter=JITTER_AMOUNT, seed=JITTER_SEED)
        if exact_trail is None or jitter_trail is None:
            continue

        t0 = time.monotonic()
        top1 = client.predict(exact_trail, key_positions, top_n=1)
        latencies_ms.append((time.monotonic() - t0) * 1000.0)
        exact_hits.append(bool(top1) and top1[0] == word)

        top3 = client.predict(jitter_trail, key_positions, top_n=3)
        jitter_hits.append(word in top3)

    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1] if latencies_ms else None

    return {
        "backend": "futo-neural",
        "exact_top1_rate": sum(exact_hits) / len(exact_hits) if exact_hits else None,
        "jitter_top3_rate": sum(jitter_hits) / len(jitter_hits) if jitter_hits else None,
        "n_evaluated": len(exact_hits),
        "latency_p95_ms_roundtrip": p95,
        "latency_mean_ms_roundtrip": statistics.mean(latencies_ms) if latencies_ms else None,
    }


def _fmt_rate(rate: float | None) -> str:
    return f"{rate * 100:.1f}%" if rate is not None else "n/a"


def run() -> bool:
    print(f"Multisyllable word set: {len(MULTISYLLABLE_WORDS)} words")
    print()

    geo = _eval_geometric(MULTISYLLABLE_WORDS)
    print("[geometric fallback decoder]")
    print(f"  in wordlist.txt today:     {len(geo['in_vocab'])}/{len(MULTISYLLABLE_WORDS)}")
    print(f"  not in wordlist.txt today: {len(geo['out_of_vocab'])} (vocabulary-coverage gap, not a decode failure - see Milestone 2)")
    if geo["out_of_vocab"]:
        print(f"    {', '.join(geo['out_of_vocab'])}")
    print(f"  exact-path top-1 rate (n={geo['n_evaluated']}):   {_fmt_rate(geo['exact_top1_rate'])}")
    print(f"  jittered-path top-3 rate (n={geo['n_evaluated']}): {_fmt_rate(geo['jitter_top3_rate'])}")
    print()

    futo = _eval_futo(MULTISYLLABLE_WORDS)
    if futo is None:
        print("[futo neural daemon] not available on /tmp/futo_swipe.sock - skipped (not a failure)")
    else:
        print("[futo neural daemon]")
        print(f"  words evaluated:            {futo['n_evaluated']}/{len(MULTISYLLABLE_WORDS)}")
        print(f"  exact-path top-1 rate:      {_fmt_rate(futo['exact_top1_rate'])}")
        print(f"  jittered-path top-3 rate:   {_fmt_rate(futo['jitter_top3_rate'])}")
        if futo["latency_p95_ms_roundtrip"] is not None:
            print(f"  client round-trip latency:  p95={futo['latency_p95_ms_roundtrip']:.2f}ms  mean={futo['latency_mean_ms_roundtrip']:.2f}ms")
            print("  (end-to-end IPC round trip, a superset of spec sec7's narrower")
            print("   'pure decode loop excluding encoder' target - that split isn't")
            print("   separately instrumented in futo_daemon.py yet)")
    print()

    # This is a measurement harness (see module docstring) - it only fails
    # on structural problems, not on hit-rate numbers.
    if geo["n_evaluated"] == 0:
        print("FAILED - no in-vocab words were evaluable against the geometric decoder.")
        return False

    print("DONE - see numbers above. Not a pass/fail gate until a baseline is recorded (Milestone 1).")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
