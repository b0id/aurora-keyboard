"""
Synthetic swipe trajectory generator for headless testing (SWIPE_SPEC/
VOCAB_CONTEXT_SPEC Milestone 1).

Produces kinematically smooth (x, y, t) trails through a word's key centers
using a centripetal Catmull-Rom spline, so corners are rounded the way a
real swipe rounds them instead of the straight-line-through-corners shape
the earlier ad-hoc test scripts used. No Qt/Wayland dependency - this is
pure geometry and can run against either the geometric decoder in-process
or the FUTO daemon over its socket.
"""

from __future__ import annotations

import math
import random

KeyPositions = dict[str, tuple[float, float]]
Point = tuple[float, float]
TrailPoint = tuple[float, float, int]


def _lerp(pa: Point, pb: Point, ta: float, tb: float, t: float) -> Point:
    ratio = (t - ta) / (tb - ta)
    return (pa[0] + (pb[0] - pa[0]) * ratio, pa[1] + (pb[1] - pa[1]) * ratio)


def _catmull_rom_segment(p0: Point, p1: Point, p2: Point, p3: Point, n: int, alpha: float = 0.5) -> list[Point]:
    """Centripetal Catmull-Rom points between p1 and p2, given neighbors p0/p3."""
    def tj(t: float, pi: Point, pj: Point) -> float:
        return t + math.dist(pi, pj) ** alpha

    t0 = 0.0
    t1 = tj(t0, p0, p1)
    t2 = tj(t1, p1, p2)
    t3 = tj(t2, p2, p3)
    if t2 == t1:
        return [p1] * n

    out = []
    for i in range(n):
        t = t1 + (t2 - t1) * (i / n)
        a1 = _lerp(p0, p1, t0, t1, t) if t1 > t0 else p1
        a2 = _lerp(p1, p2, t1, t2, t)
        a3 = _lerp(p2, p3, t2, t3, t) if t3 > t2 else p2
        b1 = _lerp(a1, a2, t0, t2, t) if t2 > t0 else a2
        b2 = _lerp(a2, a3, t1, t3, t) if t3 > t1 else a2
        c = _lerp(b1, b2, t1, t2, t)
        out.append(c)
    return out


def _catmull_rom_spline(points: list[Point], samples_per_segment: int = 8) -> list[Point]:
    """Smooth, corner-rounded curve through points. Duplicates the first/last
    point as phantom control points so the curve starts/ends exactly on the
    real endpoints (standard Catmull-Rom boundary handling)."""
    if len(points) < 2:
        return list(points)
    if len(points) == 2:
        # A straight two-key swipe has no interior corner to round.
        return [points[0], points[1]]

    padded = [points[0]] + points + [points[-1]]
    out: list[Point] = []
    for i in range(1, len(padded) - 2):
        out.extend(_catmull_rom_segment(padded[i - 1], padded[i], padded[i + 1], padded[i + 2], samples_per_segment))
    out.append(points[-1])
    return out


def _resample_by_arclength(points: list[Point], n: int) -> list[Point]:
    """Evenly re-space points along the curve's arc length, so a synthetic
    swipe moves at roughly constant speed rather than clustering samples
    wherever the spline happened to place them."""
    if not points:
        return []
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
        t = remain / seg_lengths[seg_idx] if seg_lengths[seg_idx] else 0.0
        out.append(_lerp(points[seg_idx], points[seg_idx + 1], 0.0, 1.0, t))
        target += step
    out.append(points[-1])
    return out[:n]


def word_key_path(word: str, key_positions: KeyPositions) -> list[Point] | None:
    """Key centers for a word's unique consecutive letters. None if any
    letter isn't on the given layout, matching decoder.py's own convention."""
    letters: list[str] = []
    for ch in word:
        if ch not in key_positions:
            return None
        if not letters or letters[-1] != ch:
            letters.append(ch)
    if not letters:
        return None
    return [key_positions[ch] for ch in letters]


def synthesize_swipe(
    word: str,
    key_positions: KeyPositions,
    jitter: float = 0.12,
    t_step_ms: int = 25,
    points_per_letter: int = 6,
    seed: int | None = None,
) -> list[TrailPoint] | None:
    """Synthesize a continuous, kinematically smooth (x, y, t) swipe trail
    for `word` on the given key layout. Returns None if the word isn't
    representable on this layout (a missing letter) or has fewer than 2
    unique consecutive letters (nothing to swipe through).

    jitter=0 produces the "ideal path" case; jitter>0 (Gaussian, in the same
    units as key_positions) simulates an imprecise real swipe.
    """
    key_path = word_key_path(word, key_positions)
    if key_path is None or len(key_path) < 2:
        return None

    spline = _catmull_rom_spline(key_path, samples_per_segment=8)
    n_points = max(len(key_path) * points_per_letter, 12)
    even_points = _resample_by_arclength(spline, n_points)

    rng = random.Random(seed) if seed is not None else random
    trail: list[TrailPoint] = []
    t = 0
    for x, y in even_points:
        nx = x + rng.gauss(0, jitter) if jitter else x
        ny = y + rng.gauss(0, jitter) if jitter else y
        trail.append((nx, ny, t))
        t += t_step_ms
    return trail
