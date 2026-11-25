"""
Text Detection Card Component (Stage 6)
Visual card displaying an individual image asset with thumbnail,
text region count badge, watermark candidate alert, and selection state.
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


class TextCard(QFrame):
    """Interactive card displaying asset text status in grid views."""

    clicked = Signal(int, bool, bool)  # asset_id, is_ctrl, is_shift
    selection_toggled = Signal(int, bool)  # asset_id, is_selected

    CARD_WIDTH = 220
    CARD_HEIGHT = 260

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset["id"]
        self.is_selected = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("text_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # 1. Top Badges & Selection Checkbox Row
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        # Multi-selection checkbox
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

        # Review status badge
        review_status = str(asset.get("text_review_status", "pending")).capitalize()
        status_color = (
            THEME_COLORS["status_success"] if review_status == "Reviewed"
            else (THEME_COLORS["status_info"] if review_status == "Clean"
                  else THEME_COLORS["status_warning"])
        )
        lbl_review = QLabel(review_status)
        lbl_review.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 600;
            color: {status_color};
            background-color: rgba(255, 255, 255, 0.06);
            padding: 2px 6px;
            border-radius: 4px;
        """)
        top_row.addWidget(lbl_review)

        layout.addLayout(top_row)

        # 2. Thumbnail Preview Frame
        self.thumb_container = QFrame()
        self.thumb_container.setFixedSize(200, 130)
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

        # 3. Filename & Dimensions Row
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

        # 4. Text Status & Watermark Badges
        text_row = QHBoxLayout()
        text_row.setContentsMargins(0, 0, 0, 0)
        text_row.setSpacing(4)

        detect_status = asset.get("text_detection_status", "uninspected")
        detected_count = asset.get("text_detected_count", 0) or 0
        has_wm = asset.get("has_watermark_text", 0) == 1

        if detect_status == "uninspected":
            txt_label = "Uninspected"
            txt_color = THEME_COLORS["text_muted"]
            txt_bg = "rgba(107, 114, 128, 0.15)"
        elif detect_status == "failed":
            txt_label = "✕ Failed"
            txt_color = THEME_COLORS["status_error"]
            txt_bg = "rgba(239, 68, 68, 0.15)"
        elif detected_count > 0:
            txt_label = f"🔍 {detected_count} Text"
            txt_color = THEME_COLORS["accent_primary"]
            txt_bg = "rgba(229, 169, 60, 0.15)"
        else:
            txt_label = "✓ Clean"
            txt_color = THEME_COLORS["status_success"]
            txt_bg = "rgba(16, 185, 129, 0.15)"

        lbl_text_badge = QLabel(txt_label)
        lbl_text_badge.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {txt_color};
            background-color: {txt_bg};
            padding: 2px 6px;
            border-radius: 4px;
        """)
        text_row.addWidget(lbl_text_badge)

        if has_wm:
            lbl_wm = QLabel("🛡️ Watermark")
            lbl_wm.setStyleSheet(f"""
                font-size: 10px;
                font-weight: 700;
                color: {THEME_COLORS['status_error']};
                background-color: rgba(239, 68, 68, 0.18);
                padding: 2px 6px;
                border-radius: 4px;
            """)
            lbl_wm.setToolTip("Suspected watermark or Gemini branding badge")
            text_row.addWidget(lbl_wm)

        text_row.addStretch()
        layout.addLayout(text_row)

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
            scaled = pix.scaled(196, 126, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_thumbnail.setPixmap(scaled)
        else:
            self.lbl_thumbnail.setText("No Preview")
            self.lbl_thumbnail.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px;")

    def set_selected(self, selected: bool):
        """Set visual selection state."""
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
        """Update card border and background styling based on selection state."""
        border_col = THEME_COLORS["accent_primary"] if self.is_selected else THEME_COLORS["border_subtle"]
        bg_col = THEME_COLORS["bg_card_hover"] if self.is_selected else THEME_COLORS["bg_card"]

        self.setStyleSheet(f"""
            QFrame#text_card {{
                background-color: {bg_col};
                border: {2 if self.is_selected else 1}px solid {border_col};
                border-radius: 6px;
            }}
            QFrame#text_card:hover {{
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
