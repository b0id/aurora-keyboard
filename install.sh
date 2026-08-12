#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "=========================================="
echo " Installing Aurora Touch Keyboard for Plasma 6 "
echo "=========================================="

mkdir -p "$BIN_DIR" "$DESKTOP_DIR" "$AUTOSTART_DIR" "$SYSTEMD_USER_DIR"

# Symlink executables to ~/.local/bin
ln -sf "$APP_DIR/aurora-keyboard" "$BIN_DIR/aurora-keyboard"
chmod +x "$APP_DIR/aurora-keyboard"

ln -sf "$APP_DIR/aurora-futo-daemon" "$BIN_DIR/aurora-futo-daemon"
chmod +x "$APP_DIR/aurora-futo-daemon"

# Create .desktop launcher
CAT_DESKTOP="$DESKTOP_DIR/aurora-keyboard.desktop"
cat << EOF > "$CAT_DESKTOP"
[Desktop Entry]
Name=Aurora Touch Keyboard
GenericName=On-Screen Keyboard
Comment=Modern Glassmorphic On-Screen Touch Keyboard for Aurora / Plasma 6 Tablets
Exec=$BIN_DIR/aurora-keyboard
Icon=input-keyboard
Terminal=false
Type=Application
Categories=Utility;Accessibility;Qt;KDE;
Keywords=keyboard;osk;virtual;touch;tablet;swipe;
EOF

chmod +x "$CAT_DESKTOP"

# Create Autostart entry
CAT_AUTOSTART="$AUTOSTART_DIR/aurora-keyboard.desktop"
cat << EOF > "$CAT_AUTOSTART"
[Desktop Entry]
Name=Aurora Touch Keyboard
Exec=$BIN_DIR/aurora-keyboard --badge-only
Icon=input-keyboard
Terminal=false
Type=Application
X-KDE-autostart-after=panel
EOF

echo "✓ Executable linked to: $BIN_DIR/aurora-keyboard"
echo "✓ Neural Daemon linked to: $BIN_DIR/aurora-futo-daemon"
echo "✓ Desktop launcher created at: $CAT_DESKTOP"
echo "✓ Autostart entry created at: $CAT_AUTOSTART (starts minimized as floating touch badge)"

# systemd --user unit for the neural swipe daemon: auto-starts at login and
# auto-restarts on crash (VOCAB_CONTEXT_SPEC.md Milestone 4). Without this,
# a daemon crash silently degrades every swipe to the 1,175-word geometric
# fallback until someone notices and restarts it by hand - not hypothetical,
# this happened for real during development. Skipped gracefully if the
# system has no systemd (e.g. some minimal/non-systemd distros) - the app's
# own on-launch fallback (main.py's _ensure_futo_daemon) still covers that
# case, just without crash recovery mid-session.
if command -v systemctl &>/dev/null; then
    SERVICE_FILE="$SYSTEMD_USER_DIR/aurora-futo-daemon.service"
    cat << EOF > "$SERVICE_FILE"
[Unit]
Description=Aurora Touch Keyboard - FUTO Neural Swipe Daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=$BIN_DIR/aurora-futo-daemon
Restart=on-failure
RestartSec=3
StartLimitIntervalSec=60
StartLimitBurst=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now aurora-futo-daemon.service
    echo "✓ systemd --user service installed and started: aurora-futo-daemon.service"
    echo "  (auto-starts at login, auto-restarts on crash - check with: systemctl --user status aurora-futo-daemon)"
else
    echo "⚠ systemd not found - skipping daemon auto-start/crash-recovery setup."
    echo "  Start the background neural daemon manually by running: aurora-futo-daemon &"
fi

echo ""
echo "Installation complete! Start the keyboard by running: aurora-keyboard"
