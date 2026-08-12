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
    from .context_lm import load_context_lm
except ImportError:
    from lexicon import get_lexicon
    from beam_search import ScoringParams, decode as beam_decode
    from context_lm import load_context_lm

# Published encoder-only constants (scoring.json, VOCAB_CONTEXT_SPEC.md sec6.1)
_SCORING = ScoringParams()
# Published encoder+contextlm alpha weight (scoring.json) - only applied
# when a request actually supplies context and the context LM loaded.
_CONTEXT_ALPHA = 0.6459
# How many beam-search candidates to rerank with the context LM. Wider
# than top_n so a context-boosted word ranked just outside top_n can still
# surface, without rescoring the entire vocabulary.
_RERANK_POOL = 20


def _canonical_key_positions():
    """Reference layout used only to validate "is every letter in this
    word a normal a-z key" - not tied to any live keyboard's real pixel
    geometry, which is why the same reference layout works for every
    decode request regardless of the caller's real key positions."""
    try:
        from .decoder import standard_qwerty_key_positions
    except ImportError:
        from decoder import standard_qwerty_key_positions
    return standard_qwerty_key_positions()


# Try loading ExecuTorch models
_ENCODER = None
_LEXICON = None
_CONTEXT_LM = None

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

# Context LM (Milestone 3b, VOCAB_CONTEXT_SPEC.md sec6.1 alpha term) - a
# separate optional model. Failure here degrades gracefully to no context
# scoring (same pattern as the encoder above), never breaks core decoding.
try:
    pte_ctx = hf_hub_download("futo-org/futo-swipe", "hungry_jellyfish/context_lm.pte")
    ctx_vocab_path = hf_hub_download("futo-org/futo-swipe", "hungry_jellyfish/vocab.txt")
    with open(ctx_vocab_path, "r", encoding="utf-8") as f:
        _ctx_vocab_words = [line.rstrip("\n").rstrip("\r") for line in f]
    _CONTEXT_LM = load_context_lm(lambda: Runtime.get().load_program(pte_ctx), _ctx_vocab_words)
    print(f"[FUTO Daemon] Successfully loaded hungry_jellyfish context LM ({_CONTEXT_LM.num_exact} exact embeddings).", flush=True)
except Exception as err:
    print(f"[FUTO Daemon Warning] Context LM could not be loaded: {err}", file=sys.stderr, flush=True)


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


def _rerank_with_context(results, context, top_n):
    """Blend the context LM's alpha-weighted log-likelihood into a beam
    search candidate pool (VOCAB_CONTEXT_SPEC.md sec6.1's alpha term),
    then re-truncate to top_n. No-op if the context LM isn't loaded or no
    context was supplied - same candidates, same order, just not reranked."""
    if _CONTEXT_LM is None or not context or not results:
        return [word for word, _ in results[:top_n]]

    words = [word for word, _ in results]
    lm_scores = _CONTEXT_LM.score(context, words)
    blended = [
        (word, beam_score + _CONTEXT_ALPHA * lm_score)
        for (word, beam_score), lm_score in zip(results, lm_scores)
    ]
    blended.sort(key=lambda pair: -pair[1])
    return [word for word, _ in blended[:top_n]]


def decode_swipe(raw_trail, key_positions, top_n=5, context=None):
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

            # Re-fetched per request rather than reused from the startup-time
            # _LEXICON snapshot: get_lexicon() transparently rebuilds when
            # custom_words.txt changes (VOCAB_CONTEXT_SPEC.md sec6 hot-reload),
            # and costs one stat() syscall when nothing changed.
            lexicon = get_lexicon(_canonical_key_positions())
            if lexicon is None:
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
            pool_size = _RERANK_POOL if (context and _CONTEXT_LM is not None) else top_n
            results = beam_decode(log_probs, lexicon.trie, _SCORING, beam_width=100, top_k=pool_size)
            return _rerank_with_context(results, context, top_n)
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
        context = req.get("context") or []  # optional (VOCAB_CONTEXT_SPEC.md sec3)

        t0 = time.time()
        candidates = decode_swipe(raw_trail, key_positions, top_n, context)
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
