#!/usr/bin/env python3
"""
FUTO Swipe IPC Daemon.
Runs inside the ExecuTorch container/runtime environment (Python 3.10-3.13)
and serves fast swipe word predictions over a local Unix domain socket.
"""

import os
import sys
import json
import time
import socket
import select
import threading
import numpy as np

# Socket path shared between container and host
SOCKET_PATH = "/tmp/futo_swipe.sock"

# lexicon.py is the shared vocab/index module (VOCAB_CONTEXT_SPEC.md sec5.2)
# used by both this daemon and the host-side geometric fallback. This
# script runs as a direct `python3 futo_daemon.py` (no package context -
# see aurora-futo-daemon), so relative import falls back to a plain one;
# Python auto-adds this file's own directory to sys.path for a direct run.
try:
    from .lexicon import get_lexicon
    from .beam_search import ScoringParams, decode as beam_decode
except ImportError:
    from lexicon import get_lexicon
    from beam_search import ScoringParams, decode as beam_decode

# Published encoder-only constants (scoring.json, VOCAB_CONTEXT_SPEC.md sec6.1)
_SCORING = ScoringParams()


def _canonical_key_positions():
    """Reference layout used only to validate "is every letter in this
    word a normal a-z key" - not tied to any live keyboard's real pixel
    geometry, which is why the shared lexicon only needs to be built once
    at startup rather than per decode request."""
    try:
        from .decoder import standard_qwerty_key_positions
    except ImportError:
        from decoder import standard_qwerty_key_positions
    return standard_qwerty_key_positions()


# Try loading ExecuTorch models
_ENCODER = None
_LEXICON = None

try:
    import torch
    from executorch.runtime import Runtime
    from huggingface_hub import hf_hub_download

    print("[FUTO Daemon] Downloading/loading FUTO Swipe neural models...", flush=True)
    pte_enc = hf_hub_download("futo-org/futo-swipe", "honorable_sturgeon/model_fp32.pte")
    # Ensures the file lexicon.py looks for (via its own cache glob) is
    # present; lexicon.py reads it independently so it stays host-
    # importable without a huggingface_hub dependency.
    hf_hub_download("futo-org/futo-swipe", "hungry_jellyfish/vocab.txt")

    _ENCODER = Runtime.get().load_program(pte_enc).load_method("forward")
    _LEXICON = get_lexicon(_canonical_key_positions())
    print(f"[FUTO Daemon] Successfully loaded honorable_sturgeon encoder + {len(_LEXICON.vocabulary)} vocabulary words (shared lexicon.py).", flush=True)
except Exception as err:
    print(f"[FUTO Daemon Warning] Neural models could not be loaded: {err}", file=sys.stderr, flush=True)


def _resample(px, py, pt, T=64):
    x, y, t = (np.asarray(a, dtype=np.float64) for a in (px, py, pt))
    t = t - t[0]
    if t[-1] > 1e-3:
        n60 = max(2, round(t[-1] / (1000.0 / 60.0)) + 1)
        tt = np.linspace(0.0, t[-1], n60)
        x, y = np.interp(tt, t, x), np.interp(tt, t, y)
    idx = np.linspace(0, len(x) - 1, T)
    rx = np.interp(idx, np.arange(len(x)), x)
    ry = np.interp(idx, np.arange(len(y)), y)
    return np.stack([rx, ry], axis=0).astype(np.float32)


def _compact_log_probs(log_emissions, letters):
    """[1, 32, 65] raw encoder output (64 padded key slots + blank) -> a
    [32, len(letters)+1] array (real letters in `letters` order + blank),
    matching trie.py/beam_search.py's compact character-index convention.
    Mirrors FUTO's own C++ side, which does the same layout-specific
    compaction before running beam search (trie.hpp's NUM_CLASSES)."""
    raw = log_emissions[0].numpy()  # [32, 65]
    blank_col = raw[:, raw.shape[-1] - 1:raw.shape[-1]]
    letter_cols = raw[:, :len(letters)]
    return np.concatenate([letter_cols, blank_col], axis=1)


def decode_swipe(raw_trail, key_positions, top_n=5):
    """Decode a swipe trajectory using FUTO encoder + frequency-ranked vocabulary."""
    if not raw_trail or len(raw_trail) < 2:
        return []

    letters_sorted = sorted(key_positions.keys())
    xs = [v[0] for v in key_positions.values()]
    ys = [v[1] for v in key_positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    scale_x = max_x - min_x if max_x > min_x else 1.0
    scale_y = max_y - min_y if max_y > min_y else 1.0

    def norm(x, y):
        return ((x - min_x) / scale_x, (y - min_y) / scale_y)

    # If neural encoder is loaded, use it
    if _ENCODER is not None:
        try:
            import torch
            keys_t = torch.zeros(1, 64, 2)
            mask_t = torch.zeros(1, 64, dtype=torch.bool)
            for i, ch in enumerate(letters_sorted):
                kx, ky = key_positions[ch]
                nx, ny = norm(kx, ky)
                keys_t[0, i] = torch.tensor([nx, ny])
                mask_t[0, i] = True

            px, py = [], []
            for item in raw_trail:
                nx, ny = norm(item[0], item[1])
                px.append(nx)
                py.append(ny)
            pt = [item[2] for item in raw_trail]

            features = torch.from_numpy(_resample(px, py, pt)[None])
            log_emissions, coeffs, lam = _ENCODER.execute((features, keys_t, mask_t))

            if _LEXICON is None:
                return []

            # Trie-constrained CTC beam search (VOCAB_CONTEXT_SPEC.md sec6.2),
            # ported from FUTO's own reference implementation
            # (gitlab.futo.org/keyboard/swipe-library). Replaces the previous
            # greedy-CTC-string + Levenshtein-distance approach, which
            # collapsed the encoder's graded output to one string before
            # matching - discarding exactly the information beam search
            # uses to recover long/multi-syllable words whose greedy
            # decode comes out garbled (Milestone 1 measured 35.5% top-1;
            # see VOCAB_CONTEXT_SPEC.md sec2.1 for the full comparison).
            log_probs = _compact_log_probs(log_emissions, letters_sorted)
            results = beam_decode(log_probs, _LEXICON.trie, _SCORING, beam_width=100, top_k=top_n)
            return [word for word, _ in results]
        except Exception as err:
            print(f"[FUTO Daemon] Error in neural decode: {err}", file=sys.stderr, flush=True)

    # Fallback: simple first/last matching
    return []


def handle_client(conn):
    try:
        data = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        if not data:
            return
        
        req = json.loads(data.decode("utf-8"))
        raw_trail = req.get("raw_trail", [])
        key_positions = req.get("key_positions", {})
        top_n = req.get("top_n", 5)

        t0 = time.time()
        candidates = decode_swipe(raw_trail, key_positions, top_n)
        latency_ms = (time.time() - t0) * 1000.0

        resp = {
            "candidates": candidates,
            "latency_ms": latency_ms,
            "backend": "futo-neural" if _ENCODER else "fallback"
        }
        conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
    except Exception as err:
        err_resp = {"candidates": [], "error": str(err)}
        try:
            conn.sendall(json.dumps(err_resp).encode("utf-8") + b"\n")
        except Exception:
            pass
    finally:
        conn.close()


def run_server():
    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    # Set permissions so both container and host user can read/write socket
    os.chmod(SOCKET_PATH, 0o777)
    server.listen(10)
    print(f"[FUTO Daemon] Listening on {SOCKET_PATH}", flush=True)

    try:
        while True:
            conn, _ = server.accept()
            client_thread = threading.Thread(target=handle_client, args=(conn,), daemon=True)
            client_thread.start()
    except KeyboardInterrupt:
        print("\n[FUTO Daemon] Shutting down...", flush=True)
    finally:
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


if __name__ == "__main__":
    run_server()
