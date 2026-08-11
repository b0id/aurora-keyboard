"""
Ephemeral rolling token context (VOCAB_CONTEXT_SPEC.md sec4, Milestone 3b).
Application-level FIFO of recently-committed words, feeding the context LM's
alpha-weighted term (sec6.1). No Qt/Wayland dependency - reads events the
app already sees, no new system API, no UI surface.
"""

from __future__ import annotations

import time

_BOUNDARY_KEYS = {".", "!", "?", "ENTER", "TAB", "ESC", "LEFT", "RIGHT", "UP", "DOWN"}


class RollingTokenContext:
    """Tracks the last `max_tokens` committed words within the current
    input session, with automatic boundary reset on punctuation/navigation
    and idle timeout."""

    def __init__(self, max_tokens: int = 3, idle_timeout_sec: float = 25.0):
        self.max_tokens = max_tokens
        self.idle_timeout_sec = idle_timeout_sec
        self._tokens: list[str] = []
        self._last_event_time: float = 0.0

    def push_word(self, word: str) -> None:
        word = word.strip().lower()
        if not word:
            return
        self._tokens.append(word)
        if len(self._tokens) > self.max_tokens:
            self._tokens.pop(0)
        self._last_event_time = time.time()

    def replace_last_word(self, word: str) -> None:
        """Used when a one-tap candidate replacement changes the last
        committed word after the fact (sec4 Boundary Reset Rule 3)."""
        word = word.strip().lower()
        if not word:
            return
        if self._tokens:
            self._tokens[-1] = word
        else:
            self._tokens.append(word)
        self._last_event_time = time.time()

    def handle_key(self, keycode_or_char: str) -> None:
        if keycode_or_char in _BOUNDARY_KEYS:
            self.reset()
        elif keycode_or_char == "BACKSPACE":
            self._pop_char_or_token()

    def _pop_char_or_token(self) -> None:
        if self._tokens:
            self._tokens.pop()

    def reset(self) -> None:
        self._tokens = []

    def get_context(self) -> list[str]:
        if self._tokens and time.time() - self._last_event_time > self.idle_timeout_sec:
            self.reset()
        return list(self._tokens)
