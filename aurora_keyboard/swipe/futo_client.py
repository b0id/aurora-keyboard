"""
FUTO Swipe IPC Client.
Connects from the host application (Python 3.14 / Wayland / Qt6) to the
FUTO ExecuTorch daemon running over /tmp/futo_swipe.sock.
"""

import json
import socket
import sys

SOCKET_PATH = "/tmp/futo_swipe.sock"


class FutoSwipeClient:
    """Client for querying FUTO neural swipe predictions over Unix domain socket."""

    def __init__(self, socket_path: str = SOCKET_PATH, timeout: float = 0.5):
        self.socket_path = socket_path
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.05)
                s.connect(self.socket_path)
                return True
        except Exception:
            return False

    def predict(self, raw_trail: list, key_positions: dict, top_n: int = 5, context: list[str] | None = None) -> list[str]:
        """Send swipe trajectory and key positions to the daemon and receive candidates.

        context: optional preceding words (VOCAB_CONTEXT_SPEC.md sec4/sec6.1),
        used by the daemon's context LM to rerank candidates. Omitted or
        empty behaves exactly as before - the daemon treats a missing
        context field the same as an empty one.
        """
        if not raw_trail or len(raw_trail) < 2:
            return []

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(self.socket_path)

                req = {
                    "raw_trail": raw_trail,
                    "key_positions": key_positions,
                    "top_n": top_n,
                    "context": context or [],
                }
                s.sendall(json.dumps(req).encode("utf-8") + b"\n")

                data = b""
                while True:
                    chunk = s.recv(16384)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break

                if not data:
                    return []

                resp = json.loads(data.decode("utf-8"))
                return resp.get("candidates", [])
        except Exception as err:
            # Fall back silently if daemon isn't running or timed out
            return []
