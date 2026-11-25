"""
AI Classification Card Component
Displays an asset card specialized for AI image recognition, showcasing
suggested object name, category hierarchy, confidence indicator,
composition type badge, and special detection flags.
"""

import json
from pathlib import Path
from typing import Any, Dict
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS


class ClassificationCard(QFrame):
    """Card widget representing an asset's AI classification status."""

    clicked = Signal(int, bool, bool)  # asset_id, is_ctrl, is_shift
    approve_requested = Signal(int)
    reject_requested = Signal(int)

    CARD_WIDTH = 215
    CARD_HEIGHT = 275

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset
        self.asset_id = asset["id"]
        self.is_selected = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("classification_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        # 1. Top Row: Confidence Pill & Status Pill
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        conf = float(asset.get("confidence_score") or 0.0)
        conf_pct = int(conf * 100)

        if conf >= 0.80:
            conf_color = THEME_COLORS["status_success"]
            conf_bg = "rgba(16, 185, 129, 0.15)"
            conf_text = f"★ {conf_pct}%"
        elif conf >= 0.50:
            conf_color = THEME_COLORS["status_warning"]
            conf_bg = "rgba(245, 158, 11, 0.15)"
            conf_text = f"▲ {conf_pct}%"
        elif conf > 0:
            conf_color = THEME_COLORS["status_error"]
            conf_bg = "rgba(239, 68, 68, 0.15)"
            conf_text = f"▼ {conf_pct}%"
        else:
            conf_color = THEME_COLORS["text_muted"]
            conf_bg = "rgba(255, 255, 255, 0.05)"
            conf_text = "Unanalyzed"

        self.lbl_conf = QLabel(conf_text)
        self.lbl_conf.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {conf_color};
            background-color: {conf_bg};
            padding: 2px 6px;
            border-radius: 4px;
        """)
        top_row.addWidget(self.lbl_conf)
        top_row.addStretch()

        # Classification status pill
        status = str(asset.get("classification_status") or "unclassified").capitalize()
        status_color = THEME_COLORS["status_success"] if status == "Approved" else (
            THEME_COLORS["status_error"] if status == "Rejected" else (
                THEME_COLORS["accent_primary"] if status in ("Suggested", "Manual") else THEME_COLORS["text_muted"]
            )
        )
        self.lbl_status = QLabel(status)
        self.lbl_status.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 600;
            color: {status_color};
            background-color: rgba(255, 255, 255, 0.06);
            padding: 2px 6px;
            border-radius: 4px;
        """)
        top_row.addWidget(self.lbl_status)
        layout.addLayout(top_row)

        # 2. Thumbnail Container
        self.thumb_frame = QFrame()
        self.thumb_frame.setFixedHeight(115)
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

        # 3. Suggested Object Name (Bold Headline)
        obj_name = asset.get("object_name") or "Pending Analysis"
        self.lbl_object_name = QLabel(obj_name)
        self.lbl_object_name.setToolTip(obj_name)
        self.lbl_object_name.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            color: {THEME_COLORS['text_primary']};
        """)
        layout.addWidget(self.lbl_object_name)

        # 4. Category & Subcategory Label
        main_cat = asset.get("main_category") or "Unclassified"
        sub_cat = asset.get("subcategory") or ""
        cat_display = f"{main_cat} › {sub_cat}" if sub_cat else main_cat
        self.lbl_category = QLabel(cat_display)
        self.lbl_category.setToolTip(cat_display)
        self.lbl_category.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 500;
            color: {THEME_COLORS['accent_primary']};
        """)
        layout.addWidget(self.lbl_category)

        # 5. Composition Type & Flags Row
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)

        comp = asset.get("composition_type") or "Single Object"
        self.lbl_comp = QLabel(comp)
        self.lbl_comp.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']};")
        bottom_row.addWidget(self.lbl_comp)
        bottom_row.addStretch()

        # Parse special flags
        flags_data = asset.get("special_flags") or {}
        if isinstance(flags_data, str):
            try:
                flags_data = json.loads(flags_data)
            except Exception:
                flags_data = {}

        flag_icons = []
        if flags_data.get("multiple_objects"):
            flag_icons.append("⚠️ Multi")
        if flags_data.get("sprite_sheet"):
            flag_icons.append("🎞️ Sheet")
        if flags_data.get("possible_text"):
            flag_icons.append("📝 Text")
        if flags_data.get("possible_watermark"):
            flag_icons.append("🛡️ Mark")

        if flag_icons:
            lbl_flags = QLabel(" ".join(flag_icons))
            lbl_flags.setStyleSheet(f"""
                font-size: 9px;
                font-weight: 600;
                color: {THEME_COLORS['status_warning']};
                background: rgba(245, 158, 11, 0.1);
                padding: 1px 4px;
                border-radius: 3px;
            """)
            bottom_row.addWidget(lbl_flags)

        layout.addLayout(bottom_row)

        self._load_thumbnail()
        self._update_style()

    def _load_thumbnail(self):
        """Render cached preview safely."""
        thumb_path = self.asset.get("thumbnail_path")
        pixmap = None
        if thumb_path and Path(thumb_path).exists():
            pixmap = QPixmap(thumb_path)
        elif Path(self.asset.get("original_path", "")).exists():
            pixmap = QPixmap(self.asset["original_path"])

        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(185, 105, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_thumb.setPixmap(scaled)
        else:
            self.lbl_thumb.setText("No Preview")
            self.lbl_thumb.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 10px;")

    def set_selected(self, selected: bool):
        """Update active selection appearance."""
        if self.is_selected != selected:
            self.is_selected = selected
            self._update_style()

    def _update_style(self):
        """Apply active CSS borders based on selection state."""
        if self.is_selected:
            self.setStyleSheet(f"""
                QFrame#classification_card {{
                    background-color: rgba(229, 169, 60, 0.12);
                    border: 2px solid {THEME_COLORS['accent_primary']};
                    border-radius: 8px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#classification_card {{
                    background-color: {THEME_COLORS['bg_card']};
                    border: 1px solid {THEME_COLORS['border_subtle']};
                    border-radius: 8px;
                }}
                QFrame#classification_card:hover {{
                    border: 1px solid {THEME_COLORS['border_focus']};
                    background-color: {THEME_COLORS['bg_card_hover']};
                }}
            """)

    def mousePressEvent(self, event: QMouseEvent):
        """Emit clicked signal with Ctrl and Shift state."""
        if event.button() == Qt.LeftButton:
            is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
            is_shift = bool(event.modifiers() & Qt.ShiftModifier)
            self.clicked.emit(self.asset_id, is_ctrl, is_shift)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        """Quick context menu for rapid classification approvals."""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 14px;
            }}
            QMenu::item:selected {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
            }}
        """)

        act_app = menu.addAction("✓ Approve Classification")
        act_rej = menu.addAction("✕ Reject Suggestion")
        action = menu.exec(QCursor.pos())

        if action == act_app:
            self.approve_requested.emit(self.asset_id)
        elif action == act_rej:
            self.reject_requested.emit(self.asset_id)
