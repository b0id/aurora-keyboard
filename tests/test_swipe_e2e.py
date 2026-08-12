"""
End-to-end integration test for Aurora Touch Keyboard swipe subsystem.
Verifies:
1. FUTO IPC client query against active daemon.
2. Graceful fallback to Geometric decoder when socket is unreachable.
3. CandidateBar and SwipeTrailOverlay lifecycle.
"""

import sys
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF

from aurora_keyboard.swipe import (
    SwipeDecoder,
    standard_qwerty_key_positions,
    load_wordlist,
    FutoSwipeClient,
    SwipeManager
)
from aurora_keyboard.keyboard_window import AuroraKeyboardWindow, CandidateBar, SwipeTrailOverlay


class TestSwipeIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_geometric_decoder_direct(self):
        key_pos = standard_qwerty_key_positions()
        wordlist = load_wordlist()
        decoder = SwipeDecoder(key_pos, wordlist)
        # Test path for 'bad'
        bad_path = [key_pos['b'], key_pos['a'], key_pos['d']]
        results = decoder.decode(bad_path, top_n=3)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0][0], "bad")

    def test_swipe_manager_fallback(self):
        # Point to a non-existent socket to guarantee fallback test
        manager = SwipeManager()
        manager.futo_client.socket_path = "/tmp/non_existent_swipe_test.sock"
        key_pos = standard_qwerty_key_positions()
        
        path = [key_pos['h'], key_pos['e'], key_pos['l'], key_pos['o']]
        candidates, backend = manager.decode(
            raw_points=path,
            raw_trail=[(p[0], p[1], i * 20) for i, p in enumerate(path)],
            key_positions=key_pos,
            top_n=5
        )
        self.assertEqual(backend, "geometric")
        self.assertIn("hello", candidates)

    def test_swipe_manager_fallback_uses_shared_lexicon(self):
        # The fallback used to be stuck on the 1,175-word bundled
        # wordlist.txt (couldn't produce "infrastructure" at all, a real
        # incident - see VOCAB_CONTEXT_SPEC.md sec5.1). It should now use
        # the shared ~31K-word lexicon like the neural daemon does.
        manager = SwipeManager()
        manager.futo_client.socket_path = "/tmp/non_existent_swipe_test.sock"
        self.assertGreater(len(manager.wordlist), 10000)

        key_pos = standard_qwerty_key_positions()
        from aurora_keyboard.swipe.trajectory import synthesize_swipe
        trail = synthesize_swipe("infrastructure", key_pos, jitter=0.0, seed=42)
        points = [(x, y) for x, y, _ in trail]
        candidates, backend = manager.decode(
            raw_points=points,
            raw_trail=trail,
            key_positions=key_pos,
            top_n=5
        )
        self.assertEqual(backend, "geometric")
        self.assertIn("infrastructure", candidates)

    def test_geo_decoder_cached_by_layout(self):
        manager = SwipeManager()
        key_pos_a = standard_qwerty_key_positions()
        key_pos_b = dict(key_pos_a)
        key_pos_b["a"] = (key_pos_a["a"][0] + 100, key_pos_a["a"][1])  # different layout

        d1 = manager.get_geo_decoder(key_pos_a)
        d2 = manager.get_geo_decoder(key_pos_a)
        self.assertIs(d1, d2, "same key_positions should reuse the cached decoder")

        d3 = manager.get_geo_decoder(key_pos_b)
        self.assertIsNot(d1, d3, "different key_positions should rebuild the decoder")

    def test_futo_daemon_live_if_active(self):
        client = FutoSwipeClient()
        if client.is_available():
            key_pos = standard_qwerty_key_positions()
            # Synthetic trail for 'bad'
            raw_trail = [(key_pos[c][0], key_pos[c][1], i * 30) for i, c in enumerate(['b', 'v', 'f', 'd', 's', 'a', 's', 'd'])]
            candidates = client.predict(raw_trail, key_pos, top_n=5)
            self.assertTrue(len(candidates) > 0)
            print(f"[Live FUTO Test] Predicted: {candidates}")

    def test_candidate_bar_and_trail(self):
        window = AuroraKeyboardWindow()
        self.assertIsNotNone(window.candidate_bar)
        self.assertIsNotNone(window.trail_overlay)

        # Set candidates
        window.candidate_bar.set_candidates(["well", "will", "wall"], backend="futo-neural")
        self.assertEqual(len(window.candidate_bar.chip_buttons), 3)
        self.assertIn("well", window.candidate_bar.chip_buttons[0].text())

        # Clear candidates
        window.candidate_bar.clear_candidates()
        self.assertEqual(len(window.candidate_bar.chip_buttons), 0)

        # Test trail overlay points & fade
        window.trail_overlay.add_point(window.mapToGlobal(window.rect().center()))
        self.assertTrue(len(window.trail_overlay.points) > 0)
        window.trail_overlay.start_fade()
        window.trail_overlay.clear_trail()
        self.assertEqual(len(window.trail_overlay.points), 0)


if __name__ == "__main__":
    unittest.main()
