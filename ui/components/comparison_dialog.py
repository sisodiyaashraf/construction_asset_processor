"""
Before-and-After Interactive Transparency Comparison Dialog (Stage 5)
Provides side-by-side inspection of original image vs. processed transparent image.
Features checkerboard transparency pattern, synchronized zoom & pan, fit-to-screen,
and direct manual approval/rejection controls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSlider, QSplitter, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.database import db

logger = logging.getLogger("AssetProcessor.ComparisonDialog")


def create_checkerboard_pixmap(size: int = 24) -> QPixmap:
    """Create a dark industrial transparency checkerboard tile."""
    pix = QPixmap(size, size)
    painter = QPainter(pix)
    c1 = QColor("#1A1E24")
    c2 = QColor("#262C36")
    half = size // 2
    painter.fillRect(0, 0, half, half, c1)
    painter.fillRect(half, 0, half, half, c2)
    painter.fillRect(0, half, half, half, c2)
    painter.fillRect(half, half, half, half, c1)
    painter.end()
    return pix


class ImageDisplayPanel(QScrollArea):
    """Zoomable scroll area supporting checkerboard transparency rendering."""

    def __init__(self, is_transparent: bool = False, parent=None):
        super().__init__(parent)
        self.is_transparent = is_transparent
        self.zoom_factor = 1.0
        self.raw_pixmap: Optional[QPixmap] = None

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setAlignment(Qt.AlignCenter)

        self.container = QWidget()
        self.layout_c = QVBoxLayout(self.container)
        self.layout_c.setContentsMargins(0, 0, 0, 0)
        self.layout_c.setAlignment(Qt.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.layout_c.addWidget(self.image_label)
        self.setWidget(self.container)

        if self.is_transparent:
            self.checker_brush = QBrush(create_checkerboard_pixmap(24))
        else:
            self.checker_brush = None

    def set_image(self, file_path: Path):
        """Load and display image."""
        if file_path.exists():
            self.raw_pixmap = QPixmap(str(file_path.resolve()))
            self.update_zoom()
        else:
            self.raw_pixmap = None
            self.image_label.setText("Image not available on disk")

    def set_zoom(self, factor: float):
        """Update scale factor."""
        self.zoom_factor = max(0.1, min(factor, 8.0))
        self.update_zoom()

    def update_zoom(self):
        """Render scaled pixmap."""
        if not self.raw_pixmap or self.raw_pixmap.isNull():
            return

        w = int(self.raw_pixmap.width() * self.zoom_factor)
        h = int(self.raw_pixmap.height() * self.zoom_factor)

        if self.is_transparent:
            # Draw on checkerboard background
            canvas = QPixmap(w, h)
            p = QPainter(canvas)
            p.fillRect(0, 0, w, h, self.checker_brush)
            scaled = self.raw_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(0, 0, scaled)
            p.end()
            self.image_label.setPixmap(canvas)
        else:
            scaled = self.raw_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled)

    def fit_to_view(self):
        """Scale image to fit within viewport."""
        if not self.raw_pixmap or self.raw_pixmap.isNull():
            return
        view_w = max(100, self.viewport().width() - 20)
        view_h = max(100, self.viewport().height() - 20)
        scale_w = view_w / self.raw_pixmap.width()
        scale_h = view_h / self.raw_pixmap.height()
        self.zoom_factor = min(scale_w, scale_h, 1.0)
        self.update_zoom()


class ComparisonDialog(QDialog):
    """
    Side-by-side interactive before-and-after visual inspection dialog.
    Enables close inspection of delicate edges (boom, bucket teeth, hoses, wheels).
    """

    status_changed = Signal(int, str)  # asset_id, new_approval

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.setWindowTitle(f"Transparency Comparison — {asset.get('filename')}")
        self.resize(1150, 750)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # 1. Top Header & Metadata
        header_bar = QHBoxLayout()
        header_title = QLabel("BEFORE & AFTER TRANSPARENCY AUDIT")
        header_title.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        header_bar.addWidget(header_title)
        header_bar.addStretch()

        self.lbl_zoom_text = QLabel("Zoom: 100%")
        self.lbl_zoom_text.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        header_bar.addWidget(self.lbl_zoom_text)

        # Zoom buttons
        btn_zoom_out = QPushButton("–")
        btn_zoom_out.setFixedSize(26, 26)
        btn_zoom_out.setCursor(Qt.PointingHandCursor)
        btn_zoom_out.clicked.connect(self._on_zoom_out)
        header_bar.addWidget(btn_zoom_out)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedSize(26, 26)
        btn_zoom_in.setCursor(Qt.PointingHandCursor)
        btn_zoom_in.clicked.connect(self._on_zoom_in)
        header_bar.addWidget(btn_zoom_in)

        btn_fit = QPushButton("Fit to View")
        btn_fit.setCursor(Qt.PointingHandCursor)
        btn_fit.setStyleSheet(f"background: #1E293B; color: {THEME_COLORS['text_primary']}; padding: 4px 10px; border-radius: 4px; font-size: 11px;")
        btn_fit.clicked.connect(self._on_fit_to_view)
        header_bar.addWidget(btn_fit)

        btn_actual = QPushButton("100%")
        btn_actual.setCursor(Qt.PointingHandCursor)
        btn_actual.setStyleSheet(f"background: #1E293B; color: {THEME_COLORS['text_primary']}; padding: 4px 8px; border-radius: 4px; font-size: 11px;")
        btn_actual.clicked.connect(self._on_zoom_actual)
        header_bar.addWidget(btn_actual)

        layout.addLayout(header_bar)

        # 2. Side-by-Side Comparison Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # Left: Original Image Container
        left_box = QFrame()
        left_box.setProperty("class", "card")
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        self.lbl_orig_meta = QLabel("ORIGINAL SOURCE IMAGE")
        self.lbl_orig_meta.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['text_secondary']};")
        left_layout.addWidget(self.lbl_orig_meta)

        self.panel_orig = ImageDisplayPanel(is_transparent=False)
        left_layout.addWidget(self.panel_orig, stretch=1)

        self.lbl_orig_details = QLabel("—")
        self.lbl_orig_details.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        left_layout.addWidget(self.lbl_orig_details)
        splitter.addWidget(left_box)

        # Right: Processed Transparent Container
        right_box = QFrame()
        right_box.setProperty("class", "card")
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)

        self.lbl_proc_meta = QLabel("PROCESSED TRANSPARENT IMAGE (ALPHA PREVIEW)")
        self.lbl_proc_meta.setStyleSheet("font-size: 11px; font-weight: 700; color: #10B981;")
        right_layout.addWidget(self.lbl_proc_meta)

        self.panel_proc = ImageDisplayPanel(is_transparent=True)
        right_layout.addWidget(self.panel_proc, stretch=1)

        self.lbl_proc_details = QLabel("—")
        self.lbl_proc_details.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        right_layout.addWidget(self.lbl_proc_details)
        splitter.addWidget(right_box)

        splitter.setSizes([550, 550])
        layout.addWidget(splitter, stretch=1)

        # 3. Synchronized Scrollbars
        self.panel_orig.horizontalScrollBar().valueChanged.connect(
            self.panel_proc.horizontalScrollBar().setValue
        )
        self.panel_proc.horizontalScrollBar().valueChanged.connect(
            self.panel_orig.horizontalScrollBar().setValue
        )
        self.panel_orig.verticalScrollBar().valueChanged.connect(
            self.panel_proc.verticalScrollBar().setValue
        )
        self.panel_proc.verticalScrollBar().valueChanged.connect(
            self.panel_orig.verticalScrollBar().setValue
        )

        # 4. Footer Inspection Guidance & Action Controls
        footer = QHBoxLayout()
        footer.setSpacing(10)

        guide_lbl = QLabel(
            "🔍 Inspect edges closely: Check excavator boom, bucket teeth, hydraulic hoses, and track links for artifacts."
        )
        guide_lbl.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        footer.addWidget(guide_lbl)

        footer.addStretch()

        self.btn_reject = QPushButton("✕ Reject Result")
        self.btn_reject.setCursor(Qt.PointingHandCursor)
        self.btn_reject.setStyleSheet("""
            background: #EF4444; color: white; border: none;
            padding: 8px 18px; border-radius: 4px; font-size: 11px; font-weight: 700;
        """)
        self.btn_reject.clicked.connect(self._on_reject_clicked)
        footer.addWidget(self.btn_reject)

        self.btn_approve = QPushButton("✓ Approve Result")
        self.btn_approve.setCursor(Qt.PointingHandCursor)
        self.btn_approve.setStyleSheet("""
            background: #10B981; color: white; border: none;
            padding: 8px 20px; border-radius: 4px; font-size: 11px; font-weight: 700;
        """)
        self.btn_approve.clicked.connect(self._on_approve_clicked)
        footer.addWidget(self.btn_approve)

        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            background: #1E293B; color: {THEME_COLORS['text_secondary']};
            border: 1px solid #334155; padding: 8px 16px; border-radius: 4px; font-size: 11px; font-weight: 600;
        """)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)

        layout.addLayout(footer)

        self._load_images()

    def _load_images(self):
        """Populate left and right panels with asset files."""
        orig_p_str = self.asset.get("current_path") or self.asset.get("original_path", "")
        orig_file = Path(orig_p_str)
        self.panel_orig.set_image(orig_file)

        ow = self.asset.get("width", 0)
        oh = self.asset.get("height", 0)
        osize = self.asset.get("file_size", 0)
        self.lbl_orig_details.setText(f"Dimensions: {ow} × {oh} px  •  Size: {format_bytes(osize)}  •  Path: {orig_file.name}")

        proc_p_str = self.asset.get("processed_path", "")
        proc_file = Path(proc_p_str) if proc_p_str else None

        if proc_file and proc_file.exists():
            self.panel_proc.set_image(proc_file)
            pw = self.asset.get("processed_width") or ow
            ph = self.asset.get("processed_height") or oh
            psize = self.asset.get("processed_file_size") or (proc_file.stat().st_size if proc_file.exists() else 0)
            status = self.asset.get("bg_quality_status", "valid")
            self.lbl_proc_details.setText(
                f"Dimensions: {pw} × {ph} px  •  Size: {format_bytes(psize)}  •  Quality: {status.upper()}  •  File: {proc_file.name}"
            )
            self.btn_approve.setEnabled(True)
            self.btn_reject.setEnabled(True)
        else:
            self.panel_proc.image_label.setText("Transparent image has not been processed yet.\nClick 'Remove Background' in Inspector.")
            self.lbl_proc_details.setText("No transparent output generated yet.")
            self.btn_approve.setEnabled(False)
            self.btn_reject.setEnabled(False)

    def _on_zoom_in(self):
        cur = self.panel_orig.zoom_factor
        new_z = min(cur * 1.25, 6.0)
        self._apply_zoom(new_z)

    def _on_zoom_out(self):
        cur = self.panel_orig.zoom_factor
        new_z = max(cur * 0.8, 0.1)
        self._apply_zoom(new_z)

    def _on_zoom_actual(self):
        self._apply_zoom(1.0)

    def _on_fit_to_view(self):
        self.panel_orig.fit_to_view()
        self.panel_proc.set_zoom(self.panel_orig.zoom_factor)
        self.lbl_zoom_text.setText(f"Zoom: {int(self.panel_orig.zoom_factor * 100)}%")

    def _apply_zoom(self, factor: float):
        self.panel_orig.set_zoom(factor)
        self.panel_proc.set_zoom(factor)
        self.lbl_zoom_text.setText(f"Zoom: {int(factor * 100)}%")

    def _on_approve_clicked(self):
        aid = self.asset["id"]
        db.update_transparency_approval(aid, "approved")
        self.status_changed.emit(aid, "approved")
        QMessageBox.information(self, "Approved", f"Asset #{aid} transparent output approved.")
        self.accept()

    def _on_reject_clicked(self):
        aid = self.asset["id"]
        db.update_transparency_approval(aid, "rejected")
        self.status_changed.emit(aid, "rejected")
        QMessageBox.information(self, "Rejected", f"Asset #{aid} transparent output marked as rejected.")
        self.accept()
