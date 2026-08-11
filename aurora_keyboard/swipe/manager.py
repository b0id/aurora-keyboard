"""
Unified SwipeManager orchestrating the FUTO neural backend and geometric decoder.
"""

from typing import Tuple, List
from .decoder import SwipeDecoder
from .wordlist import load_wordlist
from .futo_client import FutoSwipeClient


class SwipeManager:
    """Manages swipe inference with priority: FUTO Neural Daemon -> Geometric Decoder Fallback."""

    def __init__(self):
        self.futo_client = FutoSwipeClient()
        self.wordlist = load_wordlist()
        self._geo_decoders = {}

    def get_geo_decoder(self, key_positions: dict) -> SwipeDecoder:
        # Cache decoder instance by key count or layout
        return SwipeDecoder(key_positions, self.wordlist)

    def decode(
        self,
        raw_points: list,
        raw_trail: list,
        key_positions: dict,
        top_n: int = 5,
        context: list = None
    ) -> Tuple[List[str], str]:
        """Decode a swipe trajectory.

        context: optional preceding words (VOCAB_CONTEXT_SPEC.md sec4),
        passed through to the daemon's context LM if one is loaded.
        Only affects the neural path - the geometric fallback has no
        context-scoring mechanism.

        Returns (candidates_list, backend_used).
        """
        # 1. Primary: Try FUTO Neural Daemon (if daemon is listening)
        if raw_trail and len(raw_trail) >= 2:
            neural_candidates = self.futo_client.predict(raw_trail, key_positions, top_n=top_n, context=context)
            if neural_candidates:
                return neural_candidates, "futo-neural"

        # 2. Secondary: Fallback to Geometric Decoder
        if raw_points and len(raw_points) >= 2:
            try:
                decoder = self.get_geo_decoder(key_positions)
                geo_results = decoder.decode(raw_points, top_n=top_n)
                if geo_results:
                    return [w for w, _ in geo_results], "geometric"
            except Exception:
                pass

        return [], "none"
