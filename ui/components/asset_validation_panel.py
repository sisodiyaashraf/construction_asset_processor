"""
Asset Validation Panel Component (Stage 10)
Construction Asset Processor

Inspects quality rules, file integrity, format compliance, power-of-two bounds,
alpha transparency issues, exact & perceptual visual duplicates, and unreviewed watermarks.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView
)

from app.config import THEME_COLORS
from core.asset_validator import asset_validator
from core.database import db

logger = logging.getLogger("AssetProcessor.ValidationPanel")


class AssetValidationPanel(QWidget):
    """Panel displaying validation issues, severity flags, and batch validation triggers."""

    batch_validate_requested = Signal()
    single_validate_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_asset: Optional[Dict[str, Any]] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header Title
        title = QLabel("QUALITY & INTEGRITY VALIDATOR")
        title.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        layout.addWidget(title)

        # Summary Metrics Bar
        summary_frame = QFrame()
        summary_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        sum_layout = QHBoxLayout(summary_frame)
        sum_layout.setContentsMargins(8, 6, 8, 6)
        sum_layout.setSpacing(10)

        self.lbl_passed_count = QLabel("Passed: 0")
        self.lbl_passed_count.setStyleSheet("color: #10B981; font-weight: 700; font-size: 11px;")
        sum_layout.addWidget(self.lbl_passed_count)

        self.lbl_warning_count = QLabel("Warnings: 0")
        self.lbl_warning_count.setStyleSheet("color: #F59E0B; font-weight: 700; font-size: 11px;")
        sum_layout.addWidget(self.lbl_warning_count)

        self.lbl_failed_count = QLabel("Failed: 0")
        self.lbl_failed_count.setStyleSheet("color: #EF4444; font-weight: 700; font-size: 11px;")
        sum_layout.addWidget(self.lbl_failed_count)

        sum_layout.addStretch()
        layout.addWidget(summary_frame)

        # Table of Issues for Selected Asset
        self.table_issues = QTableWidget()
        self.table_issues.setColumnCount(3)
        self.table_issues.setHorizontalHeaderLabels(["Severity", "Check Rule", "Details"])
        self.table_issues.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_issues.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_issues.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_issues.verticalHeader().setVisible(False)
        self.table_issues.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_issues.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_input']};
                gridline-color: {THEME_COLORS['border_subtle']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_toolbar']};
                color: {THEME_COLORS['text_secondary']};
                font-weight: 600;
                border: none;
                padding: 4px;
            }}
        """)
        layout.addWidget(self.table_issues)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.btn_validate_all = QPushButton("⚡ Validate All Assets")
        self.btn_validate_all.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_secondary']};
                color: white;
                font-weight: 700;
                font-size: 11px;
                padding: 6px 12px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #2563EB;
            }}
        """)
        self.btn_validate_all.clicked.connect(self.batch_validate_requested.emit)
        btn_layout.addWidget(self.btn_validate_all)

        layout.addLayout(btn_layout)

    def load_asset_validation(self, asset: Optional[Dict[str, Any]]):
        """Display validation results for a selected asset."""
        self.current_asset = asset
        self.table_issues.setRowCount(0)
        if not asset:
            return

        asset_id = asset["id"]
        results = db.get_asset_validation_results(asset_id)

        self.table_issues.setRowCount(len(results))
        for row, res in enumerate(results):
            sev = res.get("severity", "info").upper()
            sev_item = QTableWidgetItem(sev)
            if sev == "ERROR":
                sev_item.setForeground(Qt.red)
            elif sev == "WARNING":
                sev_item.setForeground(Qt.yellow)
            else:
                sev_item.setForeground(Qt.cyan)
            self.table_issues.setItem(row, 0, sev_item)

            chk_item = QTableWidgetItem(res.get("check_type", "rule").replace("_", " ").title())
            self.table_issues.setItem(row, 1, chk_item)

            msg_item = QTableWidgetItem(res.get("message", ""))
            self.table_issues.setItem(row, 2, msg_item)

    def update_summary_stats(self, stats: Dict[str, int]):
        """Update the passed/warning/failed counts."""
        passed = stats.get("passed", 0)
        warn = stats.get("warning", 0)
        failed = stats.get("failed", 0)

        self.lbl_passed_count.setText(f"Passed: {passed}")
        self.lbl_warning_count.setText(f"Warnings: {warn}")
        self.lbl_failed_count.setText(f"Failed: {failed}")
