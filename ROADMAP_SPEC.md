# 🚀 Aurora Keyboard — Future Roadmap & Architecture Specification

This specification breaks down four strategic development initiatives for **Aurora Touch Keyboard** into modular, 1-by-1 implementation blueprints to tackle in future milestones.

---

## 📋 Table of Contents
1. [Module 1: Lock Screen & Greeter Integration (SDDM & KScreenLocker)](#-module-1-lock-screen--greeter-integration)
2. [Module 2: Universal Compositor Portability & Layer-Shell Abstraction](#-module-2-universal-compositor-portability--layer-shell-abstraction)
3. [Module 3: Rust Core Engine & Hybrid PyO3 Architecture](#-module-3-rust-core-engine--hybrid-pyo3-architecture)
4. [Module 4: FUTO Neural Swipe Training & Adaptive Feedback Loop](#-module-4-futo-neural-swipe-training--adaptive-feedback-loop)

---

## 🔒 Module 1: Lock Screen & Greeter Integration

### 1. Objective
Allow Aurora Keyboard to launch and input credentials seamlessly over Linux display managers (SDDM, GDM, LightDM) and desktop lock screens (`kscreenlocker` in KDE Plasma, GNOME Shell lock screen) without violating compositor security policies.

### 2. Architecture & Security Model
```
┌────────────────────────────────────────────────────────────────────────┐
│                        Wayland Compositor / Locker                     │
│  (KScreenLocker / SDDM Greeter / Mutter Lock Overlay / Hyprlock)       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Layer-Shell (layer = overlay)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Aurora Lock Surface (Unprivileged)                   │
│   • Frameless overlay surface via zwlr_layer_shell_v1 / input-method  │
│   • Qt::WindowDoesNotAcceptFocus (prevents credential interception)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Linux Kernel Evdev
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             /dev/uinput Kernel Device ("Aurora Virtual Touch")          │
│   • Hardware-level EV_KEY emission directly to PAM/login subsystem    │
└────────────────────────────────────────────────────────────────────────┘
```

### 3. Key Components
1. **Wayland Layer-Shell Protocol Bridge**:
   - Utilize `zwlr_layer_shell_v1` with `ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY` to render above locked surfaces.
   - Alternative for KDE: Hook into KWin Virtual Keyboard DBus interface (`org.kde.kwin.virtualkeyboard`).
2. **PAM & UInput Independence**:
   - Because Aurora emits kernel `EV_KEY` events via `/dev/uinput`, the display manager (SDDM/GDM) receives standard physical keyboard scan codes into the password field without needing custom authentication plugins.
3. **Session State Watcher**:
   - Monitor `org.freedesktop.login1.Session` DBus signals (`Lock` / `Unlock`) to automatically summon or dismiss the keyboard on lock screen activation.

### 4. Implementation Checklist
- [ ] Implement `LockScreenWatcher` listening to systemd `logind` lock/unlock signals.
- [ ] Add `zwlr-layer-shell` support for rendering in the overlay layer.
- [ ] Provide a system-level systemd user unit (`aurora-keyboard-greeter.service`) for SDDM/GDM sessions.
- [ ] Verify password asterisks receive input with zero character leak in logs.

---

## 🌐 Module 2: Universal Compositor Portability & Layer-Shell Abstraction

### 1. Objective
Decouple Aurora Keyboard from KDE-specific KWin DBus scripts, enabling full native window management across **GNOME (Mutter)**, **wlroots (Hyprland / Sway)**, **Cosmic**, and **SteamOS Gamescope**.

### 2. Compositor Strategy Pattern
```python
# Conceptual Architecture: aurora_keyboard/compositors/base.py
class BaseCompositorBackend(ABC):
    @abstractmethod
    def query_live_geometry(self, window_title: str) -> Optional[Tuple[int, int, int, int]]:
        """Retrieve live physical (x, y, w, h) coordinates on Wayland."""
        pass

    @abstractmethod
    def set_window_geometry(self, window_title: str, x: int, y: int, w: int, h: int) -> bool:
        """Position and size the window via native compositor protocol."""
        pass

    @abstractmethod
    def sync_rules(self, x: int, y: int, w: int, h: int, is_badge: bool):
        """Persist anti-centering and window rules."""
        pass
```

### 3. Backend Implementations
* **`KWinDBusBackend`** *(Current)*: Uses `qdbus-qt6 org.kde.KWin /Scripting` and `~/.config/kwinrulesrc`.
* **`WlrLayerShellBackend`** *(Hyprland / Sway)*: Uses standard Wayland layer-shell anchoring (`top`, `bottom`, `left`, `right`) with pixel margins.
* **`MutterDBusBackend`** *(GNOME)*: Uses GNOME Shell D-Bus evaluation or input-method-v2 interface.
* **`X11FallbackBackend`**: Uses standard X11 `_NET_WM_STRUT_PARTIAL` and `XMoveResizeWindow`.

### 4. Auto-Detection Logic
```python
def detect_compositor_backend() -> BaseCompositorBackend:
    xdg_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")

    if "kde" in xdg_desktop or "plasma" in xdg_desktop:
        return KWinDBusBackend()
    elif "hyprland" in xdg_desktop or "sway" in xdg_desktop or "wlroots" in xdg_desktop:
        return WlrLayerShellBackend()
    elif "gnome" in xdg_desktop:
        return MutterDBusBackend()
    return GenericX11Backend()
```

### 5. Implementation Checklist
- [ ] Refactor `GeometryManager` to delegate to `BaseCompositorBackend`.
- [ ] Implement `WlrLayerShellBackend` using `PyQt6-Wayland` layer-shell integration.
- [ ] Validate multi-monitor and display rotation handling across Hyprland and Sway.

---

## ⚡ Module 3: Rust Core Engine & Hybrid PyO3 Architecture

### 1. Objective
Significantly lower memory usage (from ~120MB down to <25MB), eliminate Python garbage collection latency spikes during fast touch typing, and achieve sub-20ms cold-start time.

### 2. Phased Migration Strategy

```
Phase 3A: PyO3 Hybrid Module ──► Phase 3B: Rust Neural Daemon ──► Phase 3C: Full Native Binary
(Keep PyQt6 UI, port engine)      (Port ONNX/Beam search to Rust)   (Native Slint/Iced GUI)
RAM: ~60MB | Speed: +40%         RAM: ~35MB | Speed: +80%          RAM: ~15MB | Startup: <20ms
```

### 3. Phase 3A: `aurora-core` (Rust / PyO3)
Port performance-critical loops to a compiled Rust extension module:
* **Kernel UInput Loop**: Direct `evdev-rs` key emission with microsecond timer precision.
* **Trajectory Feature Extractor**: Resampling raw touch trails `[(x, y, t)]`, calculating velocity vectors, curve angles, and bounding box normalization.
* **Rolling Token Context**: Fast lock-free circular ring buffer for word prediction context.

```rust
// aurora_core/src/lib.rs (PyO3 Binding Example)
use pyo3::prelude::*;

#[pyclass]
struct FastKeyEngine {
    // evdev uinput file descriptor
}

#[pymethods]
impl FastKeyEngine {
    #[new]
    fn new() -> PyResult<Self> { ... }
    fn send_keycode(&mut self, code: u16) -> PyResult<()> { ... }
    fn send_combo(&mut self, mods: Vec<u16>, target: u16) -> PyResult<()> { ... }
}

#[pyfunction]
fn resample_swipe_trail(raw_points: Vec<(f32, f32, f64)>) -> PyResult<Vec<(f32, f32)>> { ... }
```

### 4. Phase 3B & 3C: Standalone Binary (Slint + `ort`)
* **GUI Framework**: [Slint](https://slint.dev/) (Lightweight, GPU-accelerated, declarative UI targeting embedded & desktop touch devices).
* **Neural Runtime**: Native Rust [`ort`](https://github.com/pykeio/ort) (ONNX Runtime wrapper) or `candle` for running FUTO neural swipe models with zero Python dependencies.

---

## 🧠 Module 4: FUTO Neural Swipe Training & Adaptive Feedback Loop

### 1. Objective
Build an on-device, privacy-preserving feedback and fine-tuning loop that learns from your personal swipe trajectory habits, corrects recurring mistyped words, and calibrates key hitboxes.

### 2. Feedback Architecture
```
┌────────────────────────────────────────────────────────────────────────┐
│                        User Touch Interaction                          │
│   1. Swipe gesture on keyboard ──► Produces raw [(x, y, t)] trail     │
│   2. Decoder generates Top-5 predictions: ['hello', 'help', ...]       │
│   3. User selects word OR hits Backspace to correct                    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Trajectory & Selection Logger                       │
│   Logs paired record to ~/.local/share/aurora-keyboard/feedback.jsonl  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│     Vocabulary Personalizer   │               │   Touch Heatmap Calibrator    │
│  • Dynamic N-Gram frequency   │               │  • Dynamic key center offsets │
│  • Jargon / slang promotion   │               │  • Per-finger drift profiling │
└───────────────────────────────┘               └───────────────────────────────┘
```

### 3. Data Format: `feedback.jsonl`
```json
{
  "timestamp": 1723507200.123,
  "layout": "QWERTY",
  "screen_orientation": "landscape",
  "screen_resolution": [1600, 1067],
  "raw_trail": [
    {"x": 420.5, "y": 810.2, "t": 10},
    {"x": 480.1, "y": 790.0, "t": 45},
    {"x": 610.4, "y": 830.8, "t": 110}
  ],
  "top_candidates": ["quick", "quack", "thick"],
  "chosen_word": "quick",
  "was_corrected": false,
  "correction_replacement": null
}
```

### 4. Adaptation Mechanisms
1. **Dynamic Language Model (LM) Scoring**:
   - Boost candidate probabilities for words frequently selected in technical, coding, or personal workflows.
2. **Adaptive Key Center Calibration**:
   - Calculate centroid offset vectors $(\Delta x, \Delta y)$ for each key based on where your finger inflects compared to nominal key coordinates.
3. **Local Fine-Tuning Pipeline**:
   - A lightweight background script (`aurora-calibrate-model`) that fine-tunes the FUTO CTC model weights or acoustic loss using the locally collected user trajectory dataset.

### 5. Implementation Checklist
- [ ] Implement `TrajectoryLogger` recording confirmed swipes and corrections to `feedback.jsonl`.
- [ ] Add touch heatmap calibration calculation in `aurora_keyboard/swipe_manager.py`.
- [ ] Build a user toggle in UI: `⚙ Enable Adaptive Learning (Local & Private)`.
- [ ] Create automated unit tests for trajectory logging and n-gram frequency updates.

---

## 📅 Suggested Implementation Roadmap

| Milestone | Focus | Deliverable |
|---|---|---|
| **Phase A** | **Module 4: Feedback Loop** | Trajectory logger + dynamic vocabulary boosting (Immediate high value). |
| **Phase B** | **Module 2: Layer-Shell** | Compositor abstraction layer for Hyprland/Sway/GNOME. |
| **Phase C** | **Module 1: Lock Screen** | Overlay layer integration for SDDM and `kscreenlocker`. |
| **Phase D** | **Module 3: Rust Core** | PyO3 compiled extensions for `/dev/uinput` and feature extraction. |
