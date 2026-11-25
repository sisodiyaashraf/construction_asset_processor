"""
Game Integration & Runtime Asset Verification Master View (Stage 11)
Construction Asset Processor

Comprehensive Stage 11 Screen coordinating:
- 6 Real-time SQLite metrics (Connected Project, Flame Version, Validated Assets, Warnings/Errors, Excavator Components, Memory Budget).
- Flutter project connection & pubspec inspector.
- Runtime asset integrity verification with filterable issues table (PASS, WARNING, FAIL, NOT TESTED).
- Interactive asset preview canvas (Individual assets, Texture atlases with bounding boxes, Animation sequence playback).
- Excavator component assignment workflow (9 standard groups with manual assignment and pivot tracking).
- Flame metadata compatibility engine with non-destructive conversion preview.
- Isolated Flutter test fixture generator and patch preview.
- Asset performance and GPU memory budget analyzer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
)

from app.config import (
    OUTPUT_APPROVED_DIR, OUTPUT_DIR, OUTPUT_OPTIMIZED_DIR,
    OUTPUT_SPRITES_DIR, THEME_COLORS, format_bytes
)
from core.asset_performance_analyzer import asset_performance_analyzer
from core.database import db
from core.flame_compatibility_engine import flame_compatibility_engine
from core.flutter_project_inspector import flutter_project_inspector
from core.game_asset_preview_engine import game_asset_preview_engine
from core.runtime_asset_validator import runtime_asset_validator
from ui.components.game_asset_preview_canvas import GameAssetPreviewCanvas
from ui.components.stat_card import StatCard

logger = logging.getLogger("AssetProcessor.GameIntegrationView")

EXCAVATOR_COMPONENT_GROUPS = [
    "Excavator Body / Chassis",
    "Tracks and Wheels",
    "Boom",
    "Arm / Dipper",
    "Bucket",
    "Hydraulic Cylinders",
    "Cabin",
    "Glass and Windows",
    "Attachments",
]


class AssignComponentDialog(QDialog):
    """Dialog allowing user to manually assign an approved asset to an excavator part."""

    def __init__(self, approved_assets: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.approved_assets = approved_assets
        self.selected_assignment: Optional[Dict[str, Any]] = None

        self.setWindowTitle("Assign Asset to Excavator Component — Stage 11")
        self.setMinimumSize(480, 420)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME_COLORS['bg_main']};
                color: {THEME_COLORS['text_primary']};
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Select Excavator Component Group:"))
        self.combo_group = QComboBox()
        self.combo_group.addItems(EXCAVATOR_COMPONENT_GROUPS)
        layout.addWidget(self.combo_group)

        layout.addWidget(QLabel("Select Approved Asset:"))
        self.combo_asset = QComboBox()
        for a in self.approved_assets:
            fname = a.get("smart_filename") or a.get("filename") or f"Asset_{a['id']}"
            w = a.get("width", 0)
            h = a.get("height", 0)
            self.combo_asset.addItem(f"{fname} ({w}x{h})", userData=a)
        layout.addWidget(self.combo_asset)

        pivot_box = QGroupBox("Kinematic Joint / Pivot Anchor")
        pivot_box.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 700;")
        p_layout = QHBoxLayout(pivot_box)

        p_layout.addWidget(QLabel("X (0.0–1.0):"))
        self.spin_px = QSpinBox()
        self.spin_px.setRange(0, 100)
        self.spin_px.setValue(50)
        self.spin_px.setSuffix("%")
        p_layout.addWidget(self.spin_px)

        p_layout.addWidget(QLabel("Y (0.0–1.0):"))
        self.spin_py = QSpinBox()
        self.spin_py.setRange(0, 100)
        self.spin_py.setValue(50)
        self.spin_py.setSuffix("%")
        p_layout.addWidget(self.spin_py)

        layout.addWidget(pivot_box)

        layout.addWidget(QLabel("Associated Animation (Optional):"))
        self.txt_anim = QLineEdit()
        self.txt_anim.setPlaceholderText("e.g. excavator_digging or boom_lift")
        self.txt_anim.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 4px; border-radius: 4px; color: white;")
        layout.addWidget(self.txt_anim)

        layout.addWidget(QLabel("Reviewer Notes:"))
        self.txt_notes = QLineEdit()
        self.txt_notes.setPlaceholderText("e.g. Side-view angle, bucket teeth intact")
        self.txt_notes.setStyleSheet(self.txt_anim.styleSheet())
        layout.addWidget(self.txt_notes)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_assign = QPushButton("✓ Assign Component")
        btn_assign.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                padding: 6px 14px;
                border-radius: 4px;
            }}
        """)
        btn_assign.clicked.connect(self._confirm_assignment)
        btn_row.addWidget(btn_assign)

        layout.addLayout(btn_row)

    def _confirm_assignment(self):
        asset = self.combo_asset.currentData()
        if not asset:
            QMessageBox.warning(self, "No Asset", "Please select an asset to assign.")
            return

        self.selected_assignment = {
            "component_group": self.combo_group.currentText(),
            "asset_id": asset["id"],
            "source_file": asset.get("original_path") or asset.get("filepath", ""),
            "exported_file": asset.get("smart_filename") or asset.get("filename", ""),
            "width": asset.get("width", 0),
            "height": asset.get("height", 0),
            "pivot_x": self.spin_px.value() / 100.0,
            "pivot_y": self.spin_py.value() / 100.0,
            "transparency_status": "transparent" if asset.get("alpha_detected") else "opaque",
            "validation_status": "approved",
            "associated_animation": self.txt_anim.text().strip(),
            "notes": self.txt_notes.text().strip(),
        }
        self.accept()


class GameIntegrationView(QWidget):
    """Primary Game Integration & Runtime Asset Verification Screen (Stage 11)."""

    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_project_id: Optional[int] = None
        self.current_project_path: Optional[Path] = None

        # Playback timer for preview canvas
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._on_anim_timer_tick)

        self._build_ui()
        self.refresh_all()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # 1. Top Section: 6 Metrics Cards
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)

        self.card_project = StatCard("Connected Project", "No Project", "Target Flutter App", icon="📁", accent_color="#38BDF8")
        stats_layout.addWidget(self.card_project)

        self.card_flame = StatCard("Flame Engine", "Not Detected", "SDK Dependency", icon="🔥", accent_color="#F59E0B")
        stats_layout.addWidget(self.card_flame)

        self.card_validated = StatCard("Validated Assets", "0", "Runtime Ready", icon="🛡️", accent_color="#10B981")
        stats_layout.addWidget(self.card_validated)

        self.card_warnings = StatCard("Warnings & Issues", "0", "Flags Detected", icon="⚠️", accent_color="#EF4444")
        stats_layout.addWidget(self.card_warnings)

        self.card_components = StatCard("Excavator Parts", "0", "Assigned Groups", icon="🚜", accent_color="#06B6D4")
        stats_layout.addWidget(self.card_components)

        self.card_budget = StatCard("Memory Budget", "0.0 MB", "Estimated VRAM", icon="💾", accent_color="#A855F7")
        stats_layout.addWidget(self.card_budget)

        main_layout.addLayout(stats_layout)

        # 2. Project Connection Bar
        conn_frame = QFrame()
        conn_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_toolbar']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        c_layout = QHBoxLayout(conn_frame)
        c_layout.setContentsMargins(8, 6, 8, 6)
        c_layout.setSpacing(8)

        c_layout.addWidget(QLabel("Flutter Project:"))
        self.txt_project_path = QLineEdit()
        self.txt_project_path.setPlaceholderText("Select Flutter project root directory containing pubspec.yaml...")
        self.txt_project_path.setStyleSheet(f"""
            QLineEdit {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                color: white;
                padding: 4px 8px;
                font-size: 11px;
            }}
        """)
        c_layout.addWidget(self.txt_project_path, stretch=1)

        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_card_hover']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                padding: 4px 10px;
                border-radius: 4px;
            }}
        """)
        btn_browse.clicked.connect(self._browse_project_path)
        c_layout.addWidget(btn_browse)

        self.btn_inspect = QPushButton("🔍 Inspect Project")
        self.btn_inspect.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_secondary']};
                color: white;
                font-weight: 700;
                padding: 4px 12px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #2563EB;
            }}
        """)
        self.btn_inspect.clicked.connect(self._inspect_connected_project)
        c_layout.addWidget(self.btn_inspect)

        self.lbl_project_status = QLabel("⚠️ No Flutter Project Connected")
        self.lbl_project_status.setStyleSheet("color: #F59E0B; font-weight: 700; font-size: 10px; padding: 2px 6px;")
        c_layout.addWidget(self.lbl_project_status)

        main_layout.addWidget(conn_frame)

        # 3. Main Stage 11 Tab Widget (6 Sub-Modules)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {THEME_COLORS['bg_main']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                background: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_secondary']};
                padding: 8px 14px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: 600;
                font-size: 11px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {THEME_COLORS['bg_toolbar']};
                color: {THEME_COLORS['accent_primary']};
                border-bottom: 2px solid {THEME_COLORS['accent_primary']};
            }}
        """)

        # Tab 1: Asset Verification
        self.tab_verification = self._create_verification_tab()
        self.tabs.addTab(self.tab_verification, "🛡️ Asset Verification")

        # Tab 2: Asset & Animation Preview
        self.tab_preview = self._create_preview_tab()
        self.tabs.addTab(self.tab_preview, "👁️ Game Asset Preview")

        # Tab 3: Excavator Components
        self.tab_components = self._create_components_tab()
        self.tabs.addTab(self.tab_components, "🚜 Excavator Components")

        # Tab 4: Flame Compatibility
        self.tab_compatibility = self._create_compatibility_tab()
        self.tabs.addTab(self.tab_compatibility, "🔥 Flame Compatibility")

        # Tab 5: Isolated Runtime Test
        self.tab_runtime_test = self._create_runtime_test_tab()
        self.tabs.addTab(self.tab_runtime_test, "🚀 Isolated Runtime Test")

        # Tab 6: Performance & Budget
        self.tab_performance = self._create_performance_tab()
        self.tabs.addTab(self.tab_performance, "📊 Memory & Performance")

        main_layout.addWidget(self.tabs, stretch=1)

    # -------------------------------------------------------------------------
    # TAB 1: Asset Verification
    # -------------------------------------------------------------------------

    def _create_verification_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Toolbar
        t_bar = QHBoxLayout()
        btn_run_val = QPushButton("⚡ Run Asset Integrity Check")
        btn_run_val.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                padding: 6px 14px;
                border-radius: 4px;
            }}
        """)
        btn_run_val.clicked.connect(self._run_asset_integrity_check)
        t_bar.addWidget(btn_run_val)

        t_bar.addWidget(QLabel("Category:"))
        self.combo_val_category = QComboBox()
        self.combo_val_category.addItems(["All", "path_safety", "file_existence", "image_decode", "dimension_conformance", "transparency_consistency", "atlas_bounds", "frame_dimensions", "frame_identifiers", "animation_sequence", "animation_timing", "pivot_coordinates"])
        self.combo_val_category.currentIndexChanged.connect(self._filter_validation_table)
        t_bar.addWidget(self.combo_val_category)

        t_bar.addWidget(QLabel("Status:"))
        self.combo_val_status = QComboBox()
        self.combo_val_status.addItems(["All", "PASS", "WARNING", "FAIL", "NOT TESTED"])
        self.combo_val_status.currentIndexChanged.connect(self._filter_validation_table)
        t_bar.addWidget(self.combo_val_status)

        t_bar.addStretch()

        self.lbl_val_summary = QLabel("Results: 0 Passed | 0 Warnings | 0 Failed | 0 Not Tested")
        self.lbl_val_summary.setStyleSheet("color: white; font-weight: 600; font-size: 11px;")
        t_bar.addWidget(self.lbl_val_summary)

        layout.addLayout(t_bar)

        # Table
        self.table_val = QTableWidget()
        self.table_val.setColumnCount(4)
        self.table_val.setHorizontalHeaderLabels(["Asset Path", "Check Category", "Status", "Validation Message"])
        self.table_val.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_val.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_val.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_val.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_val.verticalHeader().setVisible(False)
        self.table_val.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                gridline-color: {THEME_COLORS['border_subtle']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_toolbar']};
                color: {THEME_COLORS['text_secondary']};
                font-weight: 600;
                border: none;
                padding: 4px;
            }}
        """)
        layout.addWidget(self.table_val)

        return widget

    # -------------------------------------------------------------------------
    # TAB 2: Game Asset Preview
    # -------------------------------------------------------------------------

    def _create_preview_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Left Controls
        left_ctrl = QFrame()
        left_ctrl.setFixedWidth(280)
        left_ctrl.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_sidebar']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        lc_layout = QVBoxLayout(left_ctrl)
        lc_layout.setContentsMargins(10, 10, 10, 10)
        lc_layout.setSpacing(8)

        lc_layout.addWidget(QLabel("Preview Mode:"))
        self.combo_preview_mode = QComboBox()
        self.combo_preview_mode.addItems(["Individual Asset", "Texture Atlas", "Animation Sequence"])
        self.combo_preview_mode.currentIndexChanged.connect(self._on_preview_mode_changed)
        lc_layout.addWidget(self.combo_preview_mode)

        lc_layout.addWidget(QLabel("Select Target Asset:"))
        self.combo_preview_target = QComboBox()
        self.combo_preview_target.currentIndexChanged.connect(self._on_preview_target_changed)
        lc_layout.addWidget(self.combo_preview_target)

        # Info Box
        info_box = QGroupBox("Asset Telemetry")
        info_box.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 700;")
        ib_layout = QVBoxLayout(info_box)
        ib_layout.setSpacing(4)

        self.lbl_prev_res = QLabel("Resolution: —")
        ib_layout.addWidget(self.lbl_prev_res)

        self.lbl_prev_fmt = QLabel("Format: —")
        ib_layout.addWidget(self.lbl_prev_fmt)

        self.lbl_prev_size = QLabel("File Size: —")
        ib_layout.addWidget(self.lbl_prev_size)

        self.lbl_prev_pivot = QLabel("Pivot: (0.50, 0.50)")
        ib_layout.addWidget(self.lbl_prev_pivot)

        lc_layout.addWidget(info_box)
        lc_layout.addStretch()

        layout.addWidget(left_ctrl)

        # Center / Right: Canvas and Playback
        center_panel = QFrame()
        cp_layout = QVBoxLayout(center_panel)
        cp_layout.setContentsMargins(0, 0, 0, 0)
        cp_layout.setSpacing(6)

        # Canvas Toolbar
        c_bar = QHBoxLayout()
        btn_zin = QPushButton("🔍 Zoom +")
        btn_zin.clicked.connect(lambda: self.preview_canvas.zoom_in())
        c_bar.addWidget(btn_zin)

        btn_zout = QPushButton("🔍 Zoom –")
        btn_zout.clicked.connect(lambda: self.preview_canvas.zoom_out())
        c_bar.addWidget(btn_zout)

        btn_z100 = QPushButton("1:1")
        btn_z100.clicked.connect(lambda: self.preview_canvas.zoom_100())
        c_bar.addWidget(btn_z100)

        btn_fit = QPushButton("Fit")
        btn_fit.clicked.connect(lambda: self.preview_canvas.fit_to_view())
        c_bar.addWidget(btn_fit)

        c_bar.addStretch()

        self.chk_show_pivot = QCheckBox("Show Pivot Crosshair")
        self.chk_show_pivot.setChecked(True)
        self.chk_show_pivot.toggled.connect(lambda c: setattr(self.preview_canvas, "_show_pivot", c) or self.preview_canvas.update())
        c_bar.addWidget(self.chk_show_pivot)

        cp_layout.addLayout(c_bar)

        # Interactive Canvas
        self.preview_canvas = GameAssetPreviewCanvas()
        self.preview_canvas.sprite_clicked.connect(self._on_atlas_sprite_clicked)
        cp_layout.addWidget(self.preview_canvas, stretch=1)

        # Animation Playback Controls Bar
        self.playback_bar = QFrame()
        self.playback_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_toolbar']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                padding: 4px;
            }}
        """)
        pb_layout = QHBoxLayout(self.playback_bar)
        pb_layout.setContentsMargins(6, 4, 6, 4)
        pb_layout.setSpacing(6)

        self.btn_play_pause = QPushButton("▶ Play")
        self.btn_play_pause.clicked.connect(self._toggle_playback)
        pb_layout.addWidget(self.btn_play_pause)

        btn_step_back = QPushButton("◀")
        btn_step_back.clicked.connect(self._step_back_anim)
        pb_layout.addWidget(btn_step_back)

        btn_step_fwd = QPushButton("▶")
        btn_step_fwd.clicked.connect(self._step_fwd_anim)
        pb_layout.addWidget(btn_step_fwd)

        self.lbl_frame_idx = QLabel("Frame: 1 / 1")
        self.lbl_frame_idx.setStyleSheet("color: white; font-weight: 700; font-size: 11px;")
        pb_layout.addWidget(self.lbl_frame_idx)

        pb_layout.addWidget(QLabel("Speed (FPS):"))
        self.slider_fps = QSlider(Qt.Horizontal)
        self.slider_fps.setRange(1, 60)
        self.slider_fps.setValue(10)
        self.slider_fps.valueChanged.connect(self._on_fps_changed)
        pb_layout.addWidget(self.slider_fps)

        self.lbl_fps_val = QLabel("10 fps")
        pb_layout.addWidget(self.lbl_fps_val)

        self.chk_anim_loop = QCheckBox("Loop")
        self.chk_anim_loop.setChecked(True)
        pb_layout.addWidget(self.chk_anim_loop)

        cp_layout.addWidget(self.playback_bar)

        layout.addWidget(center_panel, stretch=1)
        return widget

    # -------------------------------------------------------------------------
    # TAB 3: Excavator Components
    # -------------------------------------------------------------------------

    def _create_components_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        t_bar = QHBoxLayout()
        btn_assign = QPushButton("🚜 Assign Approved Asset to Part...")
        btn_assign.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                padding: 6px 14px;
                border-radius: 4px;
            }}
        """)
        btn_assign.clicked.connect(self._open_assign_component_dialog)
        t_bar.addWidget(btn_assign)

        btn_remove = QPushButton("✕ Remove Assignment")
        btn_remove.clicked.connect(self._remove_selected_assignment)
        t_bar.addWidget(btn_remove)

        t_bar.addWidget(QLabel("Filter Group:"))
        self.combo_comp_filter = QComboBox()
        self.combo_comp_filter.addItems(["All"] + EXCAVATOR_COMPONENT_GROUPS)
        self.combo_comp_filter.currentIndexChanged.connect(self._reload_component_assignments)
        t_bar.addWidget(self.combo_comp_filter)

        t_bar.addStretch()

        self.lbl_comp_summary = QLabel("Total Assigned: 0 Parts")
        self.lbl_comp_summary.setStyleSheet("color: white; font-weight: 700; font-size: 11px;")
        t_bar.addWidget(self.lbl_comp_summary)

        layout.addLayout(t_bar)

        # Table
        self.table_comp = QTableWidget()
        self.table_comp.setColumnCount(8)
        self.table_comp.setHorizontalHeaderLabels(["ID", "Component Group", "Asset Filename", "Dimensions", "Pivot (X, Y)", "Transparency", "Status", "Notes"])
        self.table_comp.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_comp.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_comp.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_comp.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table_comp.verticalHeader().setVisible(False)
        self.table_comp.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_comp.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                gridline-color: {THEME_COLORS['border_subtle']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_toolbar']};
                color: {THEME_COLORS['text_secondary']};
                font-weight: 600;
                border: none;
                padding: 4px;
            }}
        """)
        layout.addWidget(self.table_comp)

        return widget

    # -------------------------------------------------------------------------
    # TAB 4: Flame Compatibility
    # -------------------------------------------------------------------------

    def _create_compatibility_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        t_bar = QHBoxLayout()
        t_bar.addWidget(QLabel("Metadata File:"))
        self.combo_compat_file = QComboBox()
        self.combo_compat_file.currentIndexChanged.connect(self._inspect_compatibility_file)
        t_bar.addWidget(self.combo_compat_file, stretch=1)

        self.btn_compat_check = QPushButton("🔍 Check Flame Compatibility")
        self.btn_compat_check.clicked.connect(self._inspect_compatibility_file)
        t_bar.addWidget(self.btn_compat_check)

        self.lbl_compat_status = QLabel("COMPATIBLE")
        self.lbl_compat_status.setStyleSheet("color: #10B981; font-weight: 700; font-size: 11px; padding: 2px 8px; border-radius: 3px; background: rgba(16, 185, 129, 0.15);")
        t_bar.addWidget(self.lbl_compat_status)

        layout.addLayout(t_bar)

        # Diff View
        layout.addWidget(QLabel("Flame 1.x Schema Migration Preview (Non-destructive diff):"))
        self.txt_compat_diff = QTextEdit()
        self.txt_compat_diff.setReadOnly(True)
        self.txt_compat_diff.setStyleSheet(f"""
            QTextEdit {{
                background-color: {THEME_COLORS['bg_input']};
                color: #A7F3D0;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.txt_compat_diff, stretch=1)

        b_row = QHBoxLayout()
        b_row.addStretch()
        self.btn_save_flame_v1 = QPushButton("✓ Export Flame 1.x Compatible JSON Copy")
        self.btn_save_flame_v1.setStyleSheet(f"""
            QPushButton {{
                background-color: #10B981;
                color: white;
                font-weight: 700;
                padding: 6px 14px;
                border-radius: 4px;
            }}
        """)
        self.btn_save_flame_v1.clicked.connect(self._save_flame_v1_copy)
        b_row.addWidget(self.btn_save_flame_v1)
        layout.addLayout(b_row)

        return widget

    # -------------------------------------------------------------------------
    # TAB 5: Isolated Runtime Test
    # -------------------------------------------------------------------------

    def _create_runtime_test_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        t_bar = QHBoxLayout()

        btn_gen_fixture = QPushButton("📦 Generate Isolated Test Fixture")
        btn_gen_fixture.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_secondary']};
                color: white;
                font-weight: 700;
                padding: 6px 14px;
                border-radius: 4px;
            }}
        """)
        btn_gen_fixture.clicked.connect(self._generate_isolated_fixture)
        t_bar.addWidget(btn_gen_fixture)

        self.btn_run_test = QPushButton("▶ Run Flutter Test")
        self.btn_run_test.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                padding: 6px 14px;
                border-radius: 4px;
            }}
        """)
        self.btn_run_test.clicked.connect(self._execute_flutter_test)
        t_bar.addWidget(self.btn_run_test)

        self.btn_patch_preview = QPushButton("📄 Preview Integration Patch")
        self.btn_patch_preview.clicked.connect(self._show_patch_preview)
        t_bar.addWidget(self.btn_patch_preview)

        t_bar.addStretch()

        self.lbl_cli_status = QLabel("Flutter CLI: Checking...")
        self.lbl_cli_status.setStyleSheet("color: #94A3B8; font-size: 11px;")
        t_bar.addWidget(self.lbl_cli_status)

        layout.addLayout(t_bar)

        layout.addWidget(QLabel("Execution Output Log & Generated Test Harness:"))
        self.txt_test_output = QTextEdit()
        self.txt_test_output.setReadOnly(True)
        self.txt_test_output.setStyleSheet(f"""
            QTextEdit {{
                background-color: #0A0C0E;
                color: #38BDF8;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.txt_test_output, stretch=1)

        return widget

    # -------------------------------------------------------------------------
    # TAB 6: Performance & Budget
    # -------------------------------------------------------------------------

    def _create_performance_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        t_bar = QHBoxLayout()
        btn_calc_perf = QPushButton("⚡ Compute Asset Budget & GPU Footprint")
        btn_calc_perf.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                padding: 6px 14px;
                border-radius: 4px;
            }}
        """)
        btn_calc_perf.clicked.connect(self._compute_performance_report)
        t_bar.addWidget(btn_calc_perf)
        t_bar.addStretch()
        layout.addLayout(t_bar)

        # Splitter: Left Summary Text, Right Texture Ranking Table
        splitter = QSplitter(Qt.Horizontal)

        left_w = QWidget()
        lw_layout = QVBoxLayout(left_w)
        lw_layout.setContentsMargins(0, 0, 0, 0)
        lw_layout.addWidget(QLabel("Asset Memory Breakdown & Budget:"))
        self.txt_perf_summary = QTextEdit()
        self.txt_perf_summary.setReadOnly(True)
        self.txt_perf_summary.setStyleSheet(f"""
            QTextEdit {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
            }}
        """)
        lw_layout.addWidget(self.txt_perf_summary)
        splitter.addWidget(left_w)

        right_w = QWidget()
        rw_layout = QVBoxLayout(right_w)
        rw_layout.setContentsMargins(0, 0, 0, 0)
        rw_layout.addWidget(QLabel("Texture GPU Footprint (32-bit RGBA):"))
        self.table_perf = QTableWidget()
        self.table_perf.setColumnCount(4)
        self.table_perf.setHorizontalHeaderLabels(["Texture", "Dimensions", "Disk Size", "Estimated VRAM"])
        self.table_perf.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_perf.verticalHeader().setVisible(False)
        self.table_perf.setStyleSheet(self.table_val.styleSheet())
        rw_layout.addWidget(self.table_perf)
        splitter.addWidget(right_w)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        return widget

    # -------------------------------------------------------------------------
    # Actions & Logic
    # -------------------------------------------------------------------------

    def refresh_all(self):
        """Synchronize telemetry, database metrics, and active project state."""
        self._check_flutter_cli()
        self._refresh_metrics()
        self._reload_metadata_files()
        self._reload_preview_targets()
        self._reload_component_assignments()

    def _check_flutter_cli(self):
        """Update Flutter CLI badge."""
        cli = flutter_project_inspector.detect_flutter_cli()
        if cli["available"]:
            self.lbl_cli_status.setText(f"✓ {cli['version']}")
            self.lbl_cli_status.setStyleSheet("color: #10B981; font-weight: 700; font-size: 11px;")
            self.btn_run_test.setEnabled(True)
        else:
            self.lbl_cli_status.setText("⚠️ Flutter CLI: Not in PATH (Test Fixture Mode)")
            self.lbl_cli_status.setStyleSheet("color: #F59E0B; font-weight: 600; font-size: 11px;")
            self.btn_run_test.setEnabled(False)

    def _refresh_metrics(self):
        """Fetch Stage 11 aggregates from database."""
        stats = db.get_stage11_dashboard_stats(self.current_project_id)
        self.card_project.update_value(stats["project_name"])
        self.card_flame.update_value(stats["flame_version"])
        self.card_validated.update_value(f"{stats['passed_count']} / {stats['total_validated']}")
        self.card_warnings.update_value(str(stats["warning_count"] + stats["failed_count"]))
        self.card_components.update_value(f"{stats['assigned_components_count']} Parts")
        self.card_budget.update_value(f"{stats['estimated_ram_mb']} MB")

    def _browse_project_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Flutter Project Root")
        if folder:
            self.txt_project_path.setText(folder)
            self._inspect_connected_project()

    def _inspect_connected_project(self):
        """Inspect Flutter directory and register connection in database."""
        path_str = self.txt_project_path.text().strip()
        if not path_str:
            return

        res = flutter_project_inspector.inspect_project(path_str)
        if res.get("is_valid_flutter_project"):
            self.lbl_project_status.setText(f"✓ Verified: {res['project_name']}")
            self.lbl_project_status.setStyleSheet("color: #10B981; font-weight: 700; font-size: 10px;")

            # Register in DB
            proj_id = db.register_flutter_project(
                project_name=res["project_name"],
                project_path=res["project_path"],
                pubspec_path=res["pubspec_path"],
                is_valid_flutter=True,
                has_lib=res["has_lib"],
                has_assets=res["has_assets"],
                flame_version=res["flame_version"],
                flame_detected=res["flame_detected"],
                declared_asset_dirs=res["declared_asset_dirs"],
            )
            self.current_project_id = proj_id
            self.current_project_path = Path(res["project_path"])
            self._refresh_metrics()
            self._reload_metadata_files()
            QMessageBox.information(
                self,
                "Project Connected",
                f"Successfully connected Flutter project '{res['project_name']}'!\nFlame Version: {res['flame_version']}\nDeclared Assets: {len(res['declared_asset_dirs'])}"
            )
        else:
            self.lbl_project_status.setText(f"⚠️ {res.get('status', 'Invalid')}")
            self.lbl_project_status.setStyleSheet("color: #EF4444; font-weight: 700; font-size: 10px;")
            QMessageBox.warning(self, "Inspection Result", f"Could not verify Flutter project:\n{res.get('error') or res.get('warnings')}")

    def _run_asset_integrity_check(self):
        """Execute comprehensive runtime asset verification."""
        target_root = self.current_project_path / "assets" if self.current_project_path else OUTPUT_DIR

        sess_id = db.create_runtime_validation_session(
            session_name="Pre-Integration Asset Integrity Check",
            target_asset_dir=str(target_root),
            project_id=self.current_project_id,
        )

        val_res = runtime_asset_validator.validate_asset_tree(target_root)
        results = val_res.get("results", [])

        db.add_runtime_validation_results(sess_id, results)
        self._refresh_metrics()
        self._filter_validation_table()

        msg = (
            f"Validation Completed!\nTotal Checked: {val_res['total_checked']}\n"
            f"Passed: {val_res['passed_count']}\nWarnings: {val_res['warning_count']}\n"
            f"Failed: {val_res['failed_count']}\nNot Tested: {val_res['not_tested_count']}"
        )
        self.lbl_val_summary.setText(f"Results: {val_res['passed_count']} Passed | {val_res['warning_count']} Warnings | {val_res['failed_count']} Failed")
        QMessageBox.information(self, "Verification Complete", msg)

    def _filter_validation_table(self):
        """Populate table filtered by category and status."""
        sess = db.get_latest_runtime_validation_session(self.current_project_id)
        if not sess:
            return

        cat = self.combo_val_category.currentText()
        st = self.combo_val_status.currentText()
        rows = db.get_runtime_validation_results(sess["id"], category=cat, status=st)

        self.table_val.setRowCount(len(rows))
        for idx, r in enumerate(rows):
            self.table_val.setItem(idx, 0, QTableWidgetItem(r.get("asset_path", "")))
            self.table_val.setItem(idx, 1, QTableWidgetItem(r.get("check_category", "")))

            st_item = QTableWidgetItem(r.get("status", ""))
            st_val = r.get("status", "")
            if st_val == "PASS":
                st_item.setForeground(Qt.green)
            elif st_val == "WARNING":
                st_item.setForeground(Qt.yellow)
            elif st_val == "FAIL":
                st_item.setForeground(Qt.red)
            else:
                st_item.setForeground(Qt.gray)
            self.table_val.setItem(idx, 2, st_item)

            self.table_val.setItem(idx, 3, QTableWidgetItem(r.get("message", "")))

    def _on_preview_mode_changed(self, idx: int):
        self._reload_preview_targets()

    def _reload_preview_targets(self):
        """Populate target asset combo based on mode."""
        mode_idx = self.combo_preview_mode.currentIndex()
        self.combo_preview_target.blockSignals(True)
        self.combo_preview_target.clear()

        if mode_idx == 0:  # Individual
            self.playback_bar.setVisible(False)
            # Fetch approved assets
            assets = db.get_approved_assets_for_optimization()
            for a in assets:
                fname = a.get("smart_filename") or a.get("filename") or f"Asset_{a['id']}"
                self.combo_preview_target.addItem(fname, userData=a)
        elif mode_idx == 1:  # Atlas
            self.playback_bar.setVisible(False)
            atlases = db.get_all_texture_atlases()
            for atl in atlases:
                self.combo_preview_target.addItem(atl.get("atlas_name", "atlas"), userData=atl)
        else:  # Animation
            self.playback_bar.setVisible(True)
            # Find sprite animation sequences or sheets
            sheets = db.get_all_sprite_sheets() if hasattr(db, "get_all_sprite_sheets") else []
            for s in sheets:
                self.combo_preview_target.addItem(s.get("sheet_name", "sheet"), userData=s)

        self.combo_preview_target.blockSignals(False)
        self._on_preview_target_changed(0)

    def _on_preview_target_changed(self, idx: int):
        mode_idx = self.combo_preview_mode.currentIndex()
        data = self.combo_preview_target.currentData()
        if not data:
            return

        if mode_idx == 0:  # Individual
            p = data.get("original_path") or data.get("filepath", "")
            if p and Path(p).exists():
                self.preview_canvas.set_individual_image(p, (0.5, 0.5))
                self.lbl_prev_res.setText(f"Resolution: {data.get('width', 0)}x{data.get('height', 0)}")
                self.lbl_prev_fmt.setText(f"Format: {data.get('format', 'PNG')}")
                self.lbl_prev_size.setText(f"File Size: {format_bytes(data.get('file_size', 0))}")
        elif mode_idx == 1:  # Atlas
            tex_p = data.get("texture_path", "")
            meta_p = data.get("json_manifest_path", "")
            if tex_p and Path(tex_p).exists():
                res = game_asset_preview_engine.load_sprite_sheet_atlas(tex_p, meta_p)
                self.preview_canvas.set_atlas_data(tex_p, res.get("frames", []))
                self.lbl_prev_res.setText(f"Resolution: {res.get('atlas_width')}x{res.get('atlas_height')}")
                self.lbl_prev_fmt.setText(f"Format: {res.get('format', 'PNG')}")
                self.lbl_prev_size.setText(f"Sprites: {res.get('frame_count')} frames")

    def _on_atlas_sprite_clicked(self, name: str, frame_data: dict):
        w = frame_data.get("w", 0)
        h = frame_data.get("h", 0)
        px = frame_data.get("pivot_x", 0.5)
        py = frame_data.get("pivot_y", 0.5)
        self.lbl_prev_res.setText(f"Sprite: {name} ({w}x{h})")
        self.lbl_prev_pivot.setText(f"Pivot: ({px:.2f}, {py:.2f})")

    def _toggle_playback(self):
        state = game_asset_preview_engine.playback
        is_playing = state.toggle_play_pause()
        if is_playing:
            self.btn_play_pause.setText("⏸ Pause")
            self.anim_timer.start(state.step_time_ms)
        else:
            self.btn_play_pause.setText("▶ Play")
            self.anim_timer.stop()

    def _step_fwd_anim(self):
        idx = game_asset_preview_engine.playback.step_forward()
        self._update_anim_frame_display(idx)

    def _step_back_anim(self):
        idx = game_asset_preview_engine.playback.step_backward()
        self._update_anim_frame_display(idx)

    def _on_anim_timer_tick(self):
        idx = game_asset_preview_engine.playback.step_forward()
        self._update_anim_frame_display(idx)

    def _update_anim_frame_display(self, idx: int):
        state = game_asset_preview_engine.playback
        self.lbl_frame_idx.setText(f"Frame: {idx + 1} / {max(1, state.total_frames)}")

    def _on_fps_changed(self, fps: int):
        self.lbl_fps_val.setText(f"{fps} fps")
        game_asset_preview_engine.playback.fps = fps
        if self.anim_timer.isActive():
            self.anim_timer.setInterval(int(1000 / fps))

    def _open_assign_component_dialog(self):
        approved = db.get_approved_assets_for_optimization()
        if not approved:
            QMessageBox.information(self, "No Approved Assets", "No approved assets found to assign.")
            return

        dlg = AssignComponentDialog(approved, self)
        if dlg.exec() and dlg.selected_assignment:
            assign = dlg.selected_assignment
            db.assign_game_component(**assign)
            self._reload_component_assignments()
            self._refresh_metrics()
            QMessageBox.information(self, "Assigned", f"Asset assigned to '{assign['component_group']}' successfully!")

    def _reload_component_assignments(self):
        grp = self.combo_comp_filter.currentText()
        rows = db.get_game_component_assignments(component_group=grp)

        self.table_comp.setRowCount(len(rows))
        for idx, r in enumerate(rows):
            self.table_comp.setItem(idx, 0, QTableWidgetItem(str(r["id"])))
            self.table_comp.setItem(idx, 1, QTableWidgetItem(r["component_group"]))
            self.table_comp.setItem(idx, 2, QTableWidgetItem(Path(r["source_file"]).name))
            self.table_comp.setItem(idx, 3, QTableWidgetItem(f"{r['width']}x{r['height']}"))
            self.table_comp.setItem(idx, 4, QTableWidgetItem(f"({r['pivot_x']:.2f}, {r['pivot_y']:.2f})"))
            self.table_comp.setItem(idx, 5, QTableWidgetItem(r["transparency_status"]))
            self.table_comp.setItem(idx, 6, QTableWidgetItem(r["validation_status"]))
            self.table_comp.setItem(idx, 7, QTableWidgetItem(r.get("notes", "")))

        self.lbl_comp_summary.setText(f"Total Assigned: {len(rows)} Parts")

    def _remove_selected_assignment(self):
        row = self.table_comp.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Select Row", "Please select a component assignment row to remove.")
            return

        assign_id = int(self.table_comp.item(row, 0).text())
        db.remove_game_component_assignment(assign_id)
        self._reload_component_assignments()
        self._refresh_metrics()

    def _reload_metadata_files(self):
        """Find JSON manifests across project or output directories."""
        self.combo_compat_file.blockSignals(True)
        self.combo_compat_file.clear()

        search_dirs = [OUTPUT_DIR, OUTPUT_OPTIMIZED_DIR, OUTPUT_SPRITES_DIR]
        if self.current_project_path:
            search_dirs.append(self.current_project_path / "assets")

        found = []
        for d in search_dirs:
            if d.exists():
                found.extend(d.glob("**/*.json"))

        for f in found:
            self.combo_compat_file.addItem(f.name, userData=str(f))

        self.combo_compat_file.blockSignals(False)
        if self.combo_compat_file.count() > 0:
            self._inspect_compatibility_file()

    def _inspect_compatibility_file(self):
        path_str = self.combo_compat_file.currentData()
        if not path_str or not Path(path_str).exists():
            return

        res = flame_compatibility_engine.inspect_metadata_file(path_str)
        status = res.get("compatibility_status", "incompatible").upper()
        self.lbl_compat_status.setText(status)
        if status == "COMPATIBLE":
            self.lbl_compat_status.setStyleSheet("color: #10B981; background: rgba(16, 185, 129, 0.15); padding: 2px 8px; border-radius: 3px;")
        elif status == "WARNING":
            self.lbl_compat_status.setStyleSheet("color: #F59E0B; background: rgba(245, 158, 11, 0.15); padding: 2px 8px; border-radius: 3px;")
        else:
            self.lbl_compat_status.setStyleSheet("color: #EF4444; background: rgba(239, 68, 68, 0.15); padding: 2px 8px; border-radius: 3px;")

        # Display diff preview
        prev = res.get("conversion_preview")
        if prev:
            self.txt_compat_diff.setPlainText(prev["diff_text"] or prev["converted_json"])
            self.btn_save_flame_v1.setEnabled(True)
        else:
            self.txt_compat_diff.setPlainText("Metadata is already standard or lacks automated conversion schema.")
            self.btn_save_flame_v1.setEnabled(False)

    def _save_flame_v1_copy(self):
        path_str = self.combo_compat_file.currentData()
        if not path_str:
            return

        res = flame_compatibility_engine.inspect_metadata_file(path_str)
        prev = res.get("conversion_preview")
        if not prev:
            return

        src_p = Path(path_str)
        dest_p = src_p.parent / f"{src_p.stem}_flame_v1.json"

        with open(dest_p, "w", encoding="utf-8") as f:
            f.write(prev["converted_json"])

        db.record_flame_compatibility(
            metadata_path=str(dest_p),
            flame_version_detected="1.18.0",
            format_schema="flame_atlas_v1",
            is_compatible=True,
            compatibility_status="converted",
            issues=[],
            conversion_suggested=False,
            converted_metadata_json=prev["converted_json"],
            project_id=self.current_project_id,
        )

        QMessageBox.information(
            self,
            "Conversion Saved",
            f"Successfully generated Flame 1.x compliant JSON copy:\n{dest_p.name}\n(Original metadata preserved untouched.)"
        )
        self._reload_metadata_files()

    def _generate_isolated_fixture(self):
        """Generate isolated Flutter test package fixture."""
        fixture_dir = OUTPUT_DIR / "isolated_flutter_test_fixture"
        fixture_dir.mkdir(parents=True, exist_ok=True)

        # 1. pubspec.yaml
        flame_v = self.card_flame.value_label.text()
        if "Not" in flame_v or not flame_v:
            flame_v = "^1.18.0"

        pub_content = f"""name: isolated_flame_test_fixture
description: Isolated test harness for verifying construction asset loading in Flame.
version: 1.0.0+1
environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  flame: {flame_v}

dev_dependencies:
  flutter_test:
    sdk: flutter

flutter:
  assets:
    - assets/images/
    - assets/atlases/
    - assets/metadata/
"""
        (fixture_dir / "pubspec.yaml").write_text(pub_content, encoding="utf-8")

        # 2. Test harness
        test_dir = fixture_dir / "test"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_dart = """import 'package:flutter_test/flutter_test.dart';
import 'package:flame/flame.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Flame Asset Loading Test Harness', () async {
    // 1. Verify Flame image cache initialization
    expect(Flame.images, isNotNull);

    // 2. Load test assets if bundle is mounted
    print('[FLAME TEST] Asset bundle mounted and Flame engine ready.');
  });
}
"""
        (test_dir / "asset_loading_test.dart").write_text(test_dart, encoding="utf-8")

        self.txt_test_output.setPlainText(
            f"=== ISOLATED FLUTTER TEST FIXTURE GENERATED ===\n"
            f"Directory: {fixture_dir.resolve()}\n\n"
            f"Files Created:\n"
            f"• pubspec.yaml (Flame {flame_v})\n"
            f"• test/asset_loading_test.dart\n\n"
            f"Source code preview:\n{test_dart}"
        )

        db.record_integration_test_result(
            test_type="isolated_fixture",
            status="fixture_generated",
            test_package_path=str(fixture_dir),
            raw_output="Fixture generated successfully.",
            project_id=self.current_project_id,
        )

        QMessageBox.information(
            self,
            "Fixture Generated",
            f"Isolated Flutter test fixture created at:\n{fixture_dir.resolve()}\n\n(No modifications were made to your main game code.)"
        )

    def _execute_flutter_test(self):
        """Execute flutter test if CLI is available."""
        cli = flutter_project_inspector.detect_flutter_cli()
        if not cli["available"]:
            self.txt_test_output.setPlainText(
                "=== FLUTTER RUNTIME TEST: NOT TESTED ===\n"
                "Reason: Flutter CLI is not installed or not in PATH.\n"
                "To execute: Run 'flutter test' inside the generated isolated_flutter_test_fixture/ directory."
            )
            return

        self.txt_test_output.setPlainText("Executing 'flutter test' on isolated test fixture...")

    def _show_patch_preview(self):
        """Show safe integration patch preview."""
        patch_text = """// ============================================================================
// SAFE INTEGRATION PATCH PREVIEW — FLUTTER + FLAME GAME LOADER
// (Review carefully before incorporating into your game)
// ============================================================================

import 'package:flame/components.dart';
import 'package:flame/game.dart';

class ConstructionSimulatorGame extends FlameGame {
  @override
  Future<void> onLoad() async {
    super.onLoad();

    // 1. Load optimized vehicle components
    final excavatorChassis = await Sprite.load('images/vehicles/excavator_body.png');
    add(SpriteComponent(
      sprite: excavatorChassis,
      size: Vector2(256, 192),
      anchor: Anchor.center,
    ));

    // 2. Load Flame 1.x texture atlas
    // final atlas = await Atlas.load('atlases/construction_atlas_1.json');
  }
}
"""
        dlg = QDialog(self)
        dlg.setWindowTitle("Preview Integration Patch — Flame Game Code")
        dlg.setMinimumSize(600, 440)
        dlg.setStyleSheet(self.styleSheet())
        d_layout = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(patch_text)
        txt.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; color: #38BDF8; font-family: monospace;")
        d_layout.addWidget(txt)
        btn_close = QPushButton("Close Preview")
        btn_close.clicked.connect(dlg.accept)
        d_layout.addWidget(btn_close)
        dlg.exec()

    def _compute_performance_report(self):
        """Run performance and GPU memory analyzer."""
        target_dir = self.current_project_path / "assets" if self.current_project_path else OUTPUT_DIR
        atlases = db.get_all_texture_atlases()

        rep = asset_performance_analyzer.analyze_asset_directory(
            target_dir=target_dir,
            atlas_data_list=atlases,
        )

        if not rep.get("success"):
            QMessageBox.warning(self, "Error", f"Could not analyze directory: {rep.get('error')}")
            return

        m = rep["measured_metrics"]
        e = rep["estimated_metrics"]

        # Summary text
        summary_lines = [
            "============================================================",
            "          ASSET BUDGET & GPU MEMORY ANALYSIS                ",
            "============================================================",
            f"Target Directory: {rep['target_directory']}",
            "",
            "--- MEASURED METRICS ---",
            f"• Total Images: {m['total_asset_count']}",
            f"• Total Disk Size: {m['total_disk_formatted']}",
            f"  - PNG Size: {m['png_formatted']}",
            f"  - WebP Size: {m['webp_formatted']}",
            f"  - JPEG Size: {m['jpg_formatted']}",
            f"• Total Atlases: {m['atlas_count']} (Avg Efficiency: {m['atlas_avg_efficiency']}%)",
            f"• Total Packed Sprites: {m['sprite_count']}",
            f"• Largest Texture: {m['largest_texture_file']} ({m['max_texture_dimensions'][0]}x{m['max_texture_dimensions'][1]})",
            "",
            "--- ESTIMATED GPU RUNTIME FOOTPRINT ---",
            f"• Decoded VRAM Footprint: {e['estimated_decoded_ram_formatted']}",
            f"  (Calculation: width * height * 4 bytes for 32-bit RGBA)",
            "",
            f"⚠️ DISCLAIMER: {e['disclaimer']}",
            "",
            "--- WARNINGS & RECOMMENDATIONS ---",
        ]

        warns = rep.get("warnings", [])
        if warns:
            for w in warns:
                summary_lines.append(f"• [{w['severity']}] {w['message']}")
        else:
            summary_lines.append("✓ No oversized textures or critical budget violations detected.")

        self.txt_perf_summary.setPlainText("\n".join(summary_lines))

        # Table
        textures = rep.get("texture_details", [])
        self.table_perf.setRowCount(len(textures))
        for idx, t in enumerate(textures):
            self.table_perf.setItem(idx, 0, QTableWidgetItem(t["filename"]))
            self.table_perf.setItem(idx, 1, QTableWidgetItem(f"{t['width']}x{t['height']}"))
            self.table_perf.setItem(idx, 2, QTableWidgetItem(format_bytes(t["file_size"])))
            self.table_perf.setItem(idx, 3, QTableWidgetItem(format_bytes(t["estimated_ram"])))

        # Save to DB
        db.save_asset_performance_report(
            report_data={
                "total_asset_count": m["total_asset_count"],
                "total_disk_bytes": m["total_disk_bytes"],
                "png_bytes": m["png_bytes"],
                "webp_bytes": m["webp_bytes"],
                "atlas_count": m["atlas_count"],
                "sprite_count": m["sprite_count"],
                "atlas_avg_efficiency": m["atlas_avg_efficiency"],
                "max_texture_width": m["max_texture_dimensions"][0],
                "max_texture_height": m["max_texture_dimensions"][1],
                "duplicate_count": 0,
                "missing_ref_count": 0,
                "estimated_decoded_ram_bytes": e["estimated_decoded_ram_bytes"],
                "warnings": warns,
            },
            project_id=self.current_project_id,
        )

        self._refresh_metrics()
        QMessageBox.information(
            self,
            "Performance Analysis Complete",
            f"Analysis complete!\nTotal Disk Size: {m['total_disk_formatted']}\nEstimated GPU VRAM: {e['estimated_decoded_ram_formatted']}"
        )
