"""
QSS CSS Themes for Aurora Touch Keyboard.
"""

AURORA_GLASS = """
QWidget#keyboard_root {
    background: rgba(18, 24, 38, 0.88);
    border-top: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 20px 20px 0px 0px;
}

QFrame#action_bar {
    background: rgba(255, 255, 255, 0.05);
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 14px;
    margin-bottom: 4px;
}

QFrame#candidate_bar {
    background: rgba(15, 23, 42, 0.65);
    border: 1px solid rgba(56, 189, 248, 0.25);
    border-radius: 12px;
    margin-bottom: 6px;
    padding: 2px 6px;
}

QPushButton.candidate-chip {
    background: rgba(255, 255, 255, 0.08);
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 16px;
    font-size: 14px;
    font-weight: 600;
    padding: 4px 14px;
    min-height: 28px;
}
QPushButton.candidate-chip:hover {
    background: rgba(56, 189, 248, 0.2);
    border-color: rgba(56, 189, 248, 0.5);
    color: #38bdf8;
}
QPushButton.candidate-chip-top {
    background: linear-gradient(135deg, rgba(37, 99, 235, 0.4), rgba(56, 189, 248, 0.4));
    color: #ffffff;
    border: 1px solid #38bdf8;
    font-weight: bold;
}
QPushButton.candidate-chip-top:hover {
    background: linear-gradient(135deg, #2563eb, #38bdf8);
}

QPushButton {
    background: rgba(255, 255, 255, 0.08);
    color: #f1f5f9;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    font-size: 17px;
    font-weight: 500;
    font-family: 'Segoe UI', 'Outfit', 'Inter', 'Noto Sans', sans-serif;
    min-height: 48px;
}

QPushButton:hover {
    background: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(56, 189, 248, 0.4);
}

QPushButton:pressed {
    background: rgba(56, 189, 248, 0.35);
    border: 1px solid rgba(56, 189, 248, 0.8);
    color: #ffffff;
}

/* Special Button Classes */
QPushButton.primary-btn {
    background: linear-gradient(135deg, #2563eb, #3b82f6);
    border: 1px solid #60a5fa;
    color: #ffffff;
    font-weight: bold;
}
QPushButton.primary-btn:hover {
    background: #3b82f6;
}

QPushButton.action-btn {
    background: rgba(239, 68, 68, 0.18);
    border: 1px solid rgba(239, 68, 68, 0.35);
    color: #fca5a5;
}
QPushButton.action-btn:hover {
    background: rgba(239, 68, 68, 0.32);
}

QPushButton.modifier-btn {
    background: rgba(139, 92, 246, 0.18);
    border: 1px solid rgba(139, 92, 246, 0.35);
    color: #c4b5fd;
}
QPushButton.modifier-btn:checked {
    background: rgba(139, 92, 246, 0.6);
    border: 1px solid #a78bfa;
    color: #ffffff;
}

QPushButton.space-btn {
    background: rgba(255, 255, 255, 0.06);
}

QPushButton.nav-btn {
    background: rgba(16, 185, 129, 0.18);
    border: 1px solid rgba(16, 185, 129, 0.35);
    color: #6ee7b7;
}
QPushButton.nav-btn:hover {
    background: rgba(16, 185, 129, 0.32);
}

QComboBox {
    background: rgba(255, 255, 255, 0.1);
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    padding: 4px 12px;
    font-weight: bold;
}

/* Floating Badge */
QWidget#floating_badge {
    background: rgba(18, 24, 38, 0.95);
    border: 3px solid #475569;
    border-radius: 80px;
}
QPushButton#badge_btn {
    background: transparent;
    border: none;
    color: #64748b;
    font-size: 80px;
    border-radius: 77px;
    min-height: 154px;
    max-height: 154px;
}
QPushButton#badge_btn:hover {
    background: rgba(71, 85, 105, 0.25);
}
"""

CYBER_NEON = """
QWidget#keyboard_root {
    background: rgba(10, 10, 18, 0.94);
    border-top: 2px solid #f43f5e;
}

QFrame#action_bar {
    background: rgba(244, 63, 94, 0.08);
    border-bottom: 1px solid rgba(244, 63, 94, 0.25);
    border-radius: 12px;
    margin-bottom: 4px;
}

QFrame#candidate_bar {
    background: rgba(20, 10, 25, 0.8);
    border: 1px solid rgba(244, 63, 94, 0.4);
    border-radius: 12px;
    margin-bottom: 6px;
    padding: 2px 6px;
}

QPushButton.candidate-chip {
    background: rgba(244, 63, 94, 0.12);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.3);
    border-radius: 16px;
    font-size: 14px;
    font-weight: bold;
    padding: 4px 14px;
    min-height: 28px;
}
QPushButton.candidate-chip:hover {
    background: rgba(56, 189, 248, 0.25);
    border-color: #38bdf8;
    color: #ffffff;
}
QPushButton.candidate-chip-top {
    background: rgba(244, 63, 94, 0.4);
    color: #ffffff;
    border: 1px solid #f43f5e;
}
QPushButton.candidate-chip-top:hover {
    background: #f43f5e;
}

QPushButton {
    background: rgba(20, 20, 35, 0.8);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.3);
    border-radius: 8px;
    font-size: 17px;
    font-weight: bold;
    min-height: 48px;
}

QPushButton:hover {
    border: 1px solid #38bdf8;
    background: rgba(56, 189, 248, 0.2);
}

QPushButton:pressed {
    background: #f43f5e;
    color: #ffffff;
}

QPushButton.primary-btn {
    background: #f43f5e;
    color: #ffffff;
}

QPushButton.action-btn {
    color: #fb7185;
    border-color: rgba(251, 113, 133, 0.4);
}

QPushButton.modifier-btn {
    color: #c084fc;
    border-color: rgba(192, 132, 252, 0.4);
}
QPushButton.modifier-btn:checked {
    background: rgba(192, 132, 252, 0.6);
    color: #ffffff;
}

QPushButton.nav-btn {
    color: #34d399;
    border-color: rgba(52, 211, 153, 0.4);
}

/* Floating Badge */
QWidget#floating_badge {
    background: rgba(10, 10, 18, 0.95);
    border: 3px solid #f43f5e;
    border-radius: 80px;
}
QPushButton#badge_btn {
    background: transparent;
    border: none;
    color: #fb7185;
    font-size: 80px;
    border-radius: 77px;
    min-height: 154px;
    max-height: 154px;
}
QPushButton#badge_btn:hover {
    background: rgba(244, 63, 94, 0.25);
}
"""

OLED_DARK = """
QWidget#keyboard_root {
    background: #000000;
    border-top: 1px solid #222222;
}

QFrame#action_bar {
    background: #0a0a0a;
    border-bottom: 1px solid #222222;
    border-radius: 12px;
    margin-bottom: 4px;
}

QFrame#candidate_bar {
    background: #0a0a0a;
    border: 1px solid #333333;
    border-radius: 12px;
    margin-bottom: 6px;
    padding: 2px 6px;
}

QPushButton.candidate-chip {
    background: #181818;
    color: #cccccc;
    border: 1px solid #333333;
    border-radius: 16px;
    font-size: 14px;
    font-weight: 500;
    padding: 4px 14px;
    min-height: 28px;
}
QPushButton.candidate-chip:hover {
    background: #252525;
    border-color: #666666;
    color: #ffffff;
}
QPushButton.candidate-chip-top {
    background: #2a2a2a;
    color: #ffffff;
    border: 1px solid #888888;
}

QPushButton {
    background: #121212;
    color: #ffffff;
    border: 1px solid #282828;
    border-radius: 10px;
    font-size: 17px;
    min-height: 48px;
}

QPushButton:hover {
    background: #222222;
}

QPushButton:pressed {
    background: #ffffff;
    color: #000000;
}

QPushButton.modifier-btn:checked {
    background: #333333;
    border-color: #666666;
}

/* Floating Badge */
QWidget#floating_badge {
    background: #121212;
    border: 3px solid #ffffff;
    border-radius: 80px;
}
QPushButton#badge_btn {
    background: transparent;
    border: none;
    color: #ffffff;
    font-size: 80px;
    border-radius: 77px;
    min-height: 154px;
    max-height: 154px;
}
QPushButton#badge_btn:hover {
    background: rgba(255, 255, 255, 0.2);
}
"""

LIGHT_VELVET = """
QWidget#keyboard_root {
    background: rgba(245, 247, 250, 0.94);
    border-top: 1px solid rgba(0, 0, 0, 0.1);
}

QFrame#action_bar {
    background: rgba(0, 0, 0, 0.03);
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 12px;
    margin-bottom: 4px;
}

QFrame#candidate_bar {
    background: rgba(255, 255, 255, 0.75);
    border: 1px solid rgba(2, 132, 199, 0.25);
    border-radius: 12px;
    margin-bottom: 6px;
    padding: 2px 6px;
}

QPushButton.candidate-chip {
    background: #f1f5f9;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 16px;
    font-size: 14px;
    font-weight: 500;
    padding: 4px 14px;
    min-height: 28px;
}
QPushButton.candidate-chip:hover {
    background: #e2e8f0;
    border-color: #0284c7;
    color: #0284c7;
}
QPushButton.candidate-chip-top {
    background: rgba(2, 132, 199, 0.12);
    color: #0369a1;
    border: 1px solid #0284c7;
    font-weight: bold;
}
QPushButton.candidate-chip-top:hover {
    background: #0284c7;
    color: #ffffff;
}

QPushButton {
    background: #ffffff;
    color: #1e293b;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    font-size: 17px;
    font-weight: 500;
    min-height: 48px;
}

QPushButton:hover {
    background: #f1f5f9;
}

QPushButton:pressed {
    background: #0284c7;
    color: #ffffff;
}

QPushButton.modifier-btn:checked {
    background: #0284c7;
    color: #ffffff;
}

/* Floating Badge */
QWidget#floating_badge {
    background: #ffffff;
    border: 3px solid #0369a1;
    border-radius: 80px;
}
QPushButton#badge_btn {
    background: transparent;
    border: none;
    color: #0369a1;
    font-size: 80px;
    border-radius: 77px;
    min-height: 154px;
    max-height: 154px;
}
QPushButton#badge_btn:hover {
    background: rgba(3, 105, 161, 0.15);
}
"""

THEMES = {
    "Aurora Glass": AURORA_GLASS,
    "Cyber Neon": CYBER_NEON,
    "OLED Dark": OLED_DARK,
    "Light Velvet": LIGHT_VELVET
}
