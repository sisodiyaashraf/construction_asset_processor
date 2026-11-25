"""
Gallery List View Component
Table-based asset view with columns, miniature thumbnails, column sorting,
multi-row selection, and inspector integration.
"""

from pathlib import Path
from typing import Any, Dict, List
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHeaderView, QTableWidget, QTableWidgetItem, QWidget
)

from app.config import THEME_COLORS
from core.database import format_bytes


class GalleryTable(QTableWidget):
    """List view table showing asset records with thumbnails and sorting."""

    asset_selected = Signal(dict)
    selection_changed_signal = Signal(list)  # list of selected asset_ids
    header_sort_requested = Signal(str, bool)  # col_name, ascending

    COLUMNS = [
        ("Preview", 50),
        ("Filename", 280),
        ("Collection", 110),
        ("Width", 70),
        ("Height", 70),
        ("Format", 70),
        ("File Size", 90),
        ("Transparency", 100),
        ("Status", 90),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.assets: List[Dict[str, Any]] = []
        self._asset_map: Dict[int, Dict[str, Any]] = {}
        self._block_signals = False

        self.setColumnCount(len(self.COLUMNS))
        self.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(40)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        self.setShowGrid(True)
        self.setAlternatingRowColors(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for idx, (col_name, width) in enumerate(self.COLUMNS):
            if idx != 1:
                header.setSectionResizeMode(idx, QHeaderView.Interactive)
                self.setColumnWidth(idx, width)

        self.itemSelectionChanged.connect(self._on_selection_changed)
        header.sectionClicked.connect(self._on_header_clicked)

    def load_assets(self, assets: List[Dict[str, Any]]):
        """Populate the table with asset records."""
        self._block_signals = True
        self.assets = assets
        self._asset_map = {a["id"]: a for a in assets}
        self.setRowCount(len(assets))

        for row_idx, asset in enumerate(assets):
            # 0. Thumbnail Preview
            item_thumb = QTableWidgetItem()
            thumb_path = asset.get("thumbnail_path")
            if thumb_path and Path(thumb_path).exists():
                pixmap = QPixmap(thumb_path).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                item_thumb.setIcon(QIcon(pixmap))
            item_thumb.setTextAlignment(Qt.AlignCenter)
            item_thumb.setData(Qt.UserRole, asset["id"])
            self.setItem(row_idx, 0, item_thumb)

            # 1. Filename
            item_fname = QTableWidgetItem(asset.get("filename", ""))
            item_fname.setToolTip(asset.get("original_path", ""))
            self.setItem(row_idx, 1, item_fname)

            # 2. Collection
            coll = asset.get("collection", "other_images").replace("_", " ").title()
            item_coll = QTableWidgetItem(coll)
            self.setItem(row_idx, 2, item_coll)

            # 3. Width
            item_w = QTableWidgetItem(f"{asset.get('width', 0)} px")
            item_w.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(row_idx, 3, item_w)

            # 4. Height
            item_h = QTableWidgetItem(f"{asset.get('height', 0)} px")
            item_h.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(row_idx, 4, item_h)

            # 5. Format
            item_fmt = QTableWidgetItem(str(asset.get("format", "PNG")).upper())
            item_fmt.setTextAlignment(Qt.AlignCenter)
            self.setItem(row_idx, 5, item_fmt)

            # 6. File Size
            item_size = QTableWidgetItem(format_bytes(asset.get("file_size", 0)))
            item_size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(row_idx, 6, item_size)

            # 7. Transparency
            has_t = bool(asset.get("has_transparency", 0))
            item_t = QTableWidgetItem("Alpha" if has_t else "Opaque")
            item_t.setTextAlignment(Qt.AlignCenter)
            self.setItem(row_idx, 7, item_t)

            # 8. Status
            status = str(asset.get("status", "pending")).capitalize()
            item_st = QTableWidgetItem(status)
            item_st.setTextAlignment(Qt.AlignCenter)
            self.setItem(row_idx, 8, item_st)

        self._block_signals = False

    def select_asset_ids(self, asset_ids: set):
        """Synchronize selection from external state."""
        self._block_signals = True
        self.clearSelection()
        first_selected_row = None

        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                aid = item.data(Qt.UserRole)
                if aid in asset_ids:
                    self.selectRow(row)
                    if first_selected_row is None:
                        first_selected_row = row

        if first_selected_row is not None:
            self.scrollToItem(self.item(first_selected_row, 0))

        self._block_signals = False

    def _on_selection_changed(self):
        """Emit selected assets on row changes."""
        if self._block_signals:
            return

        selected_rows = sorted(set(idx.row() for idx in self.selectedIndexes()))
        selected_ids = []
        for r in selected_rows:
            item = self.item(r, 0)
            if item:
                aid = item.data(Qt.UserRole)
                selected_ids.append(aid)

        self.selection_changed_signal.emit(selected_ids)

        if selected_ids:
            latest_id = selected_ids[-1]
            if latest_id in self._asset_map:
                self.asset_selected.emit(self._asset_map[latest_id])

    def _on_header_clicked(self, logical_index: int):
        """Map column index to database sort key."""
        col_map = {
            1: "filename_asc",
            2: "collection",
            3: "width_desc",
            4: "height_desc",
            5: "format",
            6: "size_desc",
            8: "status",
        }
        sort_key = col_map.get(logical_index)
        if sort_key:
            self.header_sort_requested.emit(sort_key, True)
