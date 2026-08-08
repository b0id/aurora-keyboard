import sys
import os
import subprocess
import argparse
from PyQt6.QtWidgets import QApplication
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from .keyboard_window import AuroraKeyboardWindow
from .swipe.futo_client import FutoSwipeClient

# Fixed name for the single-instance IPC channel. A second launch (e.g. from
# the taskbar launcher or autostart re-firing) connects to this instead of
# starting a second process that would fight the first one for /dev/uinput
# and draw a duplicate, overlapping window.
IPC_SERVER_NAME = "aurora-touch-keyboard-singleton"


def _ensure_futo_daemon():
    """Ensure FUTO neural daemon is running in background if socket is not reachable."""
    client = FutoSwipeClient()
    if not client.is_available():
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        launcher = os.path.join(root_dir, "aurora-futo-daemon")
        if os.path.exists(launcher):
            try:
                subprocess.Popen(
                    ["bash", launcher],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            except Exception as e:
                print(f"[Main] Notice: Could not auto-launch neural daemon: {e}", file=sys.stderr)


def _notify_running_instance() -> bool:
    """If another instance is already running, ask it to show itself.

    Returns True if an existing instance was reached (caller should exit).
    """
    socket = QLocalSocket()
    socket.connectToServer(IPC_SERVER_NAME)
    if socket.waitForConnected(200):
        socket.write(b"show")
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Aurora Touch Keyboard for Plasma 6 Wayland Tablets")
    parser.add_argument("--theme", choices=["Aurora Glass", "Cyber Neon", "OLED Dark", "Light Velvet"], default="Aurora Glass", help="Theme style")
    parser.add_argument("--layout", choices=["QWERTY", "DEV/TERM", "NUMPAD"], default="QWERTY", help="Initial keyboard layout")
    parser.add_argument("--badge-only", action="store_true", help="Start collapsed as a floating badge")

    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Aurora Touch Keyboard")
    app.setDesktopFileName("aurora-keyboard")

    if _notify_running_instance():
        sys.exit(0)

    # Ensure FUTO neural swipe daemon is running
    _ensure_futo_daemon()

    # Stale socket file left behind by a crashed previous instance.
    QLocalServer.removeServer(IPC_SERVER_NAME)
    ipc_server = QLocalServer()
    ipc_server.listen(IPC_SERVER_NAME)

    window = AuroraKeyboardWindow()
    if args.theme:
        window.apply_theme(args.theme)
    if args.layout:
        window.change_layout(args.layout)

    def _on_new_connection():
        conn = ipc_server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda: (conn.readAll(), window.bring_to_front()))
        conn.disconnected.connect(conn.deleteLater)

    ipc_server.newConnection.connect(_on_new_connection)

    if args.badge_only:
        window.hide_to_badge()
    else:
        window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
