"""
Asset Optimization, Quality Validation & Flutter Export Master View (Stage 10)
Construction Asset Processor

Primary Stage 10 Screen coordinating:
- 6 Real-time SQLite metrics (Approved Assets, Optimized Assets, Texture Atlases, Storage Saved, Validated Clean, Export Jobs)
- Responsive asset grid with multi-selection and approval status
- Optimization batch worker with pause, resume, cancel, and progress telemetry
- Validation batch worker inspecting file integrity, transparency, dimensions, and duplicates
- Texture Atlas generation dialog (MaxRects bin packing)
- Flutter + Flame export dialog with pubspec.yaml backup and staging deployment
- Right-side inspector & validation panels
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QTabWidget,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.database import db
from core.workers import OptimizationBatchWorker, ValidationBatchWorker
from ui.components.asset_validation_panel import AssetValidationPanel
from ui.components.flutter_export_dialog import FlutterExportDialog
from ui.components.optimization_card import OptimizationCard
from ui.components.optimization_inspector import OptimizationInspector
from ui.components.stat_card import StatCard
from ui.components.texture_atlas_preview import TextureAtlasPreviewDialog

logger = logging.getLogger("AssetProcessor.AssetOptimizationView")


class OptimizationGridContainer(QWidget):
    """Container that flows OptimizationCards responsively based on available width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cards: List[OptimizationCard] = []

    def set_cards(self, cards: List[OptimizationCard]):
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
        card_w = OptimizationCard.CARD_WIDTH + 12
        cols = max(1, avail_width // card_w)
        for idx, card in enumerate(self.cards):
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._relayout()


class AssetOptimizationView(QWidget):
    """Primary Asset Optimization, Validation & Flutter Export View (Stage 10)."""

    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_asset_ids: Set[int] = set()
        self.active_asset: Optional[Dict[str, Any]] = None
        self.assets: List[Dict[str, Any]] = []

        self.opt_worker: Optional[OptimizationBatchWorker] = None
        self.val_worker: Optional[ValidationBatchWorker] = None

        self._build_ui()
        self.refresh_all()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # 1. Top Section: 6 Metrics Cards
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)

        self.card_approved = StatCard("Approved Assets", "0", "Ready for Export", icon="✓", accent_color="#10B981")
        stats_layout.addWidget(self.card_approved)

        self.card_optimized = StatCard("Optimized Assets", "0", "Copies Generated", icon="⚡", accent_color=THEME_COLORS["accent_primary"])
        stats_layout.addWidget(self.card_optimized)

        self.card_atlases = StatCard("Texture Atlases", "0", "Packed Atlases", icon="📐", accent_color="#38BDF8")
        stats_layout.addWidget(self.card_atlases)

        self.card_saved = StatCard("Storage Saved", "0 B", "Lossless/Lossy Gains", icon="💾", accent_color="#A855F7")
        stats_layout.addWidget(self.card_saved)

        self.card_clean = StatCard("Validated Clean", "0", "Integrity Passed", icon="🛡️", accent_color="#34D399")
        stats_layout.addWidget(self.card_clean)

        self.card_jobs = StatCard("Export Jobs", "0", "Deployments Done", icon="🚀", accent_color="#F59E0B")
        stats_layout.addWidget(self.card_jobs)

        main_layout.addLayout(stats_layout)

        # 2. Toolbar
        toolbar = QFrame()
        toolbar.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_toolbar']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        tool_layout = QHBoxLayout(toolbar)
        tool_layout.setContentsMargins(8, 6, 8, 6)
        tool_layout.setSpacing(8)

        # Search Bar
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Search filename...")
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                color: white;
                padding: 4px 8px;
                font-size: 11px;
            }}
        """)
        self.txt_search.textChanged.connect(self._apply_filters)
        tool_layout.addWidget(self.txt_search)

        # Category Filter
        self.combo_category = QComboBox()
        self.combo_category.addItems(["All Categories", "excavator", "vehicles", "equipment", "environment", "tools", "ui"])
        self.combo_category.currentIndexChanged.connect(self._apply_filters)
        tool_layout.addWidget(self.combo_category)

        # Collection Filter
        self.combo_collection = QComboBox()
        self.combo_collection.addItems(["All Collections", "excavater", "other_images"])
        self.combo_collection.currentIndexChanged.connect(self._apply_filters)
        tool_layout.addWidget(self.combo_collection)

        # Status Filter
        self.combo_status = QComboBox()
        self.combo_status.addItems([
            "All Assets",
            "Approved Only",
            "Optimized Only",
            "Unprocessed Only",
            "Validated Clean",
            "Has Warnings/Errors",
        ])
        self.combo_status.currentIndexChanged.connect(self._apply_filters)
        tool_layout.addWidget(self.combo_status)

        # Select / Deselect All
        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.clicked.connect(self._select_all_cards)
        tool_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_deselect_all.clicked.connect(self._deselect_all_cards)
        tool_layout.addWidget(self.btn_deselect_all)

        tool_layout.addStretch()

        # Action Buttons
        self.btn_batch_opt = QPushButton("⚡ Batch Optimize")
        self.btn_batch_opt.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                font-size: 11px;
                padding: 6px 12px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
        """)
        self.btn_batch_opt.clicked.connect(self._start_batch_optimization)
        tool_layout.addWidget(self.btn_batch_opt)

        self.btn_open_atlas = QPushButton("📐 Texture Atlas...")
        self.btn_open_atlas.setStyleSheet(f"""
            QPushButton {{
                background-color: #0284C7;
                color: white;
                font-weight: 700;
                font-size: 11px;
                padding: 6px 12px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #0369A1;
            }}
        """)
        self.btn_open_atlas.clicked.connect(self._open_texture_atlas_dialog)
        tool_layout.addWidget(self.btn_open_atlas)

        self.btn_export_flutter = QPushButton("🚀 Export to Flutter...")
        self.btn_export_flutter.setStyleSheet(f"""
            QPushButton {{
                background-color: #10B981;
                color: white;
                font-weight: 700;
                font-size: 11px;
                padding: 6px 14px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #059669;
            }}
        """)
        self.btn_export_flutter.clicked.connect(self._open_flutter_export_dialog)
        tool_layout.addWidget(self.btn_export_flutter)

        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setToolTip("Refresh Assets and Stats")
        self.btn_refresh.clicked.connect(self.refresh_all)
        tool_layout.addWidget(self.btn_refresh)

        main_layout.addWidget(toolbar)

        # 3. Telemetry / Progress Bar Container (Hidden until active)
        self.progress_frame = QFrame()
        self.progress_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['accent_primary']};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        p_layout = QHBoxLayout(self.progress_frame)
        p_layout.setContentsMargins(8, 4, 8, 4)

        self.lbl_progress_status = QLabel("Processing batch...")
        self.lbl_progress_status.setStyleSheet("color: white; font-weight: 600; font-size: 11px;")
        p_layout.addWidget(self.lbl_progress_status)

        self.worker_progress = QProgressBar()
        self.worker_progress.setRange(0, 100)
        self.worker_progress.setValue(0)
        p_layout.addWidget(self.worker_progress, stretch=1)

        self.btn_pause_worker = QPushButton("Pause")
        self.btn_pause_worker.clicked.connect(self._toggle_pause_worker)
        p_layout.addWidget(self.btn_pause_worker)

        self.btn_cancel_worker = QPushButton("Cancel")
        self.btn_cancel_worker.clicked.connect(self._cancel_worker)
        p_layout.addWidget(self.btn_cancel_worker)

        self.progress_frame.setVisible(False)
        main_layout.addWidget(self.progress_frame)

        # 4. Central Splitter: Asset Grid (Left) and Inspector Tabs (Right)
        splitter = QSplitter(Qt.Horizontal)

        # Left: Scrollable Card Grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        self.grid_container = OptimizationGridContainer()
        scroll.setWidget(self.grid_container)
        splitter.addWidget(scroll)

        # Right: Tabbed Inspector Panel
        right_panel = QFrame()
        right_panel.setFixedWidth(340)
        right_panel.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_inspector']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(4, 4, 4, 4)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                background: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_secondary']};
                padding: 6px 12px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: 600;
                font-size: 11px;
            }}
            QTabBar::tab:selected {{
                background: {THEME_COLORS['bg_toolbar']};
                color: {THEME_COLORS['accent_primary']};
                border-bottom: 2px solid {THEME_COLORS['accent_primary']};
            }}
        """)

        # Tab 1: Optimization Inspector
        self.inspector = OptimizationInspector()
        self.inspector.asset_optimized.connect(self._on_asset_optimized)
        self.inspector.export_approval_changed.connect(self._on_approval_changed)
        self.inspector.validation_requested.connect(self._on_validation_requested)
        self.inspector.refresh_needed.connect(self.refresh_all)
        self.tab_widget.addTab(self.inspector, "⚡ Optimization")

        # Tab 2: Validation Panel
        self.val_panel = AssetValidationPanel()
        self.val_panel.batch_validate_requested.connect(self._start_batch_validation)
        self.tab_widget.addTab(self.val_panel, "🔍 Quality Check")

        rp_layout.addWidget(self.tab_widget)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        main_layout.addWidget(splitter, stretch=1)

    def refresh_all(self):
        """Reload all metrics, assets from DB, and refresh grid."""
        self._refresh_metrics()
        self._load_assets()

    def _refresh_metrics(self):
        """Update top 6 StatCards from database."""
        stats = db.get_stage10_dashboard_stats()
        self.card_approved.update_value(str(stats.get("approved_count", 0)))
        self.card_optimized.update_value(str(stats.get("optimized_count", 0)))
        self.card_atlases.update_value(str(stats.get("atlas_count", 0)))
        self.card_saved.update_value(format_bytes(stats.get("bytes_saved", 0)))
        self.card_clean.update_value(str(stats.get("validated_clean", 0)))
        self.card_jobs.update_value(str(stats.get("exported_jobs", 0)))

        # Update validation panel summary counts
        val_stats = db.get_validation_summary_stats()
        self.val_panel.update_summary_stats(val_stats)

    def _load_assets(self):
        """Load eligible assets from database."""
        cat = self.combo_category.currentText()
        col = self.combo_collection.currentText()
        self.assets = db.get_approved_assets_for_optimization(
            category=cat if cat != "All Categories" else None,
            collection=col if col != "All Collections" else None,
        )
        self._apply_filters()

    def _apply_filters(self):
        """Filter assets by search text and status dropdown."""
        search = self.txt_search.text().strip().lower()
        st_filter = self.combo_status.currentIndex()

        filtered = []
        for a in self.assets:
            # Search match
            fname = (a.get("smart_filename") or a.get("filename") or "").lower()
            if search and search not in fname:
                continue

            # Status match
            if st_filter == 1:  # Approved Only
                if not (a.get("is_approved_for_export") or a.get("status") == "approved"):
                    continue
            elif st_filter == 2:  # Optimized Only
                if a.get("optimization_status") != "optimized":
                    continue
            elif st_filter == 3:  # Unprocessed Only
                if a.get("optimization_status") == "optimized":
                    continue
            elif st_filter == 4:  # Validated Clean
                if a.get("validation_status") != "passed":
                    continue
            elif st_filter == 5:  # Has Warnings/Errors
                if a.get("validation_status") not in ("warning", "failed"):
                    continue

            filtered.append(a)

        # Create cards
        cards = []
        for a in filtered:
            card = OptimizationCard(a)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            card.checked_toggled.connect(self._on_card_checked)
            card.set_selected(self.active_asset and self.active_asset["id"] == a["id"])
            card.set_checked(a["id"] in self.selected_asset_ids)
            cards.append(card)

        self.grid_container.set_cards(cards)

    def _on_card_clicked(self, asset_id: int, is_ctrl: bool, is_shift: bool):
        """Select an asset and update inspector & validation views."""
        found = next((a for a in self.assets if a["id"] == asset_id), None)
        if not found:
            return

        self.active_asset = found
        for c in self.grid_container.cards:
            c.set_selected(c.asset_id == asset_id)

        self.inspector.load_asset(found)
        self.val_panel.load_asset_validation(found)

    def _on_card_double_clicked(self, asset_id: int):
        """Double click selects asset and switches to optimization inspector."""
        self._on_card_clicked(asset_id, False, False)
        self.tab_widget.setCurrentIndex(0)

    def _on_card_checked(self, asset_id: int, checked: bool):
        """Handle individual checkbox state."""
        if checked:
            self.selected_asset_ids.add(asset_id)
        else:
            self.selected_asset_ids.discard(asset_id)

    def _select_all_cards(self):
        """Select all visible cards."""
        for c in self.grid_container.cards:
            c.set_checked(True)
            self.selected_asset_ids.add(c.asset_id)

    def _deselect_all_cards(self):
        """Deselect all visible cards."""
        for c in self.grid_container.cards:
            c.set_checked(False)
        self.selected_asset_ids.clear()

    def _start_batch_optimization(self):
        """Start batch optimization worker on selected or all approved assets."""
        targets = []
        if self.selected_asset_ids:
            targets = [a for a in self.assets if a["id"] in self.selected_asset_ids]
        else:
            targets = self.assets

        if not targets:
            QMessageBox.information(self, "No Assets", "No assets to optimize.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Batch Optimization",
            f"Optimize copies of {len(targets)} assets?\n(Original source images will never be modified.)",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.progress_frame.setVisible(True)
        self.worker_progress.setValue(0)
        self.lbl_progress_status.setText(f"Optimizing 0 / {len(targets)} assets...")

        self.opt_worker = OptimizationBatchWorker(targets, target_format="png", lossless=True)
        self.opt_worker.progress.connect(self._on_worker_progress)
        self.opt_worker.item_completed.connect(self._on_opt_item_completed)
        self.opt_worker.batch_finished.connect(self._on_opt_batch_finished)
        self.opt_worker.start()

    def _start_batch_validation(self):
        """Start batch validation worker on all assets."""
        if not self.assets:
            return

        self.progress_frame.setVisible(True)
        self.worker_progress.setValue(0)
        self.lbl_progress_status.setText(f"Validating 0 / {len(self.assets)} assets...")

        self.val_worker = ValidationBatchWorker(self.assets)
        self.val_worker.progress.connect(self._on_worker_progress)
        self.val_worker.item_validated.connect(self._on_val_item_completed)
        self.val_worker.batch_finished.connect(self._on_val_batch_finished)
        self.val_worker.start()

    def _on_worker_progress(self, current: int, total: int, fname: str):
        pct = int(current / total * 100) if total > 0 else 0
        self.worker_progress.setValue(pct)
        self.lbl_progress_status.setText(f"[{current}/{total}] {fname}")

    def _on_opt_item_completed(self, asset_id: int, result: dict):
        pass

    def _on_opt_batch_finished(self, stats: dict):
        self.progress_frame.setVisible(False)
        self.refresh_all()
        QMessageBox.information(
            self,
            "Optimization Complete",
            f"Batch optimization finished!\nProcessed: {stats.get('successful', 0)} / {stats.get('total', 0)}\nSaved: {format_bytes(stats.get('total_saved_bytes', 0))}"
        )

    def _on_val_item_completed(self, asset_id: int, result: dict):
        pass

    def _on_val_batch_finished(self, stats: dict):
        self.progress_frame.setVisible(False)
        self.refresh_all()
        QMessageBox.information(
            self,
            "Validation Complete",
            f"Quality validation finished!\nTotal: {stats.get('total', 0)}\nPassed: {stats.get('passed', 0)}\nWarnings: {stats.get('warning', 0)}\nFailed: {stats.get('failed', 0)}"
        )

    def _toggle_pause_worker(self):
        if self.opt_worker and self.opt_worker.isRunning():
            if self.opt_worker.is_paused:
                self.opt_worker.resume()
                self.btn_pause_worker.setText("Pause")
            else:
                self.opt_worker.pause()
                self.btn_pause_worker.setText("Resume")
        elif self.val_worker and self.val_worker.isRunning():
            if self.val_worker.is_paused:
                self.val_worker.resume()
                self.btn_pause_worker.setText("Pause")
            else:
                self.val_worker.pause()
                self.btn_pause_worker.setText("Resume")

    def _cancel_worker(self):
        if self.opt_worker and self.opt_worker.isRunning():
            self.opt_worker.cancel()
        if self.val_worker and self.val_worker.isRunning():
            self.val_worker.cancel()
        self.progress_frame.setVisible(False)

    def _open_texture_atlas_dialog(self):
        """Open Texture Atlas preview & packing dialog."""
        targets = [a for a in self.assets if a["id"] in self.selected_asset_ids] if self.selected_asset_ids else self.assets
        if not targets:
            QMessageBox.warning(self, "No Assets", "No assets available to pack into an atlas.")
            return

        dlg = TextureAtlasPreviewDialog(targets, self)
        dlg.atlas_created.connect(lambda res: self.refresh_all())
        dlg.exec()

    def _open_flutter_export_dialog(self):
        """Open Flutter & Flame Deployment dialog."""
        targets = [a for a in self.assets if a["id"] in self.selected_asset_ids] if self.selected_asset_ids else self.assets
        if not targets:
            QMessageBox.warning(self, "No Assets", "No approved assets to export.")
            return

        dlg = FlutterExportDialog(targets, self)
        dlg.export_completed.connect(lambda res: self.refresh_all())
        dlg.exec()

    def _on_asset_optimized(self, asset_id: int, res: dict):
        self.refresh_all()

    def _on_approval_changed(self, asset_id: int, is_approved: bool):
        self.refresh_all()

    def _on_validation_requested(self, asset_id: int):
        self.refresh_all()
