"""
Gallery View Component
Master Asset Gallery combining the Top Toolbar, Filter Sidebar,
Responsive Grid View of Cards, List View Table, Multi-selection,
Bulk Actions, and Pagination.
"""

import math
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QClipboard, QGuiApplication, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db
from ui.components.gallery_card import GalleryCard
from ui.components.gallery_filter_panel import GalleryFilterPanel
from ui.components.gallery_table import GalleryTable
from ui.components.gallery_toolbar import GalleryToolbar


class FlowGridContainer(QWidget):
    """Container widget that arranges GalleryCards dynamically based on available width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cards: List[GalleryCard] = []

    def set_cards(self, cards: List[GalleryCard]):
        """Clear existing and populate with new cards."""
        # Remove old cards
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self.cards = cards
        self._relayout()

    def _relayout(self):
        """Calculate column count and place cards in a grid."""
        if not self.cards:
            return

        avail_width = max(self.width() - 30, 360)
        card_w = self.cards[0].CARD_WIDTH + 12 if self.cards else (GalleryCard.CARD_WIDTH + 12)
        cols = max(1, avail_width // card_w)

        for idx, card in enumerate(self.cards):
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._relayout()


class GalleryView(QWidget):
    """Main Gallery view coordinating toolbar, filter panel, grid, table, and pagination."""

    asset_selected = Signal(dict)
    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Internal Query & Pagination State
        self.current_page = 1
        self.page_size = 48
        self.total_matching = 0
        self.current_sort = "filename_asc"
        self.search_query = ""
        self.selected_ids: Set[int] = set()
        self.last_clicked_id: Optional[int] = None
        self.current_assets: List[Dict[str, Any]] = []
        self.current_view_mode = "grid"  # "grid" or "list"
        self.card_size_mode = "medium"   # "small", "medium", "large"

        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Gallery Toolbar
        self.toolbar = GalleryToolbar(self)
        self.toolbar.search_changed.connect(self._on_search_changed)
        self.toolbar.collection_changed.connect(self._on_collection_changed)
        self.toolbar.sort_changed.connect(self._on_sort_changed)
        self.toolbar.size_changed.connect(self._on_size_changed)
        self.toolbar.view_toggled.connect(self._on_view_toggled)
        self.toolbar.refresh_clicked.connect(self.reload_gallery)
        self.toolbar.bulk_action_triggered.connect(self._on_bulk_action)
        main_layout.addWidget(self.toolbar)

        # 2. Middle Body: Splitter (Filter Panel | Content Workspace)
        body_splitter = QSplitter(Qt.Horizontal)
        body_splitter.setHandleWidth(1)

        # 2a. Filter Sidebar
        self.filter_panel = GalleryFilterPanel(self)
        self.filter_panel.filters_changed.connect(self._on_filters_changed)
        body_splitter.addWidget(self.filter_panel)

        # 2b. Central Workspace Stack (Grid vs List) + Bottom Pagination
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self.workspace_stack = QStackedWidget()

        # Grid View (View 0)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_container = FlowGridContainer()
        self.grid_scroll.setWidget(self.grid_container)
        self.workspace_stack.addWidget(self.grid_scroll)

        # List View (View 1)
        self.table_view = GalleryTable(self)
        self.table_view.asset_selected.connect(self.asset_selected.emit)
        self.table_view.selection_changed_signal.connect(self._on_table_selection_changed)
        self.table_view.header_sort_requested.connect(self._on_table_sort_requested)
        self.workspace_stack.addWidget(self.table_view)

        center_layout.addWidget(self.workspace_stack, stretch=1)

        # 3. Bottom Pagination Bar
        pagination_bar = self._create_pagination_bar()
        center_layout.addWidget(pagination_bar)

        body_splitter.addWidget(center_widget)
        body_splitter.setStretchFactor(0, 0)
        body_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(body_splitter, stretch=1)

        # Initial Load
        self.reload_gallery()

    def _create_pagination_bar(self) -> QFrame:
        """Construct bottom pagination controls."""
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

        # Showing range label
        self.lbl_page_info = QLabel("Showing 0–0 of 0 assets")
        self.lbl_page_info.setStyleSheet(f"color: {THEME_COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(self.lbl_page_info)

        layout.addStretch()

        # Page buttons
        self.btn_first = QPushButton("⏮ First")
        self.btn_first.setProperty("class", "btn_secondary")
        self.btn_first.setCursor(Qt.PointingHandCursor)
        self.btn_first.clicked.connect(self._go_first_page)
        layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton("◀ Prev")
        self.btn_prev.setProperty("class", "btn_secondary")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self._go_prev_page)
        layout.addWidget(self.btn_prev)

        self.lbl_current_page = QLabel("Page 1 of 1")
        self.lbl_current_page.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 600; font-size: 12px;")
        layout.addWidget(self.lbl_current_page)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setProperty("class", "btn_secondary")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self._go_next_page)
        layout.addWidget(self.btn_next)

        self.btn_last = QPushButton("Last ⏭")
        self.btn_last.setProperty("class", "btn_secondary")
        self.btn_last.setCursor(Qt.PointingHandCursor)
        self.btn_last.clicked.connect(self._go_last_page)
        layout.addWidget(self.btn_last)

        layout.addSpacing(12)

        # Page size selector
        lbl_size = QLabel("Per page:")
        lbl_size.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 12px;")
        layout.addWidget(lbl_size)

        self.cmb_page_size = QComboBox()
        self.cmb_page_size.addItem("24", 24)
        self.cmb_page_size.addItem("48", 48)
        self.cmb_page_size.addItem("72", 72)
        self.cmb_page_size.addItem("120", 120)
        self.cmb_page_size.addItem("All", 99999)
        self.cmb_page_size.setCurrentIndex(1)  # 48 default
        self.cmb_page_size.currentIndexChanged.connect(self._on_page_size_changed)
        layout.addWidget(self.cmb_page_size)

        return bar

    def reload_gallery(self):
        """Fetch matching assets from SQLite and render the active view."""
        # Assemble query parameters from filters + search + collection
        filters = self.filter_panel.get_filters()

        # If toolbar collection is not "all", it takes priority
        coll_override = self.toolbar.cmb_collection.currentData()
        if coll_override and coll_override != "all":
            collection_param = coll_override
        else:
            collection_param = filters["collections"]

        # Total count query
        self.total_matching = db.get_assets_count(
            collection=collection_param,
            status=filters["statuses"],
            formats=filters["formats"],
            has_transparency=filters["has_transparency"],
            dim_category=filters["dim_category"],
            min_width=filters["min_width"],
            max_width=filters["max_width"],
            min_height=filters["min_height"],
            max_height=filters["max_height"],
            search=self.search_query,
        )

        # Compute pagination
        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        if self.current_page > total_pages:
            self.current_page = total_pages

        offset = (self.current_page - 1) * self.page_size

        # Assets query
        self.current_assets = db.get_assets(
            collection=collection_param,
            status=filters["statuses"],
            formats=filters["formats"],
            has_transparency=filters["has_transparency"],
            dim_category=filters["dim_category"],
            min_width=filters["min_width"],
            max_width=filters["max_width"],
            min_height=filters["min_height"],
            max_height=filters["max_height"],
            search=self.search_query,
            sort_by=self.current_sort,
            limit=self.page_size,
            offset=offset,
        )

        # Update Toolbar counters
        self.toolbar.update_counts(self.total_matching, len(self.selected_ids))

        # Update Pagination UI
        start_idx = offset + 1 if self.total_matching > 0 else 0
        end_idx = min(offset + len(self.current_assets), self.total_matching)
        self.lbl_page_info.setText(f"Showing {start_idx}–{end_idx} of {self.total_matching} assets")
        self.lbl_current_page.setText(f"Page {self.current_page} of {total_pages}")

        self.btn_first.setEnabled(self.current_page > 1)
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < total_pages)
        self.btn_last.setEnabled(self.current_page < total_pages)

        # Render Active View
        if self.current_view_mode == "grid":
            self._render_grid_view()
        else:
            self._render_list_view()

    def _render_grid_view(self):
        """Create GalleryCard widgets for current page assets."""
        cards: List[GalleryCard] = []
        for asset in self.current_assets:
            card = GalleryCard(asset, size_mode=self.card_size_mode)
            card.set_selected(asset["id"] in self.selected_ids)
            card.clicked.connect(self._on_card_clicked)
            card.status_changed.connect(self._on_card_status_changed)
            card.action_requested.connect(self._on_card_action_requested)
            cards.append(card)

        self.grid_container.set_cards(cards)

    def _render_list_view(self):
        """Populate the table view."""
        self.table_view.load_assets(self.current_assets)
        self.table_view.select_asset_ids(self.selected_ids)

    def _on_card_clicked(self, asset_id: int, is_ctrl: bool, is_shift: bool):
        """Handle selection events on grid cards."""
        asset_map = {a["id"]: a for a in self.current_assets}
        target_asset = asset_map.get(asset_id)

        if is_shift and self.last_clicked_id is not None:
            # Range selection
            ids_in_order = [a["id"] for a in self.current_assets]
            try:
                idx1 = ids_in_order.index(self.last_clicked_id)
                idx2 = ids_in_order.index(asset_id)
                start, end = min(idx1, idx2), max(idx1, idx2)
                for i in range(start, end + 1):
                    self.selected_ids.add(ids_in_order[i])
            except ValueError:
                self.selected_ids.add(asset_id)
        elif is_ctrl:
            # Toggle multi-select
            if asset_id in self.selected_ids:
                self.selected_ids.remove(asset_id)
            else:
                self.selected_ids.add(asset_id)
        else:
            # Single select
            self.selected_ids = {asset_id}

        self.last_clicked_id = asset_id

        # Update card visuals
        for card in self.grid_container.cards:
            card.set_selected(card.asset_id in self.selected_ids)

        self.toolbar.update_counts(self.total_matching, len(self.selected_ids))

        # Notify inspector
        if target_asset:
            self.asset_selected.emit(target_asset)

    def _on_table_selection_changed(self, selected_ids: List[int]):
        """Sync selection when rows are selected in the table."""
        self.selected_ids = set(selected_ids)
        self.toolbar.update_counts(self.total_matching, len(self.selected_ids))

    def _on_card_status_changed(self, asset_id: int, new_status: str):
        """Individual card context menu status change."""
        db.update_asset_status(asset_id, new_status)
        for card in self.grid_container.cards:
            if card.asset_id == asset_id:
                card.update_status(new_status)
        self.status_updated.emit()

    def _on_card_action_requested(self, action: str, asset_id: int):
        """Context menu action handler."""
        asset = db.get_asset(asset_id)
        if not asset:
            return

        orig_path = asset.get("original_path", "")
        if action == "open_folder" and orig_path and os.path.exists(orig_path):
            subprocess.run(["explorer", "/select,", os.path.normpath(orig_path)], check=False)
        elif action == "copy_path" and orig_path:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(orig_path, QClipboard.Clipboard)

    def _on_bulk_action(self, action_name: str):
        """Execute batch actions on all selected assets."""
        if action_name == "select_all":
            self.selected_ids = {a["id"] for a in self.current_assets}
            self._sync_selection_visuals()
            return

        if action_name == "select_eligible":
            # Select all eligible assets (unprocessed and not pure background scenes)
            self.selected_ids = {
                a["id"] for a in self.current_assets
                if a.get("bg_processing_status") != "processed" and a.get("composition_type") != "Background Image"
            }
            self._sync_selection_visuals()
            return

        if action_name == "deselect_all":
            self.selected_ids.clear()
            self._sync_selection_visuals()
            return

        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select at least one image card to perform bulk actions.")
            return

        id_list = list(self.selected_ids)

        if action_name in ("approve", "pending", "reject"):
            status_map = {"approve": "approved", "pending": "pending", "reject": "rejected"}
            target_status = status_map[action_name]
            updated_count = db.bulk_update_status(id_list, target_status)
            self.status_updated.emit()
            self.reload_gallery()
            QMessageBox.information(
                self,
                "Bulk Update",
                f"Successfully marked {updated_count} selected assets as '{target_status.capitalize()}'."
            )

        elif action_name == "export_csv":
            try:
                report_file = db.export_assets_to_csv(id_list)
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Exported {len(id_list)} asset records to CSV report:\n\n{report_file.resolve()}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", f"Could not export CSV report:\n{e}")

        elif action_name == "open_explorer":
            first_id = id_list[0]
            asset = db.get_asset(first_id)
            if asset and asset.get("original_path") and os.path.exists(asset["original_path"]):
                subprocess.run(["explorer", "/select,", os.path.normpath(asset["original_path"])], check=False)

    def _sync_selection_visuals(self):
        """Update grid cards and table rows with current selection."""
        self.toolbar.update_counts(self.total_matching, len(self.selected_ids))
        for card in self.grid_container.cards:
            card.set_selected(card.asset_id in self.selected_ids)
        self.table_view.select_asset_ids(self.selected_ids)

    def _on_search_changed(self, text: str):
        self.search_query = text.strip()
        self.current_page = 1
        self.reload_gallery()

    def _on_collection_changed(self, collection_id: str):
        self.current_page = 1
        self.reload_gallery()

    def _on_sort_changed(self, sort_key: str):
        self.current_sort = sort_key
        self.current_page = 1
        self.reload_gallery()

    def _on_table_sort_requested(self, sort_key: str, ascending: bool):
        self.current_sort = sort_key
        self.current_page = 1
        self.reload_gallery()

    def _on_view_toggled(self, mode: str):
        self.current_view_mode = mode
        if mode == "grid":
            self.workspace_stack.setCurrentIndex(0)
            self._render_grid_view()
        else:
            self.workspace_stack.setCurrentIndex(1)
            self._render_list_view()

    def _on_size_changed(self, size_mode: str):
        self.card_size_mode = size_mode
        if self.current_view_mode == "grid":
            self._render_grid_view()

    def _on_filters_changed(self, filters: Dict[str, Any]):
        self.current_page = 1
        self.reload_gallery()

    def _on_page_size_changed(self, index: int):
        self.page_size = self.cmb_page_size.currentData()
        self.current_page = 1
        self.reload_gallery()

    def _go_first_page(self):
        self.current_page = 1
        self.reload_gallery()

    def _go_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.reload_gallery()

    def _go_next_page(self):
        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        if self.current_page < total_pages:
            self.current_page += 1
            self.reload_gallery()

    def _go_last_page(self):
        total_pages = max(1, math.ceil(self.total_matching / self.page_size))
        self.current_page = total_pages
        self.reload_gallery()
