"""
Optimization Asset Card Component (Stage 10)
Construction Asset Processor

Visual card for the Asset Optimization & Flutter Export pipeline.
Displays thumbnail, resolution, format, original vs optimized size, savings percentage,
validation badge, export approval toggle, and batch selection checkbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from ui.components.comparison_dialog import create_checkerboard_pixmap


class OptimizationCard(QFrame):
    """Visual asset card for the Stage 10 Optimization & Export pipeline."""

    clicked = Signal(int, bool, bool)  # asset_id, is_ctrl, is_shift
    double_clicked = Signal(int)       # asset_id
    checked_toggled = Signal(int, bool)# asset_id, is_checked
    approval_toggled = Signal(int, bool) # asset_id, is_approved

    CARD_WIDTH = 220
    CARD_HEIGHT = 290

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset["id"]
        self.is_selected = False
        self._block_signals = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("optimization_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # 1. Top Bar: Checkbox + Badges
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        self.check_box = QCheckBox()
        self.check_box.setToolTip("Select for batch optimization / export")
        self.check_box.toggled.connect(self._on_check_toggled)
        top_row.addWidget(self.check_box)

        # Format Badge
        fmt = (asset.get("format") or "PNG").upper().replace(".", "")
        lbl_fmt = QLabel(fmt)
        lbl_fmt.setStyleSheet(f"""
            color: {THEME_COLORS['accent_secondary']};
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid rgba(59, 130, 246, 0.3);
            border-radius: 3px;
            font-size: 9px;
            font-weight: 700;
            padding: 1px 4px;
        """)
        top_row.addWidget(lbl_fmt)

        top_row.addStretch()

        # Validation status badge
        val_status = asset.get("validation_status") or "unchecked"
        val_colors = {
            "passed": ("#10B981", "rgba(16, 185, 129, 0.15)", "VALID"),
            "warning": ("#F59E0B", "rgba(245, 158, 11, 0.15)", "WARN"),
            "failed": ("#EF4444", "rgba(239, 68, 68, 0.15)", "FAIL"),
            "unchecked": ("#6B7280", "rgba(107, 114, 128, 0.15)", "NEW"),
        }
        v_col, v_bg, v_txt = val_colors.get(val_status.lower(), val_colors["unchecked"])
        self.lbl_val = QLabel(v_txt)
        self.lbl_val.setToolTip(f"Validation: {val_status.upper()}")
        self.lbl_val.setStyleSheet(f"""
            color: {v_col};
            background: {v_bg};
            border: 1px solid {v_col}55;
            border-radius: 3px;
            font-size: 9px;
            font-weight: 700;
            padding: 1px 4px;
        """)
        top_row.addWidget(self.lbl_val)

        # Export approval indicator
        is_appr = bool(asset.get("is_approved_for_export", 0) or asset.get("status") == "approved")
        self.lbl_appr = QLabel("EXPORT" if is_appr else "STAGED")
        self.lbl_appr.setToolTip("Approved for export to Flutter" if is_appr else "Not yet marked for Flutter export")
        appr_col = "#10B981" if is_appr else "#94A3B8"
        appr_bg = "rgba(16, 185, 129, 0.15)" if is_appr else "rgba(148, 163, 184, 0.10)"
        self.lbl_appr.setStyleSheet(f"""
            color: {appr_col};
            background: {appr_bg};
            border: 1px solid {appr_col}44;
            border-radius: 3px;
            font-size: 9px;
            font-weight: 700;
            padding: 1px 4px;
        """)
        top_row.addWidget(self.lbl_appr)

        layout.addLayout(top_row)

        # 2. Thumbnail Preview Frame
        self.thumb_frame = QFrame()
        self.thumb_frame.setFixedHeight(145)
        self.thumb_frame.setStyleSheet("""
            QFrame {
                background-color: #121417;
                border: 1px solid #2B313A;
                border-radius: 4px;
            }
        """)
        thumb_layout = QVBoxLayout(self.thumb_frame)
        thumb_layout.setContentsMargins(2, 2, 2, 2)
        thumb_layout.setAlignment(Qt.AlignCenter)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        thumb_layout.addWidget(self.thumb_label)
        layout.addWidget(self.thumb_frame)

        # 3. Filename
        fname = asset.get("smart_filename") or asset.get("filename") or f"Asset_{self.asset_id}"
        self.name_label = QLabel(fname)
        self.name_label.setToolTip(fname)
        self.name_label.setStyleSheet(f"""
            color: {THEME_COLORS['text_primary']};
            font-size: 11px;
            font-weight: 600;
        """)
        self.name_label.setWordWrap(False)
        layout.addWidget(self.name_label)

        # 4. Dimensions & Optimization Size Row
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(4)

        w = asset.get("width") or 0
        h = asset.get("height") or 0
        self.dim_label = QLabel(f"{w}x{h}")
        self.dim_label.setStyleSheet(f"color: {THEME_COLORS['text_secondary']}; font-size: 10px;")
        meta_row.addWidget(self.dim_label)

        meta_row.addStretch()

        # Optimization sizes & savings
        orig_sz = asset.get("file_size") or 0
        opt_sz = asset.get("optimized_size") or 0
        opt_st = asset.get("optimization_status") or "unprocessed"

        if opt_sz > 0 and orig_sz > 0:
            saved_pct = max(0.0, (orig_sz - opt_sz) / orig_sz * 100.0)
            self.size_label = QLabel(f"{format_bytes(opt_sz)} (-{saved_pct:.0f}%)")
            self.size_label.setStyleSheet("color: #10B981; font-size: 10px; font-weight: 700;")
        else:
            self.size_label = QLabel(format_bytes(orig_sz))
            self.size_label.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 10px;")
        meta_row.addWidget(self.size_label)

        layout.addLayout(meta_row)

        self._update_appearance()
        self._load_thumbnail()

    def _update_appearance(self):
        """Update border and background styling based on selection state."""
        border_col = THEME_COLORS["accent_primary"] if self.is_selected else THEME_COLORS["border_subtle"]
        bg_col = "#242A33" if self.is_selected else THEME_COLORS["bg_card"]
        self.setStyleSheet(f"""
            QFrame#optimization_card {{
                background-color: {bg_col};
                border: {2 if self.is_selected else 1}px solid {border_col};
                border-radius: 6px;
            }}
            QFrame#optimization_card:hover {{
                border-color: {THEME_COLORS['accent_primary']};
                background-color: {THEME_COLORS['bg_card_hover']};
            }}
        """)

    def set_selected(self, selected: bool):
        """Set visual selection state."""
        if self.is_selected != selected:
            self.is_selected = selected
            self._update_appearance()

    def set_checked(self, checked: bool):
        """Set multi-select checkbox without recursion."""
        self._block_signals = True
        self.check_box.setChecked(checked)
        self._block_signals = False

    def is_checked(self) -> bool:
        return self.check_box.isChecked()

    def _on_check_toggled(self, checked: bool):
        if not self._block_signals:
            self.checked_toggled.emit(self.asset_id, checked)

    def _load_thumbnail(self):
        """Load asset thumbnail over checkerboard if transparency exists."""
        thumb_path_str = self.asset.get("thumbnail_path")
        orig_path_str = self.asset.get("original_path") or self.asset.get("filepath")
        
        pix = None
        if thumb_path_str and Path(thumb_path_str).exists():
            pix = QPixmap(thumb_path_str)
        elif orig_path_str and Path(orig_path_str).exists():
            pix = QPixmap(orig_path_str)

        if not pix or pix.isNull():
            self.thumb_label.setText("No Preview")
            self.thumb_label.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 10px;")
            return

        # Scale to frame size
        scaled = pix.scaled(180, 135, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Render over dark checkerboard
        composed = QPixmap(scaled.size())
        painter = QPainter(composed)
        checker = create_checkerboard_pixmap(16)
        painter.drawTiledPixmap(0, 0, scaled.width(), scaled.height(), checker)
        painter.drawPixmap(0, 0, scaled)
        painter.end()

        self.thumb_label.setPixmap(composed)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
            is_shift = bool(event.modifiers() & Qt.ShiftModifier)
            self.clicked.emit(self.asset_id, is_ctrl, is_shift)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self.asset_id)
        super().mouseDoubleClickEvent(event)
