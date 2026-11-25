"""
Smart Renaming - Safe Preview and Execution Dialog
Displays a modal before-and-after table showing proposed renames.
Enforces user confirmation and safe filesystem operations with zero data loss.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db

logger = logging.getLogger("AssetProcessor.RenamePreviewDialog")


class RenamePreviewDialog(QDialog):
    """
    Modal dialog providing a complete before-and-after audit table
    of all proposed rename operations prior to any filesystem modification.
    """

    rename_executed = Signal(int)

    def __init__(self, candidates: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview and Confirm Safe Asset Renaming")
        self.resize(950, 600)
        self.setModal(True)
        self.candidates = candidates
        self.executed_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # 1. Header Banner
        header = QLabel("SAFE ASSET RENAMING AUDIT & PREVIEW")
        header.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        layout.addWidget(header)

        desc = QLabel(
            "Review proposed file renames below. No files will be changed until you click 'Execute Safe Rename'. "
            "All operations are recorded and can be completely rolled back at any time."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {THEME_COLORS['text_secondary']}; font-size: 11px;")
        layout.addWidget(desc)

        # 2. Summary Metrics Bar
        self.summary_frame = QFrame()
        self.summary_frame.setProperty("class", "card")
        sum_layout = QHBoxLayout(self.summary_frame)
        sum_layout.setContentsMargins(12, 10, 12, 10)
        sum_layout.setSpacing(18)

        self.lbl_total = QLabel("Total: 0")
        self.lbl_valid = QLabel("Valid: 0")
        self.lbl_conflicts = QLabel("Conflicts: 0")
        self.lbl_rejected = QLabel("Rejected: 0")
        self.lbl_ready = QLabel("Ready: 0")

        self.lbl_total.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_primary']};")
        self.lbl_valid.setStyleSheet("font-weight: 600; color: #10B981;")
        self.lbl_conflicts.setStyleSheet("font-weight: 600; color: #EF4444;")
        self.lbl_rejected.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_muted']};")
        self.lbl_ready.setStyleSheet(f"font-weight: 700; color: {THEME_COLORS['accent_primary']}; font-size: 12px;")

        sum_layout.addWidget(self.lbl_total)
        sum_layout.addWidget(self.lbl_valid)
        sum_layout.addWidget(self.lbl_conflicts)
        sum_layout.addWidget(self.lbl_rejected)
        sum_layout.addStretch()
        sum_layout.addWidget(self.lbl_ready)

        layout.addWidget(self.summary_frame)

        # 3. Before-and-After Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Asset ID", "Original Filename", "Proposed Filename", "Destination Path", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # 4. Action Buttons Footer
        footer = QHBoxLayout()
        footer.setSpacing(10)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            background: #1E293B;
            color: {THEME_COLORS['text_secondary']};
            border: 1px solid #334155;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        """)
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        footer.addStretch()

        self.btn_execute = QPushButton("Execute Safe Rename")
        self.btn_execute.setCursor(Qt.PointingHandCursor)
        self.btn_execute.setStyleSheet(f"""
            background: {THEME_COLORS['accent_primary']};
            color: #0D1117;
            border: none;
            padding: 8px 22px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 700;
        """)
        self.btn_execute.clicked.connect(self._on_execute_clicked)
        footer.addWidget(self.btn_execute)

        layout.addLayout(footer)

        self._populate_table()

    def _populate_table(self) -> None:
        """Fill table rows with candidate rename operations and compute metrics."""
        self.table.setRowCount(len(self.candidates))

        total_cnt = len(self.candidates)
        valid_cnt = 0
        conflict_cnt = 0
        rejected_cnt = 0
        ready_cnt = 0

        for row, item in enumerate(self.candidates):
            asset_id = item.get("id") or item.get("asset_id")
            orig_name = item.get("filename") or item.get("original_filename", "")
            proposed_name = (
                item.get("approved_filename") or
                item.get("suggested_filename") or
                orig_name
            )
            orig_path_str = item.get("current_path") or item.get("original_path", "")
            dest_folder = Path(orig_path_str).parent if orig_path_str else Path("output")
            dest_path_str = str(dest_folder / proposed_name)

            status = item.get("naming_status", "pending")
            has_conflict = bool(item.get("naming_conflict", 0))

            if status == "rejected":
                rejected_cnt += 1
                status_display = "Rejected"
                status_color = "#64748B"
            elif has_conflict:
                conflict_cnt += 1
                status_display = "Conflict (Resolved)"
                status_color = "#F59E0B"
                ready_cnt += 1
                valid_cnt += 1
            else:
                valid_cnt += 1
                ready_cnt += 1
                status_display = "Ready" if status in ("approved", "manual") else "Proposed"
                status_color = "#10B981" if status in ("approved", "manual") else THEME_COLORS["accent_primary"]

            # Set table items
            id_item = QTableWidgetItem(str(asset_id))
            id_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, id_item)

            orig_item = QTableWidgetItem(orig_name)
            self.table.setItem(row, 1, orig_item)

            prop_item = QTableWidgetItem(proposed_name)
            prop_item.setForeground(Qt.white)
            self.table.setItem(row, 2, prop_item)

            dest_item = QTableWidgetItem(dest_path_str)
            dest_item.setForeground(Qt.lightGray)
            self.table.setItem(row, 3, dest_item)

            st_item = QTableWidgetItem(status_display)
            st_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, st_item)

        self.lbl_total.setText(f"Total: {total_cnt}")
        self.lbl_valid.setText(f"Valid: {valid_cnt}")
        self.lbl_conflicts.setText(f"Conflicts: {conflict_cnt}")
        self.lbl_rejected.setText(f"Rejected: {rejected_cnt}")
        self.lbl_ready.setText(f"Ready to Rename: {ready_cnt}")

        if ready_cnt == 0:
            self.btn_execute.setEnabled(False)
            self.btn_execute.setStyleSheet("background: #334155; color: #64748B; padding: 8px 22px; border-radius: 4px; font-weight: 700;")

    def _on_execute_clicked(self) -> None:
        """Prompt user for explicit confirmation before executing safe rename."""
        ready_items = [
            it for it in self.candidates
            if it.get("naming_status") != "rejected" and (it.get("approved_filename") or it.get("suggested_filename"))
        ]

        if not ready_items:
            QMessageBox.information(self, "No Files Ready", "There are no valid candidates ready to rename.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Safe Rename Operation",
            f"Are you sure you want to rename {len(ready_items)} file(s) on disk?\n\n"
            "• Each operation will be verified to avoid overwriting.\n"
            "• All operations will be logged for one-click rollback.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        success_count = 0
        error_messages = []

        for item in ready_items:
            asset_id = item.get("id") or item.get("asset_id")
            new_name = item.get("approved_filename") or item.get("suggested_filename")
            if not new_name:
                continue

            success, msg = db.execute_rename_asset(asset_id, new_name, user_approved=True)
            if success:
                success_count += 1
            else:
                error_messages.append(f"Asset #{asset_id}: {msg}")

        self.executed_count = success_count

        if error_messages:
            err_summary = "\n".join(error_messages[:5])
            if len(error_messages) > 5:
                err_summary += f"\n...and {len(error_messages) - 5} more."
            QMessageBox.warning(
                self,
                "Rename Partially Completed",
                f"Successfully renamed {success_count} file(s).\n\nErrors encountered:\n{err_summary}"
            )
        else:
            QMessageBox.information(
                self,
                "Rename Completed",
                f"Successfully renamed {success_count} file(s) on disk with full rollback capability."
            )

        self.rename_executed.emit(success_count)
        self.accept()
