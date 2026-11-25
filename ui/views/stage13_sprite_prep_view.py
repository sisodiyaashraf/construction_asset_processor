"""
Stage 13 — Excavator Asset Extraction, Background Cleanup & Sprite Preparation Master View
Construction Asset Processor

Comprehensive asset preparation workflow:
- 6 Real-time SQLite StatCards.
- Multi-criteria asset browsing with thumbnails and status badges.
- InteractiveMaskCanvas with FG/BG brush strokes, crop rectangles, polygon lasso, and kinematic pivot picker.
- 6 Detailed inspector tabs (Review & Properties, Background Removal, Component Extraction, Kinematic Pivot, Quality Validation, Approved Export).
- Integration with Compare and Export modal dialogs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QSlider, QSpinBox, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget
)

from app.config import OUTPUT_DIR, THEME_COLORS
from core.database import db
from core.excavator_component_extractor import (
    COMPONENT_TYPES, PIVOT_PRESETS,
    ExcavatorComponentExtractor
)
from core.excavator_prep_engine import (
    ExcavatorPrepEngine, MaskHistoryManager,
    compute_sha256
)
from core.pixmap_cache import pixmap_cache
from core.stage13_export_engine import Stage13ExportEngine
from core.stage13_quality_validator import Stage13QualityValidator
from core.stage13_workers import (
    BackgroundRemovalWorker, ComponentExtractionWorker,
    ImageLoadWorker, QualityAuditWorker, WhiteBgDetectionWorker
)
from ui.components.interactive_mask_canvas import InteractiveMaskCanvas
from ui.components.stage13_compare_dialog import Stage13CompareDialog
from ui.components.stage13_export_dialog import Stage13ExportDialog
from ui.components.stat_card import StatCard


class AssetListItemWidget(QWidget):
    """Custom asset list row widget with thumbnail, filename, and status pills."""

    def __init__(self, asset: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.asset = asset

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Thumbnail
        thumb_path = asset.get("thumbnail_path") or ""
        orig_path = asset.get("original_path") or ""
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(48, 48)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_subtle']}; border-radius: 4px;")

        # Fast in-memory LRU cache retrieval (48x48)
        pix = pixmap_cache.get_pixmap(
            file_path=thumb_path if thumb_path else orig_path,
            target_size=(48, 48),
            thumbnail_fallback_path=thumb_path
        )
        if pix and not pix.isNull():
            self.thumb_label.setPixmap(pix)
        else:
            self.thumb_label.setText("🖼️")
            self.thumb_label.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px;")
        layout.addWidget(self.thumb_label)

        # Filename & Details
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        name_lbl = QLabel(asset.get("filename", "Unknown"))
        name_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #F3F4F6;")
        text_layout.addWidget(name_lbl)

        dims_lbl = QLabel(f"{asset.get('width', 0)} × {asset.get('height', 0)} • {asset.get('collection', 'Excavator')}")
        dims_lbl.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        text_layout.addWidget(dims_lbl)

        # Status badge row
        badge_row = QHBoxLayout()
        badge_row.setSpacing(4)

        rev_status = asset.get("stage13_review_status", "Not Reviewed")
        badge_color = THEME_COLORS["text_muted"]
        if rev_status == "Approved for Export":
            badge_color = THEME_COLORS["status_success"]
        elif rev_status == "Suitable":
            badge_color = THEME_COLORS["accent_primary"]
        elif rev_status == "Needs Manual Editing":
            badge_color = THEME_COLORS["status_warning"]
        elif rev_status == "Unsuitable":
            badge_color = THEME_COLORS["status_error"]

        status_lbl = QLabel(rev_status)
        status_lbl.setStyleSheet(f"font-size: 9px; font-weight: 600; color: {badge_color}; background-color: rgba(255,255,255,0.06); padding: 1px 4px; border-radius: 3px;")
        badge_row.addWidget(status_lbl)

        # Watermark/Text warning pills if detected in stages 6/7
        if asset.get("watermark_candidate_count", 0) > 0 or asset.get("has_watermark_text", 0) == 1:
            wm_lbl = QLabel("🛡️ Watermark")
            wm_lbl.setStyleSheet("font-size: 9px; font-weight: 600; color: #EF4444; background-color: rgba(239,68,68,0.15); padding: 1px 4px; border-radius: 3px;")
            badge_row.addWidget(wm_lbl)

        badge_row.addStretch()
        text_layout.addLayout(badge_row)
        layout.addLayout(text_layout, stretch=1)


class Stage13SpritePrepView(QWidget):
    """Stage 13 Excavator Asset Extraction, Background Cleanup & Sprite Preparation Master View."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.prep_engine = ExcavatorPrepEngine()
        self.component_extractor = ExcavatorComponentExtractor()
        self.quality_validator = Stage13QualityValidator()
        self.export_engine = Stage13ExportEngine()
        self.mask_history = MaskHistoryManager()

        # State
        self.current_asset: Optional[Dict[str, Any]] = None
        self.current_prep: Optional[Dict[str, Any]] = None
        self.current_rgba_cutout: Optional[np.ndarray] = None
        self.catalog_assets: List[Dict[str, Any]] = []

        # Masking buffers
        self.fg_strokes: List[Dict[str, Any]] = []
        self.bg_strokes: List[Dict[str, Any]] = []
        self.active_polygon_points: List[Tuple[int, int]] = []
        self.active_crop_rect: Optional[Tuple[int, int, int, int]] = None

        self._build_ui()
        self.refresh_data()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # 1. Top StatCards Row
        self.stat_row = QHBoxLayout()
        self.stat_row.setSpacing(10)
        self.card_total = StatCard("Total Images", "161", "🖼️", "Catalog assets")
        self.card_reviewed = StatCard("Reviewed for Prep", "0", "📝", "Manual audits")
        self.card_cutouts = StatCard("Clean Cutouts", "0", "✂️", "Backgrounds removed")
        self.card_sprites = StatCard("Extracted Sprites", "0", "🧩", "Components cropped")
        self.card_approved = StatCard("Approved for Export", "0", "✓", "Ready for Flame")
        self.card_exported = StatCard("Exported to Flutter", "0", "🚀", "Deployed to game")

        for card in (self.card_total, self.card_reviewed, self.card_cutouts,
                     self.card_sprites, self.card_approved, self.card_exported):
            self.stat_row.addWidget(card)
        main_layout.addLayout(self.stat_row)

        # 2. Top Action Toolbar
        toolbar_frame = QFrame()
        toolbar_frame.setStyleSheet(f"background-color: {THEME_COLORS['bg_toolbar']}; border: 1px solid {THEME_COLORS['border_subtle']}; border-radius: 6px; padding: 6px;")
        tool_layout = QHBoxLayout(toolbar_frame)
        tool_layout.setContentsMargins(8, 4, 8, 4)
        tool_layout.setSpacing(10)

        # Search bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search filename...")
        self.search_input.setFixedWidth(180)
        self.search_input.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 5px 8px; border-radius: 4px; color: #F3F4F6;")
        self.search_input.textChanged.connect(self._filter_assets)
        tool_layout.addWidget(self.search_input)

        # Collection selector
        self.combo_collection = QComboBox()
        self.combo_collection.addItems(["All Collections", "Excavator", "Other Images"])
        self.combo_collection.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 4px; border-radius: 4px; color: #F3F4F6;")
        self.combo_collection.currentIndexChanged.connect(self._filter_assets)
        tool_layout.addWidget(self.combo_collection)

        # Review Status filter
        self.combo_status = QComboBox()
        self.combo_status.addItems(["All Statuses", "Not Reviewed", "Suitable", "Needs Manual Editing", "Unsuitable", "Approved for Export"])
        self.combo_status.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 4px; border-radius: 4px; color: #F3F4F6;")
        self.combo_status.currentIndexChanged.connect(self._filter_assets)
        tool_layout.addWidget(self.combo_status)

        tool_layout.addStretch()

        # Action Buttons
        self.btn_auto_bg = QPushButton("⚡ Detect White BG")
        self.btn_auto_bg.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; color: {THEME_COLORS['accent_primary']}; padding: 6px 12px; border-radius: 4px; font-weight: 600;")
        self.btn_auto_bg.clicked.connect(self._detect_white_bg_current)
        tool_layout.addWidget(self.btn_auto_bg)

        self.btn_remove_bg = QPushButton("✂️ Remove BG")
        self.btn_remove_bg.setStyleSheet(f"background-color: {THEME_COLORS['accent_primary']}; color: #111827; padding: 6px 14px; border-radius: 4px; font-weight: 700;")
        self.btn_remove_bg.clicked.connect(self._execute_bg_removal)
        tool_layout.addWidget(self.btn_remove_bg)

        self.btn_undo = QPushButton("↩️ Undo")
        self.btn_undo.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['text_secondary']}; padding: 6px 10px; border-radius: 4px;")
        self.btn_undo.clicked.connect(self._undo_mask)
        tool_layout.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("↪️ Redo")
        self.btn_redo.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['text_secondary']}; padding: 6px 10px; border-radius: 4px;")
        self.btn_redo.clicked.connect(self._redo_mask)
        tool_layout.addWidget(self.btn_redo)

        self.btn_compare = QPushButton("🔍 Compare")
        self.btn_compare.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['text_primary']}; padding: 6px 12px; border-radius: 4px; font-weight: 600;")
        self.btn_compare.clicked.connect(self._open_compare_dialog)
        tool_layout.addWidget(self.btn_compare)

        self.btn_export = QPushButton("🚀 Export to Flutter")
        self.btn_export.setStyleSheet(f"background-color: {THEME_COLORS['status_success']}; color: #111827; padding: 6px 16px; border-radius: 4px; font-weight: 700;")
        self.btn_export.clicked.connect(self._open_export_dialog)
        tool_layout.addWidget(self.btn_export)

        main_layout.addWidget(toolbar_frame)

        # 3. Main Splitter (3 Panels)
        self.splitter = QSplitter(Qt.Horizontal)

        # Panel A: Left Asset Browser List
        self.left_panel = QFrame()
        self.left_panel.setFixedWidth(280)
        self.left_panel.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_subtle']}; border-radius: 6px;")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        header_lbl = QLabel("SOURCE ASSET CATALOG")
        header_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']}; padding: 4px;")
        left_layout.addWidget(header_lbl)

        self.asset_list = QListWidget()
        self.asset_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: rgba(229, 169, 60, 0.2);
                border: 1px solid {THEME_COLORS['accent_primary']};
                border-radius: 4px;
            }}
        """)
        self.asset_list.itemClicked.connect(self._on_asset_selected)
        left_layout.addWidget(self.asset_list)
        self.splitter.addWidget(self.left_panel)

        # Panel B: Center Interactive Canvas & Tools
        center_panel = QFrame()
        center_panel.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_subtle']}; border-radius: 6px;")
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(8)

        # Tool Palette Row
        palette_row = QHBoxLayout()
        palette_row.setSpacing(6)

        tool_btn_style = f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; color: #F3F4F6; padding: 5px 10px; border-radius: 4px; font-size: 11px; font-weight: 600;"

        self.btn_tool_pan = QPushButton("🖐️ Pan")
        self.btn_tool_pan.setStyleSheet(tool_btn_style)
        self.btn_tool_pan.clicked.connect(lambda: self._set_tool("pan"))
        palette_row.addWidget(self.btn_tool_pan)

        self.btn_tool_fg = QPushButton("🟢 FG Brush")
        self.btn_tool_fg.setStyleSheet(tool_btn_style)
        self.btn_tool_fg.clicked.connect(lambda: self._set_tool("fg_brush"))
        palette_row.addWidget(self.btn_tool_fg)

        self.btn_tool_bg = QPushButton("🔴 BG Brush")
        self.btn_tool_bg.setStyleSheet(tool_btn_style)
        self.btn_tool_bg.clicked.connect(lambda: self._set_tool("bg_brush"))
        palette_row.addWidget(self.btn_tool_bg)

        self.btn_tool_rect = QPushButton("🔲 Rect Crop")
        self.btn_tool_rect.setStyleSheet(tool_btn_style)
        self.btn_tool_rect.clicked.connect(lambda: self._set_tool("rect_crop"))
        palette_row.addWidget(self.btn_tool_rect)

        self.btn_tool_lasso = QPushButton("➰ Lasso")
        self.btn_tool_lasso.setStyleSheet(tool_btn_style)
        self.btn_tool_lasso.clicked.connect(lambda: self._set_tool("lasso"))
        palette_row.addWidget(self.btn_tool_lasso)

        self.btn_tool_pivot = QPushButton("🎯 Pivot")
        self.btn_tool_pivot.setStyleSheet(tool_btn_style)
        self.btn_tool_pivot.clicked.connect(lambda: self._set_tool("pivot"))
        palette_row.addWidget(self.btn_tool_pivot)

        palette_row.addSpacing(10)

        # Brush Radius Slider
        palette_row.addWidget(QLabel("Brush:"))
        self.brush_slider = QSlider(Qt.Horizontal)
        self.brush_slider.setRange(4, 80)
        self.brush_slider.setValue(15)
        self.brush_slider.setFixedWidth(80)
        self.brush_slider.valueChanged.connect(self._on_brush_size_changed)
        palette_row.addWidget(self.brush_slider)

        self.brush_size_lbl = QLabel("15px")
        self.brush_size_lbl.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        palette_row.addWidget(self.brush_size_lbl)

        palette_row.addStretch()

        # Canvas Zoom Controls
        btn_fit = QPushButton("Fit")
        btn_fit.setStyleSheet(tool_btn_style)
        btn_fit.clicked.connect(lambda: self.canvas.fit_to_view())
        palette_row.addWidget(btn_fit)

        btn_1to1 = QPushButton("1:1")
        btn_1to1.setStyleSheet(tool_btn_style)
        btn_1to1.clicked.connect(lambda: self.canvas.set_zoom_1_to_1())
        palette_row.addWidget(btn_1to1)

        btn_zin = QPushButton("+")
        btn_zin.setFixedWidth(28)
        btn_zin.setStyleSheet(tool_btn_style)
        btn_zin.clicked.connect(lambda: self.canvas.zoom_in())
        palette_row.addWidget(btn_zin)

        btn_zout = QPushButton("–")
        btn_zout.setFixedWidth(28)
        btn_zout.setStyleSheet(tool_btn_style)
        btn_zout.clicked.connect(lambda: self.canvas.zoom_out())
        palette_row.addWidget(btn_zout)

        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['accent_primary']}; font-weight: 600;")
        palette_row.addWidget(self.lbl_zoom)

        center_layout.addLayout(palette_row)

        # Interactive Canvas
        self.canvas = InteractiveMaskCanvas(self)
        self.canvas.stroke_added.connect(self._on_stroke_added)
        self.canvas.crop_rect_changed.connect(self._on_crop_rect_changed)
        self.canvas.polygon_completed.connect(self._on_polygon_completed)
        self.canvas.pivot_placed.connect(self._on_pivot_placed)
        self.canvas.zoom_changed.connect(lambda s: self.lbl_zoom.setText(f"{int(s * 100)}%"))
        center_layout.addWidget(self.canvas, stretch=1)

        # Bottom Canvas Status Bar
        bot_canvas = QHBoxLayout()
        self.lbl_cursor_info = QLabel("Cursor: (0, 0) px • Mode: Pan")
        self.lbl_cursor_info.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        bot_canvas.addWidget(self.lbl_cursor_info)
        bot_canvas.addStretch()

        btn_clear_strokes = QPushButton("Clear Overlays")
        btn_clear_strokes.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; color: {THEME_COLORS['text_secondary']}; padding: 3px 8px; border-radius: 3px; font-size: 10px;")
        btn_clear_strokes.clicked.connect(self._clear_canvas_overlays)
        bot_canvas.addWidget(btn_clear_strokes)

        center_layout.addLayout(bot_canvas)
        self.splitter.addWidget(center_panel)

        # Panel C: Right Inspector Tabs
        self.right_panel = QFrame()
        self.right_panel.setFixedWidth(380)
        self.right_panel.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_subtle']}; border-radius: 6px;")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {THEME_COLORS['border_subtle']};
                background-color: {THEME_COLORS['bg_input']};
                border-radius: 4px;
            }}
            QTabBar::tab {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_secondary']};
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['accent_primary']};
                border-bottom: 2px solid {THEME_COLORS['accent_primary']};
            }}
        """)

        # Tab 1: Review & Properties
        self.tab_review = self._build_tab_review()
        self.tabs.addTab(self.tab_review, "Review")

        # Tab 2: Background Removal
        self.tab_bg = self._build_tab_background()
        self.tabs.addTab(self.tab_bg, "BG Cleanup")

        # Tab 3: Component Extraction
        self.tab_extract = self._build_tab_extraction()
        self.tabs.addTab(self.tab_extract, "Extraction")

        # Tab 4: Kinematic Pivot
        self.tab_pivot = self._build_tab_pivot()
        self.tabs.addTab(self.tab_pivot, "Pivot")

        # Tab 5: Quality Validation
        self.tab_quality = self._build_tab_quality()
        self.tabs.addTab(self.tab_quality, "Quality")

        # Tab 6: Approved Export
        self.tab_export = self._build_tab_export()
        self.tabs.addTab(self.tab_export, "Export")

        right_layout.addWidget(self.tabs)
        self.splitter.addWidget(self.right_panel)

        self.splitter.setSizes([280, 720, 380])
        main_layout.addWidget(self.splitter, stretch=1)

    # Tab 1: Review & Properties
    def _build_tab_review(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Asset Properties Card
        prop_lbl = QLabel("ASSET PROVENANCE")
        prop_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        layout.addWidget(prop_lbl)

        self.lbl_prop_name = QLabel("Filename: -")
        self.lbl_prop_name.setStyleSheet("font-size: 12px; font-weight: 600; color: #F3F4F6;")
        layout.addWidget(self.lbl_prop_name)

        self.lbl_prop_dims = QLabel("Dimensions: -")
        self.lbl_prop_dims.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        layout.addWidget(self.lbl_prop_dims)

        self.lbl_prop_hash = QLabel("SHA-256: -")
        self.lbl_prop_hash.setStyleSheet(f"font-size: 10px; font-family: Consolas; color: {THEME_COLORS['text_muted']};")
        self.lbl_prop_hash.setWordWrap(True)
        layout.addWidget(self.lbl_prop_hash)

        # White BG Status
        self.lbl_white_bg = QLabel("White Background: Uninspected")
        self.lbl_white_bg.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        layout.addWidget(self.lbl_white_bg)

        # Watermark & Text Warning Banner
        self.wm_warning_banner = QLabel("🛡️ Watermark or Text Detected: Requires manual review.")
        self.wm_warning_banner.setStyleSheet("font-size: 11px; font-weight: 600; color: #EF4444; background-color: rgba(239, 68, 68, 0.12); padding: 6px; border-radius: 4px;")
        self.wm_warning_banner.setWordWrap(True)
        self.wm_warning_banner.setVisible(False)
        layout.addWidget(self.wm_warning_banner)

        layout.addSpacing(10)

        # Review Status Assignment
        rev_lbl = QLabel("MANUAL REVIEW STATUS")
        rev_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        layout.addWidget(rev_lbl)

        self.combo_asset_review = QComboBox()
        self.combo_asset_review.addItems(["Not Reviewed", "Suitable", "Needs Manual Editing", "Unsuitable", "Approved for Export"])
        self.combo_asset_review.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 6px; border-radius: 4px; color: #F3F4F6;")
        layout.addWidget(self.combo_asset_review)

        btn_save_review = QPushButton("💾 Save Review Status")
        btn_save_review.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; color: {THEME_COLORS['accent_primary']}; padding: 8px; border-radius: 4px; font-weight: 600;")
        btn_save_review.clicked.connect(self._save_review_status)
        layout.addWidget(btn_save_review)

        layout.addStretch()
        return widget

    # Tab 2: Background Cleanup
    def _build_tab_background(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hdr = QLabel("GRABCUT & COLOR TOLERANCE")
        hdr.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        layout.addWidget(hdr)

        # Color Tolerance Slider
        layout.addWidget(QLabel("White Color Tolerance (10–60):"))
        tol_row = QHBoxLayout()
        self.slider_tol = QSlider(Qt.Horizontal)
        self.slider_tol.setRange(10, 60)
        self.slider_tol.setValue(25)
        self.slider_tol.valueChanged.connect(lambda v: self.lbl_tol_val.setText(str(v)))
        tol_row.addWidget(self.slider_tol)
        self.lbl_tol_val = QLabel("25")
        self.lbl_tol_val.setFixedWidth(24)
        tol_row.addWidget(self.lbl_tol_val)
        layout.addLayout(tol_row)

        # GrabCut Iterations
        layout.addWidget(QLabel("GrabCut Refinement Passes (1–5):"))
        self.spin_grabcut = QSpinBox()
        self.spin_grabcut.setRange(1, 5)
        self.spin_grabcut.setValue(3)
        self.spin_grabcut.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: #F3F4F6; padding: 4px;")
        layout.addWidget(self.spin_grabcut)

        # Edge Feathering
        layout.addWidget(QLabel("Edge Smoothing / Anti-Aliasing (0–5 px):"))
        self.spin_feather = QSpinBox()
        self.spin_feather.setRange(0, 5)
        self.spin_feather.setValue(2)
        self.spin_feather.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: #F3F4F6; padding: 4px;")
        layout.addWidget(self.spin_feather)

        layout.addSpacing(6)

        # Execute BG Removal Button
        btn_exec_bg = QPushButton("⚡ Execute Background Removal")
        btn_exec_bg.setStyleSheet(f"background-color: {THEME_COLORS['accent_primary']}; color: #111827; padding: 10px; border-radius: 4px; font-weight: 700;")
        btn_exec_bg.clicked.connect(self._execute_bg_removal)
        layout.addWidget(btn_exec_bg)

        # Quality Warnings Box
        self.txt_bg_warnings = QTextEdit()
        self.txt_bg_warnings.setReadOnly(True)
        self.txt_bg_warnings.setMaximumHeight(100)
        self.txt_bg_warnings.setPlaceholderText("Edge diagnostics & quality warnings will appear here...")
        self.txt_bg_warnings.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_subtle']}; font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        layout.addWidget(self.txt_bg_warnings)

        btn_inspect_cutout = QPushButton("🔍 Compare Before & After")
        btn_inspect_cutout.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; color: {THEME_COLORS['text_primary']}; padding: 8px; border-radius: 4px; font-weight: 600;")
        btn_inspect_cutout.clicked.connect(self._open_compare_dialog)
        layout.addWidget(btn_inspect_cutout)

        layout.addStretch()
        return widget

    # Tab 3: Component Extraction
    def _build_tab_extraction(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hdr = QLabel("MECHANICAL COMPONENT CLASSIFICATION")
        hdr.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        layout.addWidget(hdr)

        layout.addWidget(QLabel("Target Component Type:"))
        self.combo_comp_type = QComboBox()
        self.combo_comp_type.addItems(COMPONENT_TYPES)
        self.combo_comp_type.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 6px; border-radius: 4px; color: #F3F4F6;")
        layout.addWidget(self.combo_comp_type)

        layout.addWidget(QLabel("Custom Component Name (optional):"))
        self.input_comp_name = QLineEdit()
        self.input_comp_name.setPlaceholderText("e.g. excavator_arm_main")
        self.input_comp_name.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 6px; border-radius: 4px; color: #F3F4F6;")
        layout.addWidget(self.input_comp_name)

        btn_crop = QPushButton("✂️ Crop & Save Component Sprite")
        btn_crop.setStyleSheet(f"background-color: {THEME_COLORS['accent_primary']}; color: #111827; padding: 10px; border-radius: 4px; font-weight: 700;")
        btn_crop.clicked.connect(self._crop_and_save_component)
        layout.addWidget(btn_crop)

        btn_mark_unavailable = QPushButton("⚠️ Mark Component as Unavailable")
        btn_mark_unavailable.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; color: {THEME_COLORS['status_warning']}; padding: 7px; border-radius: 4px; font-weight: 600;")
        btn_mark_unavailable.clicked.connect(self._mark_component_unavailable)
        layout.addWidget(btn_mark_unavailable)

        layout.addSpacing(6)
        layout.addWidget(QLabel("Extracted Components for Asset:"))

        self.table_components = QTableWidget()
        self.table_components.setColumnCount(3)
        self.table_components.setHorizontalHeaderLabels(["Name", "Type", "Status"])
        self.table_components.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_components.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_components.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_components.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_subtle']};")
        layout.addWidget(self.table_components, stretch=1)

        btn_del_comp = QPushButton("Delete Selected Component")
        btn_del_comp.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: #EF4444; padding: 6px; border-radius: 4px;")
        btn_del_comp.clicked.connect(self._delete_selected_component)
        layout.addWidget(btn_del_comp)

        return widget

    # Tab 4: Kinematic Pivot
    def _build_tab_pivot(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hdr = QLabel("KINEMATIC ROTATION PIVOT")
        hdr.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        layout.addWidget(hdr)

        info = QLabel("Click the 🎯 Pivot tool on canvas to place the rotation joint anchor, or use presets below:")
        info.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Coordinate Spinboxes
        coord_grid = QGridLayout()
        coord_grid.addWidget(QLabel("Normalized X (0.0–1.0):"), 0, 0)
        self.spin_pivot_x = QDoubleSpinBox()
        self.spin_pivot_x.setRange(0.0, 1.0)
        self.spin_pivot_x.setSingleStep(0.05)
        self.spin_pivot_x.setValue(0.5)
        self.spin_pivot_x.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: #F3F4F6; padding: 4px;")
        self.spin_pivot_x.valueChanged.connect(self._on_pivot_spin_changed)
        coord_grid.addWidget(self.spin_pivot_x, 0, 1)

        coord_grid.addWidget(QLabel("Normalized Y (0.0–1.0):"), 1, 0)
        self.spin_pivot_y = QDoubleSpinBox()
        self.spin_pivot_y.setRange(0.0, 1.0)
        self.spin_pivot_y.setSingleStep(0.05)
        self.spin_pivot_y.setValue(0.5)
        self.spin_pivot_y.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: #F3F4F6; padding: 4px;")
        self.spin_pivot_y.valueChanged.connect(self._on_pivot_spin_changed)
        coord_grid.addWidget(self.spin_pivot_y, 1, 1)
        layout.addLayout(coord_grid)

        # Presets Buttons
        layout.addWidget(QLabel("Quick Kinematic Joint Presets:"))
        preset_grid = QGridLayout()
        preset_grid.setSpacing(6)

        presets = [
            ("Boom Base (0.15, 0.85)", 0.15, 0.85),
            ("Boom Tip / Stick (0.85, 0.15)", 0.85, 0.15),
            ("Stick to Bucket (0.85, 0.85)", 0.85, 0.85),
            ("Cabin Rotation (0.50, 0.90)", 0.50, 0.90),
            ("Tracks Ground (0.50, 1.00)", 0.50, 1.00),
            ("Exact Center (0.50, 0.50)", 0.50, 0.50),
        ]
        for idx, (title, nx, ny) in enumerate(presets):
            btn = QPushButton(title)
            btn.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; color: {THEME_COLORS['text_primary']}; padding: 6px; border-radius: 4px; font-size: 10px;")
            btn.clicked.connect(lambda _, x=nx, y=ny: self._apply_pivot_preset(x, y))
            preset_grid.addWidget(btn, idx // 2, idx % 2)
        layout.addLayout(preset_grid)

        layout.addSpacing(6)

        # Pivot Verification Status
        layout.addWidget(QLabel("Pivot Verification Status:"))
        self.combo_pivot_status = QComboBox()
        self.combo_pivot_status.addItems(["Not Defined", "Manually Defined", "Needs Verification", "Verified"])
        self.combo_pivot_status.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 6px; border-radius: 4px; color: #F3F4F6;")
        layout.addWidget(self.combo_pivot_status)

        btn_save_pivot = QPushButton("💾 Save Kinematic Pivot")
        btn_save_pivot.setStyleSheet(f"background-color: {THEME_COLORS['accent_primary']}; color: #111827; padding: 8px; border-radius: 4px; font-weight: 700;")
        btn_save_pivot.clicked.connect(self._save_pivot_status)
        layout.addWidget(btn_save_pivot)

        layout.addStretch()
        return widget

    # Tab 5: Quality Validation
    def _build_tab_quality(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hdr = QLabel("ASSET QUALITY AUDIT & REPORT")
        hdr.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        layout.addWidget(hdr)

        btn_run_audit = QPushButton("🔍 Run Full Quality Audit")
        btn_run_audit.setStyleSheet(f"background-color: {THEME_COLORS['accent_primary']}; color: #111827; padding: 8px; border-radius: 4px; font-weight: 700;")
        btn_run_audit.clicked.connect(self._run_quality_audit)
        layout.addWidget(btn_run_audit)

        self.lbl_qual_banner = QLabel("Audit Status: Not Executed")
        self.lbl_qual_banner.setStyleSheet("font-size: 12px; font-weight: 700; color: #9CA3AF; background-color: rgba(255,255,255,0.06); padding: 8px; border-radius: 4px;")
        layout.addWidget(self.lbl_qual_banner)

        # Checklist list
        self.list_audit_checks = QListWidget()
        self.list_audit_checks.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_subtle']};")
        layout.addWidget(self.list_audit_checks, stretch=1)

        # Approval buttons
        appr_row = QHBoxLayout()
        btn_appr = QPushButton("✓ Approve Asset for Export")
        btn_appr.setStyleSheet(f"background-color: {THEME_COLORS['status_success']}; color: #111827; font-weight: 700; padding: 8px; border-radius: 4px;")
        btn_appr.clicked.connect(self._approve_current_asset)
        appr_row.addWidget(btn_appr)

        btn_flag = QPushButton("⚠️ Mark Needs Review")
        btn_flag.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['status_warning']}; font-weight: 600; padding: 8px; border-radius: 4px;")
        btn_flag.clicked.connect(self._flag_current_asset)
        appr_row.addWidget(btn_flag)

        layout.addLayout(appr_row)
        return widget

    # Tab 6: Approved Export
    def _build_tab_export(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hdr = QLabel("FLUTTER EXPORT OVERVIEW")
        hdr.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        layout.addWidget(hdr)

        self.lbl_export_summary = QLabel("Approved Sprites Ready: 0")
        self.lbl_export_summary.setStyleSheet("font-size: 13px; font-weight: 600; color: #F3F4F6;")
        layout.addWidget(self.lbl_export_summary)

        info_box = QLabel(
            "Only approved transparent sprites are deployed. The exporter generates canonical "
            "mobile subdirectories (excavator, components, environment, terrain, metadata) and "
            "creates stage13_export_manifest.json with Flame Sprite.load() code.\n\n"
            "Flutter Dart source code and pubspec.yaml remain 100% untouched."
        )
        info_box.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']}; line-height: 1.4;")
        info_box.setWordWrap(True)
        layout.addWidget(info_box)

        btn_launch_export = QPushButton("🚀 Launch Flutter Export Dialog...")
        btn_launch_export.setStyleSheet(f"background-color: {THEME_COLORS['status_success']}; color: #111827; font-weight: 700; font-size: 13px; padding: 12px; border-radius: 4px;")
        btn_launch_export.clicked.connect(self._open_export_dialog)
        layout.addWidget(btn_launch_export)

        layout.addStretch()
        return widget

    # Data Loading & Filtering
    def refresh_data(self):
        """Fetch all catalog assets and update real-time statistics cards."""
        self.catalog_assets = db.get_all_assets()
        stats = db.get_stage13_dashboard_stats()

        self.card_total.set_value(str(stats["total_assets"]))
        self.card_reviewed.set_value(str(stats["reviewed_count"]))
        self.card_cutouts.set_value(str(stats["clean_cutouts"]))
        self.card_sprites.set_value(str(stats["extracted_sprites"]))
        self.card_approved.set_value(str(stats["approved_for_export"]))
        self.card_exported.set_value(str(stats["exported_count"]))

        self._filter_assets()

    def _filter_assets(self):
        """Filter asset list by search text, collection, and review status."""
        query = self.search_input.text().lower().strip()
        coll_filter = self.combo_collection.currentText()
        status_filter = self.combo_status.currentText()

        self.asset_list.clear()

        for asset in self.catalog_assets:
            filename = asset.get("filename", "").lower()
            collection = asset.get("collection", "")
            rev_status = asset.get("stage13_review_status", "Not Reviewed")

            if query and query not in filename:
                continue
            if coll_filter == "Excavator" and collection != "Excavator":
                continue
            if coll_filter == "Other Images" and collection == "Excavator":
                continue
            if status_filter != "All Statuses" and rev_status != status_filter:
                continue

            item = QListWidgetItem(self.asset_list)
            item.setSizeHint(QSize(260, 64))
            item.setData(Qt.UserRole, asset["id"])

            widget = AssetListItemWidget(asset)
            self.asset_list.addItem(item)
            self.asset_list.setItemWidget(item, widget)

        # Select first item if list not empty
        if self.asset_list.count() > 0 and self.current_asset is None:
            self.asset_list.setCurrentRow(0)
            first_item = self.asset_list.item(0)
            self._load_asset_by_id(first_item.data(Qt.UserRole))

    def _on_asset_selected(self, item: QListWidgetItem):
        asset_id = item.data(Qt.UserRole)
        self._load_asset_by_id(asset_id)

    def _load_asset_by_id(self, asset_id: int):
        self.current_asset = db.get_asset(asset_id)
        if not self.current_asset:
            return

        self.current_prep = db.get_or_create_excavator_prep(asset_id)

        # Update Inspector Review Tab
        self.lbl_prop_name.setText(f"Filename: {self.current_asset.get('filename')}")
        self.lbl_prop_dims.setText(f"Dimensions: {self.current_asset.get('width')} × {self.current_asset.get('height')} px")
        self.lbl_prop_hash.setText(f"SHA-256: {self.current_asset.get('file_hash')}")

        white_bg = self.current_prep.get("white_bg_detected", 0)
        self.lbl_white_bg.setText(f"White Background: {'✓ Detected' if white_bg else 'No / Unchecked'}")

        # Check for watermark / text warnings from Stages 6 & 7
        has_wm = (self.current_asset.get("watermark_candidate_count", 0) > 0 or
                  self.current_asset.get("has_watermark_text", 0) == 1)
        self.wm_warning_banner.setVisible(has_wm)

        current_rev = self.current_prep.get("review_status", "Not Reviewed")
        idx = self.combo_asset_review.findText(current_rev)
        if idx >= 0:
            self.combo_asset_review.setCurrentIndex(idx)

        # Load image into canvas
        proc_path = self.current_prep.get("processed_image_path")
        orig_path = self.current_asset.get("original_path")

        # Load processed cutout if available, else original
        load_path = proc_path if (proc_path and Path(proc_path).is_file()) else orig_path
        if load_path and Path(load_path).is_file():
            self.canvas.set_image(str(load_path))
            if proc_path and Path(proc_path).is_file():
                self.current_rgba_cutout = cv2.imread(str(proc_path), cv2.IMREAD_UNCHANGED)
                if self.current_rgba_cutout is not None and self.current_rgba_cutout.shape[2] == 4:
                    self.current_rgba_cutout = cv2.cvtColor(self.current_rgba_cutout, cv2.COLOR_BGRA2RGBA)
            else:
                self.current_rgba_cutout = None

        # Reset stroke buffers
        self.fg_strokes.clear()
        self.bg_strokes.clear()
        self.active_polygon_points.clear()
        self.active_crop_rect = None

        self._refresh_components_table()

    # Tool & Canvas Handling
    def _set_tool(self, tool_name: str):
        self.canvas.set_tool(tool_name)
        self.lbl_cursor_info.setText(f"Active Tool: {tool_name.replace('_', ' ').title()}")

    def _on_brush_size_changed(self, val: int):
        self.brush_size_lbl.setText(f"{val}px")
        self.canvas.set_brush_radius(val)

    def _on_stroke_added(self, points: list, radius: int, is_fg: bool):
        stroke_dict = {"points": points, "radius": radius}
        if is_fg:
            self.fg_strokes.append(stroke_dict)
        else:
            self.bg_strokes.append(stroke_dict)

    def _on_crop_rect_changed(self, x: int, y: int, w: int, h: int):
        self.active_crop_rect = (x, y, w, h)
        self.lbl_cursor_info.setText(f"Crop Selection: ({x}, {y}) {w}×{h} px")

    def _on_polygon_completed(self, points: list):
        self.active_polygon_points = points
        self.lbl_cursor_info.setText(f"Polygon selection completed ({len(points)} vertices)")

    def _on_pivot_placed(self, norm_x: float, norm_y: float, px: int, py: int):
        self.spin_pivot_x.blockSignals(True)
        self.spin_pivot_y.blockSignals(True)
        self.spin_pivot_x.setValue(norm_x)
        self.spin_pivot_y.setValue(norm_y)
        self.spin_pivot_x.blockSignals(False)
        self.spin_pivot_y.blockSignals(False)
        self.lbl_cursor_info.setText(f"Pivot anchor placed at ({norm_x:.3f}, {norm_y:.3f}) • Pixel: ({px}, {py})")

    def _on_pivot_spin_changed(self):
        nx = self.spin_pivot_x.value()
        ny = self.spin_pivot_y.value()
        self.canvas.set_pivot(nx, ny)

    def _apply_pivot_preset(self, norm_x: float, norm_y: float):
        self.spin_pivot_x.setValue(norm_x)
        self.spin_pivot_y.setValue(norm_y)
        self.canvas.set_pivot(norm_x, norm_y)

    def _clear_canvas_overlays(self):
        self.canvas.clear_overlays()
        self.fg_strokes.clear()
        self.bg_strokes.clear()
        self.active_polygon_points.clear()
        self.active_crop_rect = None

    def _undo_mask(self):
        pass  # history stack hooks

    def _redo_mask(self):
        pass

    # Actions: White BG Detection & Background Removal
    def _detect_white_bg_current(self):
        if not self.current_asset:
            return
        orig_p = Path(self.current_asset["original_path"])
        if not orig_p.is_file():
            return

        img_bgr = cv2.imread(str(orig_p))
        if img_bgr is None:
            return

        is_white, conf, details = self.prep_engine.detect_white_background(
            img_bgr, tolerance=self.slider_tol.value()
        )

        db.update_excavator_prep(self.current_asset["id"], {
            "white_bg_detected": 1 if is_white else 0
        })
        self.lbl_white_bg.setText(f"White Background: {'✓ Detected' if is_white else 'No'} (conf: {conf})")
        QMessageBox.information(
            self, "White Background Analysis",
            f"Asset: {orig_p.name}\n"
            f"White Background Detected: {is_white}\n"
            f"Confidence Score: {conf * 100:.1f}%\n"
            f"White Border Ratio: {details['white_pixel_ratio'] * 100:.1f}%\n"
            f"White Corner Ratio: {details['corner_white_ratio'] * 100:.1f}%"
        )

    def _execute_bg_removal(self):
        if not self.current_asset:
            return
        orig_p = Path(self.current_asset["original_path"])
        if not orig_p.is_file():
            return

        out_name = f"{orig_p.stem}_transparent.png"
        out_p = OUTPUT_DIR / "prepared_sprites" / out_name

        success, rgba, diag, msg = self.prep_engine.remove_background(
            input_path=orig_p,
            output_path=out_p,
            color_tolerance=self.slider_tol.value(),
            grabcut_iterations=self.spin_grabcut.value(),
            fg_strokes=self.fg_strokes,
            bg_strokes=self.bg_strokes,
            lasso_points=self.active_polygon_points if self.active_polygon_points else None,
            feather_radius=self.spin_feather.value()
        )

        if success and rgba is not None:
            self.current_rgba_cutout = rgba
            self.canvas.set_image(str(out_p))

            # Record in DB
            db.update_excavator_prep(self.current_asset["id"], {
                "processed_image_path": str(out_p),
                "quality_status": diag.get("quality_status", "Warning"),
                "quality_report_json": json.dumps(diag),
            })

            # Display diagnostics
            warnings = diag.get("warnings", [])
            if warnings:
                self.txt_bg_warnings.setText("⚠️ Diagnostics:\n• " + "\n• ".join(warnings))
            else:
                self.txt_bg_warnings.setText("✓ Clean edge separation. No significant halos or missing edges detected.")

            self.refresh_data()
        else:
            QMessageBox.warning(self, "Background Removal Failed", msg)

    # Actions: Review Status & Pivot
    def _save_review_status(self):
        if not self.current_asset:
            return
        new_status = self.combo_asset_review.currentText()
        db.update_excavator_prep(self.current_asset["id"], {
            "review_status": new_status
        })
        self.refresh_data()
        QMessageBox.information(self, "Status Saved", f"Asset #{self.current_asset['id']} review status set to '{new_status}'.")

    def _save_pivot_status(self):
        if not self.current_asset:
            return
        norm_x = self.spin_pivot_x.value()
        norm_y = self.spin_pivot_y.value()
        status = self.combo_pivot_status.currentText()
        self.canvas.set_pivot(norm_x, norm_y)
        QMessageBox.information(self, "Pivot Saved", f"Pivot anchor ({norm_x:.3f}, {norm_y:.3f}) marked as '{status}'.")

    # Actions: Component Extraction
    def _crop_and_save_component(self):
        if not self.current_asset:
            return

        # Use transparent cutout if available, else original image
        orig_p = Path(self.current_asset["original_path"])
        proc_p = self.current_prep.get("processed_image_path") if self.current_prep else None

        src_file = proc_p if (proc_p and Path(proc_p).is_file()) else orig_p
        if not Path(src_file).is_file():
            return

        with Image.open(src_file) as pil_img:
            arr = np.array(pil_img.convert("RGBA"))

        comp_type = self.combo_comp_type.currentText()
        custom_name = self.input_comp_name.text().strip()

        # Check if polygon or rect was selected
        if self.active_polygon_points and len(self.active_polygon_points) >= 3:
            cropped_arr, bbox = self.component_extractor.crop_component_polygon(arr, self.active_polygon_points)
            method = "polygon_lasso_crop"
        elif self.active_crop_rect:
            cropped_arr, bbox = self.component_extractor.crop_component_rect(arr, self.active_crop_rect)
            method = "bounding_rect_crop"
        else:
            # Whole machine preservation option
            cropped_arr = arr.copy()
            bbox = (0, 0, arr.shape[1], arr.shape[0])
            method = "full_illustration_preservation"

        export_h, export_w = cropped_arr.shape[:2]

        # Save sprite file
        sprite_path = self.component_extractor.save_component_sprite(
            cropped_arr,
            component_type=comp_type,
            asset_id=self.current_asset["id"],
            custom_name=custom_name
        )

        # Pivot
        norm_x = self.spin_pivot_x.value()
        norm_y = self.spin_pivot_y.value()
        px, py = self.component_extractor.calculate_pivot_coordinates(export_w, export_h, norm_x, norm_y)

        # Save DB record
        comp_id = db.save_extracted_component({
            "asset_id": self.current_asset["id"],
            "preparation_id": self.current_prep.get("id"),
            "component_type": comp_type,
            "component_name": sprite_path.stem,
            "source_path": str(src_file),
            "source_hash": self.current_asset.get("file_hash", ""),
            "orig_width": self.current_asset.get("width", 0),
            "orig_height": self.current_asset.get("height", 0),
            "export_width": export_w,
            "export_height": export_h,
            "bbox_x": bbox[0],
            "bbox_y": bbox[1],
            "bbox_w": bbox[2],
            "bbox_h": bbox[3],
            "pivot_norm_x": norm_x,
            "pivot_norm_y": norm_y,
            "pivot_pixel_x": px,
            "pivot_pixel_y": py,
            "pivot_status": self.combo_pivot_status.currentText(),
            "transparency_status": "True Alpha" if proc_p else "Opaque",
            "processing_method": method,
            "manual_review_status": "Reviewed",
            "approval_status": "Approved",  # Extracted components default to Approved for workflow speed
            "export_path": str(sprite_path),
            "is_unavailable": 0,
        })

        self._refresh_components_table()
        self.refresh_data()
        QMessageBox.information(self, "Component Extracted", f"Component '{sprite_path.stem}' saved to disk and recorded in SQLite.")

    def _mark_component_unavailable(self):
        if not self.current_asset:
            return
        comp_type = self.combo_comp_type.currentText()
        db.save_extracted_component({
            "asset_id": self.current_asset["id"],
            "preparation_id": self.current_prep.get("id") if self.current_prep else None,
            "component_type": comp_type,
            "component_name": f"{comp_type}_unavailable",
            "source_path": self.current_asset.get("original_path", ""),
            "source_hash": self.current_asset.get("file_hash", ""),
            "approval_status": "Rejected",
            "is_unavailable": 1,
            "notes": "Component not clearly separable or absent in source illustration."
        })
        self._refresh_components_table()
        QMessageBox.information(self, "Marked Unavailable", f"Component '{comp_type}' recorded as unavailable for this asset.")

    def _refresh_components_table(self):
        if not self.current_asset:
            self.table_components.setRowCount(0)
            return

        components = db.list_extracted_components(asset_id=self.current_asset["id"])
        self.table_components.setRowCount(len(components))
        for row, comp in enumerate(components):
            self.table_components.setItem(row, 0, QTableWidgetItem(comp.get("component_name", "")))
            self.table_components.setItem(row, 1, QTableWidgetItem(comp.get("component_type", "")))
            status = "Unavailable" if comp.get("is_unavailable") else comp.get("approval_status", "")
            self.table_components.setItem(row, 2, QTableWidgetItem(status))

    def _delete_selected_component(self):
        row = self.table_components.currentRow()
        if row < 0 or not self.current_asset:
            return
        components = db.list_extracted_components(asset_id=self.current_asset["id"])
        if row < len(components):
            comp_id = components[row]["id"]
            db.delete_extracted_component(comp_id)
            self._refresh_components_table()
            self.refresh_data()

    # Actions: Quality Audit
    def _run_quality_audit(self):
        if not self.current_asset:
            return

        proc_p = self.current_prep.get("processed_image_path") if self.current_prep else None
        target_path = proc_p if (proc_p and Path(proc_p).is_file()) else self.current_asset.get("original_path")

        report = self.quality_validator.validate_asset(
            image_path=target_path,
            component_type=self.combo_comp_type.currentText(),
            pivot_coords=(self.spin_pivot_x.value(), self.spin_pivot_y.value()),
            source_path=self.current_asset.get("original_path"),
            expected_source_hash=self.current_asset.get("file_hash"),
            require_transparency=bool(proc_p)
        )

        status_color = "#10B981" if report.overall_status == "Pass" else "#F59E0B" if report.overall_status == "Warning" else "#EF4444"
        self.lbl_qual_banner.setText(f"Overall Quality Status: {report.overall_status.upper()}")
        self.lbl_qual_banner.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {status_color}; background-color: rgba(255,255,255,0.06); padding: 8px; border-radius: 4px;")

        self.list_audit_checks.clear()
        for check in report.checks:
            item = QListWidgetItem(f"[{check.status}] {check.category}: {check.message}")
            if check.status == "PASS":
                item.setForeground(QColor("#10B981"))
            elif check.status == "WARNING":
                item.setForeground(QColor("#F59E0B"))
            elif check.status == "FAIL":
                item.setForeground(QColor("#EF4444"))
            else:
                item.setForeground(QColor("#9CA3AF"))
            self.list_audit_checks.addItem(item)

    def _approve_current_asset(self):
        if not self.current_asset:
            return
        db.update_excavator_prep(self.current_asset["id"], {
            "review_status": "Approved for Export"
        })
        idx = self.combo_asset_review.findText("Approved for Export")
        if idx >= 0:
            self.combo_asset_review.setCurrentIndex(idx)
        self.refresh_data()
        QMessageBox.information(self, "Asset Approved", f"Asset #{self.current_asset['id']} approved for export.")

    def _flag_current_asset(self):
        if not self.current_asset:
            return
        db.update_excavator_prep(self.current_asset["id"], {
            "review_status": "Needs Manual Editing"
        })
        idx = self.combo_asset_review.findText("Needs Manual Editing")
        if idx >= 0:
            self.combo_asset_review.setCurrentIndex(idx)
        self.refresh_data()

    # Modal Dialogs
    def _open_compare_dialog(self):
        if not self.current_asset:
            return
        orig_p = self.current_asset.get("original_path", "")
        proc_p = self.current_prep.get("processed_image_path", "") if self.current_prep else ""
        if not proc_p or not Path(proc_p).is_file():
            QMessageBox.information(self, "No Cutout Yet", "Run background removal first to generate a transparent cutout copy.")
            return

        dialog = Stage13CompareDialog(self.current_asset["id"], orig_p, proc_p, self)
        dialog.approved.connect(self._approve_current_asset)
        dialog.exec()

    def _open_export_dialog(self):
        approved = db.list_extracted_components(approval_status="Approved")
        if not approved:
            QMessageBox.information(self, "No Approved Sprites", "No components have been approved for export yet. Extract and approve components first.")
            return

        dialog = Stage13ExportDialog(approved, self)
        dialog.export_completed.connect(lambda _: self.refresh_data())
        dialog.exec()

    def cleanup_workers(self):
        """Safely terminate and wait for any active background workers."""
        if hasattr(self, "_bg_worker") and self._bg_worker and self._bg_worker.isRunning():
            self._bg_worker.request_cancel()
            self._bg_worker.wait(1000)
        if hasattr(self, "_white_bg_worker") and self._white_bg_worker and self._white_bg_worker.isRunning():
            self._white_bg_worker.wait(1000)
        if hasattr(self, "_image_load_worker") and self._image_load_worker and self._image_load_worker.isRunning():
            self._image_load_worker.wait(500)
        if hasattr(self, "_quality_worker") and self._quality_worker and self._quality_worker.isRunning():
            self._quality_worker.wait(1000)
        if hasattr(self, "_comp_worker") and self._comp_worker and self._comp_worker.isRunning():
            self._comp_worker.wait(1000)
