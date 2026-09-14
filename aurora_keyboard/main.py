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


DAEMON_UNIT = "aurora-futo-daemon.service"


def _systemd_unit_installed() -> bool:
    try:
        return subprocess.run(
            ["systemctl", "--user", "cat", DAEMON_UNIT],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        ).returncode == 0
    except Exception:
        return False


def _ensure_futo_daemon():
    """Ensure the FUTO neural daemon is running if the socket is not reachable.

    Where the Milestone 4a systemd --user unit is installed, defer to it:
    `systemctl start` is idempotent, so a daemon that is merely still loading
    its models is left alone. Spawning the launcher directly instead used to
    lose a login race - the unit takes ~20s to load PyTorch, is_available()
    said no, and this spawned a *second* daemon that then took the socket
    over, leaving the supervised one stranded and the unsupervised one
    serving swipes (i.e. no auto-restart, the exact failure 4a fixed).
    """
    client = FutoSwipeClient()
    if client.is_available():
        return

    if _systemd_unit_installed():
        try:
            subprocess.run(
                ["systemctl", "--user", "start", DAEMON_UNIT],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
            )
            return
        except Exception as e:
            print(f"[Main] Notice: systemd start failed, falling back: {e}", file=sys.stderr)

    # No systemd unit (portable/non-systemd install) - launch directly.
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aurora Touch Keyboard for Plasma 6 Wayland Tablets")
    # NOTE: these default to None on purpose. A non-None argparse default is
    # always truthy, so the `if args.theme` / `if args.layout` guards below
    # would unconditionally overwrite the theme and layout restored from
    # ~/.config/aurora-keyboard/config.json - the keyboard always came back
    # up as Aurora Glass / QWERTY no matter what the user had chosen.
    parser.add_argument("--theme", choices=["Aurora Glass", "Cyber Neon", "OLED Dark", "Light Velvet"], default=None, help="Theme style (default: last used)")
    parser.add_argument("--layout", choices=["QWERTY", "DEV", "DEV/TERM", "NUM", "NUMPAD"], default=None, help="Initial keyboard layout (default: last used)")
    parser.add_argument("--badge-only", action="store_true", help="Start collapsed as a floating badge")
    return parser


def main():
    args = build_parser().parse_args()

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
        window.show_keyboard()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
