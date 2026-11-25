"""
Asset Workflow & Global Pipeline Workstation View (Stage 13.2)
Central entry point for the Construction Asset Processor.
Provides an 8-stage ordered workflow timeline, authentic live database telemetry,
stage gate progression controls, batch queue execution, filtering, and bulk management.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QAbstractItemView
)

from app.config import THEME_COLORS
from core.database import db
from core.pixmap_cache import pixmap_cache
from core.workflow_engine import workflow_engine
from ui.components.stat_card import StatCard


class StageTimelineCard(QFrame):
    """Visual clickable card representing one stage in the 8-step pipeline timeline."""

    clicked = Signal(int)  # stage_id

    STATUS_COLORS = {
        "locked": ("#475569", "#1E293B"),
        "ready": (THEME_COLORS["accent_secondary"], "rgba(59, 130, 246, 0.15)"),
        "running": ("#A855F7", "rgba(168, 85, 247, 0.20)"),
        "paused": (THEME_COLORS["status_warning"], "rgba(245, 158, 11, 0.15)"),
        "needs_review": (THEME_COLORS["status_warning"], "rgba(245, 158, 11, 0.20)"),
        "completed": (THEME_COLORS["status_success"], "rgba(16, 185, 129, 0.15)"),
        "failed": (THEME_COLORS["status_error"], "rgba(239, 68, 68, 0.15)"),
    }

    STAGE_ICONS = {
        1: "✂️", 2: "🛡️", 3: "🔍", 4: "🏷️",
        5: "🔀", 6: "🚜", 7: "⚡", 8: "🎮"
    }

    def __init__(self, stage_id: int, stage_name: str, parent=None):
        super().__init__(parent)
        self.stage_id = stage_id
        self.stage_name = stage_name
        self._is_active = False

        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(130)
        self.setMaximumHeight(85)
        self.setProperty("class", "card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header Row: Icon + Stage Number
        top_row = QHBoxLayout()
        icon = self.STAGE_ICONS.get(stage_id, "⚙️")
        lbl_num = QLabel(f"{icon} STAGE {stage_id}")
        lbl_num.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        top_row.addWidget(lbl_num)
        top_row.addStretch()

        self.lbl_status = QLabel("LOCKED")
        self.lbl_status.setStyleSheet("""
            font-size: 9px;
            font-weight: 700;
            padding: 2px 5px;
            border-radius: 3px;
        """)
        top_row.addWidget(self.lbl_status)
        layout.addLayout(top_row)

        # Stage Name
        self.lbl_name = QLabel(stage_name)
        self.lbl_name.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['text_primary']};")
        self.lbl_name.setWordWrap(True)
        layout.addWidget(self.lbl_name)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #1E2228;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #10B981;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Progress text
        self.lbl_progress = QLabel("0 / 0")
        self.lbl_progress.setStyleSheet(f"font-size: 9px; color: {THEME_COLORS['text_muted']};")
        layout.addWidget(self.lbl_progress)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self.stage_id)

    def set_active(self, active: bool):
        self._is_active = active
        border_col = THEME_COLORS["accent_primary"] if active else THEME_COLORS["border_subtle"]
        bg_col = "#242B35" if active else THEME_COLORS["bg_card"]
        self.setStyleSheet(f"""
            StageTimelineCard {{
                background-color: {bg_col};
                border: 1px solid {border_col};
                border-radius: 6px;
            }}
        """)

    def update_stage_data(self, stage_data: Dict[str, Any]):
        status = stage_data.get("status", "locked")
        total = stage_data.get("total_eligible", 0)
        completed = stage_data.get("completed_count", 0)

        fg_col, bg_col = self.STATUS_COLORS.get(status, ("#94A3B8", "#1E293B"))
        status_text = status.upper().replace("_", " ")

        self.lbl_status.setText(status_text)
        self.lbl_status.setStyleSheet(f"""
            font-size: 9px;
            font-weight: 700;
            color: {fg_col};
            background-color: {bg_col};
            padding: 2px 5px;
            border-radius: 3px;
        """)

        pct = int((completed / total * 100)) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.lbl_progress.setText(f"{completed}/{total} ({pct}%)")


class AssetWorkflowView(QWidget):
    """
    Main central workspace for the complete sequential construction asset workflow.
    """

    navigate_to_specialized_view = Signal(int)  # stage_id (maps to MainWindow views)
    asset_selected = Signal(dict)               # emit to inspector

    STAGE_TO_VIEW_INDEX = {
        1: 5,   # Stage 1 (Bg Removal) -> BackgroundRemovalView (index 5)
        2: 7,   # Stage 2 (Watermark) -> WatermarkReviewView (index 7)
        3: 6,   # Stage 3 (Text Detect) -> TextDetectionView (index 6)
        4: 3,   # Stage 4 (Classification) -> ClassificationView (index 3)
        5: 8,   # Stage 5 (Splitter) -> CollectionSplitterView (index 8)
        6: 12,  # Stage 6 (Sprite Prep) -> Stage13SpritePrepView (index 12)
        7: 10,  # Stage 7 (Optimization) -> AssetOptimizationView (index 10)
        8: 11,  # Stage 8 (Export / Integration) -> GameIntegrationView (index 11)
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.current_stage_id = 1
        self.timeline_cards: Dict[int, StageTimelineCard] = {}
        self.selected_queue_asset_ids: Set[int] = set()

        self._build_ui()
        self._wire_signals()
        self.reload_data()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Main Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        self.main_layout = QVBoxLayout(container)
        self.main_layout.setContentsMargins(16, 14, 16, 14)
        self.main_layout.setSpacing(14)

        # 1. Header & Actions Bar
        header_bar = self._create_header_bar()
        self.main_layout.addWidget(header_bar)

        # 2. Global Workflow Telemetry Cards (10 authentic metrics)
        metrics_panel = self._create_metrics_panel()
        self.main_layout.addWidget(metrics_panel)

        # 3. 8-Stage Timeline Stepper
        timeline_panel = self._create_timeline_panel()
        self.main_layout.addWidget(timeline_panel)

        # 4. Active Stage Controls & Live Progress Banner
        controls_panel = self._create_stage_controls_panel()
        self.main_layout.addWidget(controls_panel)

        # 5. Stage Queue Table & Filter Toolbar
        queue_panel = self._create_queue_panel()
        self.main_layout.addWidget(queue_panel, stretch=1)

        scroll.setWidget(container)
        root_layout.addWidget(scroll)

    def _create_header_bar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("class", "card")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # Title block
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("🚀 GLOBAL ASSET PIPELINE WORKFLOW")
        title.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {THEME_COLORS['accent_primary']}; letter-spacing: 0.5px;")
        title_box.addWidget(title)

        subtitle = QLabel("Sequential stage-by-stage construction asset processing, verification & Flutter export")
        subtitle.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)

        layout.addStretch()

        # Action Buttons
        btn_exclude_scenes = QPushButton("🏞️ Auto-Exclude Scenes")
        btn_exclude_scenes.setProperty("class", "btn_secondary")
        btn_exclude_scenes.setToolTip("Protect full construction scene illustrations from Stage 1 background removal.")
        btn_exclude_scenes.setCursor(Qt.PointingHandCursor)
        btn_exclude_scenes.clicked.connect(self._on_exclude_scenes_clicked)
        layout.addWidget(btn_exclude_scenes)

        btn_sync = QPushButton("🛡️ Sync Existing Data")
        btn_sync.setProperty("class", "btn_secondary")
        btn_sync.setToolTip("Rescan SQLite and disk records to resume existing progress without reprocessing.")
        btn_sync.setCursor(Qt.PointingHandCursor)
        btn_sync.clicked.connect(self._on_sync_clicked)
        layout.addWidget(btn_sync)

        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.setProperty("class", "btn_secondary")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.reload_data)
        layout.addWidget(btn_refresh)

        return bar

    def _create_metrics_panel(self) -> QWidget:
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        self.card_total = StatCard("Total Assets", "0", "Catalog images", "🖼️")
        self.card_orig_alpha = StatCard("Source Alpha", "0", "Images with alpha", "💎", accent_color="#A855F7")
        self.card_bg_done = StatCard("Backgrounds Done", "0", "Cutouts generated", "✂️", accent_color=THEME_COLORS["status_success"])
        self.card_wm_rev = StatCard("Watermarks Rev.", "0", "Candidates reviewed", "🛡️", accent_color=THEME_COLORS["status_info"])
        self.card_txt_rev = StatCard("Text Reviewed", "0", "Text scanned & approved", "🔍", accent_color=THEME_COLORS["status_info"])
        self.card_classified = StatCard("Classified", "0", "Vehicles & terrain", "🏷️", accent_color="#EC4899")
        self.card_sprites = StatCard("Extracted Sprites", "0", "Multi-objects & parts", "🔀", accent_color=THEME_COLORS["accent_primary"])
        self.card_approved = StatCard("Approved Assets", "0", "Ready for export", "✅", accent_color=THEME_COLORS["status_success"])
        self.card_review = StatCard("Needs Review", "0", "Manual attention", "⚠️", accent_color=THEME_COLORS["status_warning"])
        self.card_failed = StatCard("Failed Items", "0", "Requires retry", "❌", accent_color=THEME_COLORS["status_error"])

        cards = [
            self.card_total, self.card_orig_alpha, self.card_bg_done, self.card_wm_rev, self.card_txt_rev,
            self.card_classified, self.card_sprites, self.card_approved, self.card_review, self.card_failed
        ]

        # 2 rows of 5 cards
        for idx, c in enumerate(cards):
            r = idx // 5
            col = idx % 5
            grid.addWidget(c, r, col)

        return panel

    def _create_timeline_panel(self) -> QWidget:
        box = QFrame()
        box.setProperty("class", "card")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        header = QLabel("ORDERED WORKFLOW PIPELINE TIMELINE")
        header.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']}; letter-spacing: 0.6px;")
        layout.addWidget(header)

        # 8 Horizontal Step Cards
        steps_row = QHBoxLayout()
        steps_row.setSpacing(8)

        stages = db.get_workflow_stages()
        for s in stages:
            sid = s["stage_id"]
            sname = s["stage_name"]
            card = StageTimelineCard(sid, sname)
            card.clicked.connect(self._on_stage_card_clicked)
            card.update_stage_data(s)
            self.timeline_cards[sid] = card
            steps_row.addWidget(card)

        layout.addLayout(steps_row)
        return box

    def _create_stage_controls_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("class", "card")
        self.controls_layout = QVBoxLayout(panel)
        self.controls_layout.setContentsMargins(14, 12, 14, 12)
        self.controls_layout.setSpacing(10)

        # Top Stage Info Row
        info_row = QHBoxLayout()
        self.lbl_stage_title = QLabel("Stage 1 — Background Removal")
        self.lbl_stage_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        info_row.addWidget(self.lbl_stage_title)

        self.lbl_stage_badge = QLabel("READY")
        self.lbl_stage_badge.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {THEME_COLORS['accent_secondary']};
            background: rgba(59, 130, 246, 0.15);
            padding: 3px 8px;
            border-radius: 4px;
        """)
        info_row.addWidget(self.lbl_stage_badge)
        info_row.addStretch()

        # Gate Progression Status
        self.lbl_gate_status = QLabel("Gate: Ready to process.")
        self.lbl_gate_status.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']}; font-weight: 500;")
        info_row.addWidget(self.lbl_gate_status)

        self.controls_layout.addLayout(info_row)

        self.lbl_stage_desc = QLabel("Detect white/solid backgrounds, apply GrabCut segmentation, create transparent PNG working copies.")
        self.lbl_stage_desc.setStyleSheet(f"font-size: 12px; color: {THEME_COLORS['text_muted']};")
        self.controls_layout.addWidget(self.lbl_stage_desc)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_start = QPushButton("▶ Start Stage Batch")
        self.btn_start.setProperty("class", "btn_primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.btn_start)

        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setProperty("class", "btn_secondary")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        btn_row.addWidget(self.btn_pause)

        self.btn_resume = QPushButton("▶ Resume")
        self.btn_resume.setProperty("class", "btn_secondary")
        self.btn_resume.setCursor(Qt.PointingHandCursor)
        self.btn_resume.setVisible(False)
        self.btn_resume.clicked.connect(self._on_resume_clicked)
        btn_row.addWidget(self.btn_resume)

        self.btn_cancel = QPushButton("⏹ Cancel")
        self.btn_cancel.setProperty("class", "btn_secondary")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.btn_cancel)

        self.btn_retry_failed = QPushButton("🔄 Retry Failed")
        self.btn_retry_failed.setProperty("class", "btn_secondary")
        self.btn_retry_failed.setCursor(Qt.PointingHandCursor)
        self.btn_retry_failed.clicked.connect(self._on_retry_failed_clicked)
        btn_row.addWidget(self.btn_retry_failed)

        btn_row.addStretch()

        self.btn_review_view = QPushButton("👁 Review in Stage View")
        self.btn_review_view.setProperty("class", "btn_secondary")
        self.btn_review_view.setCursor(Qt.PointingHandCursor)
        self.btn_review_view.setToolTip("Open this stage's dedicated workstation view for interactive inspection.")
        self.btn_review_view.clicked.connect(self._on_review_view_clicked)
        btn_row.addWidget(self.btn_review_view)

        self.btn_next_stage = QPushButton("⏭ Continue to Next Stage")
        self.btn_next_stage.setStyleSheet(f"""
            background-color: {THEME_COLORS['accent_primary']};
            color: {THEME_COLORS['text_inverse']};
            font-weight: 700;
            padding: 6px 14px;
            border-radius: 4px;
            font-size: 11px;
            border: none;
        """)
        self.btn_next_stage.setCursor(Qt.PointingHandCursor)
        self.btn_next_stage.clicked.connect(self._on_next_stage_clicked)
        btn_row.addWidget(self.btn_next_stage)

        self.controls_layout.addLayout(btn_row)

        # Live Progress Banner (Always visible with real counts)
        self.progress_banner = QFrame()
        self.progress_banner.setStyleSheet("background: #15181C; border-radius: 4px; padding: 6px;")
        pb_layout = QVBoxLayout(self.progress_banner)
        pb_layout.setContentsMargins(8, 6, 8, 6)
        pb_layout.setSpacing(4)

        pb_top = QHBoxLayout()
        self.lbl_progress_status = QLabel("Ready for batch execution.")
        self.lbl_progress_status.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['accent_primary']};")
        pb_top.addWidget(self.lbl_progress_status)
        pb_top.addStretch()

        self.lbl_progress_counts = QLabel("0 completed • 0 remaining • 0 skipped • 0 failed")
        self.lbl_progress_counts.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']};")
        pb_top.addWidget(self.lbl_progress_counts)
        pb_layout.addLayout(pb_top)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #1E2228;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #10B981;
                border-radius: 3px;
            }
        """)
        pb_layout.addWidget(self.progress_bar)

        self.controls_layout.addWidget(self.progress_banner)
        return panel

    def _create_queue_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("class", "card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # Filter and Search Toolbar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        lbl_filter = QLabel("FILTER QUEUE:")
        lbl_filter.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        filter_row.addWidget(lbl_filter)

        self.combo_status = QComboBox()
        self.combo_status.addItems(["All Statuses", "pending", "running", "completed", "needs_review", "skipped", "failed"])
        self.combo_status.currentTextChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.combo_status)

        self.combo_approval = QComboBox()
        self.combo_approval.addItems(["All Approvals", "unreviewed", "approved", "rejected"])
        self.combo_approval.currentTextChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.combo_approval)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search filename or category...")
        self.search_input.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.search_input, stretch=1)

        btn_select_all = QPushButton("Select All")
        btn_select_all.setProperty("class", "btn_secondary")
        btn_select_all.setCursor(Qt.PointingHandCursor)
        btn_select_all.clicked.connect(self._on_select_all)
        filter_row.addWidget(btn_select_all)

        btn_clear_sel = QPushButton("Clear")
        btn_clear_sel.setProperty("class", "btn_secondary")
        btn_clear_sel.setCursor(Qt.PointingHandCursor)
        btn_clear_sel.clicked.connect(self._on_clear_selection)
        filter_row.addWidget(btn_clear_sel)

        btn_approve_sel = QPushButton("✓ Approve Selected")
        btn_approve_sel.setStyleSheet("background: #10B981; color: white; padding: 4px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; border: none;")
        btn_approve_sel.setCursor(Qt.PointingHandCursor)
        btn_approve_sel.clicked.connect(self._on_approve_selected)
        filter_row.addWidget(btn_approve_sel)

        btn_skip_sel = QPushButton("⏭ Skip Selected")
        btn_skip_sel.setProperty("class", "btn_secondary")
        btn_skip_sel.setCursor(Qt.PointingHandCursor)
        btn_skip_sel.clicked.connect(self._on_skip_selected)
        filter_row.addWidget(btn_skip_sel)

        btn_reprocess_sel = QPushButton("🔄 Reprocess Selected")
        btn_reprocess_sel.setProperty("class", "btn_secondary")
        btn_reprocess_sel.setCursor(Qt.PointingHandCursor)
        btn_reprocess_sel.clicked.connect(self._on_reprocess_selected)
        filter_row.addWidget(btn_reprocess_sel)

        layout.addLayout(filter_row)

        # Queue Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID", "Preview", "Filename", "Collection", "Dimensions", "Stage Status", "Approval", "Output Path"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(280)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                gridline-color: #242932;
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_secondary']};
                font-weight: 700;
                font-size: 10px;
                padding: 4px;
                border: 1px solid {THEME_COLORS['border_subtle']};
            }}
        """)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 48)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)

        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_table_double_clicked)
        layout.addWidget(self.table)

        return panel

    def _wire_signals(self):
        """Connect workflow engine signals to view slots."""
        workflow_engine.stage_status_changed.connect(self._on_engine_stage_status_changed)
        workflow_engine.progress_updated.connect(self._on_engine_progress_updated)
        workflow_engine.stage_finished.connect(self._on_engine_stage_finished)
        workflow_engine.telemetry_updated.connect(self._on_engine_telemetry_updated)

    # -------------------------------------------------------------------------
    # Data Reload & UI Synchronization
    # -------------------------------------------------------------------------

    def reload_data(self):
        """Query fresh database telemetry and reload active stage queue."""
        stats = db.get_workflow_dashboard_stats()
        self._update_telemetry_cards(stats)
        self._update_timeline_stepper(stats.get("stages", []))
        self._load_active_stage_info()
        self._load_queue_table()

    def _update_telemetry_cards(self, stats: Dict[str, Any]):
        self.card_total.update_data(str(stats.get("total_assets", 0)))
        self.card_orig_alpha.update_data(str(stats.get("original_transparent_assets", 0)))
        self.card_bg_done.update_data(str(stats.get("backgrounds_processed", 0)))
        self.card_wm_rev.update_data(str(stats.get("watermarks_reviewed", 0)))
        self.card_txt_rev.update_data(str(stats.get("text_reviewed", 0)))
        self.card_classified.update_data(str(stats.get("classified_assets", 0)))
        self.card_sprites.update_data(str(stats.get("extracted_sprites", 0)))
        self.card_approved.update_data(str(stats.get("approved_assets", 0)))
        self.card_review.update_data(str(stats.get("needs_review_assets", 0)))
        self.card_failed.update_data(str(stats.get("failed_assets", 0)))

    def _update_timeline_stepper(self, stages: List[Dict[str, Any]]):
        for s in stages:
            sid = s["stage_id"]
            if sid in self.timeline_cards:
                self.timeline_cards[sid].update_stage_data(s)
                self.timeline_cards[sid].set_active(sid == self.current_stage_id)

    def _load_active_stage_info(self):
        stage = db.get_workflow_stage(self.current_stage_id)
        if not stage:
            return

        self.lbl_stage_title.setText(f"Stage {self.current_stage_id} — {stage['stage_name']}")
        self.lbl_stage_desc.setText(stage.get("description", ""))

        status = stage.get("status", "locked")
        status_text = status.upper().replace("_", " ")
        self.lbl_stage_badge.setText(status_text)

        fg_col, bg_col = StageTimelineCard.STATUS_COLORS.get(status, ("#94A3B8", "#1E293B"))
        self.lbl_stage_badge.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {fg_col};
            background: {bg_col};
            padding: 3px 8px;
            border-radius: 4px;
        """)

        # Gate status evaluation
        can_next, gate_msg = workflow_engine.can_progress_to_next_stage(self.current_stage_id)
        if can_next:
            self.lbl_gate_status.setText("✓ Gate Criteria Met: Ready to continue to next stage.")
            self.lbl_gate_status.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['status_success']}; font-weight: 600;")
        else:
            self.lbl_gate_status.setText(f"⏳ Gate: {gate_msg}")
            self.lbl_gate_status.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['status_warning']}; font-weight: 500;")

        # Update button states
        is_running = workflow_engine.is_running() and workflow_engine.get_active_stage_id() == self.current_stage_id
        is_unlocked = stage.get("is_unlocked", 0) == 1

        self.btn_start.setEnabled(not is_running and is_unlocked)
        self.btn_pause.setEnabled(is_running)
        self.btn_cancel.setEnabled(is_running)
        self.btn_next_stage.setEnabled(is_unlocked and self.current_stage_id < 8)

        # Progress bar
        total = stage.get("total_eligible", 0)
        completed = stage.get("completed_count", 0)
        skipped = stage.get("skipped_count", 0)
        failed = stage.get("failed_count", 0)
        remaining = max(0, total - completed - skipped)

        pct = int((completed / total * 100)) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.lbl_progress_counts.setText(f"{completed} completed • {remaining} remaining • {skipped} skipped • {failed} failed")

        if is_running:
            self.lbl_progress_status.setText(f"Stage {self.current_stage_id} processing active...")
        elif pct == 100 or (completed + skipped == total and total > 0):
            self.lbl_progress_status.setText(f"Stage {self.current_stage_id} completed successfully.")
        else:
            self.lbl_progress_status.setText(f"Stage {self.current_stage_id} — {remaining} items awaiting execution.")

    def _load_queue_table(self):
        """Query workflow queue and render items into table."""
        status_filter = self.combo_status.currentText()
        status_param = status_filter if status_filter != "All Statuses" else None

        approval_filter = self.combo_approval.currentText()
        approval_param = approval_filter if approval_filter != "All Approvals" else None

        search_param = self.search_input.text().strip() or None

        items = db.get_workflow_queue(
            stage_id=self.current_stage_id,
            status=status_param,
            approval_status=approval_param,
            search=search_param,
            limit=250
        )

        self.table.setRowCount(len(items))
        self.table.setRowHeight(36, 36)

        for row, item in enumerate(items):
            aid = item["asset_id"]

            # ID
            item_id = QTableWidgetItem(str(aid))
            item_id.setTextAlignment(Qt.AlignCenter)
            item_id.setData(Qt.UserRole, item)
            self.table.setItem(row, 0, item_id)

            # Thumbnail Icon
            thumb_path = item.get("thumbnail_path") or item.get("original_path")
            lbl_icon = QLabel()
            lbl_icon.setAlignment(Qt.AlignCenter)
            if thumb_path and os.path.exists(thumb_path):
                pm = pixmap_cache.get_pixmap(thumb_path, 32, 32)
                if pm:
                    lbl_icon.setPixmap(pm)
            self.table.setCellWidget(row, 1, lbl_icon)

            # Filename
            fname = item.get("filename", "")
            item_fname = QTableWidgetItem(fname)
            self.table.setItem(row, 2, item_fname)

            # Collection
            col = item.get("collection", "")
            item_col = QTableWidgetItem(col)
            self.table.setItem(row, 3, item_col)

            # Dimensions
            dims = f"{item.get('width', 0)} × {item.get('height', 0)}"
            item_dims = QTableWidgetItem(dims)
            item_dims.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item_dims)

            # Stage Status Badge
            st = item.get("queue_status", "pending")
            item_st = QTableWidgetItem(st.upper())
            item_st.setTextAlignment(Qt.AlignCenter)
            fg, bg = StageTimelineCard.STATUS_COLORS.get(st, ("#94A3B8", "#1E293B"))
            item_st.setForeground(QColor(fg))
            self.table.setItem(row, 5, item_st)

            # Approval Status
            appr = item.get("approval_status", "unreviewed")
            item_appr = QTableWidgetItem(appr.capitalize())
            item_appr.setTextAlignment(Qt.AlignCenter)
            if appr == "approved":
                item_appr.setForeground(QColor(THEME_COLORS["status_success"]))
            elif appr == "rejected":
                item_appr.setForeground(QColor(THEME_COLORS["status_error"]))
            self.table.setItem(row, 6, item_appr)

            # Output Path / Error
            out_p = item.get("output_path", "")
            err = item.get("error_message", "")
            display_txt = err if err else (Path(out_p).name if out_p else "—")
            item_out = QTableWidgetItem(display_txt)
            if err:
                item_out.setForeground(QColor(THEME_COLORS["status_error"]))
            self.table.setItem(row, 7, item_out)

    # -------------------------------------------------------------------------
    # Event Handlers & User Actions
    # -------------------------------------------------------------------------

    def _on_stage_card_clicked(self, stage_id: int):
        self.current_stage_id = stage_id
        for sid, card in self.timeline_cards.items():
            card.set_active(sid == stage_id)
        self._load_active_stage_info()
        self._load_queue_table()

    def _on_filter_changed(self):
        self._load_queue_table()

    def _on_table_selection_changed(self):
        selected_rows = self.table.selectionModel().selectedRows()
        self.selected_queue_asset_ids.clear()
        for idx in selected_rows:
            item = self.table.item(idx.row(), 0)
            if item:
                self.selected_queue_asset_ids.add(int(item.text()))

        # If single asset selected, emit to inspector
        if len(self.selected_queue_asset_ids) == 1:
            aid = next(iter(self.selected_queue_asset_ids))
            asset_dict = db.get_asset(aid)
            if asset_dict:
                self.asset_selected.emit(asset_dict)

    def _on_table_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        id_item = self.table.item(row, 0)
        if id_item:
            aid = int(id_item.text())
            asset_dict = db.get_asset(aid)
            if asset_dict:
                self.asset_selected.emit(asset_dict)

    def _on_select_all(self):
        self.table.selectAll()

    def _on_clear_selection(self):
        self.table.clearSelection()

    def _on_approve_selected(self):
        if not self.selected_queue_asset_ids:
            QMessageBox.information(self, "Selection Required", "Please select assets to approve.")
            return
        workflow_engine.approve_assets(self.current_stage_id, list(self.selected_queue_asset_ids))
        self.reload_data()

    def _on_skip_selected(self):
        if not self.selected_queue_asset_ids:
            QMessageBox.information(self, "Selection Required", "Please select assets to skip.")
            return
        workflow_engine.skip_assets(self.current_stage_id, list(self.selected_queue_asset_ids))
        self.reload_data()

    def _on_reprocess_selected(self):
        if not self.selected_queue_asset_ids:
            QMessageBox.information(self, "Selection Required", "Please select assets to reprocess.")
            return
        workflow_engine.reprocess_assets(self.current_stage_id, list(self.selected_queue_asset_ids))
        self.reload_data()

    def _on_start_clicked(self):
        workflow_engine.start_stage(self.current_stage_id)
        self._load_active_stage_info()

    def _on_pause_clicked(self):
        workflow_engine.pause()
        self.btn_pause.setVisible(False)
        self.btn_resume.setVisible(True)
        self._load_active_stage_info()

    def _on_resume_clicked(self):
        workflow_engine.resume()
        self.btn_resume.setVisible(False)
        self.btn_pause.setVisible(True)
        self._load_active_stage_info()

    def _on_cancel_clicked(self):
        workflow_engine.cancel()
        self.btn_resume.setVisible(False)
        self.btn_pause.setVisible(True)
        self._load_active_stage_info()

    def _on_retry_failed_clicked(self):
        retried = workflow_engine.retry_failed(self.current_stage_id)
        QMessageBox.information(self, "Retry Failed", f"Reset {retried} failed items to pending.")
        self.reload_data()

    def _on_next_stage_clicked(self):
        allowed, msg = workflow_engine.can_progress_to_next_stage(self.current_stage_id)
        if not allowed:
            reply = QMessageBox.question(
                self,
                "Stage Gating Warning",
                f"{msg}\n\nDo you want to override and continue to the next stage anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        success, advance_msg = workflow_engine.unlock_next_stage(self.current_stage_id, force=True)
        if success:
            self.current_stage_id = min(8, self.current_stage_id + 1)
            self.reload_data()
        else:
            QMessageBox.warning(self, "Cannot Continue", advance_msg)

    def _on_review_view_clicked(self):
        view_idx = self.STAGE_TO_VIEW_INDEX.get(self.current_stage_id)
        if view_idx is not None:
            self.navigate_to_specialized_view.emit(view_idx)

    def _on_exclude_scenes_clicked(self):
        count = workflow_engine.exclude_scene_backgrounds(stage_id=1)
        QMessageBox.information(
            self,
            "Scenes Excluded",
            f"Flagged {count} scene and terrain illustrations as skipped in Stage 1 background removal."
        )
        self.reload_data()

    def _on_sync_clicked(self):
        stats = db.sync_workflow_from_existing_data()
        self._update_telemetry_cards(stats)
        self.reload_data()
        QMessageBox.information(self, "Data Synced", "Successfully scanned and synchronized existing processed results.")

    # -------------------------------------------------------------------------
    # Engine Signals Slots
    # -------------------------------------------------------------------------

    def _on_engine_stage_status_changed(self, stage_id: int, status: str):
        if stage_id in self.timeline_cards:
            stage_data = db.get_workflow_stage(stage_id)
            if stage_data:
                self.timeline_cards[stage_id].update_stage_data(stage_data)
        if stage_id == self.current_stage_id:
            self._load_active_stage_info()

    def _on_engine_progress_updated(self, stage_id: int, current: int, total: int, item_name: str):
        if stage_id == self.current_stage_id:
            pct = int((current / total * 100)) if total > 0 else 0
            self.progress_bar.setValue(pct)
            self.lbl_progress_status.setText(f"Processing ({current}/{total}): {item_name}")

    def _on_engine_stage_finished(self, stage_id: int, completed: int, failed: int):
        self.reload_data()

    def _on_engine_telemetry_updated(self, stats: Dict[str, Any]):
        self._update_telemetry_cards(stats)
        self._update_timeline_stepper(stats.get("stages", []))
