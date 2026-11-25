"""
Collection Splitter & Asset Extraction Master View (Stage 8)
Coordinates CV contour & alpha-channel segmentation, 6 real-time SQLite metric cards,
responsive asset grid, telemetry banner, background analysis worker,
and dedicated right-side collection inspector with manual region editing,
sprite sheet grid generator, and extraction preview/export.
Strictly non-destructive — preserves original source images completely intact.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QVBoxLayout,
    QWidget
)

from app.config import THEME_COLORS
from core.collection_splitter_engine import (
    COMPOSITION_COLORS, COMPOSITION_TYPES, collection_splitter_engine
)
from core.database import db
from core.workers import CollectionAnalysisWorker
from ui.components.collection_card import CollectionCard
from ui.components.extraction_inspector import ExtractionInspector
from ui.components.stat_card import StatCard


class CollectionGridContainer(QWidget):
    """Container that flows CollectionCards responsively based on available width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cards: List[CollectionCard] = []

    def set_cards(self, cards: List[CollectionCard]):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cards = cards
        self._relayout()

    def _relayout(self):
        if not self.cards:
            return
        avail_width = max(self.width() - 30, 480)
        card_w = CollectionCard.CARD_WIDTH + 12
        cols = max(1, avail_width // card_w)
        for idx, card in enumerate(self.cards):
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._relayout()


class CollectionSplitterView(QWidget):
    """Primary Collection Splitter & Asset Extraction screen (Stage 8)."""

    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_page = 1
        self.page_size = 48
        self.total_matching = 0
        self.current_assets: List[Dict[str, Any]] = []
        self.selected_ids: Set[int] = set()
        self.last_clicked_id: Optional[int] = None

        self.worker: Optional[CollectionAnalysisWorker] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Toolbar
        self._build_toolbar(main_layout)

        # 2. 6 Statistics Metric Cards
        self._build_stats_section(main_layout)

        # 3. Live Telemetry Banner (for worker runs)
        self._build_telemetry_banner(main_layout)

        # 4. Main Workspace Splitter (Grid on Left, Inspector on Right)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {THEME_COLORS['border_subtle']};
                width: 2px;
            }}
        """)

        # Left Container (Selection Bar + Grid + Pagination)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(14, 10, 14, 10)
        left_layout.setSpacing(8)

        self._build_selection_bar(left_layout)

        # Scroll Area for Grid
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']};")

        self.grid_container = CollectionGridContainer()
        self.scroll_area.setWidget(self.grid_container)
        left_layout.addWidget(self.scroll_area, stretch=1)

        self._build_pagination(left_layout)
        self.splitter.addWidget(left_container)

        # Right Inspector Panel
        self.inspector = ExtractionInspector(self)
        self.inspector.setMinimumWidth(380)
        self.inspector.setMaximumWidth(640)
        self.inspector.asset_updated.connect(self._on_inspector_asset_updated)
        self.inspector.close_requested.connect(lambda: self.inspector.setVisible(False))
        self.splitter.addWidget(self.inspector)

        # Splitter proportions
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)

        main_layout.addWidget(self.splitter, stretch=1)

        # Load initial data
        self.refresh()

    def _build_toolbar(self, parent_layout: QVBoxLayout):
        """Build top controls toolbar."""
        toolbar_frame = QFrame()
        toolbar_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_toolbar']};
                border-bottom: 1px solid {THEME_COLORS['border_subtle']};
            }}
        """)
        tb_layout = QHBoxLayout(toolbar_frame)
        tb_layout.setContentsMargins(16, 10, 16, 10)
        tb_layout.setSpacing(10)

        title = QLabel("Collection Splitter")
        title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 700;
            color: {THEME_COLORS['text_primary']};
        """)
        tb_layout.addWidget(title)

        # Engine pill
        self.lbl_engine = QLabel("✂️ CV Contour & Alpha Splitter (100% Offline)")
        self.lbl_engine.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 600;
            color: #10B981;
            background-color: rgba(16, 185, 129, 0.12);
            padding: 3px 8px;
            border-radius: 4px;
            border: 1px solid rgba(16, 185, 129, 0.3);
        """)
        tb_layout.addWidget(self.lbl_engine)

        tb_layout.addSpacing(10)

        # Analyze All
        self.btn_analyze_all = QPushButton("🔍 Analyze All")
        self.btn_analyze_all.setToolTip("Run collection composition analysis across all imported assets")
        self.btn_analyze_all.setStyleSheet(self._btn_primary_style())
        self.btn_analyze_all.clicked.connect(self._analyze_all)
        tb_layout.addWidget(self.btn_analyze_all)

        # Analyze Selected
        self.btn_analyze_sel = QPushButton("Analyze Selected")
        self.btn_analyze_sel.setStyleSheet(self._btn_secondary_style())
        self.btn_analyze_sel.clicked.connect(self._analyze_selected)
        tb_layout.addWidget(self.btn_analyze_sel)

        # Analyze Uninspected
        self.btn_analyze_uninspected = QPushButton("Analyze Uninspected")
        self.btn_analyze_uninspected.setStyleSheet(self._btn_secondary_style())
        self.btn_analyze_uninspected.clicked.connect(self._analyze_uninspected)
        tb_layout.addWidget(self.btn_analyze_uninspected)

        # Pause / Resume / Cancel Controls
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(self._btn_secondary_style())
        self.btn_pause.clicked.connect(self._pause_worker)
        tb_layout.addWidget(self.btn_pause)

        self.btn_resume = QPushButton("▶ Resume")
        self.btn_resume.setEnabled(False)
        self.btn_resume.setStyleSheet(self._btn_secondary_style())
        self.btn_resume.clicked.connect(self._resume_worker)
        tb_layout.addWidget(self.btn_resume)

        self.btn_cancel = QPushButton("⏹ Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet(self._btn_danger_style())
        self.btn_cancel.clicked.connect(self._cancel_worker)
        tb_layout.addWidget(self.btn_cancel)

        tb_layout.addStretch()

        # Search Bar
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search filenames...")
        self.txt_search.setFixedWidth(160)
        self.txt_search.setStyleSheet(self._input_style())
        self.txt_search.textChanged.connect(self._on_filter_changed)
        tb_layout.addWidget(self.txt_search)

        # Collection Filter
        self.combo_coll = QComboBox()
        self.combo_coll.addItems(["All Collections", "Excavator", "Other Images"])
        self.combo_coll.setStyleSheet(self._input_style())
        self.combo_coll.currentIndexChanged.connect(self._on_filter_changed)
        tb_layout.addWidget(self.combo_coll)

        # Composition Filter Dropdown
        self.combo_comp_filter = QComboBox()
        self.combo_comp_filter.addItems([
            "All Compositions",
            "Collections (Multi/Sprite)",
            "Multiple Object Collection",
            "Overlapping Object Collection",
            "Sprite Sheet",
            "Animation Frame Grid",
            "Single Object",
            "Background Scene",
            "Unknown Composition",
            "Ready to Split",
            "Extracted",
            "Uninspected",
        ])
        self.combo_comp_filter.setStyleSheet(self._input_style())
        self.combo_comp_filter.currentIndexChanged.connect(self._on_filter_changed)
        tb_layout.addWidget(self.combo_comp_filter)

        # Refresh Button
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setFixedSize(32, 32)
        self.btn_refresh.setToolTip("Refresh view")
        self.btn_refresh.setStyleSheet(self._btn_secondary_style())
        self.btn_refresh.clicked.connect(self.refresh)
        tb_layout.addWidget(self.btn_refresh)

        parent_layout.addWidget(toolbar_frame)

    def _build_stats_section(self, parent_layout: QVBoxLayout):
        """Build 6 metric cards from real SQLite database queries."""
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_main']};
                border-bottom: 1px solid {THEME_COLORS['border_subtle']};
            }}
        """)
        s_layout = QHBoxLayout(stats_frame)
        s_layout.setContentsMargins(16, 10, 16, 10)
        s_layout.setSpacing(12)

        self.card_total = StatCard("TOTAL IMAGES", "0", "All assets in catalog", "📁")
        self.card_analyzed = StatCard("ANALYZED", "0", "Completed composition scan", "🔍")
        self.card_collections = StatCard("COLLECTION CANDIDATES", "0", "Multi-object images", "🧩")
        self.card_sprites = StatCard("SPRITE SHEETS", "0", "Uniform frame grids", "🎞️")
        self.card_ready = StatCard("READY TO SPLIT", "0", "Approved for extraction", "✂️")
        self.card_extracted = StatCard("EXTRACTED ASSETS", "0", "Total isolated assets saved", "✓")

        for c in [
            self.card_total, self.card_analyzed, self.card_collections,
            self.card_sprites, self.card_ready, self.card_extracted,
        ]:
            s_layout.addWidget(c)

        parent_layout.addWidget(stats_frame)

    def _build_telemetry_banner(self, parent_layout: QVBoxLayout):
        """Live progress banner shown when background analysis is active."""
        self.telemetry_banner = QFrame()
        self.telemetry_banner.setVisible(False)
        self.telemetry_banner.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border-bottom: 2px solid {THEME_COLORS['accent_primary']};
            }}
        """)
        t_layout = QVBoxLayout(self.telemetry_banner)
        t_layout.setContentsMargins(16, 8, 16, 8)
        t_layout.setSpacing(6)

        info_row = QHBoxLayout()
        self.lbl_telemetry_status = QLabel("Analyzing images for collections and sprite sheets...")
        self.lbl_telemetry_status.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {THEME_COLORS['text_primary']};")
        info_row.addWidget(self.lbl_telemetry_status)
        info_row.addStretch()

        self.lbl_telemetry_metrics = QLabel("0/0 (0%) • Collections: 0 • Single: 0 • Remaining: 0")
        self.lbl_telemetry_metrics.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['accent_primary']}; font-weight: 600;")
        info_row.addWidget(self.lbl_telemetry_metrics)
        t_layout.addLayout(info_row)

        self.telemetry_bar = QProgressBar()
        self.telemetry_bar.setFixedHeight(8)
        self.telemetry_bar.setTextVisible(False)
        self.telemetry_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {THEME_COLORS['bg_input']};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {THEME_COLORS['accent_primary']};
                border-radius: 4px;
            }}
        """)
        t_layout.addWidget(self.telemetry_bar)

        parent_layout.addWidget(self.telemetry_banner)

    def _build_selection_bar(self, parent_layout: QVBoxLayout):
        """Row with select all, clear, and item count."""
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)

        self.lbl_match_count = QLabel("Showing 0 assets")
        self.lbl_match_count.setStyleSheet(f"font-size: 12px; color: {THEME_COLORS['text_secondary']};")
        bar.addWidget(self.lbl_match_count)

        bar.addSpacing(12)

        self.lbl_selected_count = QLabel("0 selected")
        self.lbl_selected_count.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {THEME_COLORS['accent_primary']};")
        bar.addWidget(self.lbl_selected_count)

        btn_select_all = QPushButton("Select All")
        btn_select_all.setStyleSheet(self._link_btn_style())
        btn_select_all.clicked.connect(self._select_all)
        bar.addWidget(btn_select_all)

        btn_clear = QPushButton("Clear")
        btn_clear.setStyleSheet(self._link_btn_style())
        btn_clear.clicked.connect(self._clear_selection)
        bar.addWidget(btn_clear)

        bar.addStretch()
        parent_layout.addLayout(bar)

    def _build_pagination(self, parent_layout: QVBoxLayout):
        """Bottom page navigation."""
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 6, 0, 0)
        bar.addStretch()

        self.btn_prev = QPushButton("◀ Previous")
        self.btn_prev.setStyleSheet(self._btn_secondary_style())
        self.btn_prev.clicked.connect(self._prev_page)
        bar.addWidget(self.btn_prev)

        self.lbl_page = QLabel("Page 1 of 1")
        self.lbl_page.setStyleSheet(f"font-size: 12px; color: {THEME_COLORS['text_secondary']}; padding: 0 10px;")
        bar.addWidget(self.lbl_page)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setStyleSheet(self._btn_secondary_style())
        self.btn_next.clicked.connect(self._next_page)
        bar.addWidget(self.btn_next)

        bar.addStretch()
        parent_layout.addLayout(bar)

    # Filtering & Queries
    def _build_query_kwargs(self) -> Dict[str, Any]:
        """Convert UI filter selections into DatabaseManager query parameters."""
        kw: Dict[str, Any] = {}

        q = self.txt_search.text().strip()
        if q:
            kw["search"] = q

        coll_idx = self.combo_coll.currentIndex()
        if coll_idx == 1:
            kw["collection"] = "excavator"
        elif coll_idx == 2:
            kw["collection"] = "other_images"

        cf = self.combo_comp_filter.currentText()
        if cf == "Collections (Multi/Sprite)":
            kw["splitter_status"] = "has_multiple"
        elif cf == "Ready to Split":
            kw["splitter_status"] = "ready_to_split"
        elif cf == "Extracted":
            kw["splitter_extraction"] = "extracted"
        elif cf == "Uninspected":
            kw["splitter_status"] = "uninspected"
        elif cf in COMPOSITION_TYPES:
            kw["splitter_composition"] = cf

        return kw

    def refresh(self):
        """Full refresh of statistics cards, database queries, and grid cards."""
        self._refresh_stats()
        self._reload_page()

    def _refresh_stats(self):
        """Query real SQLite metrics for cards."""
        stats = db.get_collection_splitter_stats()
        self.card_total.update_value(str(stats["total_images"]))
        self.card_analyzed.update_value(str(stats["analyzed_images"]))
        self.card_collections.update_value(str(stats["collection_candidates"]))
        self.card_sprites.update_value(str(stats["sprite_sheets"]))
        self.card_ready.update_value(str(stats["ready_to_split"]))
        self.card_extracted.update_value(str(stats["extracted_assets"]))

    def _reload_page(self):
        """Fetch current page of assets and populate grid."""
        kw = self._build_query_kwargs()
        self.total_matching = db.get_assets_count(**kw)

        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        if self.current_page > total_pages:
            self.current_page = total_pages

        offset = (self.current_page - 1) * self.page_size
        self.current_assets = db.get_assets(
            limit=self.page_size,
            offset=offset,
            order_by="id ASC",
            **kw
        )

        cards: List[CollectionCard] = []
        for asset in self.current_assets:
            card = CollectionCard(asset, self.grid_container)
            card.set_selected(asset["id"] in self.selected_ids)
            card.clicked.connect(self._on_card_clicked)
            card.selection_toggled.connect(self._on_card_selection_toggled)
            cards.append(card)

        self.grid_container.set_cards(cards)

        # Update labels & pagination buttons
        start_idx = offset + 1 if self.total_matching > 0 else 0
        end_idx = min(offset + len(self.current_assets), self.total_matching)
        self.lbl_match_count.setText(f"Showing {start_idx}–{end_idx} of {self.total_matching} assets")
        self.lbl_page.setText(f"Page {self.current_page} of {total_pages}")
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < total_pages)
        self.lbl_selected_count.setText(f"{len(self.selected_ids)} selected")

        # Select first asset in inspector if none loaded
        if self.current_assets and self.inspector.current_asset is None:
            self.inspector.load_asset(self.current_assets[0])

    def _on_filter_changed(self):
        self.current_page = 1
        self._reload_page()

    def _prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._reload_page()

    def _next_page(self):
        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        if self.current_page < total_pages:
            self.current_page += 1
            self._reload_page()

    def _select_all(self):
        for asset in self.current_assets:
            self.selected_ids.add(asset["id"])
        for card in self.grid_container.cards:
            card.set_selected(True)
        self.lbl_selected_count.setText(f"{len(self.selected_ids)} selected")

    def _clear_selection(self):
        self.selected_ids.clear()
        for card in self.grid_container.cards:
            card.set_selected(False)
        self.lbl_selected_count.setText("0 selected")

    def _on_card_clicked(self, asset_id: int, is_ctrl: bool, is_shift: bool):
        """Card clicked -> load into inspector and handle multi-selection."""
        asset = next((a for a in self.current_assets if a["id"] == asset_id), None)
        if not asset:
            return

        # Load into inspector
        self.inspector.setVisible(True)
        self.inspector.load_asset(asset)

        if is_ctrl:
            if asset_id in self.selected_ids:
                self.selected_ids.remove(asset_id)
            else:
                self.selected_ids.add(asset_id)
        elif is_shift and self.last_clicked_id is not None:
            ids = [a["id"] for a in self.current_assets]
            try:
                idx1 = ids.index(self.last_clicked_id)
                idx2 = ids.index(asset_id)
                start, end = min(idx1, idx2), max(idx1, idx2)
                for aid in ids[start:end + 1]:
                    self.selected_ids.add(aid)
            except ValueError:
                self.selected_ids.add(asset_id)
        else:
            self.selected_ids.clear()
            self.selected_ids.add(asset_id)

        self.last_clicked_id = asset_id
        for card in self.grid_container.cards:
            card.set_selected(card.asset_id in self.selected_ids)
        self.lbl_selected_count.setText(f"{len(self.selected_ids)} selected")

    def _on_card_selection_toggled(self, asset_id: int, is_selected: bool):
        if is_selected:
            self.selected_ids.add(asset_id)
        else:
            self.selected_ids.discard(asset_id)
        self.lbl_selected_count.setText(f"{len(self.selected_ids)} selected")

    def _on_inspector_asset_updated(self, asset_id: int):
        """Inspector saved changes to asset or regions."""
        self._refresh_stats()
        # Update matching card in grid without full reset
        updated = db.get_asset(asset_id)
        if updated:
            for card in self.grid_container.cards:
                if card.asset_id == asset_id:
                    card.asset = updated
                    break
        self.status_updated.emit()

    # Background Worker Execution
    def _analyze_all(self):
        coll_idx = self.combo_coll.currentIndex()
        coll = None
        if coll_idx == 1:
            coll = "excavator"
        elif coll_idx == 2:
            coll = "other_images"
        self._start_worker(mode="all", collection=coll)

    def _analyze_selected(self):
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select at least one asset to analyze.")
            return
        self._start_worker(mode="selected", asset_ids=list(self.selected_ids))

    def _analyze_uninspected(self):
        coll_idx = self.combo_coll.currentIndex()
        coll = None
        if coll_idx == 1:
            coll = "excavator"
        elif coll_idx == 2:
            coll = "other_images"
        self._start_worker(mode="uninspected", collection=coll)

    def _start_worker(self, mode: str, asset_ids: Optional[List[int]] = None, collection: Optional[str] = None):
        """Launch background CollectionAnalysisWorker."""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Worker Running", "An analysis process is already in progress.")
            return

        self.worker = CollectionAnalysisWorker(
            mode=mode,
            asset_ids=asset_ids,
            collection=collection,
            parent=self,
        )

        self.worker.analysis_started.connect(self._on_worker_started)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.asset_analyzed.connect(self._on_worker_asset_analyzed)
        self.worker.analysis_paused.connect(self._on_worker_paused)
        self.worker.analysis_finished.connect(self._on_worker_finished)
        self.worker.analysis_error.connect(self._on_worker_error)

        # Set UI state
        self.btn_analyze_all.setEnabled(False)
        self.btn_analyze_sel.setEnabled(False)
        self.btn_analyze_uninspected.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        self.telemetry_banner.setVisible(True)
        self.telemetry_bar.setValue(0)
        self.lbl_telemetry_status.setText(f"Initiating collection analysis ({mode})...")

        self.worker.start()

    def _pause_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.pause()
            self.btn_pause.setEnabled(False)
            self.btn_resume.setEnabled(True)

    def _resume_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.resume()
            self.btn_pause.setEnabled(True)
            self.btn_resume.setEnabled(False)

    def _cancel_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.lbl_telemetry_status.setText("Halting collection analysis...")

    def _on_worker_started(self, total: int):
        self.telemetry_bar.setMaximum(total)
        self.telemetry_bar.setValue(0)
        self.lbl_telemetry_status.setText(f"Analyzing {total} images for object collections...")

    def _on_worker_progress(self, current: int, total: int, filename: str, collections: int, single: int, remaining: int):
        self.telemetry_bar.setValue(current)
        pct = int(current / total * 100) if total > 0 else 0
        self.lbl_telemetry_status.setText(f"Analyzing: {filename}")
        self.lbl_telemetry_metrics.setText(
            f"{current}/{total} ({pct}%) • Collections: {collections} • Single: {single} • Remaining: {remaining}"
        )

    def _on_worker_asset_analyzed(self, asset: dict):
        # Dynamically update card in view
        for card in self.grid_container.cards:
            if card.asset_id == asset["id"]:
                card.asset = asset
                break

    def _on_worker_paused(self, is_paused: bool):
        if is_paused:
            self.lbl_telemetry_status.setText("Collection analysis paused by user.")
        else:
            self.lbl_telemetry_status.setText("Resuming collection analysis...")

    def _on_worker_finished(self, summary: dict):
        self.btn_analyze_all.setEnabled(True)
        self.btn_analyze_sel.setEnabled(True)
        self.btn_analyze_uninspected.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_cancel.setEnabled(False)

        self.telemetry_banner.setVisible(False)
        self.refresh()
        self.status_updated.emit()

        if not summary.get("cancelled"):
            QMessageBox.information(
                self,
                "Analysis Complete",
                f"Collection analysis completed for {summary.get('processed', 0)} images.\n"
                f"• Collections: {summary.get('collections', 0)}\n"
                f"• Sprite Sheets: {summary.get('sprite_sheets', 0)}\n"
                f"• Single Objects: {summary.get('single_objects', 0)}\n"
                f"• Background Scenes: {summary.get('scenes', 0)}"
            )

    def _on_worker_error(self, err_msg: str):
        self.btn_analyze_all.setEnabled(True)
        self.btn_analyze_sel.setEnabled(True)
        self.btn_analyze_uninspected.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.telemetry_banner.setVisible(False)
        QMessageBox.critical(self, "Analysis Worker Error", err_msg)

    # Styles
    def _btn_primary_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_muted']};
            }}
        """

    def _btn_secondary_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['bg_card_hover']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
            QPushButton:disabled {{
                color: {THEME_COLORS['text_muted']};
                border-color: {THEME_COLORS['border_subtle']};
            }}
        """

    def _btn_danger_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: rgba(239, 68, 68, 0.15);
                color: {THEME_COLORS['status_error']};
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['status_error']};
                color: #FFFFFF;
            }}
            QPushButton:disabled {{
                color: {THEME_COLORS['text_muted']};
                border-color: {THEME_COLORS['border_subtle']};
                background: transparent;
            }}
        """

    def _input_style(self) -> str:
        return f"""
            background-color: {THEME_COLORS['bg_input']};
            color: {THEME_COLORS['text_primary']};
            border: 1px solid {THEME_COLORS['border_medium']};
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 11px;
        """

    def _link_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {THEME_COLORS['accent_primary']};
                font-size: 11px;
                font-weight: 600;
                text-decoration: underline;
                padding: 0 4px;
            }}
            QPushButton:hover {{
                color: {THEME_COLORS['accent_hover']};
            }}
        """
