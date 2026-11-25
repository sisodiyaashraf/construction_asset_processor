"""
Gallery Asset Card Component (Stage 13.2 Redesign)
Displays an individual image asset in an industrial dark themed card
with cached thumbnail, category, dimensions, transparency status,
current workflow stage, processing status, and multi-selection support.
"""

from pathlib import Path
from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFontMetrics, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import format_bytes
from core.pixmap_cache import pixmap_cache


class GalleryCard(QFrame):
    """Interactive asset card showing thumbnail, metadata, stage, and selection state."""

    clicked = Signal(int, bool, bool)    # asset_id, is_ctrl, is_shift
    status_changed = Signal(int, str)    # asset_id, new_status
    action_requested = Signal(str, int)  # action_name, asset_id

    CARD_WIDTH = 200
    CARD_HEIGHT = 250

    def __init__(self, asset: Dict[str, Any], size_mode: str = "medium", parent=None):
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset["id"]
        self.is_selected = False
        self.size_mode = size_mode

        self._apply_dimensions()
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("gallery_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 1. Top Badges Row: Category / Collection & Processing Status
        badges_row = QHBoxLayout()
        badges_row.setContentsMargins(0, 0, 0, 0)
        badges_row.setSpacing(4)

        # Category / Collection badge
        cat = asset.get("main_category") or asset.get("collection", "other_images")
        if cat == "Unclassified" or not cat:
            cat = "🚜 Excavator" if "excavat" in asset.get("collection", "").lower() else "🧱 Prop"
        elif len(cat) > 14:
            cat = f"{cat[:12]}…"

        self.lbl_category = QLabel(cat)
        self.lbl_category.setStyleSheet(f"""
            font-size: 9px;
            font-weight: 600;
            color: {THEME_COLORS['accent_primary']};
            background-color: rgba(229, 169, 60, 0.12);
            padding: 1px 5px;
            border-radius: 3px;
        """)
        badges_row.addWidget(self.lbl_category)
        badges_row.addStretch()

        # Processing Status badge
        status = str(asset.get("status", "pending")).capitalize()
        status_color = THEME_COLORS['status_success'] if status == "Approved" else (
            THEME_COLORS['status_error'] if status == "Rejected" else THEME_COLORS['status_warning']
        )
        status_bg = "rgba(16, 185, 129, 0.15)" if status == "Approved" else (
            "rgba(239, 68, 68, 0.15)" if status == "Rejected" else "rgba(245, 158, 11, 0.15)"
        )
        self.lbl_status = QLabel(status)
        self.lbl_status.setStyleSheet(f"""
            font-size: 9px;
            font-weight: 700;
            color: {status_color};
            background-color: {status_bg};
            padding: 1px 5px;
            border-radius: 3px;
        """)
        badges_row.addWidget(self.lbl_status)
        layout.addLayout(badges_row)

        # 2. Thumbnail Preview Container
        self.thumb_frame = QFrame()
        self.thumb_height = 115 if size_mode == "medium" else (95 if size_mode == "small" else 145)
        self.thumb_frame.setFixedHeight(self.thumb_height)
        self.thumb_frame.setStyleSheet(f"""
            background-color: #0E1012;
            border: 1px solid {THEME_COLORS['border_subtle']};
            border-radius: 4px;
        """)
        thumb_layout = QVBoxLayout(self.thumb_frame)
        thumb_layout.setContentsMargins(2, 2, 2, 2)
        thumb_layout.setAlignment(Qt.AlignCenter)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setStyleSheet("background: transparent;")
        thumb_layout.addWidget(self.lbl_thumb)
        layout.addWidget(self.thumb_frame)

        # 3. Filename Label (Elided with tooltip)
        fname = asset.get("filename", "Unknown")
        self.lbl_filename = QLabel(fname)
        self.lbl_filename.setToolTip(f"{fname}\nPath: {asset.get('original_path')}")
        self.lbl_filename.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 600;
            color: {THEME_COLORS['text_primary']};
        """)
        layout.addWidget(self.lbl_filename)

        # 4. Details Row: Dimensions • Format • Workflow Stage
        wf_stage = asset.get("workflow_current_stage", 1)
        dim_text = f"{asset.get('width', 0)} × {asset.get('height', 0)} • {str(asset.get('format', 'PNG')).upper()}"
        details_row = QHBoxLayout()
        details_row.setContentsMargins(0, 0, 0, 0)

        self.lbl_dims = QLabel(dim_text)
        self.lbl_dims.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']};")
        details_row.addWidget(self.lbl_dims)
        details_row.addStretch()

        self.lbl_stage = QLabel(f"Stage {wf_stage}")
        self.lbl_stage.setStyleSheet(f"""
            font-size: 9px;
            font-weight: 600;
            color: {THEME_COLORS['accent_secondary']};
            background-color: rgba(59, 130, 246, 0.12);
            padding: 1px 4px;
            border-radius: 2px;
        """)
        details_row.addWidget(self.lbl_stage)
        layout.addLayout(details_row)

        # 5. Bottom Row: File Size • Transparency Status
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)

        size_text = format_bytes(asset.get("file_size", 0))
        self.lbl_size = QLabel(size_text)
        self.lbl_size.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        bottom_row.addWidget(self.lbl_size)
        bottom_row.addStretch()

        # Transparency status distinction: Processed vs Source Alpha vs Opaque
        bg_proc = asset.get("bg_processing_status")
        if bg_proc == "processed":
            trans_text = "✓ Transparent"
            trans_color = THEME_COLORS['status_success']
            trans_bg = "rgba(16, 185, 129, 0.15)"
        elif asset.get("alpha_detected") == 1 or asset.get("has_transparency") == 1:
            trans_text = "💎 Alpha"
            trans_color = "#A855F7"
            trans_bg = "rgba(168, 85, 247, 0.12)"
        else:
            trans_text = "Opaque"
            trans_color = THEME_COLORS['text_muted']
            trans_bg = "rgba(255, 255, 255, 0.04)"

        self.lbl_trans = QLabel(trans_text)
        self.lbl_trans.setStyleSheet(f"""
            font-size: 9px;
            font-weight: 600;
            color: {trans_color};
            background-color: {trans_bg};
            padding: 1px 4px;
            border-radius: 3px;
        """)
        bottom_row.addWidget(self.lbl_trans)
        layout.addLayout(bottom_row)

        # Load Thumbnail & Apply Style
        self._load_thumbnail()
        self._update_style()

    def _apply_dimensions(self):
        if self.size_mode == "small":
            self.CARD_WIDTH = 165
            self.CARD_HEIGHT = 215
        elif self.size_mode == "large":
            self.CARD_WIDTH = 240
            self.CARD_HEIGHT = 285
        else:
            self.CARD_WIDTH = 200
            self.CARD_HEIGHT = 250
        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)

    def set_size_mode(self, mode: str):
        self.size_mode = mode
        self._apply_dimensions()
        self.thumb_height = 115 if mode == "medium" else (95 if mode == "small" else 145)
        self.thumb_frame.setFixedHeight(self.thumb_height)
        self._load_thumbnail()

    def _load_thumbnail(self):
        """Load cached thumbnail safely using thread-safe in-memory LRU cache."""
        thumb_path = self.asset.get("thumbnail_path")
        orig_path = self.asset.get("original_path", "")
        proc_path = self.asset.get("processed_path")

        # Prefer transparent processed path if available
        src = proc_path if (proc_path and Path(proc_path).exists()) else (thumb_path or orig_path)
        tw = self.CARD_WIDTH - 20
        th = self.thumb_height - 10

        pixmap = pixmap_cache.get_pixmap(
            file_path=src,
            target_size=(tw, th),
            thumbnail_fallback_path=thumb_path
        )

        if pixmap and not pixmap.isNull():
            self.lbl_thumb.setPixmap(pixmap)
        else:
            self.lbl_thumb.setText("🖼️ Preview")
            self.lbl_thumb.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 10px;")

    def set_selected(self, selected: bool):
        """Update selected visual state."""
        if self.is_selected != selected:
            self.is_selected = selected
            self._update_style()

    def _update_style(self):
        """Update border styling reflecting selection state."""
        if self.is_selected:
            self.setStyleSheet(f"""
                QFrame#gallery_card {{
                    background-color: {THEME_COLORS['bg_card_hover']};
                    border: 2px solid {THEME_COLORS['accent_primary']};
                    border-radius: 6px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#gallery_card {{
                    background-color: {THEME_COLORS['bg_card']};
                    border: 1px solid {THEME_COLORS['border_subtle']};
                    border-radius: 6px;
                }}
                QFrame#gallery_card:hover {{
                    border-color: {THEME_COLORS['border_medium']};
                    background-color: {THEME_COLORS['bg_card_hover']};
                }}
            """)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
            is_shift = bool(event.modifiers() & Qt.ShiftModifier)
            self.clicked.emit(self.asset_id, is_ctrl, is_shift)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 16px;
                font-size: 11px;
            }}
            QMenu::item:selected {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
            }}
        """)

        act_app = menu.addAction("✓ Mark as Approved")
        act_app.triggered.connect(lambda: self.status_changed.emit(self.asset_id, "approved"))

        act_pend = menu.addAction("⏳ Mark as Pending")
        act_pend.triggered.connect(lambda: self.status_changed.emit(self.asset_id, "pending"))

        act_rej = menu.addAction("✕ Mark as Rejected")
        act_rej.triggered.connect(lambda: self.status_changed.emit(self.asset_id, "rejected"))

        menu.addSeparator()
        act_exp = menu.addAction("📂 Reveal in File Explorer")
        act_exp.triggered.connect(lambda: self.action_requested.emit("reveal", self.asset_id))

        menu.exec(event.globalPos())
