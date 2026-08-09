"""
UI Widgets module for Aurora Touch Keyboard.
"""

from .trail_overlay import SwipeTrailOverlay
from .candidate_bar import CandidateBar
from .drag_handle import DragHandleLabel, TouchResizeGrip
from .badge import FloatingBadge, BadgeButton
from .key_button import SwipeKeyButton

__all__ = [
    "SwipeTrailOverlay",
    "CandidateBar",
    "DragHandleLabel",
    "TouchResizeGrip",
    "FloatingBadge",
    "BadgeButton",
    "SwipeKeyButton",
]
