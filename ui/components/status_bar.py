"""
Bottom Status Bar Component
Displays current background status, progress bar, and real-time database totals.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QWidget
)

from app.config import THEME_COLORS


class StatusBar(QWidget):
    """Bottom application status bar with worker progress and metrics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("status_bar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(14)

        # Status text
        self.status_label = QLabel("● Ready")
        self.status_label.setStyleSheet(f"color: {THEME_COLORS['status_success']}; font-weight: 500;")
        layout.addWidget(self.status_label)

        # Message detail
        self.detail_label = QLabel("Database initialized and ready.")
        self.detail_label.setStyleSheet(f"color: {THEME_COLORS['text_secondary']};")
        layout.addWidget(self.detail_label)

        layout.addStretch()

        # Background Task Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # System Metrics Pill
        self.metrics_label = QLabel("Total: 0 assets • 0 B")
        self.metrics_label.setStyleSheet(f"""
            color: {THEME_COLORS['text_muted']};
            font-size: 11px;
            font-weight: 600;
        """)
        layout.addWidget(self.metrics_label)

    def set_status(self, message: str, level: str = "info"):
        """Update status label and color indicator."""
        colors = {
            "info": THEME_COLORS["status_info"],
            "success": THEME_COLORS["status_success"],
            "warning": THEME_COLORS["status_warning"],
            "error": THEME_COLORS["status_error"],
        }
        color = colors.get(level, THEME_COLORS["text_secondary"])
        dot = "●"
        self.status_label.setText(f"{dot} {level.capitalize()}")
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.detail_label.setText(message)

    def show_progress(self, current: int, total: int):
        """Show and update progress percentage."""
        self.progress_bar.setVisible(True)
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{pct}% ({current}/{total})")
        else:
            self.progress_bar.setValue(0)

    def hide_progress(self):
        """Hide progress bar when tasks complete."""
        self.progress_bar.setVisible(False)

    def update_metrics(self, total_images: int, storage_formatted: str):
        """Update bottom metrics summary pill."""
        self.metrics_label.setText(f"Total: {total_images} assets • {storage_formatted}")
