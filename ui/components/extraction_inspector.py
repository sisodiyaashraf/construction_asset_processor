"""
Collection Splitter & Asset Extraction Inspector Component (Stage 8)
Dedicated right-side panel for inspecting collection composition,
viewing the interactive canvas with bounding box overlays, manually drawing/adjusting regions,
generating sprite sheet grids, and initiating asset extraction preview/export.
Strictly non-destructive — never modifies or overwrites source images.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.collection_splitter_engine import (
    COMPOSITION_COLORS, COMPOSITION_TYPES, collection_splitter_engine
)
from core.database import db
from ui.components.collection_canvas import CollectionCanvasContainer
from ui.components.extraction_preview import ExtractionPreviewDialog

logger = logging.getLogger("AssetProcessor.ExtractionInspector")


class ExtractionInspector(QWidget):
    """Right-side inspector dedicated to Stage 8 collection analysis and asset extraction."""

    asset_updated = Signal(int)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("extraction_inspector")
        self.current_asset: Optional[Dict[str, Any]] = None
        self.current_regions: List[Dict[str, Any]] = []
        self.selected_region: Optional[Dict[str, Any]] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # 1. Header with Close Button
        header_layout = QHBoxLayout()
        header_title = QLabel("COLLECTION & EXTRACTION INSPECTOR")
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
        self.content_layout.setSpacing(10)

        # 2a. Interactive Canvas Container
        self.canvas_card = QFrame()
        self.canvas_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        c_layout = QVBoxLayout(self.canvas_card)
        c_layout.setContentsMargins(6, 6, 6, 6)
        c_layout.setSpacing(4)

        c_header = QLabel("COLLECTION ASSET OVERLAY")
        c_header.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        c_layout.addWidget(c_header)

        self.canvas = CollectionCanvasContainer()
        self.canvas.setMinimumHeight(260)
        self.canvas.region_selected.connect(self._on_canvas_region_selected)
        self.canvas.region_deselected.connect(self._on_canvas_region_deselected)
        self.canvas.new_region_drawn.connect(self._on_new_region_drawn)
        self.canvas.region_modified.connect(self._on_region_modified)
        self.canvas.region_deleted.connect(self._on_region_deleted)
        c_layout.addWidget(self.canvas)

        self.content_layout.addWidget(self.canvas_card)

        # 2b. Asset Metadata & Composition Card
        meta_card = QFrame()
        meta_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        meta_layout = QVBoxLayout(meta_card)
        meta_layout.setContentsMargins(10, 10, 10, 10)
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

        lbl_alpha_title = QLabel("Transparency:")
        lbl_alpha_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_alpha_val = QLabel("—")
        self.lbl_alpha_val.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        grid.addWidget(lbl_alpha_title, 2, 0)
        grid.addWidget(self.lbl_alpha_val, 2, 1)

        meta_layout.addLayout(grid)

        # Composition Selector (Editable Dropdown)
        comp_box = QHBoxLayout()
        lbl_comp_title = QLabel("Composition:")
        lbl_comp_title.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['text_secondary']};")
        comp_box.addWidget(lbl_comp_title)

        self.cmb_composition = QComboBox()
        self.cmb_composition.addItems(COMPOSITION_TYPES)
        self.cmb_composition.setStyleSheet(self._combo_style())
        self.cmb_composition.currentIndexChanged.connect(self._on_composition_changed)
        comp_box.addWidget(self.cmb_composition, stretch=1)
        meta_layout.addLayout(comp_box)

        self.lbl_explanation = QLabel("No analysis history available.")
        self.lbl_explanation.setWordWrap(True)
        self.lbl_explanation.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        meta_layout.addWidget(self.lbl_explanation)

        self.content_layout.addWidget(meta_card)

        # 2c. Candidate Regions Table
        regions_card = QFrame()
        regions_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        r_layout = QVBoxLayout(regions_card)
        r_layout.setContentsMargins(10, 10, 10, 10)
        r_layout.setSpacing(6)

        r_hdr = QHBoxLayout()
        self.lbl_regions_count = QLabel("DETECTED CANDIDATE REGIONS (0)")
        self.lbl_regions_count.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        r_hdr.addWidget(self.lbl_regions_count)
        r_hdr.addStretch()

        btn_add_box = QPushButton("+ Add Box")
        btn_add_box.setToolTip("Enable Draw Box mode on canvas")
        btn_add_box.setStyleSheet(self._btn_secondary_style())
        btn_add_box.clicked.connect(self._enable_canvas_draw)
        r_hdr.addWidget(btn_add_box)
        r_layout.addLayout(r_hdr)

        self.tbl_regions = QTableWidget(0, 4)
        self.tbl_regions.setHorizontalHeaderLabels(["#", "Type", "Size", "Pos"])
        self.tbl_regions.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl_regions.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_regions.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_regions.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_regions.verticalHeader().setVisible(False)
        self.tbl_regions.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_regions.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl_regions.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                font-size: 10px;
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_secondary']};
                padding: 3px;
                border: 1px solid {THEME_COLORS['border_subtle']};
                font-size: 10px;
                font-weight: 600;
            }}
        """)
        self.tbl_regions.itemSelectionChanged.connect(self._on_table_selection_changed)
        r_layout.addWidget(self.tbl_regions)

        self.content_layout.addWidget(regions_card)

        # 2d. Selected Region Detail Card
        self.detail_card = QFrame()
        self.detail_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        d_layout = QVBoxLayout(self.detail_card)
        d_layout.setContentsMargins(10, 10, 10, 10)
        d_layout.setSpacing(6)

        self.lbl_detail_title = QLabel("SELECTED REGION DETAILS")
        self.lbl_detail_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        d_layout.addWidget(self.lbl_detail_title)

        h_detail = QHBoxLayout()
        # Crop Preview Thumbnail
        self.lbl_crop_preview = QLabel("No Region")
        self.lbl_crop_preview.setFixedSize(80, 80)
        self.lbl_crop_preview.setAlignment(Qt.AlignCenter)
        self.lbl_crop_preview.setStyleSheet(f"""
            background-color: {THEME_COLORS['bg_main']};
            border: 1px solid {THEME_COLORS['border_subtle']};
            border-radius: 4px;
            font-size: 10px;
            color: {THEME_COLORS['text_muted']};
        """)
        h_detail.addWidget(self.lbl_crop_preview)

        # Spinboxes for X, Y, W, H
        coord_grid = QGridLayout()
        coord_grid.setSpacing(4)

        coord_grid.addWidget(QLabel("X:"), 0, 0)
        self.spn_x = QSpinBox()
        self.spn_x.setRange(0, 10000)
        self.spn_x.setStyleSheet(self._spin_style())
        coord_grid.addWidget(self.spn_x, 0, 1)

        coord_grid.addWidget(QLabel("Y:"), 0, 2)
        self.spn_y = QSpinBox()
        self.spn_y.setRange(0, 10000)
        self.spn_y.setStyleSheet(self._spin_style())
        coord_grid.addWidget(self.spn_y, 0, 3)

        coord_grid.addWidget(QLabel("W:"), 1, 0)
        self.spn_w = QSpinBox()
        self.spn_w.setRange(1, 10000)
        self.spn_w.setStyleSheet(self._spin_style())
        coord_grid.addWidget(self.spn_w, 1, 1)

        coord_grid.addWidget(QLabel("H:"), 1, 2)
        self.spn_h = QSpinBox()
        self.spn_h.setRange(1, 10000)
        self.spn_h.setStyleSheet(self._spin_style())
        coord_grid.addWidget(self.spn_h, 1, 3)

        h_detail.addLayout(coord_grid)
        d_layout.addLayout(h_detail)

        # Region Type & Update Buttons
        h_type = QHBoxLayout()
        h_type.addWidget(QLabel("Type:"))
        self.cmb_region_type = QComboBox()
        self.cmb_region_type.addItems([
            "isolated_asset", "sprite_frame", "candidate_region",
            "overlapping_part", "background_scene", "manual_box"
        ])
        self.cmb_region_type.setStyleSheet(self._combo_style())
        h_type.addWidget(self.cmb_region_type, stretch=1)
        d_layout.addLayout(h_type)

        h_reg_btns = QHBoxLayout()
        btn_apply_box = QPushButton("Apply Box Edits")
        btn_apply_box.setStyleSheet(self._btn_secondary_style())
        btn_apply_box.clicked.connect(self._apply_region_edits)
        h_reg_btns.addWidget(btn_apply_box)

        btn_del_reg = QPushButton("Delete Box")
        btn_del_reg.setStyleSheet(self._btn_secondary_style())
        btn_del_reg.clicked.connect(self._delete_selected_region)
        h_reg_btns.addWidget(btn_del_reg)
        d_layout.addLayout(h_reg_btns)

        self.content_layout.addWidget(self.detail_card)

        # 2e. Sprite Sheet Grid Generator Panel
        grid_card = QFrame()
        grid_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        g_layout = QVBoxLayout(grid_card)
        g_layout.setContentsMargins(10, 10, 10, 10)
        g_layout.setSpacing(6)

        g_title = QLabel("SPRITE SHEET GRID GENERATOR")
        g_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        g_layout.addWidget(g_title)

        grid_inputs = QGridLayout()
        grid_inputs.setSpacing(4)

        grid_inputs.addWidget(QLabel("Columns:"), 0, 0)
        self.spn_cols = QSpinBox()
        self.spn_cols.setRange(1, 32)
        self.spn_cols.setValue(3)
        self.spn_cols.setStyleSheet(self._spin_style())
        grid_inputs.addWidget(self.spn_cols, 0, 1)

        grid_inputs.addWidget(QLabel("Rows:"), 0, 2)
        self.spn_rows = QSpinBox()
        self.spn_rows.setRange(1, 32)
        self.spn_rows.setValue(1)
        self.spn_rows.setStyleSheet(self._spin_style())
        grid_inputs.addWidget(self.spn_rows, 0, 3)

        grid_inputs.addWidget(QLabel("Margin:"), 1, 0)
        self.spn_margin = QSpinBox()
        self.spn_margin.setRange(0, 100)
        self.spn_margin.setValue(0)
        self.spn_margin.setStyleSheet(self._spin_style())
        grid_inputs.addWidget(self.spn_margin, 1, 1)

        grid_inputs.addWidget(QLabel("Spacing:"), 1, 2)
        self.spn_spacing = QSpinBox()
        self.spn_spacing.setRange(0, 100)
        self.spn_spacing.setValue(0)
        self.spn_spacing.setStyleSheet(self._spin_style())
        grid_inputs.addWidget(self.spn_spacing, 1, 3)

        g_layout.addLayout(grid_inputs)

        btn_calc_grid = QPushButton("⚡ Generate Grid Frames")
        btn_calc_grid.setToolTip("Divide image into a uniform NxM frame grid")
        btn_calc_grid.setStyleSheet(self._btn_secondary_style())
        btn_calc_grid.clicked.connect(self._generate_sprite_grid)
        g_layout.addWidget(btn_calc_grid)

        self.content_layout.addWidget(grid_card)

        # 2f. Action Buttons Card
        action_card = QFrame()
        action_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        a_layout = QVBoxLayout(action_card)
        a_layout.setContentsMargins(10, 10, 10, 10)
        a_layout.setSpacing(8)

        self.btn_preview_extract = QPushButton("✂️ Open Extraction Preview Dialog")
        self.btn_preview_extract.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
        """)
        self.btn_preview_extract.clicked.connect(self._open_extraction_preview)
        a_layout.addWidget(self.btn_preview_extract)

        h_sub_actions = QHBoxLayout()
        btn_reanalyze = QPushButton("Re-Analyze Asset")
        btn_reanalyze.setStyleSheet(self._btn_secondary_style())
        btn_reanalyze.clicked.connect(self._reanalyze_current_asset)
        h_sub_actions.addWidget(btn_reanalyze)

        btn_clear_all = QPushButton("Clear All Regions")
        btn_clear_all.setStyleSheet(self._btn_secondary_style())
        btn_clear_all.clicked.connect(self._clear_all_regions)
        h_sub_actions.addWidget(btn_clear_all)
        a_layout.addLayout(h_sub_actions)

        self.content_layout.addWidget(action_card)

        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

    def load_asset(self, asset: Dict[str, Any]):
        """Load an asset and its detected regions into the inspector."""
        self.current_asset = asset
        asset_id = asset["id"]

        self.lbl_filename.setText(asset.get("filename", "unknown.png"))
        w = asset.get("width", 0)
        h = asset.get("height", 0)
        self.lbl_dim_val.setText(f"{w} × {h} px" if w and h else "—")
        self.lbl_size_val.setText(format_bytes(asset.get("file_size_bytes", 0)))
        has_alpha = bool(asset.get("has_transparency", 0))
        self.lbl_alpha_val.setText("Yes (RGBA / Alpha Channel)" if has_alpha else "No (Opaque RGB)")

        # Composition ComboBox
        comp_type = asset.get("splitter_composition_type") or "Unknown Composition"
        idx = self.cmb_composition.findText(comp_type)
        if idx >= 0:
            self.cmb_composition.blockSignals(True)
            self.cmb_composition.setCurrentIndex(idx)
            self.cmb_composition.blockSignals(False)

        # Load explanation from history
        history = db.get_collection_analysis_history(asset_id)
        if history:
            latest = history[0]
            self.lbl_explanation.setText(f"Analysis: {latest.get('explanation', '—')}")
        else:
            self.lbl_explanation.setText("No analysis run yet.")

        # Load regions from SQLite
        self.current_regions = db.get_collection_regions(asset_id)
        self._populate_regions_table()

        # Load image into canvas
        orig_path = asset.get("original_path")
        self.canvas.load_image(orig_path, self.current_regions)
        self.selected_region = None
        self._update_detail_card()

    def _populate_regions_table(self):
        """Populate detected regions table."""
        self.tbl_regions.blockSignals(True)
        self.tbl_regions.setRowCount(len(self.current_regions))
        self.lbl_regions_count.setText(f"DETECTED CANDIDATE REGIONS ({len(self.current_regions)})")

        for row, reg in enumerate(self.current_regions):
            reg_id = reg.get("id")
            reg_type = reg.get("region_type", "isolated_asset")
            bw = reg.get("width", 0)
            bh = reg.get("height", 0)
            bx = reg.get("x", 0)
            by = reg.get("y", 0)

            item_id = QTableWidgetItem(f"#{row + 1}")
            item_id.setData(Qt.UserRole, reg_id)
            item_type = QTableWidgetItem(reg_type.replace("_", " ").title())
            item_size = QTableWidgetItem(f"{bw}×{bh}")
            item_pos = QTableWidgetItem(f"({bx},{by})")

            for it in (item_id, item_type, item_size, item_pos):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            self.tbl_regions.setItem(row, 0, item_id)
            self.tbl_regions.setItem(row, 1, item_type)
            self.tbl_regions.setItem(row, 2, item_size)
            self.tbl_regions.setItem(row, 3, item_pos)

        self.tbl_regions.blockSignals(False)

    def _on_canvas_region_selected(self, reg_dict: Dict[str, Any]):
        reg_id = reg_dict.get("id")
        self.selected_region = reg_dict

        # Highlight row in table
        for r in range(self.tbl_regions.rowCount()):
            item = self.tbl_regions.item(r, 0)
            if item and item.data(Qt.UserRole) == reg_id:
                self.tbl_regions.blockSignals(True)
                self.tbl_regions.selectRow(r)
                self.tbl_regions.blockSignals(False)
                break

        self._update_detail_card()

    def _on_canvas_region_deselected(self):
        self.selected_region = None
        self.tbl_regions.blockSignals(True)
        self.tbl_regions.clearSelection()
        self.tbl_regions.blockSignals(False)
        self._update_detail_card()

    def _on_table_selection_changed(self):
        selected_rows = self.tbl_regions.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        item = self.tbl_regions.item(row, 0)
        if item:
            reg_id = item.data(Qt.UserRole)
            self.canvas.select_region(reg_id)
            self.selected_region = next((r for r in self.current_regions if r.get("id") == reg_id), None)
            self._update_detail_card()

    def _update_detail_card(self):
        """Update spinboxes and crop preview for selected region."""
        if not self.selected_region:
            self.spn_x.setValue(0)
            self.spn_y.setValue(0)
            self.spn_w.setValue(10)
            self.spn_h.setValue(10)
            self.lbl_crop_preview.setPixmap(QPixmap())
            self.lbl_crop_preview.setText("No Region")
            return

        bx = self.selected_region.get("x", 0)
        by = self.selected_region.get("y", 0)
        bw = self.selected_region.get("width", 10)
        bh = self.selected_region.get("height", 10)
        reg_type = self.selected_region.get("region_type", "isolated_asset")

        self.spn_x.setValue(bx)
        self.spn_y.setValue(by)
        self.spn_w.setValue(bw)
        self.spn_h.setValue(bh)

        idx = self.cmb_region_type.findText(reg_type)
        if idx >= 0:
            self.cmb_region_type.setCurrentIndex(idx)

        # Generate crop thumbnail
        if self.current_asset:
            orig_path = self.current_asset.get("original_path")
            if orig_path and Path(orig_path).exists():
                try:
                    with Image.open(orig_path) as full_img:
                        crop = collection_splitter_engine.extract_region(full_img, bx, by, bw, bh, padding=0)
                        if crop.mode != "RGBA":
                            crop = crop.convert("RGBA")
                        data = crop.tobytes("raw", "RGBA")
                        qim = QImage(data, crop.width, crop.height, QImage.Format_RGBA8888)
                        pix = QPixmap.fromImage(qim).scaled(76, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.lbl_crop_preview.setPixmap(pix)
                        self.lbl_crop_preview.setText("")
                except Exception:
                    self.lbl_crop_preview.setText("Error")

    def _apply_region_edits(self):
        """Apply manual spinbox / type edits to current region."""
        if not self.selected_region or not self.current_asset:
            return

        reg_id = self.selected_region["id"]
        nx = self.spn_x.value()
        ny = self.spn_y.value()
        nw = self.spn_w.value()
        nh = self.spn_h.value()
        ntype = self.cmb_region_type.currentText()

        # Update in SQLite
        db.update_collection_region(reg_id, {
            "x": nx, "y": ny, "width": nw, "height": nh, "region_type": ntype
        })

        # Reload regions
        self.current_regions = db.get_collection_regions(self.current_asset["id"])
        self._populate_regions_table()
        self.canvas.set_regions(self.current_regions)
        self.canvas.select_region(reg_id)
        self.selected_region = next((r for r in self.current_regions if r.get("id") == reg_id), None)
        self._update_detail_card()

    def _delete_selected_region(self):
        """Delete currently selected region."""
        if not self.selected_region or not self.current_asset:
            return
        reg_id = self.selected_region["id"]
        self._on_region_deleted(reg_id)

    def _on_region_deleted(self, region_id: int):
        if not self.current_asset:
            return
        db.delete_collection_region(region_id)
        # Update candidate count on asset
        remaining = db.get_collection_regions(self.current_asset["id"])
        db.update_asset(self.current_asset["id"], {"splitter_candidate_count": len(remaining)})
        self.current_regions = remaining
        self._populate_regions_table()
        self.canvas.set_regions(remaining)
        self.selected_region = None
        self._update_detail_card()
        self.asset_updated.emit(self.current_asset["id"])

    def _on_new_region_drawn(self, x: int, y: int, w: int, h: int):
        """User manually dragged a candidate box on canvas."""
        if not self.current_asset:
            return

        new_id = db.add_collection_region(
            asset_id=self.current_asset["id"],
            x=x, y=y, width=w, height=h,
            region_type="manual_box",
            confidence_score=1.0,
            source_method="manual_user_box",
            review_status="confirmed",
        )

        remaining = db.get_collection_regions(self.current_asset["id"])
        db.update_asset(self.current_asset["id"], {
            "splitter_candidate_count": len(remaining),
            "splitter_composition_type": "Multiple Object Collection" if len(remaining) > 1 else "Single Object"
        })

        self.current_regions = remaining
        self._populate_regions_table()
        self.canvas.set_regions(remaining)
        self.canvas.select_region(new_id)
        self.selected_region = next((r for r in remaining if r.get("id") == new_id), None)
        self._update_detail_card()
        self.asset_updated.emit(self.current_asset["id"])

    def _on_region_modified(self, reg_id: int, x: int, y: int, w: int, h: int):
        """User resized/moved box interactively on canvas."""
        if not self.current_asset:
            return
        db.update_collection_region(reg_id, {"x": x, "y": y, "width": w, "height": h})
        self.current_regions = db.get_collection_regions(self.current_asset["id"])
        self._populate_regions_table()
        self.selected_region = next((r for r in self.current_regions if r.get("id") == reg_id), None)
        self._update_detail_card()

    def _enable_canvas_draw(self):
        self.canvas.set_draw_mode(True)

    def _on_composition_changed(self, idx: int):
        if not self.current_asset:
            return
        new_comp = self.cmb_composition.currentText()
        db.update_asset(self.current_asset["id"], {"splitter_composition_type": new_comp})
        self.asset_updated.emit(self.current_asset["id"])

    def _generate_sprite_grid(self):
        """Divide current asset into uniform sprite sheet grid."""
        if not self.current_asset:
            return

        cols = self.spn_cols.value()
        rows = self.spn_rows.value()
        margin = self.spn_margin.value()
        spacing = self.spn_spacing.value()

        w = self.current_asset.get("width", 0)
        h = self.current_asset.get("height", 0)
        if w <= 0 or h <= 0:
            QMessageBox.warning(self, "Invalid Dimensions", "Image dimensions are invalid.")
            return

        grid_boxes = collection_splitter_engine.generate_sprite_grid(
            image_width=w,
            image_height=h,
            cols=cols,
            rows=rows,
            margin_x=margin,
            margin_y=margin,
            spacing_x=spacing,
            spacing_y=spacing,
        )

        if not grid_boxes:
            QMessageBox.warning(self, "Grid Calculation Error", "Could not calculate valid grid with current parameters.")
            return

        # Replace existing regions with sprite sheet frames
        db.delete_collection_regions_for_asset(self.current_asset["id"])

        for idx, box in enumerate(grid_boxes):
            db.add_collection_region(
                asset_id=self.current_asset["id"],
                x=box["x"], y=box["y"], width=box["width"], height=box["height"],
                region_type="sprite_frame",
                confidence_score=0.95,
                source_method="sprite_grid_generator",
                review_status="pending",
            )

        db.update_asset(self.current_asset["id"], {
            "splitter_candidate_count": len(grid_boxes),
            "splitter_composition_type": "Sprite Sheet",
        })

        self.current_regions = db.get_collection_regions(self.current_asset["id"])
        self._populate_regions_table()
        self.canvas.set_regions(self.current_regions)
        self.selected_region = None
        self._update_detail_card()
        self.asset_updated.emit(self.current_asset["id"])

        QMessageBox.information(
            self,
            "Grid Generated",
            f"Successfully generated {len(grid_boxes)} sprite sheet frames ({cols}×{rows})."
        )

    def _open_extraction_preview(self):
        """Open the extraction preview modal dialog."""
        if not self.current_asset:
            QMessageBox.information(self, "No Asset", "Please select an asset first.")
            return

        if not self.current_regions:
            QMessageBox.information(
                self,
                "No Regions",
                "This image has no candidate regions to extract. Click '+ Add Box' or '⚡ Generate Grid Frames' first."
            )
            return

        dlg = ExtractionPreviewDialog(
            source_asset=self.current_asset,
            regions=self.current_regions,
            default_padding=8,
            parent=self.window(),
        )
        dlg.extraction_completed.connect(self._on_extraction_completed)
        dlg.exec()

    def _on_extraction_completed(self, summary: dict):
        asset_id = summary["source_asset_id"]
        self.current_asset = db.get_asset(asset_id)
        self.asset_updated.emit(asset_id)

    def _clear_all_regions(self):
        """Clear all detected regions for current asset."""
        if not self.current_asset:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Clear",
            "Are you sure you want to clear all candidate regions for this image?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            db.delete_collection_regions_for_asset(self.current_asset["id"])
            db.update_asset(self.current_asset["id"], {
                "splitter_candidate_count": 0,
                "splitter_composition_type": "Single Object"
            })
            self.current_regions = []
            self._populate_regions_table()
            self.canvas.set_regions([])
            self.selected_region = None
            self._update_detail_card()
            self.asset_updated.emit(self.current_asset["id"])

    def _reanalyze_current_asset(self):
        """Re-run collection splitter analysis on current asset."""
        if not self.current_asset:
            return

        success, comp_type, count, msg = collection_splitter_engine.process_and_save_asset(self.current_asset)
        self.current_asset = db.get_asset(self.current_asset["id"])
        self.load_asset(self.current_asset)
        self.asset_updated.emit(self.current_asset["id"])

        QMessageBox.information(
            self,
            "Re-Analysis Complete",
            f"Classified as: {comp_type}\nFound {count} candidate regions.\n{msg}"
        )

    def _btn_secondary_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['bg_card_hover']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_primary']};
                selection-background-color: {THEME_COLORS['accent_primary']};
                selection-color: {THEME_COLORS['text_inverse']};
            }}
        """

    def _spin_style(self) -> str:
        return f"""
            QSpinBox {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 2px 4px;
                font-size: 11px;
            }}
            QSpinBox:focus {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """
