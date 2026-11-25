"""
Background Removal & Transparency Master View (Stage 5)
Coordinates eligibility analysis, background removal batch processing,
real-time telemetry banner, metric cards, responsive asset grid,
and right-side transparency inspector.
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
from core.database import db
from core.transparency_engine import (
    ALL_ELIGIBILITY_LABELS, REMBG_AVAILABLE,
    transparency_engine
)
from core.workers import TransparencyWorker
from ui.components.comparison_dialog import ComparisonDialog
from ui.components.stat_card import StatCard
from ui.components.transparency_card import TransparencyCard
from ui.components.transparency_inspector import TransparencyInspector


class TransparencyGridContainer(QWidget):
    """Container that flows TransparencyCards responsively based on width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cards: List[TransparencyCard] = []

    def set_cards(self, cards: List[TransparencyCard]):
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
        card_w = TransparencyCard.CARD_WIDTH + 12
        cols = max(1, avail_width // card_w)
        for idx, card in enumerate(self.cards):
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._relayout()


class BackgroundRemovalView(QWidget):
    """Primary Background Removal & Transparency screen."""

    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_page = 1
        self.page_size = 48
        self.total_matching = 0
        self.current_assets: List[Dict[str, Any]] = []
        self.selected_ids: Set[int] = set()
        self.last_clicked_id: Optional[int] = None

        self.worker: Optional[TransparencyWorker] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Control Toolbar
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)

        # 2. Main Body Splitter (Workspace | Right Inspector)
        body_splitter = QSplitter(Qt.Horizontal)
        body_splitter.setHandleWidth(1)

        # 2a. Workspace
        workspace = QWidget()
        ws_layout = QVBoxLayout(workspace)
        ws_layout.setContentsMargins(14, 12, 14, 0)
        ws_layout.setSpacing(10)

        # Statistics Cards Row (6 real database values)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        self.card_total = StatCard("Total Images", "0", "Cataloged assets", "🖼️")
        self.card_suitable = StatCard("Suitable", "0", "Isolated objects", "✂️", accent_color=THEME_COLORS["status_success"])
        self.card_review = StatCard("Needs Review", "0", "Manual inspection", "⚠️", accent_color=THEME_COLORS["status_warning"])
        self.card_transparent = StatCard("Already Alpha", "0", "Transparent files", "💎", accent_color="#A855F7")
        self.card_processed = StatCard("Processed", "0", "Background removed", "✅", accent_color="#10B981")
        self.card_failed = StatCard("Failed", "0", "Processing errors", "❌", accent_color=THEME_COLORS["status_error"])

        for c in [self.card_total, self.card_suitable, self.card_review, self.card_transparent, self.card_processed, self.card_failed]:
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
        self.lbl_progress_status = QLabel("Background removal in progress...")
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
        self.grid_container = TransparencyGridContainer()
        self.grid_scroll.setWidget(self.grid_container)
        ws_layout.addWidget(self.grid_scroll, stretch=1)

        # Bottom Pagination Bar
        pagination_bar = self._create_pagination_bar()
        ws_layout.addWidget(pagination_bar)

        body_splitter.addWidget(workspace)

        # 2b. Right Transparency Inspector
        self.inspector = TransparencyInspector()
        self.inspector.asset_updated.connect(self._on_inspector_asset_updated)
        self.inspector.close_requested.connect(self._on_inspector_close)
        body_splitter.addWidget(self.inspector)

        body_splitter.setStretchFactor(0, 1)
        body_splitter.setStretchFactor(1, 0)
        body_splitter.setSizes([920, 360])

        main_layout.addWidget(body_splitter)

        # Initial Load
        self.refresh()

    def _create_toolbar(self) -> QWidget:
        """Create toolbar with batch controls, engine status, and filters."""
        bar = QFrame()
        bar.setProperty("class", "card")
        bar.setStyleSheet("border-radius: 0px; border-bottom: 1px solid #1E293B;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        # Batch Action Buttons
        self.btn_eval_eligibility = QPushButton("🔍 Analyze Eligibility")
        self.btn_eval_eligibility.setCursor(Qt.PointingHandCursor)
        self.btn_eval_eligibility.setStyleSheet(f"""
            background: {THEME_COLORS['accent_primary']};
            color: #0D1117;
            font-weight: 700;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 11px;
            border: none;
        """)
        self.btn_eval_eligibility.clicked.connect(self._on_eval_eligibility_clicked)
        layout.addWidget(self.btn_eval_eligibility)

        self.btn_process_sel = QPushButton("⚡ Process Selected")
        self.btn_process_sel.setCursor(Qt.PointingHandCursor)
        self.btn_process_sel.setStyleSheet("""
            background: #10B981;
            color: white;
            font-weight: 700;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 11px;
            border: none;
        """)
        self.btn_process_sel.clicked.connect(self._on_process_selected_clicked)
        layout.addWidget(self.btn_process_sel)

        self.btn_process_approved = QPushButton("Process Approved")
        self.btn_process_approved.setCursor(Qt.PointingHandCursor)
        self.btn_process_approved.setStyleSheet("""
            background: #1E293B;
            color: #38BDF8;
            border: 1px solid #334155;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        """)
        self.btn_process_approved.clicked.connect(self._on_process_approved_clicked)
        layout.addWidget(self.btn_process_approved)

        # Pause / Resume / Cancel Controls
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet("background: #1E293B; color: #CBD5E1; padding: 6px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;")
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        layout.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹ Cancel")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("background: #1E293B; color: #EF4444; padding: 6px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self.btn_cancel)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search assets...")
        self.search_input.setFixedWidth(160)
        self.search_input.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            border-radius: 4px;
            color: {THEME_COLORS['text_primary']};
            padding: 5px 8px;
            font-size: 11px;
        """)
        self.search_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.search_input)

        # Collection Filter
        self.combo_collection = QComboBox()
        self.combo_collection.addItems(["All Collections", "Excavator", "Other Images"])
        self.combo_collection.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            color: {THEME_COLORS['text_primary']};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
        """)
        self.combo_collection.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self.combo_collection)

        # Eligibility Filter
        self.combo_eligibility = QComboBox()
        self.combo_eligibility.addItems(["All Eligibility"] + ALL_ELIGIBILITY_LABELS)
        self.combo_eligibility.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            color: {THEME_COLORS['text_primary']};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
        """)
        self.combo_eligibility.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self.combo_eligibility)

        # Processing Status Filter
        self.combo_proc_status = QComboBox()
        self.combo_proc_status.addItems(["All Process States", "Not Processed", "Processed", "Failed"])
        self.combo_proc_status.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            color: {THEME_COLORS['text_primary']};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
        """)
        self.combo_proc_status.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self.combo_proc_status)

        layout.addStretch()

        # Engine Status Pill
        engine_txt = "rembg AI: Ready" if REMBG_AVAILABLE else "Engine: Local CV (Active)"
        engine_col = "#10B981" if REMBG_AVAILABLE else THEME_COLORS["status_info"]
        self.lbl_engine_status = QLabel(engine_txt)
        self.lbl_engine_status.setToolTip("Local CV uses OpenCV & GrabCut (100% offline, zero downloads).")
        self.lbl_engine_status.setStyleSheet(f"""
            color: {engine_col};
            background: #131720;
            border: 1px solid {engine_col}55;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
        """)
        layout.addWidget(self.lbl_engine_status)

        return bar

    def _create_pagination_bar(self) -> QWidget:
        """Create bottom bar with selection counter, bulk buttons and pagination."""
        bar = QFrame()
        bar.setStyleSheet("border-top: 1px solid #1E293B; padding: 4px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        self.lbl_selected_info = QLabel("0 selected")
        self.lbl_selected_info.setStyleSheet(f"color: {THEME_COLORS['accent_primary']}; font-weight: 600; font-size: 11px;")
        layout.addWidget(self.lbl_selected_info)

        btn_sel_all = QPushButton("Select All")
        btn_sel_all.setCursor(Qt.PointingHandCursor)
        btn_sel_all.setStyleSheet("background: transparent; color: #94A3B8; font-size: 11px; border: none;")
        btn_sel_all.clicked.connect(self._on_select_all)
        layout.addWidget(btn_sel_all)

        btn_desel = QPushButton("Clear")
        btn_desel.setCursor(Qt.PointingHandCursor)
        btn_desel.setStyleSheet("background: transparent; color: #94A3B8; font-size: 11px; border: none;")
        btn_desel.clicked.connect(self._on_clear_selection)
        layout.addWidget(btn_desel)

        # Bulk review buttons
        btn_approve_sel = QPushButton("Approve Selected")
        btn_approve_sel.setCursor(Qt.PointingHandCursor)
        btn_approve_sel.setStyleSheet("background: #10B981; color: white; padding: 4px 10px; border-radius: 4px; font-size: 10px; font-weight: 600; border: none;")
        btn_approve_sel.clicked.connect(self._on_bulk_approve_clicked)
        layout.addWidget(btn_approve_sel)

        btn_reject_sel = QPushButton("Reject Selected")
        btn_reject_sel.setCursor(Qt.PointingHandCursor)
        btn_reject_sel.setStyleSheet("background: #EF4444; color: white; padding: 4px 10px; border-radius: 4px; font-size: 10px; font-weight: 600; border: none;")
        btn_reject_sel.clicked.connect(self._on_bulk_reject_clicked)
        layout.addWidget(btn_reject_sel)

        layout.addStretch()

        self.lbl_page_info = QLabel("Page 1 of 1 (0 assets)")
        self.lbl_page_info.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_page_info)

        self.btn_prev = QPushButton("◀ Prev")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.setStyleSheet("background: #1E293B; color: #CBD5E1; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;")
        self.btn_prev.clicked.connect(self._on_prev_page)
        layout.addWidget(self.btn_prev)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setStyleSheet("background: #1E293B; color: #CBD5E1; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;")
        self.btn_next.clicked.connect(self._on_next_page)
        layout.addWidget(self.btn_next)

        return bar

    def refresh(self):
        """Reload statistics and refresh asset grid."""
        self._update_stats_cards()
        self._load_grid_data()

    def _update_stats_cards(self):
        """Query real SQLite stats and update the 6 StatCards."""
        stats = db.get_transparency_stats()
        self.card_total.update_data(str(stats["total_images"]))
        self.card_suitable.update_data(str(stats["suitable_images"]))
        self.card_review.update_data(str(stats["needs_review"]))
        self.card_transparent.update_data(str(stats["already_transparent"]))
        self.card_processed.update_data(str(stats["successfully_processed"]))
        self.card_failed.update_data(str(stats["processing_failed"]))

    def _load_grid_data(self):
        """Query matching assets from SQLite and render into grid."""
        col_text = self.combo_collection.currentText()
        col_param = None
        if col_text == "Excavator":
            col_param = "excavator"
        elif col_text == "Other Images":
            col_param = "other_images"

        elig_text = self.combo_eligibility.currentText()
        elig_param = elig_text if elig_text != "All Eligibility" else None

        proc_text = self.combo_proc_status.currentText()
        proc_param = None
        if proc_text == "Not Processed":
            proc_param = "not_processed"
        elif proc_text == "Processed":
            proc_param = "processed"
        elif proc_text == "Failed":
            proc_param = "failed"

        search_text = self.search_input.text().strip() or None

        kwargs: Dict[str, Any] = {}
        if elig_param:
            kwargs["bg_eligibility"] = elig_param
        if proc_param:
            kwargs["bg_processing_status"] = proc_param

        self.total_matching = db.get_asset_count(
            collection=col_param,
            search=search_text,
            **kwargs
        )

        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        if self.current_page > total_pages:
            self.current_page = total_pages

        offset = (self.current_page - 1) * self.page_size
        self.current_assets = db.get_assets(
            collection=col_param,
            search=search_text,
            limit=self.page_size,
            offset=offset,
            sort_by="id",
            ascending=True,
            **kwargs
        )

        # Render cards
        cards = []
        for asset in self.current_assets:
            card = TransparencyCard(asset)
            card.set_selected(asset["id"] in self.selected_ids)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            cards.append(card)

        self.grid_container.set_cards(cards)

        # Update pagination
        self.lbl_page_info.setText(f"Page {self.current_page} of {total_pages} ({self.total_matching} assets)")
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < total_pages)

        # Load first item in inspector if available
        if self.current_assets:
            target = next((a for a in self.current_assets if a["id"] in self.selected_ids), self.current_assets[0])
            self.inspector.load_asset(target)

    def _on_card_clicked(self, asset_id: int, is_ctrl: bool, is_shift: bool):
        """Handle single selection, Ctrl multi-selection, and Shift range selection."""
        asset_ids_in_page = [a["id"] for a in self.current_assets]

        if is_shift and self.last_clicked_id in asset_ids_in_page and asset_id in asset_ids_in_page:
            idx1 = asset_ids_in_page.index(self.last_clicked_id)
            idx2 = asset_ids_in_page.index(asset_id)
            start_i, end_i = min(idx1, idx2), max(idx1, idx2)
            for i in range(start_i, end_i + 1):
                self.selected_ids.add(asset_ids_in_page[i])
        elif is_ctrl:
            if asset_id in self.selected_ids:
                self.selected_ids.remove(asset_id)
            else:
                self.selected_ids.add(asset_id)
            self.last_clicked_id = asset_id
        else:
            self.selected_ids = {asset_id}
            self.last_clicked_id = asset_id

        # Update visual card states
        for card in self.grid_container.cards:
            card.set_selected(card.asset_id in self.selected_ids)

        self.lbl_selected_info.setText(f"{len(self.selected_ids)} selected")

        # Load into inspector
        target = next((a for a in self.current_assets if a["id"] == asset_id), None)
        if target:
            self.inspector.load_asset(target)
            if not self.inspector.isVisible():
                self.inspector.setVisible(True)

    def _on_card_double_clicked(self, asset_id: int):
        """Double clicking card opens Before-and-After Comparison Dialog."""
        target = next((a for a in self.current_assets if a["id"] == asset_id), None)
        if target:
            dialog = ComparisonDialog(target, self)
            dialog.status_changed.connect(lambda aid, st: self.refresh())
            dialog.exec()
            self.refresh()

    def _on_filter_changed(self):
        self.current_page = 1
        self._load_grid_data()

    def _on_select_all(self):
        self.selected_ids = {a["id"] for a in self.current_assets}
        for card in self.grid_container.cards:
            card.set_selected(True)
        self.lbl_selected_info.setText(f"{len(self.selected_ids)} selected")

    def _on_clear_selection(self):
        self.selected_ids.clear()
        for card in self.grid_container.cards:
            card.set_selected(False)
        self.lbl_selected_info.setText("0 selected")

    def _on_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._load_grid_data()

    def _on_next_page(self):
        self.current_page += 1
        self._load_grid_data()

    def _on_eval_eligibility_clicked(self):
        """Batch evaluate background eligibility across all cataloged assets."""
        count = transparency_engine.batch_evaluate_eligibility()
        QMessageBox.information(
            self,
            "Eligibility Evaluated",
            f"Successfully evaluated background eligibility for {count} assets using computer vision & taxonomy rules."
        )
        self.refresh()
        self.status_updated.emit()

    def _on_process_selected_clicked(self):
        """Process background removal for currently selected assets."""
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select one or more assets to process.")
            return

        self._start_worker(mode="selected", asset_ids=list(self.selected_ids))

    def _on_process_approved_clicked(self):
        """Process background removal for all assets marked as approved."""
        self._start_worker(mode="approved")

    def _start_worker(self, mode: str = "selected", asset_ids: Optional[List[int]] = None):
        """Launch background TransparencyWorker thread."""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Busy", "A background removal job is already running.")
            return

        self.worker = TransparencyWorker(
            mode=mode,
            asset_ids=asset_ids,
            method="auto",
            collection=None,
            parent=self,
        )

        self.worker.processing_started.connect(self._on_worker_started)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.asset_processed.connect(self._on_worker_asset_processed)
        self.worker.processing_finished.connect(self._on_worker_finished)
        self.worker.processing_error.connect(self._on_worker_error)

        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.btn_process_sel.setEnabled(False)
        self.progress_banner.setVisible(True)

        self.worker.start()

    def _on_worker_started(self, total: int):
        self.progress_bar.setValue(0)
        self.lbl_progress_count.setText(f"0 / {total} (0%)")
        self.lbl_progress_status.setText("Processing background removal...")

    def _on_worker_progress(self, current: int, total: int, fname: str, succ: int, fail: int, rem: int):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.lbl_progress_count.setText(f"{current} / {total} ({pct}%)  •  ✓ {succ}  ✗ {fail}  •  Remaining: {rem}")
        self.lbl_progress_item.setText(f"Current: {fname}")

    def _on_worker_asset_processed(self, asset: dict):
        if self.inspector.current_asset and self.inspector.current_asset["id"] == asset["id"]:
            self.inspector.load_asset(asset)

    def _on_worker_finished(self, summary: dict):
        self.btn_pause.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_process_sel.setEnabled(True)
        self.progress_banner.setVisible(False)
        self.refresh()
        self.status_updated.emit()

        QMessageBox.information(
            self,
            "Processing Complete",
            f"Finished background removal:\n\n"
            f"• Total Processed: {summary.get('processed', 0)}\n"
            f"• Successful: {summary.get('success', 0)}\n"
            f"• Failed: {summary.get('failed', 0)}"
        )

    def _on_worker_error(self, err: str):
        self.btn_pause.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_process_sel.setEnabled(True)
        self.progress_banner.setVisible(False)
        QMessageBox.critical(self, "Processing Error", err)

    def _on_pause_clicked(self):
        if not self.worker:
            return
        if self.worker._is_paused:
            self.worker.resume()
            self.btn_pause.setText("⏸ Pause")
        else:
            self.worker.pause()
            self.btn_pause.setText("▶ Resume")

    def _on_cancel_clicked(self):
        if self.worker:
            self.worker.cancel()

    def _on_bulk_approve_clicked(self):
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select assets to approve.")
            return
        for aid in self.selected_ids:
            db.update_transparency_approval(aid, "approved")
        self.refresh()
        self.status_updated.emit()
        QMessageBox.information(self, "Approved", f"Marked {len(self.selected_ids)} transparent results as approved.")

    def _on_bulk_reject_clicked(self):
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select assets to reject.")
            return
        for aid in self.selected_ids:
            db.update_transparency_approval(aid, "rejected")
        self.refresh()
        self.status_updated.emit()
        QMessageBox.information(self, "Rejected", f"Marked {len(self.selected_ids)} transparent results as rejected.")

    def _on_inspector_asset_updated(self, asset_id: int):
        self.refresh()
        self.status_updated.emit()

    def _on_inspector_close(self):
        self.inspector.setVisible(False)
