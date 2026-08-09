"""
Word candidate suggestion bar for swipe-to-type input with touch chips.
"""

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt


class CandidateBar(QFrame):
    """Sleek suggestion bar displaying word candidates with instant auto-commit and responsive touch chips."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setObjectName("candidate_bar")
        self.setMinimumHeight(24)
        self.setMaximumHeight(36)

        self.auto_commit = True
        self.last_inserted_word = None

        self.bar_layout = QHBoxLayout(self)
        self.bar_layout.setContentsMargins(6, 2, 6, 2)
        self.bar_layout.setSpacing(4)
        self.chip_buttons = []

        self._placeholder_label = QLabel("✦ Swipe across keys to type")
        self._placeholder_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 11px; font-style: italic; padding: 1px 4px;")
        self.bar_layout.addWidget(self._placeholder_label)
        self.bar_layout.addStretch()

    def show_toast(self, message: str, duration_ms: int = 2000):
        """Displays a brief status toast or notification in the candidate bar."""
        while self.bar_layout.count():
            item = self.bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.chip_buttons = []

        msg_label = QLabel(message)
        msg_label.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: bold; padding: 2px 8px;")
        self.bar_layout.addWidget(msg_label)
        self.bar_layout.addStretch()

    def set_candidates(self, candidates: list, backend: str = "neural"):
        # Clear existing chips
        while self.bar_layout.count():
            item = self.bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.chip_buttons = []

        if not candidates:
            self.last_inserted_word = None
            self._placeholder_label = QLabel("✦ Swipe across keys to type")
            self._placeholder_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); font-size: 11px; font-style: italic; padding: 1px 4px;")
            self.bar_layout.addWidget(self._placeholder_label)
            self.bar_layout.addStretch()
            return

        # Engine Badge
        tag = "⚡ FUTO" if "futo" in backend else "✦ Swipe"
        badge = QLabel(tag)
        badge.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: bold; padding: 2px 4px; background: rgba(56, 189, 248, 0.15); border-radius: 4px;")
        self.bar_layout.addWidget(badge)

        top_word = candidates[0]

        # Auto-commit top candidate immediately if enabled
        if self.auto_commit and top_word:
            self.parent_window.engine.type_text(top_word + " ")
            self.last_inserted_word = top_word

        for i, word in enumerate(candidates[:5]):
            display_text = f"✓ {word}" if (i == 0 and self.auto_commit) else word
            btn = QPushButton(display_text)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            btn.setMinimumHeight(20)
            btn.setStyleSheet("font-size: 12px; padding: 1px 6px;")
            if i == 0:
                btn.setProperty("class", "candidate-chip-top")
            else:
                btn.setProperty("class", "candidate-chip")

            btn.clicked.connect(lambda checked, w=word, idx=i: self._on_chip_clicked(w, idx))
            self.bar_layout.addWidget(btn)
            self.chip_buttons.append(btn)

        self.bar_layout.addStretch()

    def _on_chip_clicked(self, word: str, index: int):
        if self.auto_commit and self.last_inserted_word is not None:
            if index == 0 and word == self.last_inserted_word:
                self.clear_candidates()
                return
            # Replace previously auto-inserted word: backspace len(last_word)+1 and type replacement
            backspaces = len(self.last_inserted_word) + 1
            bs_code = self.parent_window.engine.get_keycode("BACKSPACE")
            for _ in range(backspaces):
                self.parent_window.engine.send_keycode(bs_code)
            self.parent_window.engine.type_text(word + " ")
            self.clear_candidates()
        else:
            self.parent_window.engine.type_text(word + " ")
            self.clear_candidates()

    def clear_candidates(self):
        self.set_candidates([], "")
