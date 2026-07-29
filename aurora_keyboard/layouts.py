"""
Layout definitions for Aurora Touch Keyboard featuring full modifier key support (Ctrl, Alt, Super/Meta, Shift, AltGr, Caps Lock).
"""

QWERTY_ROWS = [
    # Row 0: Numbers & Symbols
    [
        {"label": "1", "shift_label": "!", "type": "char"},
        {"label": "2", "shift_label": "@", "type": "char"},
        {"label": "3", "shift_label": "#", "type": "char"},
        {"label": "4", "shift_label": "$", "type": "char"},
        {"label": "5", "shift_label": "%", "type": "char"},
        {"label": "6", "shift_label": "^", "type": "char"},
        {"label": "7", "shift_label": "&", "type": "char"},
        {"label": "8", "shift_label": "*", "type": "char"},
        {"label": "9", "shift_label": "(", "type": "char"},
        {"label": "0", "shift_label": ")", "type": "char"},
        {"label": "-", "shift_label": "_", "type": "char"},
        {"label": "=", "shift_label": "+", "type": "char"},
        {"label": "⌫", "type": "key", "keycode": "BACKSPACE", "span": 1.5, "class": "action-btn"}
    ],
    # Row 1: QWERTY
    [
        {"label": "Tab ↹", "type": "key", "keycode": "TAB", "span": 1.2, "class": "modifier-btn"},
        {"label": "q", "shift_label": "Q", "type": "char"},
        {"label": "w", "shift_label": "W", "type": "char"},
        {"label": "e", "shift_label": "E", "type": "char"},
        {"label": "r", "shift_label": "R", "type": "char"},
        {"label": "t", "shift_label": "T", "type": "char"},
        {"label": "y", "shift_label": "Y", "type": "char"},
        {"label": "u", "shift_label": "U", "type": "char"},
        {"label": "i", "shift_label": "I", "type": "char"},
        {"label": "o", "shift_label": "O", "type": "char"},
        {"label": "p", "shift_label": "P", "type": "char"},
        {"label": "[", "shift_label": "{", "type": "char"},
        {"label": "]", "shift_label": "}", "type": "char"},
        {"label": "\\", "shift_label": "|", "type": "char"}
    ],
    # Row 2: ASDF
    [
        {"label": "Caps", "type": "caps", "span": 1.3, "class": "modifier-btn"},
        {"label": "a", "shift_label": "A", "type": "char"},
        {"label": "s", "shift_label": "S", "type": "char"},
        {"label": "d", "shift_label": "D", "type": "char"},
        {"label": "f", "shift_label": "F", "type": "char"},
        {"label": "g", "shift_label": "G", "type": "char"},
        {"label": "h", "shift_label": "H", "type": "char"},
        {"label": "j", "shift_label": "J", "type": "char"},
        {"label": "k", "shift_label": "K", "type": "char"},
        {"label": "l", "shift_label": "L", "type": "char"},
        {"label": ";", "shift_label": ":", "type": "char"},
        {"label": "'", "shift_label": '"', "type": "char"},
        {"label": "Enter ↵", "type": "key", "keycode": "ENTER", "span": 1.7, "class": "primary-btn"}
    ],
    # Row 3: ZXCV
    [
        {"label": "Shift ⇧", "type": "shift", "span": 1.7, "class": "modifier-btn"},
        {"label": "z", "shift_label": "Z", "type": "char"},
        {"label": "x", "shift_label": "X", "type": "char"},
        {"label": "c", "shift_label": "C", "type": "char"},
        {"label": "v", "shift_label": "V", "type": "char"},
        {"label": "b", "shift_label": "B", "type": "char"},
        {"label": "n", "shift_label": "N", "type": "char"},
        {"label": "m", "shift_label": "M", "type": "char"},
        {"label": ",", "shift_label": "<", "type": "char"},
        {"label": ".", "shift_label": ">", "type": "char"},
        {"label": "/", "shift_label": "?", "type": "char"},
        {"label": "Shift ⇧", "type": "shift", "span": 1.7, "class": "modifier-btn"}
    ],
    # Row 4: FULL MODIFIERS ROW (Ctrl, Super/Meta, Alt, Space, AltGr, Arrows)
    [
        {"label": "Ctrl", "type": "toggle_modifier", "mod": "LEFTCTRL", "span": 1.2, "class": "modifier-btn"},
        {"label": "Super ❖", "type": "toggle_modifier", "mod": "LEFTMETA", "span": 1.2, "class": "modifier-btn"},
        {"label": "Alt", "type": "toggle_modifier", "mod": "LEFTALT", "span": 1.2, "class": "modifier-btn"},
        {"label": "Space", "type": "key", "keycode": "SPACE", "span": 4.2, "class": "space-btn"},
        {"label": "AltGr", "type": "toggle_modifier", "mod": "RIGHTALT", "span": 1.1, "class": "modifier-btn"},
        {"label": "◄", "type": "key", "keycode": "LEFT", "span": 0.9, "class": "nav-btn"},
        {"label": "▲", "type": "key", "keycode": "UP", "span": 0.9, "class": "nav-btn"},
        {"label": "▼", "type": "key", "keycode": "DOWN", "span": 0.9, "class": "nav-btn"},
        {"label": "►", "type": "key", "keycode": "RIGHT", "span": 0.9, "class": "nav-btn"}
    ]
]

DEV_ROWS = [
    # Row 0: F-Keys & Esc
    [
        {"label": "Esc", "type": "key", "keycode": "ESC", "class": "action-btn"},
        {"label": "F1", "type": "key", "keycode": "F1"},
        {"label": "F2", "type": "key", "keycode": "F2"},
        {"label": "F3", "type": "key", "keycode": "F3"},
        {"label": "F4", "type": "key", "keycode": "F4"},
        {"label": "F5", "type": "key", "keycode": "F5"},
        {"label": "F6", "type": "key", "keycode": "F6"},
        {"label": "F7", "type": "key", "keycode": "F7"},
        {"label": "F8", "type": "key", "keycode": "F8"},
        {"label": "F9", "type": "key", "keycode": "F9"},
        {"label": "F10", "type": "key", "keycode": "F10"},
        {"label": "F11", "type": "key", "keycode": "F11"},
        {"label": "F12", "type": "key", "keycode": "F12"},
        {"label": "Del", "type": "key", "keycode": "DELETE", "class": "action-btn"}
    ],
    # Row 1: Terminal Symbols
    [
        {"label": "`", "type": "char"},
        {"label": "~", "type": "char"},
        {"label": "!", "type": "char"},
        {"label": "@", "type": "char"},
        {"label": "#", "type": "char"},
        {"label": "$", "type": "char"},
        {"label": "%", "type": "char"},
        {"label": "^", "type": "char"},
        {"label": "&", "type": "char"},
        {"label": "*", "type": "char"},
        {"label": "(", "type": "char"},
        {"label": ")", "type": "char"},
        {"label": "_", "type": "char"},
        {"label": "+", "type": "char"}
    ],
    # Row 2: Code Brackets & Operators
    [
        {"label": "Tab ↹", "type": "key", "keycode": "TAB", "span": 1.2, "class": "modifier-btn"},
        {"label": "|", "type": "char"},
        {"label": "/", "type": "char"},
        {"label": "\\", "type": "char"},
        {"label": "{", "type": "char"},
        {"label": "}", "type": "char"},
        {"label": "[", "type": "char"},
        {"label": "]", "type": "char"},
        {"label": "<", "type": "char"},
        {"label": ">", "type": "char"},
        {"label": "=", "type": "char"},
        {"label": "\"", "type": "char"},
        {"label": "'", "type": "char"},
        {"label": "Enter ↵", "type": "key", "keycode": "ENTER", "span": 1.5, "class": "primary-btn"}
    ],
    # Row 3: Navigation & Modifiers
    [
        {"label": "Ctrl", "type": "toggle_modifier", "mod": "LEFTCTRL", "span": 1.1, "class": "modifier-btn"},
        {"label": "Super ❖", "type": "toggle_modifier", "mod": "LEFTMETA", "span": 1.1, "class": "modifier-btn"},
        {"label": "Alt", "type": "toggle_modifier", "mod": "LEFTALT", "span": 1.1, "class": "modifier-btn"},
        {"label": "Shift ⇧", "type": "shift", "span": 1.1, "class": "modifier-btn"},
        {"label": "Home", "type": "key", "keycode": "HOME"},
        {"label": "End", "type": "key", "keycode": "END"},
        {"label": "PgUp", "type": "key", "keycode": "PAGEUP"},
        {"label": "PgDn", "type": "key", "keycode": "PAGEDOWN"},
        {"label": "Insert", "type": "key", "keycode": "INSERT"},
        {"label": "◄", "type": "key", "keycode": "LEFT", "class": "nav-btn"},
        {"label": "▲", "type": "key", "keycode": "UP", "class": "nav-btn"},
        {"label": "▼", "type": "key", "keycode": "DOWN", "class": "nav-btn"},
        {"label": "►", "type": "key", "keycode": "RIGHT", "class": "nav-btn"}
    ]
]

NUMPAD_ROWS = [
    [
        {"label": "7", "type": "char"},
        {"label": "8", "type": "char"},
        {"label": "9", "type": "char"},
        {"label": "/", "type": "char"},
        {"label": "⌫", "type": "key", "keycode": "BACKSPACE", "class": "action-btn"}
    ],
    [
        {"label": "4", "type": "char"},
        {"label": "5", "type": "char"},
        {"label": "6", "type": "char"},
        {"label": "*", "type": "char"},
        {"label": "Tab", "type": "key", "keycode": "TAB", "class": "modifier-btn"}
    ],
    [
        {"label": "1", "type": "char"},
        {"label": "2", "type": "char"},
        {"label": "3", "type": "char"},
        {"label": "-", "type": "char"},
        {"label": "Esc", "type": "key", "keycode": "ESC", "class": "action-btn"}
    ],
    [
        {"label": "0", "type": "char", "span": 2.0},
        {"label": ".", "type": "char"},
        {"label": "+", "type": "char"},
        {"label": "=", "type": "char"}
    ],
    [
        {"label": "Space", "type": "key", "keycode": "SPACE", "span": 3.0, "class": "space-btn"},
        {"label": "Enter ↵", "type": "key", "keycode": "ENTER", "span": 2.0, "class": "primary-btn"}
    ]
]
