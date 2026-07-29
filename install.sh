#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

echo "=========================================="
echo " Installing Aurora Touch Keyboard for Plasma 6 "
echo "=========================================="

mkdir -p "$BIN_DIR" "$DESKTOP_DIR" "$AUTOSTART_DIR"

# Symlink executable to ~/.local/bin
ln -sf "$APP_DIR/aurora-keyboard" "$BIN_DIR/aurora-keyboard"
chmod +x "$APP_DIR/aurora-keyboard"

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
Keywords=keyboard;osk;virtual;touch;tablet;
EOF

chmod +x "$CAT_DESKTOP"

# Optionally create Autostart entry
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
echo "✓ Desktop launcher created at: $CAT_DESKTOP"
echo "✓ Autostart entry created at: $CAT_AUTOSTART (starts minimized as floating touch badge)"
echo ""
echo "Installation complete! You can start it now by running: aurora-keyboard"
