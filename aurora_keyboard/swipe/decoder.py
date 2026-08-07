"""
Geometric swipe-to-type decoder (SHARK2-lite).

No neural network, no external service, no model download: a candidate word's
score is how closely the straight-line path through its letters' key centers
matches the user's swipe path. Key positions are passed in rather than
hardcoded, so this module has no idea whether it's being tested against a
synthetic grid or driven by the live keyboard's real button geometry -
that's what keeps it independently testable.
"""

from __future__ import annotations

import math

KeyPositions = dict[str, tuple[float, float]]
Point = tuple[float, float]


def standard_qwerty_key_positions() -> KeyPositions:
    """Unit-space key centers for a standard staggered QWERTY layout, used
    for standalone testing. Real integration passes live button centers
    from the keyboard UI instead of this."""
    rows = [
        ("qwertyuiop", 0.0, 0.0),
        ("asdfghjkl", 0.5, 1.0),
        ("zxcvbnm", 1.0, 2.0),
    ]
    positions: KeyPositions = {}
    for letters, x_offset, y in rows:
        for i, ch in enumerate(letters):
            positions[ch] = (x_offset + i, y)
    return positions


def _resample(points: list[Point], n: int) -> list[Point]:
    """Resample a polyline to exactly n points, evenly spaced by arc length,
    so paths of different raw lengths become directly comparable point-by-point."""
    if not points:
        return [(0.0, 0.0)] * n
    if len(points) == 1 or n == 1:
        return [points[0]] * n

    seg_lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(seg_lengths)
    if total == 0:
        return [points[0]] * n

    step = total / (n - 1)
    out = [points[0]]
    seg_idx = 0
    seg_pos = 0.0
    target = step
    while len(out) < n - 1:
        while seg_idx < len(seg_lengths) and seg_pos + seg_lengths[seg_idx] < target:
            seg_pos += seg_lengths[seg_idx]
            seg_idx += 1
        if seg_idx >= len(seg_lengths):
            out.append(points[-1])
            continue
        remain = target - seg_pos
        x0, y0 = points[seg_idx]
        x1, y1 = points[seg_idx + 1]
        t = remain / seg_lengths[seg_idx] if seg_lengths[seg_idx] else 0.0
        out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        target += step
    out.append(points[-1])
    return out[:n]


def _estimate_key_spacing(key_positions: KeyPositions) -> float:
    """Median nearest-neighbor distance between keys. Lets pruning scale to
    whatever coordinate space key_positions are actually in - the synthetic
    unit grid, or a live keyboard's on-screen pixel centers at any window
    size, DPI, or orientation - instead of assuming a fixed unit scale."""
    coords = list(key_positions.values())
    if len(coords) < 2:
        return 1.0
    nearest = [min(math.dist(p, q) for j, q in enumerate(coords) if j != i) for i, p in enumerate(coords)]
    nearest.sort()
    mid = nearest[len(nearest) // 2]
    return mid if mid > 0 else 1.0


def _word_path(word: str, key_positions: KeyPositions) -> list[Point] | None:
    """Straight-line path through a word's unique consecutive letters - a
    swipe doesn't loop back on itself for double letters like 'hello'."""
    letters = []
    for ch in word:
        if ch not in key_positions:
            return None
        if not letters or letters[-1] != ch:
            letters.append(ch)
    if not letters:
        return None
    return [key_positions[ch] for ch in letters]


class SwipeDecoder:
    """Matches a raw swipe path against a dictionary via key-center geometry."""

    RESAMPLE_POINTS = 16
    ENDPOINT_PRUNE_FACTOR = 2.5  # multiplier of the keyboard's own key spacing

    def __init__(self, key_positions: KeyPositions, wordlist: list[str]):
        self.key_positions = key_positions
        self._prune_radius = _estimate_key_spacing(key_positions) * self.ENDPOINT_PRUNE_FACTOR
        self._candidates: list[tuple[str, list[Point], Point, Point]] = []
        for word in wordlist:
            path = _word_path(word, key_positions)
            if path is None or len(path) < 2:
                continue
            resampled = _resample(path, self.RESAMPLE_POINTS)
            self._candidates.append((word, resampled, path[0], path[-1]))

    def decode(self, raw_points: list[Point], top_n: int = 5) -> list[tuple[str, float]]:
        """Return up to top_n (word, distance) pairs, closest match first."""
        if len(raw_points) < 2:
            return []

        user_path = _resample(raw_points, self.RESAMPLE_POINTS)
        start, end = raw_points[0], raw_points[-1]

        pruned = [
            c for c in self._candidates
            if math.dist(start, c[2]) < self._prune_radius
            and math.dist(end, c[3]) < self._prune_radius
        ]
        pool = pruned or self._candidates

        scored = []
        for word, path, _, _ in pool:
            dist = sum(math.dist(a, b) for a, b in zip(user_path, path)) / self.RESAMPLE_POINTS
            scored.append((word, dist))

        scored.sort(key=lambda pair: pair[1])
        return scored[:top_n]
