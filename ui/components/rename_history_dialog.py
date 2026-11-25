"""
Smart Renaming - Rename History and Rollback Dialog
Displays complete audit log of all rename operations and provides
one-click safe rollback to restore original filenames without data loss.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout
)

from app.config import THEME_COLORS
from core.database import db

logger = logging.getLogger("AssetProcessor.RenameHistoryDialog")


class RenameHistoryDialog(QDialog):
    """Modal audit and rollback dialog for past file rename operations."""

    rollback_completed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rename History & Rollback Audit")
        self.resize(950, 550)
        self.setModal(True)
        self.records: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # 1. Header
        header = QLabel("RENAME OPERATIONS AUDIT & REVERSIBILITY LOG")
        header.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        layout.addWidget(header)

        desc = QLabel(
            "Every file rename operation is permanently recorded in SQLite. "
            "You can restore any renamed file back to its original filename with one click."
        )
        desc.setStyleSheet(f"color: {THEME_COLORS['text_secondary']}; font-size: 11px;")
        layout.addWidget(desc)

        # 2. Filter Bar
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filter Status:"))

        self.combo_filter = QComboBox()
        self.combo_filter.addItems(["All Operations", "Success Only", "Rolled Back Only", "Failed Only"])
        self.combo_filter.setStyleSheet(f"""
            background: #1E293B;
            border: 1px solid #334155;
            color: {THEME_COLORS['text_primary']};
            padding: 4px 8px;
            border-radius: 4px;
        """)
        self.combo_filter.currentTextChanged.connect(self._load_records)
        filter_bar.addWidget(self.combo_filter)
        filter_bar.addStretch()

        self.lbl_record_count = QLabel("0 operations logged")
        self.lbl_record_count.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px;")
        filter_bar.addWidget(self.lbl_record_count)

        layout.addLayout(filter_bar)

        # 3. History Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "Timestamp", "Original Filename", "Renamed Filename", "Status", "Rollback State"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # 4. Footer
        footer = QHBoxLayout()
        footer.setSpacing(10)

        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            background: #1E293B;
            color: {THEME_COLORS['text_secondary']};
            border: 1px solid #334155;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        """)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)

        footer.addStretch()

        self.btn_rollback = QPushButton("Roll Back Selected Operation")
        self.btn_rollback.setCursor(Qt.PointingHandCursor)
        self.btn_rollback.setStyleSheet("""
            background: #EF4444;
            color: white;
            border: none;
            padding: 8px 20px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 700;
        """)
        self.btn_rollback.clicked.connect(self._on_rollback_clicked)
        footer.addWidget(self.btn_rollback)

        layout.addLayout(footer)

        self._load_records()

    def _load_records(self) -> None:
        """Fetch and populate history records based on active filter."""
        flt_text = self.combo_filter.currentText()
        status_param = None
        if "Success" in flt_text:
            status_param = "success"
        elif "Failed" in flt_text:
            status_param = "failed"

        raw_records = db.get_rename_history(limit=200, status=status_param)

        if "Rolled Back" in flt_text:
            self.records = [r for r in raw_records if r.get("rollback_status") == "rolled_back"]
        else:
            self.records = raw_records

        self.table.setRowCount(len(self.records))
        self.lbl_record_count.setText(f"{len(self.records)} operations logged")

        for row, rec in enumerate(self.records):
            h_id = rec["id"]
            ts = rec.get("timestamp") or "—"
            orig = rec.get("original_filename") or "—"
            new_fn = rec.get("new_filename") or "—"
            op_st = rec.get("operation_status") or "success"
            rb_st = rec.get("rollback_status") or "active"

            item_id = QTableWidgetItem(str(h_id))
            item_id.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, item_id)

            item_ts = QTableWidgetItem(str(ts)[:19])
            item_ts.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, item_ts)

            item_orig = QTableWidgetItem(orig)
            self.table.setItem(row, 2, item_orig)

            item_new = QTableWidgetItem(new_fn)
            self.table.setItem(row, 3, item_new)

            item_op = QTableWidgetItem(op_st.upper())
            item_op.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item_op)

            item_rb = QTableWidgetItem(rb_st.upper())
            item_rb.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, item_rb)

    def _on_rollback_clicked(self) -> None:
        """Roll back the selected rename operation."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Selection Required", "Please select a history record to roll back.")
            return

        row = selected_rows[0].row()
        rec = self.records[row]
        history_id = rec["id"]

        if rec.get("rollback_status") == "rolled_back":
            QMessageBox.information(self, "Already Rolled Back", "This rename operation has already been restored.")
            return

        if rec.get("operation_status") != "success":
            QMessageBox.warning(self, "Cannot Roll Back", "Only successful rename operations can be rolled back.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Rollback",
            f"Restore file '{rec['new_filename']}' back to its original name '{rec['original_filename']}'?\n\n"
            "This will safely rename the file on disk and update SQLite.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        success, msg = db.rollback_rename_asset(history_id)
        if success:
            QMessageBox.information(self, "Rollback Successful", msg)
            self.rollback_completed.emit(history_id)
            self._load_records()
        else:
            QMessageBox.critical(self, "Rollback Error", f"Failed to restore file:\n{msg}")
