"""
Text & Label Detection Inspector Component (Stage 6)
Dedicated right-side panel for inspecting text regions in game assets,
viewing interactive canvas with bounding boxes, editing recognized text,
correcting categories, tagging watermark candidates, and deleting false positives.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.database import db
from core.text_engine import (
    CATEGORIES, CATEGORY_COLORS, REVIEW_STATUSES, text_engine
)
from ui.components.text_region_canvas import TextRegionCanvas

logger = logging.getLogger("AssetProcessor.TextInspector")


class TextInspector(QWidget):
    """Right-side inspector dedicated to Stage 6 text detection and label editing."""

    asset_updated = Signal(int)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("text_inspector")
        self.current_asset: Optional[Dict[str, Any]] = None
        self.current_regions: List[Dict[str, Any]] = []
        self.selected_region: Optional[Dict[str, Any]] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # 1. Header with Close Button
        header_layout = QHBoxLayout()
        header_title = QLabel("TEXT & LABEL INSPECTOR")
        header_title.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        header_layout.addWidget(header_title)
        header_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(22, 22)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            border: none;
            color: {THEME_COLORS['text_secondary']};
            font-weight: bold;
            font-size: 12px;
            background: transparent;
        """)
        btn_close.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(btn_close)
        main_layout.addLayout(header_layout)

        # 2. Scroll Area for Body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)

        # 2a. Interactive Canvas Widget
        self.canvas_card = QFrame()
        self.canvas_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        c_layout = QVBoxLayout(self.canvas_card)
        c_layout.setContentsMargins(8, 8, 8, 8)
        c_layout.setSpacing(6)

        c_header = QLabel("IMAGE TEXT OVERLAY")
        c_header.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        c_layout.addWidget(c_header)

        self.canvas = TextRegionCanvas()
        self.canvas.setMinimumHeight(240)
        self.canvas.region_selected.connect(self._on_canvas_region_selected)
        self.canvas.region_deselected.connect(self._on_canvas_region_deselected)
        self.canvas.new_region_drawn.connect(self._on_new_region_drawn)
        c_layout.addWidget(self.canvas)

        self.content_layout.addWidget(self.canvas_card)

        # 2b. Asset Metadata Card
        meta_card = QFrame()
        meta_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        meta_layout = QVBoxLayout(meta_card)
        meta_layout.setContentsMargins(12, 12, 12, 12)
        meta_layout.setSpacing(6)

        self.lbl_filename = QLabel("No Asset Selected")
        self.lbl_filename.setWordWrap(True)
        self.lbl_filename.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {THEME_COLORS['text_primary']};")
        meta_layout.addWidget(self.lbl_filename)

        grid = QGridLayout()
        grid.setSpacing(4)
        lbl_dim_title = QLabel("Dimensions:")
        lbl_dim_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_dim_val = QLabel("—")
        self.lbl_dim_val.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        grid.addWidget(lbl_dim_title, 0, 0)
        grid.addWidget(self.lbl_dim_val, 0, 1)

        lbl_size_title = QLabel("File Size:")
        lbl_size_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_size_val = QLabel("—")
        self.lbl_size_val.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        grid.addWidget(lbl_size_title, 1, 0)
        grid.addWidget(self.lbl_size_val, 1, 1)

        lbl_reg_title = QLabel("Detected Regions:")
        lbl_reg_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_reg_val = QLabel("0 regions")
        self.lbl_reg_val.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        grid.addWidget(lbl_reg_title, 2, 0)
        grid.addWidget(self.lbl_reg_val, 2, 1)

        meta_layout.addLayout(grid)
        self.content_layout.addWidget(meta_card)

        # 2c. Regions Table Card
        table_card = QFrame()
        table_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        t_layout = QVBoxLayout(table_card)
        t_layout.setContentsMargins(12, 12, 12, 12)
        t_layout.setSpacing(8)

        t_header = QLabel("DETECTED TEXT REGIONS")
        t_header.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        t_layout.addWidget(t_header)

        self.table_regions = QTableWidget(0, 3)
        self.table_regions.setHorizontalHeaderLabels(["Category", "Text", "Conf"])
        self.table_regions.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_regions.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_regions.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_regions.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_regions.setSelectionMode(QTableWidget.SingleSelection)
        self.table_regions.verticalHeader().setVisible(False)
        self.table_regions.setMaximumHeight(140)
        self.table_regions.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_toolbar']};
                color: {THEME_COLORS['text_secondary']};
                padding: 4px;
                font-size: 10px;
                font-weight: 700;
                border: none;
            }}
        """)
        self.table_regions.itemSelectionChanged.connect(self._on_table_selection_changed)
        t_layout.addWidget(self.table_regions)

        self.content_layout.addWidget(table_card)

        # 2d. Selected Region Detail & Correction Card
        self.editor_card = QFrame()
        self.editor_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        ed_layout = QVBoxLayout(self.editor_card)
        ed_layout.setContentsMargins(12, 12, 12, 12)
        ed_layout.setSpacing(8)

        self.lbl_ed_title = QLabel("REGION EDITOR")
        self.lbl_ed_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        ed_layout.addWidget(self.lbl_ed_title)

        # Editable Recognized Text
        lbl_txt_prompt = QLabel("Recognized / Manual Text:")
        lbl_txt_prompt.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        ed_layout.addWidget(lbl_txt_prompt)

        self.txt_recognized = QLineEdit()
        self.txt_recognized.setPlaceholderText("Enter or correct text...")
        self.txt_recognized.setStyleSheet(f"""
            QLineEdit {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 5px 8px;
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        ed_layout.addWidget(self.txt_recognized)

        # Category Dropdown
        lbl_cat_prompt = QLabel("Text Category:")
        lbl_cat_prompt.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        ed_layout.addWidget(lbl_cat_prompt)

        self.combo_category = QComboBox()
        self.combo_category.addItems(CATEGORIES)
        self.combo_category.setStyleSheet(f"""
            QComboBox {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
            }}
        """)
        ed_layout.addWidget(self.combo_category)

        # Geometry coordinates display
        self.lbl_coords = QLabel("Bounding Box: X: 0, Y: 0, W: 0, H: 0")
        self.lbl_coords.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        ed_layout.addWidget(self.lbl_coords)

        # Watermark flag checkbox
        self.chk_watermark = QCheckBox("Flag as Watermark Candidate (for Stage 7 Review)")
        self.chk_watermark.setStyleSheet(f"""
            QCheckBox {{
                color: {THEME_COLORS['status_error']};
                font-size: 11px;
                font-weight: 600;
            }}
        """)
        ed_layout.addWidget(self.chk_watermark)

        # Region Actions Buttons
        reg_btn_layout = QHBoxLayout()
        self.btn_save_region = QPushButton("💾 Save Edits")
        self.btn_save_region.setStyleSheet(self._action_btn_style(THEME_COLORS["accent_primary"], "#111827"))
        self.btn_save_region.clicked.connect(self._save_region_edits)
        reg_btn_layout.addWidget(self.btn_save_region)

        self.btn_delete_region = QPushButton("✕ Reject Box")
        self.btn_delete_region.setToolTip("Delete this false positive text region")
        self.btn_delete_region.setStyleSheet(self._action_btn_style("rgba(239, 68, 68, 0.2)", THEME_COLORS["status_error"]))
        self.btn_delete_region.clicked.connect(self._delete_current_region)
        reg_btn_layout.addWidget(self.btn_delete_region)

        ed_layout.addLayout(reg_btn_layout)

        # Tag Unwanted / Intentional Quick Buttons
        quick_row = QHBoxLayout()
        self.btn_unwanted = QPushButton("⚠️ Mark Unwanted")
        self.btn_unwanted.setToolTip("Flag region as unwanted artificial writing")
        self.btn_unwanted.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_warning"]))
        self.btn_unwanted.clicked.connect(lambda: self._set_region_review("unwanted"))
        quick_row.addWidget(self.btn_unwanted)

        self.btn_intentional = QPushButton("✓ Mark Intentional")
        self.btn_intentional.setToolTip("Mark region as intended in-game text / UI asset")
        self.btn_intentional.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_success"]))
        self.btn_intentional.clicked.connect(lambda: self._set_region_review("intentional"))
        quick_row.addWidget(self.btn_intentional)

        ed_layout.addLayout(quick_row)
        self.content_layout.addWidget(self.editor_card)

        # 2e. Asset Review Status Actions Card
        review_card = QFrame()
        review_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        rev_layout = QVBoxLayout(review_card)
        rev_layout.setContentsMargins(12, 12, 12, 12)
        rev_layout.setSpacing(8)

        rev_header = QLabel("ASSET REVIEW ACTIONS")
        rev_header.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        rev_layout.addWidget(rev_header)

        self.btn_analyze_single = QPushButton("🔍 Re-Analyze Asset")
        self.btn_analyze_single.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["text_primary"]))
        self.btn_analyze_single.clicked.connect(self._reanalyze_single_asset)
        rev_layout.addWidget(self.btn_analyze_single)

        status_actions_layout = QHBoxLayout()
        self.btn_mark_clean = QPushButton("✓ Mark Clean")
        self.btn_mark_clean.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_success"]))
        self.btn_mark_clean.clicked.connect(lambda: self._set_asset_review("clean"))
        status_actions_layout.addWidget(self.btn_mark_clean)

        self.btn_flag_review = QPushButton("⚠️ Flag Asset")
        self.btn_flag_review.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_warning"]))
        self.btn_flag_review.clicked.connect(lambda: self._set_asset_review("flagged"))
        status_actions_layout.addWidget(self.btn_flag_review)

        self.btn_approve_review = QPushButton("⭐ Approve")
        self.btn_approve_review.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_info"]))
        self.btn_approve_review.clicked.connect(lambda: self._set_asset_review("reviewed"))
        status_actions_layout.addWidget(self.btn_approve_review)

        rev_layout.addLayout(status_actions_layout)
        self.content_layout.addWidget(review_card)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self._set_editor_enabled(False)

    def inspect_asset(self, asset: Dict[str, Any]):
        """Load and inspect an asset record."""
        self.current_asset = asset
        asset_id = asset["id"]

        # Filename & metadata
        self.lbl_filename.setText(asset.get("filename", "unknown"))
        w = asset.get("width", 0)
        h = asset.get("height", 0)
        self.lbl_dim_val.setText(f"{w} × {h} px" if w and h else "—")
        self.lbl_size_val.setText(format_bytes(asset.get("file_size_bytes", 0)))

        # Fetch real text regions from database
        self.current_regions = db.get_text_regions(asset_id)
        count = len(self.current_regions)
        self.lbl_reg_val.setText(f"{count} region(s)" if count > 0 else "0 (Clean)")

        # Load image & regions into interactive canvas
        orig_path = asset.get("original_path", "")
        self.canvas.load_image(orig_path, self.current_regions)

        # Populate regions table
        self._populate_table()

        # Reset editor
        self.selected_region = None
        self._set_editor_enabled(False)

    def _populate_table(self):
        """Populate the regions list table."""
        self.table_regions.blockSignals(True)
        self.table_regions.setRowCount(0)

        for row_idx, r in enumerate(self.current_regions):
            self.table_regions.insertRow(row_idx)

            # Category item with colored dot/text
            cat_name = r.get("category", "Unknown writing")
            item_cat = QTableWidgetItem(cat_name)
            item_cat.setForeground(QColor(CATEGORY_COLORS.get(cat_name, "#9CA3AF")))
            self.table_regions.setItem(row_idx, 0, item_cat)

            # Text item
            text_str = r.get("recognized_text", "")
            item_text = QTableWidgetItem(text_str)
            item_text.setToolTip(text_str)
            self.table_regions.setItem(row_idx, 1, item_text)

            # Confidence item
            conf = int(r.get("confidence", 0) * 100)
            item_conf = QTableWidgetItem(f"{conf}%")
            self.table_regions.setItem(row_idx, 2, item_conf)

        self.table_regions.blockSignals(False)

    def _on_canvas_region_selected(self, region: Dict[str, Any]):
        """Handle region clicked on interactive canvas."""
        self.selected_region = region
        self._set_editor_enabled(True)

        # Highlight in table
        reg_id = region.get("id")
        self.table_regions.blockSignals(True)
        for row in range(self.table_regions.rowCount()):
            if row < len(self.current_regions) and self.current_regions[row].get("id") == reg_id:
                self.table_regions.selectRow(row)
                break
        self.table_regions.blockSignals(False)

        self._populate_editor(region)

    def _on_canvas_region_deselected(self):
        """Canvas background clicked."""
        self.selected_region = None
        self._set_editor_enabled(False)
        self.table_regions.clearSelection()

    def _on_table_selection_changed(self):
        """Table row selected."""
        selected_rows = self.table_regions.selectionModel().selectedRows()
        if not selected_rows:
            self.selected_region = None
            self.canvas.select_region(None)
            self._set_editor_enabled(False)
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self.current_regions):
            region = self.current_regions[row]
            self.selected_region = region
            self.canvas.select_region(region.get("id"))
            self._set_editor_enabled(True)
            self._populate_editor(region)

    def _populate_editor(self, region: Dict[str, Any]):
        """Fill editor card with selected region data."""
        reg_id = region.get("id")
        self.lbl_ed_title.setText(f"REGION EDITOR — ID #{reg_id}")
        self.txt_recognized.setText(region.get("recognized_text", ""))

        category = region.get("category", "Unknown writing")
        idx = self.combo_category.findText(category)
        if idx >= 0:
            self.combo_category.setCurrentIndex(idx)

        bx = region.get("box_x", 0)
        by = region.get("box_y", 0)
        bw = region.get("box_w", 0)
        bh = region.get("box_h", 0)
        self.lbl_coords.setText(f"Coordinates: X: {bx}, Y: {by} | Size: {bw} × {bh} px")

        is_wm = region.get("is_watermark_candidate", 0) == 1
        self.chk_watermark.setChecked(is_wm)

    def _on_new_region_drawn(self, bx: int, by: int, bw: int, bh: int):
        """Add manually drawn bounding box rectangle."""
        if not self.current_asset:
            return

        asset_id = self.current_asset["id"]
        # Determine category and watermark status for manual box
        w = self.current_asset.get("width", 1000)
        h = self.current_asset.get("height", 1000)

        new_region_dict = {
            "box_x": bx,
            "box_y": by,
            "box_w": bw,
            "box_h": bh,
            "recognized_text": "[Manual Box]",
            "confidence": 1.0,
            "category": "Alphabetic text",
            "is_watermark_candidate": 1 if (bx + bw >= w * 0.82 and by + bh >= h * 0.82) else 0,
            "model_name": "Manual",
        }

        new_id = db.add_text_region(asset_id, new_region_dict)
        logger.info("Added manual text region #%s to asset #%s", new_id, asset_id)

        # Refresh asset data
        self.refresh_current_asset()
        self.asset_updated.emit(asset_id)

        # Select new region
        self.canvas.select_region(new_id)

    def _save_region_edits(self):
        """Save manual correction and category updates for selected region."""
        if not self.selected_region:
            return

        reg_id = self.selected_region.get("id")
        new_text = self.txt_recognized.text().strip()
        new_cat = self.combo_category.currentText()
        is_wm = 1 if self.chk_watermark.isChecked() else 0

        updates = {
            "recognized_text": new_text,
            "manual_correction": new_text,
            "category": new_cat,
            "is_watermark_candidate": is_wm,
        }

        db.update_text_region(reg_id, updates)
        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _delete_current_region(self):
        """Delete selected false positive bounding box."""
        if not self.selected_region:
            return

        reg_id = self.selected_region.get("id")
        db.delete_text_region(reg_id)
        self.selected_region = None
        self._set_editor_enabled(False)

        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _set_region_review(self, status: str):
        """Set review status on selected region."""
        if not self.selected_region:
            return

        reg_id = self.selected_region.get("id")
        db.update_text_region(reg_id, {"review_status": status})
        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _set_asset_review(self, status: str):
        """Update top-level asset text review status."""
        if not self.current_asset:
            return

        asset_id = self.current_asset["id"]
        db.update_asset_text_review(asset_id, status)
        self.refresh_current_asset()
        self.asset_updated.emit(asset_id)

    def _reanalyze_single_asset(self):
        """Re-run text detection on current asset."""
        if not self.current_asset:
            return

        success, count, _ = text_engine.process_and_save_asset(self.current_asset, method="auto")
        self.refresh_current_asset()
        self.asset_updated.emit(self.current_asset["id"])

    def refresh_current_asset(self):
        """Re-read current asset from SQLite and update UI."""
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        fresh = db.get_asset(aid)
        if fresh:
            self.inspect_asset(fresh)

    def _set_editor_enabled(self, enabled: bool):
        """Enable or disable editor controls."""
        self.txt_recognized.setEnabled(enabled)
        self.combo_category.setEnabled(enabled)
        self.chk_watermark.setEnabled(enabled)
        self.btn_save_region.setEnabled(enabled)
        self.btn_delete_region.setEnabled(enabled)
        self.btn_unwanted.setEnabled(enabled)
        self.btn_intentional.setEnabled(enabled)
        if not enabled:
            self.lbl_ed_title.setText("REGION EDITOR (Select a region)")
            self.lbl_coords.setText("Coordinates: —")
            self.txt_recognized.clear()
            self.chk_watermark.setChecked(False)

    def _action_btn_style(self, bg: str, text: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {text};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
            QPushButton:disabled {{
                opacity: 0.4;
                color: {THEME_COLORS['text_muted']};
            }}
        """
