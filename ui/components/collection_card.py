"""
Collection Splitter Card Component (Stage 8)
Visual card displaying an individual image asset in the Collection Splitter grid,
featuring thumbnail preview, composition type badge, candidate object count,
extraction status, and multi-selection checkbox.
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
from core.collection_splitter_engine import COMPOSITION_COLORS


class CollectionCard(QFrame):
    """Interactive card displaying asset collection composition and extraction status."""

    clicked = Signal(int, bool, bool)  # asset_id, is_ctrl, is_shift
    selection_toggled = Signal(int, bool)  # asset_id, is_selected

    CARD_WIDTH = 220
    CARD_HEIGHT = 280

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset["id"]
        self.is_selected = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("collection_card")

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

        # Composition Type Badge
        comp_type = asset.get("splitter_composition_type") or "Unknown"
        comp_color = COMPOSITION_COLORS.get(comp_type, "#9CA3AF")
        comp_short = comp_type
        if comp_type == "Multiple Object Collection":
            comp_short = "🧩 Collection"
        elif comp_type == "Overlapping Object Collection":
            comp_short = "⚠️ Overlapping"
        elif comp_type == "Sprite Sheet":
            comp_short = "🎞️ Sprite Sheet"
        elif comp_type == "Animation Frame Grid":
            comp_short = "⚡ Anim Grid"
        elif comp_type == "Single Object":
            comp_short = "📦 Single Object"
        elif comp_type == "Background Scene":
            comp_short = "🏞️ Scene"
        else:
            comp_short = "❔ Unknown"

        lbl_comp = QLabel(comp_short)
        lbl_comp.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {comp_color};
            background-color: rgba(30, 41, 59, 0.8);
            border: 1px solid {comp_color};
            padding: 2px 6px;
            border-radius: 4px;
        """)
        lbl_comp.setToolTip(f"Composition: {comp_type}")
        top_row.addWidget(lbl_comp)
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

        # 4. Candidate Count & Extraction Status Row
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(4)

        cand_count = asset.get("splitter_candidate_count", 0) or 0
        ana_status = asset.get("splitter_analysis_status", "uninspected")
        ext_status = asset.get("splitter_extraction_status", "unextracted")
        extracted_cnt = asset.get("extracted_assets_count", 0) or 0

        if ana_status == "uninspected":
            lbl_cand = QLabel("Uninspected")
            lbl_cand.setStyleSheet(f"""
                font-size: 10px; font-weight: 600; color: {THEME_COLORS['text_muted']};
                background-color: rgba(107, 114, 128, 0.15); padding: 2px 6px; border-radius: 4px;
            """)
        elif cand_count > 1:
            lbl_cand = QLabel(f"✂️ {cand_count} Candidate Objects")
            lbl_cand.setStyleSheet(f"""
                font-size: 10px; font-weight: 700; color: #10B981;
                background-color: rgba(16, 185, 129, 0.18); padding: 2px 6px; border-radius: 4px;
            """)
        elif cand_count == 1:
            lbl_cand = QLabel("📦 1 Object")
            lbl_cand.setStyleSheet(f"""
                font-size: 10px; font-weight: 600; color: #3B82F6;
                background-color: rgba(59, 130, 246, 0.15); padding: 2px 6px; border-radius: 4px;
            """)
        else:
            lbl_cand = QLabel("No Objects")
            lbl_cand.setStyleSheet(f"""
                font-size: 10px; font-weight: 600; color: {THEME_COLORS['text_muted']};
                background-color: rgba(107, 114, 128, 0.15); padding: 2px 6px; border-radius: 4px;
            """)
        badge_row.addWidget(lbl_cand)

        # Extraction badge
        if ext_status == "extracted" or extracted_cnt > 0:
            lbl_ext = QLabel(f"✓ Split ({extracted_cnt})")
            lbl_ext.setStyleSheet(f"""
                font-size: 10px; font-weight: 700; color: {THEME_COLORS['status_success']};
                background-color: rgba(16, 185, 129, 0.18); padding: 2px 6px; border-radius: 4px;
            """)
            badge_row.addWidget(lbl_ext)
        elif cand_count > 1 and comp_type != "Background Scene":
            lbl_ext = QLabel("Ready to Split")
            lbl_ext.setStyleSheet(f"""
                font-size: 10px; font-weight: 700; color: {THEME_COLORS['accent_primary']};
                background-color: rgba(229, 169, 60, 0.18); padding: 2px 6px; border-radius: 4px;
            """)
            badge_row.addWidget(lbl_ext)

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
            QFrame#collection_card {{
                background-color: {bg_col};
                border: {2 if self.is_selected else 1}px solid {border_col};
                border-radius: 6px;
            }}
            QFrame#collection_card:hover {{
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
