"""
Dashboard Metric Card Component
Displays real-time database numbers, storage sizes, and progress metrics.
"""

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from app.config import THEME_COLORS


class StatCard(QFrame):
    """Reusable metric card with icon, headline, large value, and secondary status."""

    def __init__(
        self,
        title: str,
        value: str,
        subtitle: str = "",
        icon: str = "📊",
        accent_color: Optional[str] = None,
        show_progress: bool = False,
        progress_val: int = 0,
        parent=None
    ):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.accent_color = accent_color or THEME_COLORS["accent_primary"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # Header Row: Title + Icon
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: {THEME_COLORS['text_secondary']};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        """)
        top_row.addWidget(self.title_label)

        top_row.addStretch()

        self.icon_label = QLabel(icon)
        self.icon_label.setStyleSheet(f"font-size: 16px; color: {self.accent_color};")
        top_row.addWidget(self.icon_label)

        layout.addLayout(top_row)

        # Large Value Label
        self.value_label = QLabel(str(value))
        self.value_label.setStyleSheet(f"""
            font-size: 26px;
            font-weight: 700;
            color: {THEME_COLORS['text_primary']};
            letter-spacing: -0.5px;
        """)
        layout.addWidget(self.value_label)

        # Optional Progress Bar
        self.progress_bar = None
        if show_progress:
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(progress_val)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setFixedHeight(6)
            layout.addWidget(self.progress_bar)

        # Subtitle / Detail Label
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet(f"font-size: 12px; color: {THEME_COLORS['text_muted']};")
        layout.addWidget(self.subtitle_label)

    def update_data(self, value: str, subtitle: Optional[str] = None, progress: Optional[int] = None):
        """Update the card's displayed values."""
        self.value_label.setText(str(value))
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)
        if self.progress_bar is not None and progress is not None:
            self.progress_bar.setValue(int(progress))

    update_value = update_data
    set_value = update_data
