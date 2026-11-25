"""
Stage 13 Flutter Export Dialog
Construction Asset Processor

Final confirmation dialog displaying:
1. List of approved excavator components ready for deployment.
2. Target Flutter destination subfolders.
3. Zero-touch safety assurances (no Dart code or pubspec.yaml modification).
4. Manifest preview & execute button.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.stage13_export_engine import (
    COMPONENT_SUBFOLDER_MAP, DEFAULT_FLUTTER_ASSETS_DIR,
    Stage13ExportEngine
)


class Stage13ExportDialog(QDialog):
    """Confirmation modal for deploying approved assets to the Flutter game project."""

    export_completed = Signal(dict)

    def __init__(self, approved_components: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.approved_components = approved_components
        self.export_engine = Stage13ExportEngine()

        self.setWindowTitle("Export Approved Assets to Flutter + Flame Game")
        self.resize(950, 620)
        self.setMinimumSize(800, 500)
        self.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']}; color: {THEME_COLORS['text_primary']};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Title
        title_lbl = QLabel("🚀 Deploy Approved Sprites to Flutter Project")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #F3F4F6;")
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "Review the list of approved excavator components below. Sprites will be copied cleanly into "
            "canonical subdirectories inside your Flutter project's assets/images directory."
        )
        desc_lbl.setStyleSheet(f"font-size: 13px; color: {THEME_COLORS['text_secondary']};")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        # Destination Directory Picker Row
        dir_frame = QFrame()
        dir_frame.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; border: 1px solid {THEME_COLORS['border_subtle']}; border-radius: 6px; padding: 10px;")
        dir_layout = QHBoxLayout(dir_frame)
        dir_layout.setContentsMargins(8, 4, 8, 4)

        dir_lbl = QLabel("Flutter Assets Directory:")
        dir_lbl.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_primary']};")
        dir_layout.addWidget(dir_lbl)

        self.path_input = QLineEdit(str(DEFAULT_FLUTTER_ASSETS_DIR))
        self.path_input.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 6px; border-radius: 4px; color: #F3F4F6;")
        dir_layout.addWidget(self.path_input, stretch=1)

        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; color: {THEME_COLORS['text_primary']}; padding: 6px 14px; border-radius: 4px;")
        btn_browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(btn_browse)

        layout.addWidget(dir_frame)

        # Approved Components Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Component", "Type", "Subfolder", "Dimensions", "Pivot (Norm)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                gridline-color: {THEME_COLORS['border_subtle']};
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_secondary']};
                font-weight: 600;
                padding: 6px;
                border: 1px solid {THEME_COLORS['border_subtle']};
            }}
        """)

        self._populate_table()
        layout.addWidget(self.table, stretch=1)

        # Safety & Non-destructive Notice Card
        notice_card = QFrame()
        notice_card.setStyleSheet(f"background-color: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 6px; padding: 10px;")
        notice_layout = QVBoxLayout(notice_card)
        notice_layout.setContentsMargins(10, 8, 10, 8)
        notice_layout.setSpacing(4)

        n_title = QLabel("🛡️ Safety & Project Separation Guarantees")
        n_title.setStyleSheet(f"font-weight: 700; color: {THEME_COLORS['status_success']}; font-size: 12px;")
        notice_layout.addWidget(n_title)

        n_text = QLabel(
            "• Original source images are 100% untouched.\n"
            "• Flutter Dart code, architecture, and pubspec.yaml will NOT be modified.\n"
            "• Generates stage13_export_manifest.json with Flame Sprite.load() metadata.\n"
            "• Only approved assets are exported; unapproved assets are excluded."
        )
        n_text.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']}; line-height: 1.4;")
        notice_layout.addWidget(n_text)

        layout.addWidget(notice_card)

        # Bottom Actions
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(f"background-color: {THEME_COLORS['bg_card']}; color: {THEME_COLORS['text_secondary']}; padding: 8px 18px; border-radius: 4px;")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_deploy = QPushButton(f"🚀 Deploy {len(self.approved_components)} Approved Sprites")
        btn_deploy.setStyleSheet(f"background-color: {THEME_COLORS['accent_primary']}; color: #111827; font-weight: 700; font-size: 13px; padding: 8px 24px; border-radius: 4px;")
        btn_deploy.clicked.connect(self._execute_deploy)
        btn_layout.addWidget(btn_deploy)

        layout.addLayout(btn_layout)

    def _browse_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Flutter assets/images Directory", self.path_input.text())
        if chosen:
            self.path_input.setText(chosen)

    def _populate_table(self):
        self.table.setRowCount(len(self.approved_components))
        for row, comp in enumerate(self.approved_components):
            comp_type = comp.get("component_type", "other")
            subfolder = COMPONENT_SUBFOLDER_MAP.get(comp_type, "components")
            name = comp.get("component_name") or f"Asset_{comp.get('id')}"
            dims = f"{comp.get('export_width', 0)} × {comp.get('export_height', 0)}"
            pivot = f"({comp.get('pivot_norm_x', 0.5):.2f}, {comp.get('pivot_norm_y', 0.5):.2f})"

            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(comp_type))
            self.table.setItem(row, 2, QTableWidgetItem(f"assets/images/{subfolder}/"))
            self.table.setItem(row, 3, QTableWidgetItem(dims))
            self.table.setItem(row, 4, QTableWidgetItem(pivot))

    def _execute_deploy(self):
        target_dir = Path(self.path_input.text().strip())
        success, summary, msg = self.export_engine.execute_export(
            self.approved_components,
            destination_override=target_dir
        )
        if success:
            QMessageBox.information(self, "Export Successful", msg)
            self.export_completed.emit(summary)
            self.accept()
        else:
            QMessageBox.warning(self, "Export Failed", msg)
