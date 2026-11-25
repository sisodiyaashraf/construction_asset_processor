"""
Transparency Asset Card Component (Stage 5)
Interactive card for the Background Removal gallery displaying thumbnail
(rendered over checkerboard when transparent), eligibility pill,
review status, format, and dimension metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QCursor, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.config import THEME_COLORS
from core.transparency_engine import (
    ELIGIBILITY_ALREADY_TRANSPARENT, ELIGIBILITY_POSSIBLY,
    ELIGIBILITY_PRESERVE_SCENE, ELIGIBILITY_SPRITE_SHEET,
    ELIGIBILITY_SUITABLE, ELIGIBILITY_UNKNOWN
)
from ui.components.comparison_dialog import create_checkerboard_pixmap


class TransparencyCard(QFrame):
    """Visual asset card for the Background Removal module."""

    clicked = Signal(int, bool, bool)  # asset_id, is_ctrl, is_shift
    double_clicked = Signal(int)  # asset_id
    compare_requested = Signal(dict)

    CARD_WIDTH = 220
    CARD_HEIGHT = 280

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset["id"]
        self.is_selected = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("transparency_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        # 1. Top Badges Row (Eligibility & Review Status)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        elig = asset.get("background_eligibility") or ELIGIBILITY_UNKNOWN
        elig_colors = {
            ELIGIBILITY_SUITABLE: ("#10B981", "rgba(16, 185, 129, 0.15)", "SUITABLE"),
            ELIGIBILITY_POSSIBLY: ("#F59E0B", "rgba(245, 158, 11, 0.15)", "REVIEW"),
            ELIGIBILITY_PRESERVE_SCENE: ("#38BDF8", "rgba(56, 189, 248, 0.15)", "SCENE"),
            ELIGIBILITY_ALREADY_TRANSPARENT: ("#A855F7", "rgba(168, 85, 247, 0.15)", "ALPHA"),
            ELIGIBILITY_SPRITE_SHEET: ("#EC4899", "rgba(236, 72, 153, 0.15)", "SHEET"),
            ELIGIBILITY_UNKNOWN: ("#94A3B8", "rgba(148, 163, 184, 0.15)", "UNKNOWN"),
        }
        color, bg_col, short_label = elig_colors.get(elig, ("#94A3B8", "rgba(148, 163, 184, 0.15)", "UNKNOWN"))

        lbl_elig = QLabel(short_label)
        lbl_elig.setToolTip(elig)
        lbl_elig.setStyleSheet(f"""
            color: {color};
            background: {bg_col};
            border: 1px solid {color}44;
            border-radius: 3px;
            font-size: 9px;
            font-weight: 700;
            padding: 2px 5px;
        """)
        top_row.addWidget(lbl_elig)
        top_row.addStretch()

        rev_st = asset.get("bg_manual_approval", "unreviewed")
        rev_colors = {
            "approved": ("#10B981", "APPROVED"),
            "rejected": ("#EF4444", "REJECTED"),
            "unreviewed": ("#64748B", "UNREVIEWED"),
        }
        r_col, r_text = rev_colors.get(rev_st, ("#64748B", "UNREVIEWED"))

        lbl_rev = QLabel(r_text)
        lbl_rev.setStyleSheet(f"""
            color: {r_col};
            font-size: 9px;
            font-weight: 700;
            padding: 2px 4px;
        """)
        top_row.addWidget(lbl_rev)
        layout.addLayout(top_row)

        # 2. Thumbnail Preview Frame
        self.thumb_frame = QFrame()
        self.thumb_frame.setFixedHeight(140)
        self.thumb_frame.setStyleSheet("""
            background: #111418;
            border: 1px solid #1E232B;
            border-radius: 4px;
        """)
        tf_layout = QVBoxLayout(self.thumb_frame)
        tf_layout.setContentsMargins(2, 2, 2, 2)
        tf_layout.setAlignment(Qt.AlignCenter)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        tf_layout.addWidget(self.thumb_label)
        layout.addWidget(self.thumb_frame)

        self._load_thumbnail()

        # 3. Filename
        fname = asset.get("approved_filename") or asset.get("suggested_filename") or asset.get("filename", "")
        lbl_fname = QLabel(fname)
        lbl_fname.setToolTip(fname)
        lbl_fname.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 600;
            color: {THEME_COLORS['text_primary']};
        """)
        lbl_fname.setFixedHeight(16)
        layout.addWidget(lbl_fname)

        # 4. Category
        cat_str = asset.get("main_category") or "Unclassified"
        sub = asset.get("subcategory")
        if sub:
            cat_str = f"{sub}"
        lbl_cat = QLabel(cat_str)
        lbl_cat.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        lbl_cat.setFixedHeight(14)
        layout.addWidget(lbl_cat)

        # 5. Bottom Metadata Row
        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)

        w = asset.get("processed_width") or asset.get("width", 0)
        h = asset.get("processed_height") or asset.get("height", 0)
        lbl_dim = QLabel(f"{w}×{h}")
        lbl_dim.setStyleSheet(f"font-size: 9px; color: {THEME_COLORS['text_muted']};")
        bot_row.addWidget(lbl_dim)
        bot_row.addStretch()

        proc_st = asset.get("bg_processing_status", "not_processed")
        if proc_st == "processed":
            st_text = "● TRANSPARENT"
            st_color = "#10B981"
        elif proc_st == "failed":
            st_text = "● FAILED"
            st_color = "#EF4444"
        else:
            st_text = "○ OPAQUE"
            st_color = "#64748B"

        lbl_status = QLabel(st_text)
        lbl_status.setStyleSheet(f"font-size: 9px; font-weight: 700; color: {st_color};")
        bot_row.addWidget(lbl_status)
        layout.addLayout(bot_row)

        self.update_style()

    def _load_thumbnail(self):
        """Render thumbnail (over checkerboard if transparent output exists)."""
        proc_path = self.asset.get("processed_path")
        orig_path = self.asset.get("current_path") or self.asset.get("original_path")
        thumb_path = self.asset.get("thumbnail_path")

        target_file = None
        is_transparent = False

        if proc_path and Path(proc_path).exists():
            target_file = Path(proc_path)
            is_transparent = True
        elif thumb_path and Path(thumb_path).exists():
            target_file = Path(thumb_path)
        elif orig_path and Path(orig_path).exists():
            target_file = Path(orig_path)

        if target_file and target_file.exists():
            pix = QPixmap(str(target_file))
            if not pix.isNull():
                max_w = self.CARD_WIDTH - 24
                max_h = 136
                scaled = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                if is_transparent:
                    sw, sh = scaled.width(), scaled.height()
                    canvas = QPixmap(sw, sh)
                    p = QPainter(canvas)
                    brush = QBrush(create_checkerboard_pixmap(16))
                    p.fillRect(0, 0, sw, sh, brush)
                    p.drawPixmap(0, 0, scaled)
                    p.end()
                    self.thumb_label.setPixmap(canvas)
                else:
                    self.thumb_label.setPixmap(scaled)
                return

        self.thumb_label.setText("No Preview")

    def set_selected(self, selected: bool):
        """Update card visual selection highlight."""
        if self.is_selected != selected:
            self.is_selected = selected
            self.update_style()

    def update_style(self):
        """Apply CSS styling based on selection state."""
        if self.is_selected:
            self.setStyleSheet(f"""
                QFrame#transparency_card {{
                    background: #1E232B;
                    border: 2px solid {THEME_COLORS['accent_primary']};
                    border-radius: 6px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#transparency_card {{
                    background: #171A1F;
                    border: 1px solid #232832;
                    border-radius: 6px;
                }}
                QFrame#transparency_card:hover {{
                    background: #1D2128;
                    border: 1px solid {THEME_COLORS['border_medium']};
                }}
            """)

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
