"""
Stage 13 Side-by-Side Comparison Dialog
Construction Asset Processor

Allows side-by-side zoomed edge inspection of:
- Original source image (with white background).
- Processed transparent PNG cutout (with dark industrial checkerboard).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from ui.components.interactive_mask_canvas import InteractiveMaskCanvas


class Stage13CompareDialog(QDialog):
    """Side-by-side before-and-after comparison dialog with synchronized controls."""

    approved = Signal(int)  # asset_id

    def __init__(self, asset_id: int, original_path: str, processed_path: str, parent=None):
        super().__init__(parent)
        self.asset_id = asset_id
        self.original_path = original_path
        self.processed_path = processed_path

        self.setWindowTitle(f"Before & After Edge Comparison — Asset #{asset_id}")
        self.resize(1200, 720)
        self.setMinimumSize(900, 500)
        self.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']}; color: {THEME_COLORS['text_primary']};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Banner
        header = QHBoxLayout()
        title_lbl = QLabel(f"🔍 Cutout Edge & Detail Inspection — Asset #{asset_id}")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #F3F4F6;")
        header.addWidget(title_lbl)
        header.addStretch()

        btn_fit = QPushButton("Fit Both")
        btn_fit.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['text_primary']}; padding: 6px 12px; border-radius: 4px;")
        btn_fit.clicked.connect(self._fit_both)
        header.addWidget(btn_fit)

        btn_1to1 = QPushButton("1:1 Pixel Scale")
        btn_1to1.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['text_primary']}; padding: 6px 12px; border-radius: 4px;")
        btn_1to1.clicked.connect(self._zoom_1to1)
        header.addWidget(btn_1to1)

        layout.addLayout(header)

        # Splitter with Two Canvas Panels
        splitter = QSplitter(Qt.Horizontal)

        # Left: Original Image
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_lbl = QLabel("ORIGINAL SOURCE (WITH BACKGROUND)")
        left_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']}; margin-bottom: 4px;")
        left_layout.addWidget(left_lbl)

        self.canvas_orig = InteractiveMaskCanvas(self)
        self.canvas_orig.set_image(self.original_path)
        left_layout.addWidget(self.canvas_orig)
        splitter.addWidget(left_widget)

        # Right: Processed Cutout
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_lbl = QLabel("PROCESSED TRANSPARENT CUTOUT (CHECKERBOARD BACKING)")
        right_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['status_success']}; margin-bottom: 4px;")
        right_layout.addWidget(right_lbl)

        self.canvas_proc = InteractiveMaskCanvas(self)
        self.canvas_proc.set_image(self.processed_path)
        right_layout.addWidget(self.canvas_proc)
        splitter.addWidget(right_widget)

        splitter.setSizes([600, 600])
        layout.addWidget(splitter, stretch=1)

        # Bottom Action Bar
        bottom_row = QHBoxLayout()
        tip_lbl = QLabel("💡 Tip: Use mouse wheel to zoom into mechanical edges (hydraulic rods, bucket teeth).")
        tip_lbl.setStyleSheet(f"font-size: 12px; color: {THEME_COLORS['text_muted']};")
        bottom_row.addWidget(tip_lbl)
        bottom_row.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['text_secondary']}; padding: 8px 16px; border-radius: 4px;")
        btn_close.clicked.connect(self.reject)
        bottom_row.addWidget(btn_close)

        btn_approve = QPushButton("✓ Approve Cutout Quality")
        btn_approve.setStyleSheet(f"background-color: {THEME_COLORS['status_success']}; color: #111827; font-weight: 700; padding: 8px 18px; border-radius: 4px;")
        btn_approve.clicked.connect(self._on_approve)
        bottom_row.addWidget(btn_approve)

        layout.addLayout(bottom_row)

    def _fit_both(self):
        self.canvas_orig.fit_to_view()
        self.canvas_proc.fit_to_view()

    def _zoom_1to1(self):
        self.canvas_orig.set_zoom_1_to_1()
        self.canvas_proc.set_zoom_1_to_1()

    def _on_approve(self):
        self.approved.emit(self.asset_id)
        self.accept()
