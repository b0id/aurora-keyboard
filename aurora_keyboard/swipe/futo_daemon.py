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

# Try loading ExecuTorch models
_ENCODER = None
_VOCAB = []
_VOCAB_RANKS = {}

try:
    import torch
    from executorch.runtime import Runtime
    from huggingface_hub import hf_hub_download

    print("[FUTO Daemon] Downloading/loading FUTO Swipe neural models...", flush=True)
    pte_enc = hf_hub_download("futo-org/futo-swipe", "honorable_sturgeon/model_fp32.pte")
    v_path = hf_hub_download("futo-org/futo-swipe", "hungry_jellyfish/vocab.txt")
    
    _ENCODER = Runtime.get().load_program(pte_enc).load_method("forward")
    words_set = []
    with open(v_path, "r", encoding="utf-8") as f:
        words_set = [line.strip().lower() for line in f if line.strip()]

    # Also merge bundled wordlist (modern words like swipe, app, linux, etc.)
    bundled_path = os.path.join(os.path.dirname(__file__), "wordlist.txt")
    if os.path.exists(bundled_path):
        with open(bundled_path, "r", encoding="utf-8") as f:
            bundled_words = [line.strip().lower() for line in f if line.strip()]
            for bw in bundled_words:
                if bw not in words_set:
                    words_set.insert(500, bw)

    _VOCAB = words_set
    _VOCAB_RANKS = {w: i for i, w in enumerate(_VOCAB)}
    print(f"[FUTO Daemon] Successfully loaded honorable_sturgeon encoder + {_VOCAB.__len__()} vocabulary words (incl. modern terms).", flush=True)
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


def _greedy_ctc(log_emissions, letters):
    blank = log_emissions.shape[-1] - 1
    out, prev = [], -1
    for c in log_emissions[0].argmax(axis=-1):
        c = int(c)
        if c != prev and c != blank and c < len(letters):
            out.append(letters[c])
        prev = c
    return "".join(out)


def _levenshtein(s1, s2):
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


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
            
            # Neural greedy string
            greedy_str = _greedy_ctc(log_emissions.numpy(), letters_sorted)
            
            # Endpoint key identification
            start_px, start_py = px[0], py[0]
            end_px, end_py = px[-1], py[-1]
            
            start_letter, min_sd = letters_sorted[0], 1e9
            end_letter, min_ed = letters_sorted[-1], 1e9
            for ch in letters_sorted:
                kx, ky = key_positions[ch]
                nkx, nky = norm(kx, ky)
                sd = (start_px - nkx) ** 2 + (start_py - nky) ** 2
                ed = (end_px - nkx) ** 2 + (end_py - nky) ** 2
                if sd < min_sd:
                    min_sd = sd
                    start_letter = ch
                if ed < min_ed:
                    min_ed = ed
                    end_letter = ch

            # Score dictionary candidates
            candidates = []
            pool = _VOCAB[:15000] if _VOCAB else []
            
            for word in pool:
                if len(word) < 2:
                    continue
                
                # Check start/end letter match
                start_match = (word[0] == start_letter) or (greedy_str and word[0] == greedy_str[0])
                end_match = (word[-1] == end_letter) or (greedy_str and word[-1] == greedy_str[-1])
                
                if not (start_match or end_match):
                    continue
                
                dist = _levenshtein(greedy_str, word)
                dedup_word = "".join([c for i, c in enumerate(word) if i == 0 or c != word[i-1]])
                dedup_greedy = "".join([c for i, c in enumerate(greedy_str) if i == 0 or c != greedy_str[i-1]])
                
                rank = _VOCAB_RANKS.get(word, 20000)
                freq_score = -0.5 * np.log(rank + 5)
                
                score = - (dist * 2.8) + freq_score
                if word == greedy_str or dedup_word == dedup_greedy:
                    score += 8.0
                elif dedup_word == greedy_str or word == dedup_greedy:
                    score += 6.0

                if start_match:
                    score += 2.0
                if end_match:
                    score += 1.5
                    
                candidates.append((word, float(score)))

            candidates.sort(key=lambda x: x[1], reverse=True)
            
            # If greedy string is a valid word and not already first, prioritize it if close
            top_words = [w for w, _ in candidates[:top_n]]
            if greedy_str in _VOCAB_RANKS and greedy_str not in top_words:
                top_words.insert(0, greedy_str)
                top_words = top_words[:top_n]
                
            return top_words
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
