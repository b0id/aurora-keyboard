# Swipe-to-Type — Complete Architecture & Specification

## Current Status: Fully Implemented & Shipped (Aug 2026)

The swipe gesture engine is fully built, tested, and integrated into Aurora Touch Keyboard:

1. **Continuous Gesture Recognition**: `SwipeKeyButton` differentiates discrete taps from continuous swipe drags using a 16px manhattan distance threshold.
2. **Dual-Backend Decoding Architecture**:
   - **Primary Backend (FUTO Neural Engine)**: Connects via Unix domain socket (`/tmp/futo_swipe.sock`) to `futo_daemon.py`, running FUTO's 1D-CNN spatial encoder (`honorable_sturgeon`) and transformer sequence decoder (`magic_macaw`) with ExecuTorch edge inference.
   - **Fallback Backend (SHARK² Geometric Decoder)**: If the neural daemon is offline, `SwipeManager` seamlessly falls back to `aurora_keyboard/swipe/decoder.py` using geometric curve matching against the bundled high-frequency dictionary.
3. **Real-time Candidate Suggestion Bar (`CandidateBar`)**:
   - Displays top 5 predicted words with visual engine indicators (`⚡ FUTO` or `✦ Swipe`).
   - **Instant Auto-Commit**: Automatically types the top predicted candidate with a trailing space on gesture release.
   - **One-Tap Replacement**: Tapping secondary candidate chips automatically backspaces the last committed word and substitutes the selected candidate.
4. **Glowing Gesture Trail Overlay (`SwipeTrailOverlay`)**:
   - 60 FPS transparent overlay rendering glowing anti-aliased Bézier paths themed to match the active glassmorphic theme color.
   - Smooth exponential decay fade animation on gesture release.

---

## Technical Specifications

### Input Pipeline
```
Touch Drag → SwipeKeyButton (mouseMoveEvent)
  → SwipeTrailOverlay.add_point()
  → swipe_raw_sample(pos, timestamp_ms)
  → gesture release
  → SwipeManager.decode(raw_points, raw_trail, key_positions)
  → CandidateBar.set_candidates(words, backend)
  → KeyEngine.type_text(top_word + " ")
```

### Performance Metrics
- **Kinematic Resampling**: 60 Hz uniform temporal interpolation.
- **Inference Latency**: 18–24 ms on modern x86_64 / ARM64 CPUs.
- **Memory Footprint**: <45 MB resident memory for neural weights.
