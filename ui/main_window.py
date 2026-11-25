"""
Main Application Window
Construction Asset Processor
Assembles the Left Sidebar, Top Toolbar, Central Workspace Stack,
Right Image Inspector, and Bottom Status Bar into a cohesive desktop app.
"""

import os
import subprocess
from pathlib import Path
from typing import Dict
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QMainWindow, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget
)

from app.config import (
    APP_NAME, APP_VERSION, NAVIGATION_ITEMS,
    OUTPUT_DIR, THEME_COLORS
)
from core.database import db
from ui.components.inspector import ImageInspector
from ui.components.sidebar import Sidebar
from ui.components.status_bar import StatusBar
from ui.components.toolbar import TopToolbar
from ui.theme import get_application_stylesheet
from ui.views.workflow_view import AssetWorkflowView
from ui.views.dashboard import DashboardView
from ui.views.import_view import AssetImportView
from ui.views.gallery_view import GalleryView
from ui.views.classification_view import ClassificationView
from ui.views.renaming_view import RenamingView
from ui.views.background_removal_view import BackgroundRemovalView
from ui.views.text_detection_view import TextDetectionView
from ui.views.watermark_review_view import WatermarkReviewView
from ui.views.collection_splitter_view import CollectionSplitterView
from ui.views.sprite_sheet_editor_view import SpriteSheetEditorView
from ui.views.asset_optimization_view import AssetOptimizationView
from ui.views.game_integration_view import GameIntegrationView
from ui.views.stage13_sprite_prep_view import Stage13SpritePrepView
from ui.views.placeholder import StagePlaceholderView


class MainWindow(QMainWindow):
    """Primary application window hosting modular views, status and inspector panels."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        self.resize(1400, 880)
        self.setMinimumSize(1100, 700)

        # Apply global theme stylesheet
        self.setStyleSheet(get_application_stylesheet())

        # Main Root Layout
        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Top Toolbar
        self.toolbar = TopToolbar(self)
        root_layout.addWidget(self.toolbar)

        # 2. Main Middle Workspace Area (Sidebar + Splitter[Workspace Stack, Inspector])
        middle_container = QWidget()
        middle_layout = QHBoxLayout(middle_container)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        # 2a. Left Navigation Sidebar (collapsible compact / expanded)
        self.sidebar = Sidebar(self)
        middle_layout.addWidget(self.sidebar)

        # 2b. Central Splitter (Stacked Workspace + Right Inspector)
        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setHandleWidth(1)

        self.workspace_stack = QStackedWidget()

        # View 0: Asset Workflow (Stage 13.2 Central Pipeline & Global Dashboard)
        self.workflow_view = AssetWorkflowView(self)
        self.workspace_stack.addWidget(self.workflow_view)
        # DashboardView backward-compatibility alias
        self.dashboard_view = self.workflow_view

        # View 1: Asset Import
        self.import_view = AssetImportView(self)
        self.workspace_stack.addWidget(self.import_view)

        # View 2: Asset Gallery (Stage 2)
        self.gallery_view = GalleryView(self)
        self.workspace_stack.addWidget(self.gallery_view)

        # View 3: AI Classification (Stage 3)
        self.classification_view = ClassificationView(self)
        self.workspace_stack.addWidget(self.classification_view)

        # View 4: Smart Renaming (Stage 4)
        self.renaming_view = RenamingView(self)
        self.workspace_stack.addWidget(self.renaming_view)

        # View 5: Background Removal (Stage 5)
        self.bg_removal_view = BackgroundRemovalView(self)
        self.workspace_stack.addWidget(self.bg_removal_view)

        # View 6: Text & Label Detection (Stage 6)
        self.text_detection_view = TextDetectionView(self)
        self.workspace_stack.addWidget(self.text_detection_view)

        # View 7: Watermark Review (Stage 7)
        self.watermark_review_view = WatermarkReviewView(self)
        self.workspace_stack.addWidget(self.watermark_review_view)

        # View 8: Collection Splitter (Stage 8)
        self.collection_splitter_view = CollectionSplitterView(self)
        self.workspace_stack.addWidget(self.collection_splitter_view)

        # View 9: Sprite Sheet Editor (Stage 9)
        self.sprite_sheet_editor_view = SpriteSheetEditorView(self)
        self.workspace_stack.addWidget(self.sprite_sheet_editor_view)

        # View 10: Asset Optimization, Validation & Flutter Export Pipeline (Stage 10)
        self.asset_optimization_view = AssetOptimizationView(self)
        self.workspace_stack.addWidget(self.asset_optimization_view)

        # View 11: Game Integration & Runtime Verification (Stage 11)
        self.game_integration_view = GameIntegrationView(self)
        self.workspace_stack.addWidget(self.game_integration_view)

        # View 12: Excavator Asset Extraction, Background Cleanup & Sprite Preparation (Stage 13)
        self.stage13_sprite_prep_view = Stage13SpritePrepView(self)
        self.workspace_stack.addWidget(self.stage13_sprite_prep_view)

        # Views 13+: Placeholders for subsequent stages
        for item in NAVIGATION_ITEMS[13:]:
            view = StagePlaceholderView(item["id"], self)
            self.workspace_stack.addWidget(view)

        self.workspace_splitter.addWidget(self.workspace_stack)

        # 2c. Right Asset Inspector Panel
        self.inspector = ImageInspector(self)
        self.workspace_splitter.addWidget(self.inspector)

        self.workspace_splitter.setCollapsible(0, False)
        self.workspace_splitter.setCollapsible(1, True)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 0)
        self.workspace_splitter.setSizes([1050, 290])

        middle_layout.addWidget(self.workspace_splitter, stretch=1)

        root_layout.addWidget(middle_container, stretch=1)

        # 3. Bottom Status Bar
        self.status_bar = StatusBar(self)
        root_layout.addWidget(self.status_bar)

        # Connect Event Signals
        self._wire_signals()

        # Update initial metrics
        self._refresh_system_metrics()

    def _wire_signals(self):
        """Bind UI events across components."""
        # Navigation & Sidebar
        self.sidebar.navigation_changed.connect(self._on_navigation_changed)
        self.sidebar.collapsed_changed.connect(self._on_sidebar_collapsed_changed)

        # Toolbar Actions
        self.toolbar.toggle_sidebar_clicked.connect(self.sidebar.toggle_compact_mode)
        self.toolbar.workflow_clicked.connect(self._nav_to_workflow)
        self.toolbar.import_clicked.connect(self._nav_to_import)
        self.toolbar.refresh_clicked.connect(self._refresh_all)
        self.toolbar.open_output_clicked.connect(self._open_output_dir)
        self.toolbar.toggle_inspector_clicked.connect(self._toggle_inspector)

        # Inspector Actions
        self.inspector.close_requested.connect(lambda: self.inspector.setVisible(False))
        self.inspector.asset_status_updated.connect(self._on_asset_status_updated)

        # Workflow View Signals (View 0)
        self.workflow_view.navigate_to_specialized_view.connect(self._switch_to_view_index)
        self.workflow_view.asset_selected.connect(self._inspect_asset)

        # Import View Signals
        self.import_view.asset_selected.connect(self._inspect_asset)
        self.import_view.import_completed.connect(self._on_import_completed)

        # Gallery View Signals
        self.gallery_view.asset_selected.connect(self._inspect_asset)
        self.gallery_view.status_updated.connect(self._refresh_all)

        # Classification View Signals
        self.classification_view.status_updated.connect(self._refresh_all)

        # Smart Renaming Signals (Stage 4)
        self.renaming_view.status_updated.connect(self._refresh_all)

        # Background Removal Signals (Stage 5)
        self.bg_removal_view.status_updated.connect(self._refresh_all)

        # Text & Label Detection Signals (Stage 6)
        self.text_detection_view.status_updated.connect(self._refresh_all)

        # Watermark Review Signals (Stage 7)
        self.watermark_review_view.status_updated.connect(self._refresh_all)

        # Collection Splitter Signals (Stage 8)
        self.collection_splitter_view.status_updated.connect(self._refresh_all)

        # Sprite Sheet Editor Signals (Stage 9)
        self.sprite_sheet_editor_view.status_updated.connect(self._refresh_all)

        # Asset Optimization & Flutter Export Signals (Stage 10)
        self.asset_optimization_view.status_updated.connect(self._refresh_all)

        # Game Integration & Runtime Verification Signals (Stage 11)
        self.game_integration_view.status_updated.connect(self._refresh_all)

    def _on_navigation_changed(self, page_id: str, index: int):
        """Handle screen switching."""
        self.workspace_stack.setCurrentIndex(index)
        title = NAVIGATION_ITEMS[index]["title"]
        self.toolbar.set_breadcrumb(title)

        # Auto-hide generic inspector on views with dedicated right inspectors to prevent horizontal squishing
        if index in (5, 12):
            self.inspector.setVisible(False)

        if index == 0:
            # Refresh workflow pipeline telemetry when switching to it
            self.workflow_view.reload_data()
            self._refresh_system_metrics()
        elif index == 2:
            # Refresh gallery when switching to it
            self.gallery_view.reload_gallery()
        elif index == 3:
            # Refresh AI classification view
            self.classification_view.reload_view()
        elif index == 4:
            # Refresh Smart Renaming view
            self.renaming_view.refresh()
        elif index == 5:
            # Refresh Background Removal view
            self.bg_removal_view.refresh()
        elif index == 6:
            # Refresh Text & Label Detection view
            self.text_detection_view.refresh()
        elif index == 7:
            # Refresh Watermark Review view
            self.watermark_review_view.refresh()
        elif index == 8:
            # Refresh Collection Splitter view
            self.collection_splitter_view.refresh()
        elif index == 9:
            # Refresh Sprite Sheet Editor view
            self.sprite_sheet_editor_view.refresh()
        elif index == 10:
            # Refresh Asset Optimization view
            self.asset_optimization_view.refresh_all()
        elif index == 11:
            # Refresh Game Integration view (Stage 11)
            self.game_integration_view.refresh_all()
        elif index == 12:
            # Refresh Sprite Preparation view (Stage 13)
            self.stage13_sprite_prep_view.refresh_data()

    def _switch_to_view_index(self, index: int):
        """Programmatically switch sidebar and workspace to given view index."""
        if 0 <= index < len(NAVIGATION_ITEMS):
            page_id = NAVIGATION_ITEMS[index]["id"]
            self.sidebar.select_index(index)
            self._on_navigation_changed(page_id, index)

    def _nav_to_workflow(self):
        """Quick jump to Asset Workflow workspace (View 0)."""
        self._switch_to_view_index(0)

    def _on_sidebar_collapsed_changed(self, collapsed: bool):
        mode_str = "Compact (icons only)" if collapsed else "Expanded"
        self.status_bar.set_status(f"Sidebar set to {mode_str} mode.", "info")

    def _nav_to_import(self):
        """Quick jump to Asset Import view."""
        self.sidebar.select_id("import")
        self.workspace_stack.setCurrentIndex(1)
        self.toolbar.set_breadcrumb("Asset Import")

    def _nav_to_gallery(self):
        """Quick jump to Asset Gallery view."""
        self.sidebar.select_id("gallery")
        self.workspace_stack.setCurrentIndex(2)
        self.toolbar.set_breadcrumb("Asset Gallery")
        self.gallery_view.reload_gallery()

    def _inspect_asset(self, asset_dict: Dict):
        """Open and populate the right inspector with given asset."""
        self.inspector.setVisible(True)
        self.inspector.inspect_asset(asset_dict)

    def _toggle_inspector(self):
        """Toggle right panel visibility."""
        self.inspector.setVisible(not self.inspector.isVisible())

    def _open_output_dir(self):
        """Open output directory in file explorer."""
        p = Path(OUTPUT_DIR)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
        subprocess.run(["explorer", os.path.normpath(str(p.resolve()))], check=False)

    def _refresh_active_view(self):
        """Refresh only the currently visible workspace view to maintain high UI responsiveness."""
        current = self.workspace_stack.currentWidget()
        if current == self.dashboard_view:
            self.dashboard_view.reload_data()
        elif current == self.gallery_view:
            self.gallery_view.reload_gallery()
        elif current == self.classification_view:
            self.classification_view.reload_view()
        elif current == self.renaming_view:
            self.renaming_view.refresh()
        elif current == self.bg_removal_view:
            self.bg_removal_view.refresh()
        elif current == getattr(self, "text_detection_view", None):
            self.text_detection_view.refresh()
        elif current == getattr(self, "watermark_review_view", None):
            self.watermark_review_view.refresh()
        elif current == getattr(self, "collection_splitter_view", None):
            self.collection_splitter_view.refresh()
        elif current == getattr(self, "sprite_sheet_editor_view", None):
            self.sprite_sheet_editor_view.refresh()
        elif current == getattr(self, "asset_optimization_view", None):
            self.asset_optimization_view.refresh_all()
        elif current == getattr(self, "game_integration_view", None):
            self.game_integration_view.refresh_all()
        elif current == getattr(self, "stage13_sprite_prep_view", None):
            self.stage13_sprite_prep_view.refresh_data()
        self._refresh_system_metrics()

    def _refresh_all(self):
        """Manual user refresh via toolbar button."""
        self._refresh_active_view()
        self.status_bar.set_status("Active view and database statistics synchronized.", "success")

    def _on_asset_status_updated(self, asset_id: int, new_status: str):
        """Handle status change in inspector without freezing background views."""
        self._refresh_active_view()
        self.status_bar.set_status(f"Asset #{asset_id} updated to {new_status.capitalize()}.", "info")

    def _on_import_completed(self, summary: Dict):
        """Handle completed scan batch."""
        self.dashboard_view.reload_data()
        self.gallery_view.reload_gallery()
        self.classification_view.reload_view()
        self.renaming_view.refresh()
        self.bg_removal_view.refresh()
        if hasattr(self, "asset_optimization_view"):
            self.asset_optimization_view.refresh_all()
        if hasattr(self, "game_integration_view"):
            self.game_integration_view.refresh_all()
        if hasattr(self, "stage13_sprite_prep_view"):
            self.stage13_sprite_prep_view.refresh_data()
        self._refresh_system_metrics()
        self.status_bar.set_status(
            f"Import complete: {summary['new_imported']} added, {summary['updated']} updated.",
            "success"
        )

    def _refresh_system_metrics(self):
        """Sync bottom status bar with real database values."""
        stats = db.get_dashboard_stats()
        self.status_bar.update_metrics(stats["total_images"], stats["total_storage_formatted"])

    def closeEvent(self, event):
        """Clean up background workers on window close."""
        if hasattr(self.import_view, "worker") and self.import_view.worker and self.import_view.worker.isRunning():
            self.import_view.worker.request_cancel()
            self.import_view.worker.wait(2000)
        if hasattr(self.classification_view, "worker") and self.classification_view.worker and self.classification_view.worker.isRunning():
            self.classification_view.worker.request_cancel()
            self.classification_view.worker.wait(2000)
        if hasattr(self.collection_splitter_view, "worker") and self.collection_splitter_view.worker and self.collection_splitter_view.worker.isRunning():
            self.collection_splitter_view.worker.cancel()
            self.collection_splitter_view.worker.wait(2000)
        if hasattr(self, "asset_optimization_view"):
            if self.asset_optimization_view.opt_worker and self.asset_optimization_view.opt_worker.isRunning():
                self.asset_optimization_view.opt_worker.cancel()
                self.asset_optimization_view.opt_worker.wait(2000)
            if self.asset_optimization_view.val_worker and self.asset_optimization_view.val_worker.isRunning():
                self.asset_optimization_view.val_worker.cancel()
                self.asset_optimization_view.val_worker.wait(2000)
        if hasattr(self, "game_integration_view"):
            if self.game_integration_view.anim_timer.isActive():
                self.game_integration_view.anim_timer.stop()
        if hasattr(self, "stage13_sprite_prep_view"):
            self.stage13_sprite_prep_view.cleanup_workers()
        event.accept()
