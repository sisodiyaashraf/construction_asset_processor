"""
AI Classification Master View
Coordinates AI batch analysis, progress telemetry, filter toolbar,
metric cards, card grid, pagination, and the AI Inspector.
"""

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
from core.ai_engine import CATEGORIES, vision_classifier
from core.database import db
from core.workers import ClassificationWorker
from ui.components.ai_inspector import AIInspector
from ui.components.classification_card import ClassificationCard
from ui.components.stat_card import StatCard


class ClassificationGridContainer(QWidget):
    """Container that flows ClassificationCards responsively based on width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cards: List[ClassificationCard] = []

    def set_cards(self, cards: List[ClassificationCard]):
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
        avail_width = max(self.width() - 30, 460)
        card_w = ClassificationCard.CARD_WIDTH + 12
        cols = max(1, avail_width // card_w)
        for idx, card in enumerate(self.cards):
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._relayout()


class ClassificationView(QWidget):
    """Primary AI Classification screen for batch analysis and verification."""

    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_page = 1
        self.page_size = 48
        self.total_matching = 0
        self.current_assets: List[Dict[str, Any]] = []
        self.selected_ids: Set[int] = set()
        self.last_clicked_id: Optional[int] = None

        self.worker: Optional[ClassificationWorker] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Control & Batch Toolbar
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)

        # 2. Main Body Splitter (Workspace | Right AI Inspector)
        body_splitter = QSplitter(Qt.Horizontal)
        body_splitter.setHandleWidth(1)

        # 2a. Left Workspace (Metrics + Live Progress + Grid + Pagination)
        workspace = QWidget()
        ws_layout = QVBoxLayout(workspace)
        ws_layout.setContentsMargins(14, 12, 14, 0)
        ws_layout.setSpacing(10)

        # Statistics Cards Row (6 real database metrics)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        self.card_total = StatCard("Total Images", "0", "Cataloged assets", "🖼️")
        self.card_analyzed = StatCard("Analyzed", "0", "Processed by AI", "⚡", accent_color=THEME_COLORS["status_info"])
        self.card_pending = StatCard("Pending AI", "0", "Awaiting recognition", "⏳", accent_color=THEME_COLORS["status_warning"])
        self.card_classified = StatCard("High Conf", "0", "Confidence ≥ 75%", "✅", accent_color=THEME_COLORS["status_success"])
        self.card_review = StatCard("Needs Review", "0", "Flagged or Low Conf", "⚠️", accent_color=THEME_COLORS["status_warning"])
        self.card_unknown = StatCard("Unknown", "0", "Uncertain objects", "❓", accent_color=THEME_COLORS["text_muted"])

        for c in [self.card_total, self.card_analyzed, self.card_pending, self.card_classified, self.card_review, self.card_unknown]:
            stats_row.addWidget(c)
        ws_layout.addLayout(stats_row)

        # Live Progress Banner (Hidden when idle)
        self.progress_banner = QFrame()
        self.progress_banner.setProperty("class", "card")
        self.progress_banner.setVisible(False)
        pb_layout = QVBoxLayout(self.progress_banner)
        pb_layout.setContentsMargins(12, 8, 12, 8)
        pb_layout.setSpacing(4)

        pb_top = QHBoxLayout()
        self.lbl_progress_status = QLabel("AI Recognition in progress...")
        self.lbl_progress_status.setStyleSheet(f"font-weight: 700; color: {THEME_COLORS['accent_primary']}; font-size: 12px;")
        pb_top.addWidget(self.lbl_progress_status)
        pb_top.addStretch()

        self.lbl_progress_count = QLabel("0 / 0 (0%)")
        self.lbl_progress_count.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_primary']}; font-size: 11px;")
        pb_top.addWidget(self.lbl_progress_count)
        pb_layout.addLayout(pb_top)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        pb_layout.addWidget(self.progress_bar)

        self.lbl_progress_item = QLabel("Processing...")
        self.lbl_progress_item.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        pb_layout.addWidget(self.lbl_progress_item)

        ws_layout.addWidget(self.progress_banner)

        # Card Grid Scroll Area
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_container = ClassificationGridContainer()
        self.grid_scroll.setWidget(self.grid_container)
        ws_layout.addWidget(self.grid_scroll, stretch=1)

        # Bottom Pagination Bar
        pagination_bar = self._create_pagination_bar()
        ws_layout.addWidget(pagination_bar)

        body_splitter.addWidget(workspace)

        # 2b. Right AI Inspector
        self.inspector = AIInspector(self)
        self.inspector.classification_approved.connect(self._on_inspector_approved)
        self.inspector.classification_saved.connect(self._on_inspector_saved)
        self.inspector.classification_rejected.connect(self._on_inspector_rejected)
        self.inspector.reanalyze_requested.connect(self._on_inspector_reanalyze)
        self.inspector.close_requested.connect(lambda: self.inspector.setVisible(False))
        body_splitter.addWidget(self.inspector)

        body_splitter.setStretchFactor(0, 3)
        body_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(body_splitter, stretch=1)

        self.reload_view()

    def _create_toolbar(self) -> QFrame:
        """Create the top controls toolbar."""
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"""
            background-color: {THEME_COLORS['bg_toolbar']};
            border-bottom: 1px solid {THEME_COLORS['border_subtle']};
            padding: 0 14px;
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        # Title
        lbl_title = QLabel("AI Recognition")
        lbl_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {THEME_COLORS['text_primary']};")
        layout.addWidget(lbl_title)

        layout.addSpacing(6)

        # Batch Action Buttons
        self.btn_start = QPushButton("▶ Start AI Analysis")
        self.btn_start.setProperty("class", "btn_primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_batch_analysis)
        layout.addWidget(self.btn_start)

        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setProperty("class", "btn_secondary")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._pause_resume_analysis)
        layout.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹ Cancel")
        self.btn_cancel.setProperty("class", "btn_danger")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_analysis)
        layout.addWidget(self.btn_cancel)

        self.btn_reanalyze_sel = QPushButton("⚡ Re-analyze Sel")
        self.btn_reanalyze_sel.setProperty("class", "btn_secondary")
        self.btn_reanalyze_sel.setCursor(Qt.PointingHandCursor)
        self.btn_reanalyze_sel.clicked.connect(self._analyze_selected)
        layout.addWidget(self.btn_reanalyze_sel)

        layout.addStretch()

        # Search box
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Search asset or object...")
        self.txt_search.setFixedWidth(180)
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.txt_search)

        # Collection Filter
        self.cmb_collection = QComboBox()
        self.cmb_collection.setFixedWidth(130)
        self.cmb_collection.addItem("All Collections", "all")
        self.cmb_collection.addItem("🚜 Excavator", "excavator")
        self.cmb_collection.addItem("🧱 Other Images", "other_images")
        self.cmb_collection.currentIndexChanged.connect(lambda: self.reload_view())
        layout.addWidget(self.cmb_collection)

        # Category Filter
        self.cmb_cat_filter = QComboBox()
        self.cmb_cat_filter.setFixedWidth(160)
        self.cmb_cat_filter.addItem("All Categories", "all")
        for cat in CATEGORIES.keys():
            self.cmb_cat_filter.addItem(cat, cat)
        self.cmb_cat_filter.addItem("Unclassified", "Unclassified")
        self.cmb_cat_filter.currentIndexChanged.connect(lambda: self.reload_view())
        layout.addWidget(self.cmb_cat_filter)

        # Status Filter
        self.cmb_status_filter = QComboBox()
        self.cmb_status_filter.setFixedWidth(130)
        self.cmb_status_filter.addItem("All Statuses", "all")
        self.cmb_status_filter.addItem("Unclassified", "unclassified")
        self.cmb_status_filter.addItem("Suggested", "suggested")
        self.cmb_status_filter.addItem("Approved", "approved")
        self.cmb_status_filter.addItem("Rejected", "rejected")
        self.cmb_status_filter.addItem("Manual", "manual")
        self.cmb_status_filter.currentIndexChanged.connect(lambda: self.reload_view())
        layout.addWidget(self.cmb_status_filter)

        # Reload Button
        btn_refresh = QPushButton("🔄")
        btn_refresh.setProperty("class", "btn_secondary")
        btn_refresh.setFixedSize(32, 32)
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.reload_view)
        layout.addWidget(btn_refresh)

        return bar

    def _create_pagination_bar(self) -> QFrame:
        """Create bottom pagination navigation."""
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"""
            background-color: {THEME_COLORS['bg_toolbar']};
            border-top: 1px solid {THEME_COLORS['border_subtle']};
            padding: 0 14px;
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        self.lbl_page_info = QLabel("Showing 0–0 of 0 assets")
        self.lbl_page_info.setStyleSheet(f"color: {THEME_COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(self.lbl_page_info)

        layout.addStretch()

        self.btn_first = QPushButton("⏮ First")
        self.btn_first.setProperty("class", "btn_secondary")
        self.btn_first.setCursor(Qt.PointingHandCursor)
        self.btn_first.clicked.connect(lambda: self._set_page(1))
        layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton("◀ Prev")
        self.btn_prev.setProperty("class", "btn_secondary")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(lambda: self._set_page(self.current_page - 1))
        layout.addWidget(self.btn_prev)

        self.lbl_current_page = QLabel("Page 1 of 1")
        self.lbl_current_page.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 600; font-size: 12px;")
        layout.addWidget(self.lbl_current_page)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setProperty("class", "btn_secondary")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(lambda: self._set_page(self.current_page + 1))
        layout.addWidget(self.btn_next)

        self.btn_last = QPushButton("Last ⏭")
        self.btn_last.setProperty("class", "btn_secondary")
        self.btn_last.setCursor(Qt.PointingHandCursor)
        self.btn_last.clicked.connect(self._go_last_page)
        layout.addWidget(self.btn_last)

        layout.addSpacing(10)

        self.cmb_page_size = QComboBox()
        self.cmb_page_size.addItem("24", 24)
        self.cmb_page_size.addItem("48", 48)
        self.cmb_page_size.addItem("72", 72)
        self.cmb_page_size.addItem("All", 99999)
        self.cmb_page_size.setCurrentIndex(1)
        self.cmb_page_size.currentIndexChanged.connect(self._on_page_size_changed)
        layout.addWidget(self.cmb_page_size)

        return bar

    def reload_view(self):
        """Update metrics cards and render active card page."""
        # 1. Update 6 Real Database Stat Cards
        stats = db.get_classification_stats()
        self.card_total.update_data(str(stats["total_images"]))
        self.card_analyzed.update_data(str(stats["analyzed_images"]))
        self.card_pending.update_data(str(stats["pending_analysis"]))
        self.card_classified.update_data(str(stats["successfully_classified"]))
        self.card_review.update_data(str(stats["needs_manual_review"]))
        self.card_unknown.update_data(str(stats["unknown_images"]))

        # 2. Build Query Filters
        coll = self.cmb_collection.currentData()
        coll_param = coll if coll != "all" else None

        cat = self.cmb_cat_filter.currentData()
        cat_param = cat if cat != "all" else None

        st = self.cmb_status_filter.currentData()
        st_param = st if st != "all" else None

        search_txt = self.txt_search.text().strip()

        # Total Matching
        self.total_matching = db.get_assets_count(
            collection=coll_param,
            category=cat_param,
            classification_status=st_param,
            search=search_txt
        )

        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        if self.current_page > total_pages:
            self.current_page = total_pages

        offset = (self.current_page - 1) * self.page_size

        # Fetch Paginated Assets
        self.current_assets = db.get_assets(
            collection=coll_param,
            category=cat_param,
            classification_status=st_param,
            search=search_txt,
            sort_by="id",
            ascending=True,
            limit=self.page_size,
            offset=offset
        )

        # Update Pagination UI
        start_idx = offset + 1 if self.total_matching > 0 else 0
        end_idx = min(offset + len(self.current_assets), self.total_matching)
        self.lbl_page_info.setText(f"Showing {start_idx}–{end_idx} of {self.total_matching} assets")
        self.lbl_current_page.setText(f"Page {self.current_page} of {total_pages}")

        self.btn_first.setEnabled(self.current_page > 1)
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < total_pages)
        self.btn_last.setEnabled(self.current_page < total_pages)

        # Render Cards
        cards: List[ClassificationCard] = []
        for asset in self.current_assets:
            card = ClassificationCard(asset)
            card.set_selected(asset["id"] in self.selected_ids)
            card.clicked.connect(self._on_card_clicked)
            card.approve_requested.connect(self._on_card_approve)
            card.reject_requested.connect(self._on_card_reject)
            cards.append(card)

        self.grid_container.set_cards(cards)

    def _on_card_clicked(self, asset_id: int, is_ctrl: bool, is_shift: bool):
        """Card selection and inspector synchronization."""
        target_asset = next((a for a in self.current_assets if a["id"] == asset_id), None)

        if is_shift and self.last_clicked_id is not None:
            ids = [a["id"] for a in self.current_assets]
            try:
                i1 = ids.index(self.last_clicked_id)
                i2 = ids.index(asset_id)
                start, end = min(i1, i2), max(i1, i2)
                for i in range(start, end + 1):
                    self.selected_ids.add(ids[i])
            except ValueError:
                self.selected_ids.add(asset_id)
        elif is_ctrl:
            if asset_id in self.selected_ids:
                self.selected_ids.remove(asset_id)
            else:
                self.selected_ids.add(asset_id)
        else:
            self.selected_ids = {asset_id}

        self.last_clicked_id = asset_id

        # Update visuals
        for card in self.grid_container.cards:
            card.set_selected(card.asset_id in self.selected_ids)

        if target_asset:
            self.inspector.setVisible(True)
            self.inspector.inspect_asset(target_asset)

    def _start_batch_analysis(self):
        """Initiate background batch analysis on all pending or unclassified assets."""
        coll = self.cmb_collection.currentData()
        coll_param = coll if coll != "all" else None

        self._run_worker(mode="unclassified", collection=coll_param)

    def _analyze_selected(self):
        """Analyze currently selected cards."""
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select one or more assets to analyze.")
            return
        self._run_worker(mode="selected", asset_ids=list(self.selected_ids))

    def _run_worker(self, mode: str, collection: Optional[str] = None, asset_ids: Optional[List[int]] = None):
        """Launch background classification thread."""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Worker Busy", "AI Classification is already running.")
            return

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸ Pause")
        self.btn_cancel.setEnabled(True)
        self.btn_reanalyze_sel.setEnabled(False)

        self.progress_banner.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_progress_status.setText("Initializing AI vision analysis...")

        self.worker = ClassificationWorker(
            asset_ids=asset_ids,
            collection=collection,
            mode=mode,
            parent=self
        )
        self.worker.analysis_started.connect(self._on_worker_started)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.asset_classified.connect(self._on_worker_asset_classified)
        self.worker.analysis_finished.connect(self._on_worker_finished)
        self.worker.analysis_paused.connect(self._on_worker_paused)
        self.worker.analysis_error.connect(self._on_worker_error)
        self.worker.start()

    def _pause_resume_analysis(self):
        if self.worker and self.worker.isRunning():
            if self.worker._is_paused:
                self.worker.resume()
                self.btn_pause.setText("⏸ Pause")
            else:
                self.worker.pause()
                self.btn_pause.setText("▶ Resume")

    def _cancel_analysis(self):
        if self.worker and self.worker.isRunning():
            self.lbl_progress_status.setText("Cancelling analysis...")
            self.worker.request_cancel()
            self.btn_cancel.setEnabled(False)

    def _on_worker_started(self, total: int):
        self.lbl_progress_status.setText(f"Running LocalVisionEngine on {total} images...")
        self.lbl_progress_count.setText(f"0 / {total} (0%)")

    def _on_worker_progress(self, current: int, total: int, filename: str, result: dict):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.lbl_progress_count.setText(f"{current} / {total} ({pct}%)")
        self.lbl_progress_item.setText(f"Classified: {filename} → {result.get('object_name')} ({result.get('main_category')})")

    def _on_worker_asset_classified(self, asset: dict):
        """Update active card if present on current page."""
        aid = asset["id"]
        for card in self.grid_container.cards:
            if card.asset_id == aid:
                card.asset = asset
                card.lbl_object_name.setText(asset.get("object_name") or "")
                card.lbl_category.setText(f"{asset.get('main_category')} › {asset.get('subcategory')}")
                conf = float(asset.get("confidence_score") or 0.0)
                card.lbl_conf.setText(f"{int(conf*100)}%")
                card.lbl_status.setText(str(asset.get("classification_status")).capitalize())

        # If currently open in inspector, update inspector view
        if self.inspector.current_asset and self.inspector.current_asset["id"] == aid:
            self.inspector.inspect_asset(asset)

    def _on_worker_finished(self, summary: dict):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Pause")
        self.btn_cancel.setEnabled(False)
        self.btn_reanalyze_sel.setEnabled(True)

        self.lbl_progress_status.setText(
            f"Finished! Processed {summary['processed']} assets ({summary['classified']} classified, {summary['errors']} errors)."
        )
        self.status_updated.emit()
        self.reload_view()

    def _on_worker_paused(self, is_paused: bool):
        if is_paused:
            self.lbl_progress_status.setText("AI Recognition paused. Click Resume to continue.")
        else:
            self.lbl_progress_status.setText("AI Recognition resumed.")

    def _on_worker_error(self, err_msg: str):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_reanalyze_sel.setEnabled(True)
        self.lbl_progress_status.setText("Analysis failed with error.")
        QMessageBox.critical(self, "AI Error", err_msg)

    def _on_card_approve(self, asset_id: int):
        db.update_classification_status(asset_id, "approved")
        self.status_updated.emit()
        self.reload_view()

    def _on_card_reject(self, asset_id: int):
        db.update_classification_status(asset_id, "rejected")
        self.status_updated.emit()
        self.reload_view()

    def _on_inspector_approved(self, asset_id: int):
        self.status_updated.emit()
        self.reload_view()

    def _on_inspector_saved(self, asset_id: int, edits: dict):
        self.status_updated.emit()
        self.reload_view()

    def _on_inspector_rejected(self, asset_id: int):
        self.status_updated.emit()
        self.reload_view()

    def _on_inspector_reanalyze(self, asset_id: int):
        asset = db.get_asset(asset_id)
        if asset:
            res = vision_classifier.analyze_asset(asset)
            db.save_classification(asset_id, res.to_dict(), action="reanalyzed")
            updated = db.get_asset(asset_id)
            if updated:
                self.inspector.inspect_asset(updated)
            self.status_updated.emit()
            self.reload_view()

    def _on_search_changed(self, text: str):
        self.current_page = 1
        self.reload_view()

    def _set_page(self, page_num: int):
        self.current_page = max(1, page_num)
        self.reload_view()

    def _go_last_page(self):
        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        self.current_page = total_pages
        self.reload_view()

    def _on_page_size_changed(self, index: int):
        self.page_size = self.cmb_page_size.currentData()
        self.current_page = 1
        self.reload_view()
