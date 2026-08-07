"""Bundled common-word list for the swipe decoder. Offline, no system
dictionary dependency (see SWIPE_SPEC.md for why: no frequency data on
/usr/share/dict/words, and it's full of obscure entries that would hurt
match quality more than they'd help coverage)."""

from pathlib import Path

_WORDLIST_PATH = Path(__file__).parent / "wordlist.txt"


def load_wordlist() -> list[str]:
    with open(_WORDLIST_PATH, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]
    return list(dict.fromkeys(words))
