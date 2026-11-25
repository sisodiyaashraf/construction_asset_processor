"""
Smart Asset Renaming Master View (Stage 4)
Provides complete interface for batch standardized filename generation,
collision resolution, review status management, safe rename preview dialog,
and rollback audit history.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db
from core.naming_engine import clean_filename, naming_engine
from ui.components.rename_history_dialog import RenameHistoryDialog
from ui.components.rename_preview_dialog import RenamePreviewDialog
from ui.components.renaming_inspector import RenamingInspector
from ui.components.stat_card import StatCard


class RenamingView(QWidget):
    """Primary Smart Asset Renaming interface."""

    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_page = 1
        self.page_size = 50
        self.total_matching = 0
        self.current_assets: List[Dict[str, Any]] = []
        self.selected_ids: Set[int] = set()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Control & Action Toolbar
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)

        # 2. Splitter (Workspace | Right Renaming Inspector)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)

        # 2a. Left Workspace
        workspace = QWidget()
        ws_layout = QVBoxLayout(workspace)
        ws_layout.setContentsMargins(14, 12, 14, 0)
        ws_layout.setSpacing(10)

        # Statistics Cards Row (6 real database values)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        self.card_total = StatCard("Total Images", "0", "Cataloged assets", "🖼️")
        self.card_generated = StatCard("Names Generated", "0", "Standardized proposals", "🏷️", accent_color=THEME_COLORS["status_info"])
        self.card_approved = StatCard("Approved Names", "0", "Ready to rename", "✅", accent_color=THEME_COLORS["status_success"])
        self.card_pending = StatCard("Pending Review", "0", "Awaiting confirmation", "⏳", accent_color=THEME_COLORS["status_warning"])
        self.card_conflicts = StatCard("Naming Conflicts", "0", "Collisions flagged", "⚠️", accent_color="#EF4444")
        self.card_manual = StatCard("Manually Edited", "0", "Custom user names", "✏️", accent_color="#38BDF8")

        for c in [self.card_total, self.card_generated, self.card_approved, self.card_pending, self.card_conflicts, self.card_manual]:
            stats_row.addWidget(c)
        ws_layout.addLayout(stats_row)

        # Main Table for Asset Renaming
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Thumbnail", "Original Filename", "Category", "Suggested Filename",
            "Review Status", "Extension", "Rename Status"
        ])
        self.table.setIconSize(self.table.iconSize())
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 60)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 230)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 160)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        ws_layout.addWidget(self.table, stretch=1)

        # Bottom Pagination & Bulk Action Bar
        pagination_bar = self._create_pagination_bar()
        ws_layout.addWidget(pagination_bar)

        self.splitter.addWidget(workspace)

        # 2b. Right Renaming Inspector
        self.inspector = RenamingInspector()
        self.inspector.name_approved.connect(self._on_inspector_name_approved)
        self.inspector.name_saved.connect(self._on_inspector_name_saved)
        self.inspector.name_rejected.connect(self._on_inspector_name_rejected)
        self.inspector.name_regenerated.connect(self._on_inspector_name_regenerated)
        self.inspector.name_restored.connect(self._on_inspector_name_restored)
        self.inspector.close_requested.connect(self._on_inspector_close)
        self.splitter.addWidget(self.inspector)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([900, 340])

        main_layout.addWidget(self.splitter)

        # Initial Load
        self.refresh()

    def _create_toolbar(self) -> QWidget:
        """Create the top controls toolbar with generation, filters, and modals."""
        bar = QFrame()
        bar.setProperty("class", "card")
        bar.setStyleSheet("border-radius: 0px; border-bottom: 1px solid #1E293B;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        # Generation buttons
        self.btn_gen_batch = QPushButton("⚡ Generate Suggestions")
        self.btn_gen_batch.setCursor(Qt.PointingHandCursor)
        self.btn_gen_batch.setStyleSheet(f"""
            background: {THEME_COLORS['accent_primary']};
            color: #0D1117;
            font-weight: 700;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 11px;
            border: none;
        """)
        self.btn_gen_batch.clicked.connect(self._on_generate_batch_clicked)
        layout.addWidget(self.btn_gen_batch)

        self.btn_regen_selected = QPushButton("Regenerate Selected")
        self.btn_regen_selected.setCursor(Qt.PointingHandCursor)
        self.btn_regen_selected.setStyleSheet("""
            background: #1E293B;
            color: #CBD5E1;
            border: 1px solid #334155;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        """)
        self.btn_regen_selected.clicked.connect(self._on_regenerate_selected_clicked)
        layout.addWidget(self.btn_regen_selected)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search filenames or suggested names...")
        self.search_input.setFixedWidth(210)
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

        # Category Filter
        self.combo_category = QComboBox()
        self.combo_category.addItems([
            "All Categories", "Construction Vehicles", "Excavator Components",
            "Vehicle Components", "Construction Equipment and Tools",
            "Construction Environment", "Game Interface", "Unknown"
        ])
        self.combo_category.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            color: {THEME_COLORS['text_primary']};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
        """)
        self.combo_category.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self.combo_category)

        # Status Filter
        self.combo_status = QComboBox()
        self.combo_status.addItems([
            "All Statuses", "Pending Review", "Approved", "Conflicts Only", "Manual Edits", "Rejected"
        ])
        self.combo_status.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            color: {THEME_COLORS['text_primary']};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
        """)
        self.combo_status.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self.combo_status)

        layout.addStretch()

        # Selection shortcuts
        btn_sel_all = QPushButton("Select All")
        btn_sel_all.setCursor(Qt.PointingHandCursor)
        btn_sel_all.setStyleSheet("background: transparent; color: #94A3B8; font-size: 11px; border: none;")
        btn_sel_all.clicked.connect(self._select_all_rows)
        layout.addWidget(btn_sel_all)

        btn_desel = QPushButton("Clear")
        btn_desel.setCursor(Qt.PointingHandCursor)
        btn_desel.setStyleSheet("background: transparent; color: #94A3B8; font-size: 11px; border: none;")
        btn_desel.clicked.connect(self._clear_all_rows)
        layout.addWidget(btn_desel)

        # Preview & Execute Modal Trigger
        self.btn_preview_rename = QPushButton("🚀 Preview & Rename")
        self.btn_preview_rename.setCursor(Qt.PointingHandCursor)
        self.btn_preview_rename.setStyleSheet(f"""
            background: #10B981;
            color: white;
            font-weight: 700;
            padding: 6px 14px;
            border-radius: 4px;
            font-size: 11px;
            border: none;
        """)
        self.btn_preview_rename.clicked.connect(self._open_preview_dialog)
        layout.addWidget(self.btn_preview_rename)

        # History Modal Trigger
        self.btn_history = QPushButton("📜 History & Rollback")
        self.btn_history.setCursor(Qt.PointingHandCursor)
        self.btn_history.setStyleSheet("""
            background: #1E293B;
            color: #38BDF8;
            border: 1px solid #334155;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        """)
        self.btn_history.clicked.connect(self._open_history_dialog)
        layout.addWidget(self.btn_history)

        return bar

    def _create_pagination_bar(self) -> QWidget:
        """Create bottom bar showing selection info and pagination controls."""
        bar = QFrame()
        bar.setStyleSheet("border-top: 1px solid #1E293B; padding: 4px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        self.lbl_selected_info = QLabel("0 selected")
        self.lbl_selected_info.setStyleSheet(f"color: {THEME_COLORS['accent_primary']}; font-weight: 600; font-size: 11px;")
        layout.addWidget(self.lbl_selected_info)

        # Bulk status buttons
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

        self.btn_prev_page = QPushButton("◀ Prev")
        self.btn_prev_page.setCursor(Qt.PointingHandCursor)
        self.btn_prev_page.setStyleSheet("background: #1E293B; color: #CBD5E1; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;")
        self.btn_prev_page.clicked.connect(self._on_prev_page)
        layout.addWidget(self.btn_prev_page)

        self.btn_next_page = QPushButton("Next ▶")
        self.btn_next_page.setCursor(Qt.PointingHandCursor)
        self.btn_next_page.setStyleSheet("background: #1E293B; color: #CBD5E1; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;")
        self.btn_next_page.clicked.connect(self._on_next_page)
        layout.addWidget(self.btn_next_page)

        return bar

    def refresh(self) -> None:
        """Reload database statistics and fetch current page of assets."""
        self._update_stats_cards()
        self._load_table_data()

    def _update_stats_cards(self) -> None:
        """Fetch real SQLite statistics and update the 6 StatCards."""
        stats = db.get_naming_stats()
        self.card_total.update_value(str(stats["total_images"]))
        self.card_generated.update_value(str(stats["names_generated"]))
        self.card_approved.update_value(str(stats["approved_names"]))
        self.card_pending.update_value(str(stats["pending_review"]))
        self.card_conflicts.update_value(str(stats["naming_conflicts"]))
        self.card_manual.update_value(str(stats["manually_edited"]))

    def _load_table_data(self) -> None:
        """Query matching assets from SQLite and populate the table."""
        col_text = self.combo_collection.currentText()
        col_param = None
        if col_text == "Excavator":
            col_param = "excavator"
        elif col_text == "Other Images":
            col_param = "other_images"

        cat_text = self.combo_category.currentText()
        cat_param = cat_text if cat_text != "All Categories" else None

        st_text = self.combo_status.currentText()
        st_param = None
        has_conflict_filter = None
        if st_text == "Pending Review":
            st_param = "pending"
        elif st_text == "Approved":
            st_param = "approved"
        elif st_text == "Conflicts Only":
            has_conflict_filter = 1
        elif st_text == "Manual Edits":
            st_param = "manual"
        elif st_text == "Rejected":
            st_param = "rejected"

        search_text = self.search_input.text().strip() or None

        # Build custom kwargs
        kwargs: Dict[str, Any] = {}
        if cat_param:
            kwargs["main_category"] = cat_param
        if has_conflict_filter is not None:
            kwargs["naming_conflict"] = 1
        if st_param:
            kwargs["naming_status"] = st_param

        # Fetch total count
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

        self._populate_table_rows()

        # Update pagination controls
        self.lbl_page_info.setText(f"Page {self.current_page} of {total_pages} ({self.total_matching} assets)")
        self.btn_prev_page.setEnabled(self.current_page > 1)
        self.btn_next_page.setEnabled(self.current_page < total_pages)

    def _populate_table_rows(self) -> None:
        """Render rows into QTableWidget."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.current_assets))

        status_colors = {
            "approved": "#10B981",
            "pending": THEME_COLORS["accent_primary"],
            "conflict": "#EF4444",
            "manual": "#38BDF8",
            "rejected": "#64748B",
        }

        for row, asset in enumerate(self.current_assets):
            # 1. Thumbnail
            thumb_path = asset.get("thumbnail_path")
            thumb_item = QTableWidgetItem()
            if thumb_path and Path(thumb_path).exists():
                pix = QPixmap(str(thumb_path)).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb_item.setIcon(QIcon(pix))
            thumb_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, thumb_item)

            # 2. Original Filename
            orig_name = asset.get("filename", "")
            orig_item = QTableWidgetItem(orig_name)
            self.table.setItem(row, 1, orig_item)

            # 3. Category
            cat_str = asset.get("main_category") or "Unclassified"
            subcat = asset.get("subcategory")
            if subcat:
                cat_str += f" ({subcat})"
            cat_item = QTableWidgetItem(cat_str)
            cat_item.setForeground(Qt.lightGray)
            self.table.setItem(row, 2, cat_item)

            # 4. Suggested Filename
            sug_name = asset.get("approved_filename") or asset.get("suggested_filename") or ""
            sug_item = QTableWidgetItem(sug_name)
            sug_item.setForeground(Qt.white)
            self.table.setItem(row, 3, sug_item)

            # 5. Review Status
            st = asset.get("naming_status", "pending")
            conflict = bool(asset.get("naming_conflict", 0))
            display_status = "CONFLICT" if conflict else st.upper()
            st_item = QTableWidgetItem(display_status)
            st_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, st_item)

            # 6. Extension
            ext = asset.get("format", "").upper()
            ext_item = QTableWidgetItem(f".{ext.lower()}")
            ext_item.setTextAlignment(Qt.AlignCenter)
            ext_item.setForeground(Qt.gray)
            self.table.setItem(row, 5, ext_item)

            # 7. Rename Status
            rn_st = asset.get("rename_status", "not_renamed")
            rn_display = "RENAMED" if rn_st == "renamed" else "ORIGINAL"
            rn_item = QTableWidgetItem(rn_display)
            rn_item.setTextAlignment(Qt.AlignCenter)
            rn_item.setForeground(Qt.green if rn_st == "renamed" else Qt.gray)
            self.table.setItem(row, 6, rn_item)

        self.table.blockSignals(False)

        # Restore inspector for first item if available
        if self.current_assets:
            self.inspector.load_asset(self.current_assets[0])

    def _on_table_selection_changed(self) -> None:
        """Handle row selection changes in table."""
        selected_rows = self.table.selectionModel().selectedRows()
        self.selected_ids = {self.current_assets[r.row()]["id"] for r in selected_rows if r.row() < len(self.current_assets)}
        self.lbl_selected_info.setText(f"{len(self.selected_ids)} selected")

        if selected_rows:
            target_asset = self.current_assets[selected_rows[0].row()]
            self.inspector.load_asset(target_asset)
            if not self.inspector.isVisible():
                self.inspector.setVisible(True)

    def _on_table_double_clicked(self, row: int, col: int) -> None:
        """Double clicking a row focuses inspector editing."""
        if 0 <= row < len(self.current_assets):
            self.inspector.load_asset(self.current_assets[row])
            self.inspector.edit_proposed_name.setFocus()
            self.inspector.edit_proposed_name.selectAll()

    def _select_all_rows(self) -> None:
        if hasattr(self, "table"):
            self.table.selectAll()

    def _clear_all_rows(self) -> None:
        if hasattr(self, "table"):
            self.table.clearSelection()

    def _on_filter_changed(self) -> None:
        """Reset to page 1 and reload table when search/filter inputs change."""
        self.current_page = 1
        self._load_table_data()

    def _on_prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self._load_table_data()

    def _on_next_page(self) -> None:
        self.current_page += 1
        self._load_table_data()

    def _on_generate_batch_clicked(self) -> None:
        """Generate smart filenames across all matching assets using NamingEngine."""
        all_assets = db.get_assets(limit=10000, sort_by="id", ascending=True)
        proposals = naming_engine.process_all_assets(all_assets)
        saved = naming_engine.apply_batch_suggestions(proposals)

        QMessageBox.information(
            self,
            "Names Generated",
            f"Successfully generated standardized smart filenames for {saved} assets.\n"
            "Naming collisions have been resolved with sequential suffixes and flagged for review."
        )
        self.refresh()
        self.status_updated.emit()

    def _on_regenerate_selected_clicked(self) -> None:
        """Regenerate suggestions for currently selected rows."""
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select one or more assets to regenerate.")
            return

        selected_assets = [a for a in self.current_assets if a["id"] in self.selected_ids]
        proposals = naming_engine.process_all_assets(selected_assets)
        saved = naming_engine.apply_batch_suggestions(proposals)

        QMessageBox.information(
            self,
            "Regeneration Complete",
            f"Regenerated suggestions for {saved} selected asset(s)."
        )
        self.refresh()
        self.status_updated.emit()

    def _on_bulk_approve_clicked(self) -> None:
        """Batch approve proposed names for all selected assets."""
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select assets to approve.")
            return

        count = db.bulk_update_naming_status(list(self.selected_ids), "approved")
        self.refresh()
        self.status_updated.emit()
        QMessageBox.information(self, "Approved", f"Marked {count} assets as approved.")

    def _on_bulk_reject_clicked(self) -> None:
        """Batch reject proposed names for all selected assets."""
        if not self.selected_ids:
            QMessageBox.information(self, "No Selection", "Please select assets to reject.")
            return

        count = db.bulk_update_naming_status(list(self.selected_ids), "rejected")
        self.refresh()
        self.status_updated.emit()
        QMessageBox.information(self, "Rejected", f"Marked {count} assets as rejected.")

    def _open_preview_dialog(self) -> None:
        """Open the modal Before-and-After Safe Rename Preview dialog."""
        if self.selected_ids:
            candidates = [a for a in self.current_assets if a["id"] in self.selected_ids]
        else:
            candidates = self.current_assets

        if not candidates:
            QMessageBox.information(self, "No Candidates", "No assets available to preview for renaming.")
            return

        dialog = RenamePreviewDialog(candidates, self)
        dialog.rename_executed.connect(self._on_rename_executed)
        dialog.exec()

    def _open_history_dialog(self) -> None:
        """Open the Rename History and Rollback audit dialog."""
        dialog = RenameHistoryDialog(self)
        dialog.rollback_completed.connect(self._on_rollback_completed)
        dialog.exec()

    def _on_rename_executed(self, count: int) -> None:
        """Handle completion of a rename operation."""
        self.refresh()
        self.status_updated.emit()

    def _on_rollback_completed(self, history_id: int) -> None:
        """Handle completion of a rollback operation."""
        self.refresh()
        self.status_updated.emit()

    # Inspector Signal Handlers
    def _on_inspector_name_approved(self, asset_id: int, new_name: str) -> None:
        self.refresh()
        self.status_updated.emit()

    def _on_inspector_name_saved(self, asset_id: int, new_name: str) -> None:
        self.refresh()
        self.status_updated.emit()

    def _on_inspector_name_rejected(self, asset_id: int) -> None:
        self.refresh()
        self.status_updated.emit()

    def _on_inspector_name_regenerated(self, asset_id: int) -> None:
        pass

    def _on_inspector_name_restored(self, asset_id: int) -> None:
        pass

    def _on_inspector_close(self) -> None:
        self.inspector.setVisible(False)
