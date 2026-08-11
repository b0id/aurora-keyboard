"""
Headless unit tests for aurora_keyboard/swipe/rolling_context.py
(VOCAB_CONTEXT_SPEC.md sec4, Milestone 3b). No Qt/Wayland dependency -
verified standalone before wiring into keyboard_window.py, per sec9. Run:

    python3 -m unittest tests.test_rolling_context
"""

import time
import unittest

from aurora_keyboard.swipe.rolling_context import RollingTokenContext


class TestPushAndFIFO(unittest.TestCase):
    def test_push_and_get(self):
        ctx = RollingTokenContext(max_tokens=3)
        ctx.push_word("the")
        ctx.push_word("quick")
        self.assertEqual(ctx.get_context(), ["the", "quick"])

    def test_fifo_evicts_oldest(self):
        ctx = RollingTokenContext(max_tokens=2)
        ctx.push_word("the")
        ctx.push_word("quick")
        ctx.push_word("brown")
        self.assertEqual(ctx.get_context(), ["quick", "brown"])

    def test_lowercased_and_stripped(self):
        ctx = RollingTokenContext()
        ctx.push_word("  Critical  ")
        self.assertEqual(ctx.get_context(), ["critical"])

    def test_empty_word_ignored(self):
        ctx = RollingTokenContext()
        ctx.push_word("   ")
        self.assertEqual(ctx.get_context(), [])


class TestBoundaryReset(unittest.TestCase):
    def test_sentence_terminator_resets(self):
        ctx = RollingTokenContext()
        ctx.push_word("hello")
        ctx.handle_key(".")
        self.assertEqual(ctx.get_context(), [])

    def test_enter_resets(self):
        ctx = RollingTokenContext()
        ctx.push_word("hello")
        ctx.handle_key("ENTER")
        self.assertEqual(ctx.get_context(), [])

    def test_navigation_resets(self):
        ctx = RollingTokenContext()
        ctx.push_word("hello")
        ctx.handle_key("LEFT")
        self.assertEqual(ctx.get_context(), [])

    def test_ordinary_char_does_not_reset(self):
        ctx = RollingTokenContext()
        ctx.push_word("hello")
        ctx.handle_key("a")
        self.assertEqual(ctx.get_context(), ["hello"])

    def test_backspace_pops_last_token(self):
        ctx = RollingTokenContext()
        ctx.push_word("hello")
        ctx.push_word("world")
        ctx.handle_key("BACKSPACE")
        self.assertEqual(ctx.get_context(), ["hello"])


class TestReplaceLastWord(unittest.TestCase):
    def test_replaces_most_recent(self):
        ctx = RollingTokenContext()
        ctx.push_word("teh")
        ctx.replace_last_word("the")
        self.assertEqual(ctx.get_context(), ["the"])

    def test_replace_on_empty_context_appends(self):
        ctx = RollingTokenContext()
        ctx.replace_last_word("the")
        self.assertEqual(ctx.get_context(), ["the"])


class TestIdleTimeout(unittest.TestCase):
    def test_expires_after_idle_timeout(self):
        ctx = RollingTokenContext(idle_timeout_sec=0.05)
        ctx.push_word("hello")
        time.sleep(0.1)
        self.assertEqual(ctx.get_context(), [])

    def test_does_not_expire_before_timeout(self):
        ctx = RollingTokenContext(idle_timeout_sec=5.0)
        ctx.push_word("hello")
        self.assertEqual(ctx.get_context(), ["hello"])


if __name__ == "__main__":
    unittest.main()
