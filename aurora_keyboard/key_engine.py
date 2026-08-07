"""
Direct Kernel UInput Key Engine for Aurora Touch Keyboard using evdev.
"""

import time
import sys
import evdev
from evdev import UInput, ecodes as e

# Character to keycode & shift required mapping
CHAR_MAP = {
    'a': (e.KEY_A, False), 'b': (e.KEY_B, False), 'c': (e.KEY_C, False), 'd': (e.KEY_D, False),
    'e': (e.KEY_E, False), 'f': (e.KEY_F, False), 'g': (e.KEY_G, False), 'h': (e.KEY_H, False),
    'i': (e.KEY_I, False), 'j': (e.KEY_J, False), 'k': (e.KEY_K, False), 'l': (e.KEY_L, False),
    'm': (e.KEY_M, False), 'n': (e.KEY_N, False), 'o': (e.KEY_O, False), 'p': (e.KEY_P, False),
    'q': (e.KEY_Q, False), 'r': (e.KEY_R, False), 's': (e.KEY_S, False), 't': (e.KEY_T, False),
    'u': (e.KEY_U, False), 'v': (e.KEY_V, False), 'w': (e.KEY_W, False), 'x': (e.KEY_X, False),
    'y': (e.KEY_Y, False), 'z': (e.KEY_Z, False),

    'A': (e.KEY_A, True), 'B': (e.KEY_B, True), 'C': (e.KEY_C, True), 'D': (e.KEY_D, True),
    'E': (e.KEY_E, True), 'F': (e.KEY_F, True), 'G': (e.KEY_G, True), 'H': (e.KEY_H, True),
    'I': (e.KEY_I, True), 'J': (e.KEY_J, True), 'K': (e.KEY_K, True), 'L': (e.KEY_L, True),
    'M': (e.KEY_M, True), 'N': (e.KEY_N, True), 'O': (e.KEY_O, True), 'P': (e.KEY_P, True),
    'Q': (e.KEY_Q, True), 'R': (e.KEY_R, True), 'S': (e.KEY_S, True), 'T': (e.KEY_T, True),
    'U': (e.KEY_U, True), 'V': (e.KEY_V, True), 'W': (e.KEY_W, True), 'X': (e.KEY_X, True),
    'Y': (e.KEY_Y, True), 'Z': (e.KEY_Z, True),

    '1': (e.KEY_1, False), '2': (e.KEY_2, False), '3': (e.KEY_3, False), '4': (e.KEY_4, False),
    '5': (e.KEY_5, False), '6': (e.KEY_6, False), '7': (e.KEY_7, False), '8': (e.KEY_8, False),
    '9': (e.KEY_9, False), '0': (e.KEY_0, False),

    '!': (e.KEY_1, True), '@': (e.KEY_2, True), '#': (e.KEY_3, True), '$': (e.KEY_4, True),
    '%': (e.KEY_5, True), '^': (e.KEY_6, True), '&': (e.KEY_7, True), '*': (e.KEY_8, True),
    '(': (e.KEY_9, True), ')': (e.KEY_0, True),

    '-': (e.KEY_MINUS, False), '_': (e.KEY_MINUS, True),
    '=': (e.KEY_EQUAL, False), '+': (e.KEY_EQUAL, True),
    '[': (e.KEY_LEFTBRACE, False), '{': (e.KEY_LEFTBRACE, True),
    ']': (e.KEY_RIGHTBRACE, False), '}': (e.KEY_RIGHTBRACE, True),
    '\\': (e.KEY_BACKSLASH, False), '|': (e.KEY_BACKSLASH, True),
    ';': (e.KEY_SEMICOLON, False), ':': (e.KEY_SEMICOLON, True),
    '\'': (e.KEY_APOSTROPHE, False), '"': (e.KEY_APOSTROPHE, True),
    ',': (e.KEY_COMMA, False), '<': (e.KEY_COMMA, True),
    '.': (e.KEY_DOT, False), '>': (e.KEY_DOT, True),
    '/': (e.KEY_SLASH, False), '?': (e.KEY_SLASH, True),
    '`': (e.KEY_GRAVE, False), '~': (e.KEY_GRAVE, True),
    ' ': (e.KEY_SPACE, False)
}


class KeyEngine:
    """Direct Kernel UInput Input Engine."""

    def __init__(self):
        self.ui = None
        self._init_uinput()

    def _init_uinput(self):
        try:
            # Enable key events (exclude sentinel codes like KEY_CNT that exceed KEY_MAX)
            events = {e.EV_KEY: [code for code in e.KEY.keys() if code <= e.KEY_MAX]}
            self.ui = UInput(events, name='Aurora-Virtual-Touch-Keyboard')
            time.sleep(0.1) # brief pause to let kernel register input device
        except Exception as err:
            print(f"[KeyEngine Error] Could not initialize uinput: {err}", file=sys.stderr)

    def get_keycode(self, key_name: str) -> int:
        key_upper = key_name.upper()
        if not key_upper.startswith('KEY_'):
            key_upper = 'KEY_' + key_upper
        return getattr(e, key_upper, None)

    def _emit_key(self, code: int, shift: bool = False):
        if not self.ui or not code:
            return
        if shift:
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
            self.ui.syn()
            time.sleep(0.02)

        self.ui.write(e.EV_KEY, code, 1)
        self.ui.syn()
        time.sleep(0.02)
        self.ui.write(e.EV_KEY, code, 0)
        self.ui.syn()

        if shift:
            time.sleep(0.02)
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
            self.ui.syn()

    def send_keycode(self, code: int):
        self._emit_key(code, False)

    def type_text(self, text: str):
        if not self.ui or not text:
            return
        for char in text:
            if char in CHAR_MAP:
                code, shift = CHAR_MAP[char]
                self._emit_key(code, shift)
            else:
                # Fallback for unmapped unicode
                code = self.get_keycode(char)
                if code:
                    self._emit_key(code, False)

    def send_combo(self, modifiers: list, key_target: str):
        if not self.ui:
            return

        mod_codes = []
        has_shift_in_mods = False
        for m in modifiers:
            code = self.get_keycode(m) if isinstance(m, str) else m
            if code:
                mod_codes.append(code)
                if code in (e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT):
                    has_shift_in_mods = True

        target_code = None
        target_shift = False
        if isinstance(key_target, str) and len(key_target) == 1 and key_target in CHAR_MAP:
            target_code, target_shift = CHAR_MAP[key_target]
        elif isinstance(key_target, str):
            target_code = self.get_keycode(key_target)
        else:
            target_code = key_target

        if has_shift_in_mods:
            target_shift = False

        # Press modifiers down
        for mc in mod_codes:
            self.ui.write(e.EV_KEY, mc, 1)
        if target_shift:
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
        self.ui.syn()

        # Press target key
        if target_code:
            self.ui.write(e.EV_KEY, target_code, 1)
            self.ui.syn()
            time.sleep(0.01)
            self.ui.write(e.EV_KEY, target_code, 0)
            self.ui.syn()

        # Release modifiers
        if target_shift:
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
        for mc in reversed(mod_codes):
            self.ui.write(e.EV_KEY, mc, 0)
        self.ui.syn()
