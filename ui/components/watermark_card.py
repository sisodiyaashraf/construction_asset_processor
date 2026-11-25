"""
Watermark Candidate Card Component (Stage 7)
Visual card displaying an individual image asset in the Watermark Review grid,
featuring thumbnail preview, candidate count, candidate categories,
score badge, and review warning indicator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFontMetrics, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.watermark_engine import WATERMARK_CATEGORY_COLORS


class WatermarkCard(QFrame):
    """Interactive card displaying asset watermark candidate status."""

    clicked = Signal(int, bool, bool)  # asset_id, is_ctrl, is_shift
    selection_toggled = Signal(int, bool)  # asset_id, is_selected

    CARD_WIDTH = 220
    CARD_HEIGHT = 275

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset["id"]
        self.is_selected = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("watermark_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # 1. Top Badges & Selection Checkbox Row
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        # Multi-select checkbox
        self.chk_select = QCheckBox()
        self.chk_select.setCursor(Qt.PointingHandCursor)
        self.chk_select.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 3px;
                background-color: {THEME_COLORS['bg_input']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {THEME_COLORS['accent_primary']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.chk_select.toggled.connect(self._on_check_toggled)
        top_row.addWidget(self.chk_select)

        # Collection badge
        coll_name = asset.get("collection", "other_images")
        is_excavator = "excavat" in coll_name.lower()
        coll_text = "🚜 Excavator" if is_excavator else "🧱 Other"
        lbl_collection = QLabel(coll_text)
        lbl_collection.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 600;
            color: {THEME_COLORS['accent_primary'] if is_excavator else THEME_COLORS['text_secondary']};
            background-color: rgba(229, 169, 60, 0.12) if is_excavator else rgba(255, 255, 255, 0.06);
            padding: 2px 6px;
            border-radius: 4px;
        """)
        top_row.addWidget(lbl_collection)
        top_row.addStretch()

        # Review Status Badge
        rev_status = str(asset.get("watermark_review_status", "unreviewed")).lower()
        if rev_status in ("needs_replacement", "confirmed"):
            st_text = "🚨 Replacement"
            st_col = THEME_COLORS["status_error"]
            st_bg = "rgba(239, 68, 68, 0.18)"
        elif rev_status in ("reviewed", "clean", "no_watermark"):
            st_text = "✓ Clear"
            st_col = THEME_COLORS["status_success"]
            st_bg = "rgba(16, 185, 129, 0.18)"
        elif rev_status == "rejected":
            st_text = "✕ Rejected"
            st_col = THEME_COLORS["text_secondary"]
            st_bg = "rgba(156, 163, 175, 0.15)"
        else:
            st_text = "Pending"
            st_col = THEME_COLORS["status_warning"]
            st_bg = "rgba(245, 158, 11, 0.18)"

        lbl_review = QLabel(st_text)
        lbl_review.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {st_col};
            background-color: {st_bg};
            padding: 2px 6px;
            border-radius: 4px;
        """)
        top_row.addWidget(lbl_review)
        layout.addLayout(top_row)

        # 2. Thumbnail Container
        self.thumb_container = QFrame()
        self.thumb_container.setFixedSize(200, 125)
        self.thumb_container.setStyleSheet(f"""
            background-color: {THEME_COLORS['bg_main']};
            border: 1px solid {THEME_COLORS['border_subtle']};
            border-radius: 4px;
        """)
        thumb_layout = QVBoxLayout(self.thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setAlignment(Qt.AlignCenter)

        self.lbl_thumbnail = QLabel()
        self.lbl_thumbnail.setAlignment(Qt.AlignCenter)
        self._load_thumbnail()
        thumb_layout.addWidget(self.lbl_thumbnail)
        layout.addWidget(self.thumb_container)

        # 3. Filename & Dimensions
        self.lbl_filename = QLabel()
        raw_name = asset.get("filename", "unknown.png")
        metrics = QFontMetrics(self.lbl_filename.font())
        elided_name = metrics.elidedText(raw_name, Qt.ElideMiddle, 195)
        self.lbl_filename.setText(elided_name)
        self.lbl_filename.setToolTip(raw_name)
        self.lbl_filename.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 600;
            color: {THEME_COLORS['text_primary']};
        """)
        layout.addWidget(self.lbl_filename)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        w = asset.get("width", 0)
        h = asset.get("height", 0)
        dim_str = f"{w}×{h}" if w and h else "—"
        size_str = format_bytes(asset.get("file_size_bytes", 0))

        lbl_dim = QLabel(f"{dim_str} • {size_str}")
        lbl_dim.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        meta_row.addWidget(lbl_dim)
        meta_row.addStretch()
        layout.addLayout(meta_row)

        # 4. Watermark Candidate Badges Row
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(4)

        cand_count = asset.get("watermark_candidate_count", 0) or 0
        det_status = asset.get("watermark_detection_status", "uninspected")

        if det_status == "uninspected":
            lbl_cand = QLabel("Uninspected")
            lbl_cand.setStyleSheet(f"""
                font-size: 10px; font-weight: 600; color: {THEME_COLORS['text_muted']};
                background-color: rgba(107, 114, 128, 0.15); padding: 2px 6px; border-radius: 4px;
            """)
        elif cand_count > 0:
            lbl_cand = QLabel(f"🛡️ {cand_count} Candidate{'s' if cand_count != 1 else ''}")
            lbl_cand.setStyleSheet(f"""
                font-size: 10px; font-weight: 700; color: {THEME_COLORS['status_error']};
                background-color: rgba(239, 68, 68, 0.18); padding: 2px 6px; border-radius: 4px;
            """)
        else:
            lbl_cand = QLabel("✓ No Candidate")
            lbl_cand.setStyleSheet(f"""
                font-size: 10px; font-weight: 600; color: {THEME_COLORS['status_success']};
                background-color: rgba(16, 185, 129, 0.15); padding: 2px 6px; border-radius: 4px;
            """)
        badge_row.addWidget(lbl_cand)

        # Warning indicator when review is required
        if cand_count > 0 and rev_status in ("pending", "unreviewed"):
            lbl_warn = QLabel("⚠️ Review")
            lbl_warn.setStyleSheet(f"""
                font-size: 10px; font-weight: 700; color: {THEME_COLORS['status_warning']};
                background-color: rgba(245, 158, 11, 0.18); padding: 2px 6px; border-radius: 4px;
            """)
            lbl_warn.setToolTip("Asset contains detected watermark candidates requiring manual review")
            badge_row.addWidget(lbl_warn)

        badge_row.addStretch()
        layout.addLayout(badge_row)

        self._update_appearance()

    def _load_thumbnail(self):
        """Load cached thumbnail or fallback to original."""
        thumb_path = self.asset.get("thumbnail_path")
        orig_path = self.asset.get("original_path")

        pix = None
        if thumb_path and Path(thumb_path).exists():
            pix = QPixmap(thumb_path)
        elif orig_path and Path(orig_path).exists():
            pix = QPixmap(orig_path)

        if pix and not pix.isNull():
            scaled = pix.scaled(196, 121, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_thumbnail.setPixmap(scaled)
        else:
            self.lbl_thumbnail.setText("No Preview")
            self.lbl_thumbnail.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px;")

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.chk_select.blockSignals(True)
        self.chk_select.setChecked(selected)
        self.chk_select.blockSignals(False)
        self._update_appearance()

    def _on_check_toggled(self, checked: bool):
        self.is_selected = checked
        self._update_appearance()
        self.selection_toggled.emit(self.asset_id, checked)

    def _update_appearance(self):
        border_col = THEME_COLORS["accent_primary"] if self.is_selected else THEME_COLORS["border_subtle"]
        bg_col = THEME_COLORS["bg_card_hover"] if self.is_selected else THEME_COLORS["bg_card"]

        self.setStyleSheet(f"""
            QFrame#watermark_card {{
                background-color: {bg_col};
                border: {2 if self.is_selected else 1}px solid {border_col};
                border-radius: 6px;
            }}
            QFrame#watermark_card:hover {{
                border-color: {THEME_COLORS['accent_primary']};
                background-color: {THEME_COLORS['bg_card_hover']};
            }}
        """)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
            is_shift = bool(event.modifiers() & Qt.ShiftModifier)
            self.clicked.emit(self.asset_id, is_ctrl, is_shift)
        super().mousePressEvent(event)
