"""
Aurora Touch Keyboard swipe-to-type module.
"""

from .decoder import SwipeDecoder, standard_qwerty_key_positions
from .wordlist import load_wordlist
from .futo_client import FutoSwipeClient
from .manager import SwipeManager

__all__ = [
    "SwipeDecoder",
    "standard_qwerty_key_positions",
    "load_wordlist",
    "FutoSwipeClient",
    "SwipeManager"
]
