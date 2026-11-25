"""
Asset Import View
Folder selection interface, recursive scan configuration, non-blocking
background worker execution, real-time asset table, and live log telemetry.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget
)

from app.config import (
    INPUT_DIR, INPUT_EXCAVATOR_DIR, INPUT_OTHER_DIR,
    ROOT_DIR, THEME_COLORS
)
from core.database import db, format_bytes
from core.workers import ScanWorker


class AssetImportView(QWidget):
    """View dedicated to selecting folders, scanning assets, and reviewing live imports."""

    asset_selected = Signal(dict)
    import_completed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[ScanWorker] = None
        self.imported_assets: List[Dict[str, Any]] = []

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Header Section
        header_row = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(4)

        title = QLabel("ASSET IMPORT & FOLDER SCANNER")
        title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 700;
            color: {THEME_COLORS['text_primary']};
            letter-spacing: 0.5px;
        """)
        header_text.addWidget(title)

        subtitle = QLabel("Index raw images non-destructively, compute SHA-256 hashes, and generate thumbnails")
        subtitle.setStyleSheet(f"font-size: 13px; color: {THEME_COLORS['text_secondary']};")
        header_text.addWidget(subtitle)
        header_row.addLayout(header_text)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # 2. Folder Selection & Controls Card
        folder_card = QFrame()
        folder_card.setProperty("class", "card")
        folder_layout = QVBoxLayout(folder_card)
        folder_layout.setContentsMargins(16, 14, 16, 14)
        folder_layout.setSpacing(12)

        # Folder Path Row
        path_row = QHBoxLayout()
        path_row.setSpacing(10)

        lbl_folder = QLabel("Source Folder:")
        lbl_folder.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_primary']};")
        path_row.addWidget(lbl_folder)

        # Default path checks workspace folder 'excavater' or 'input/'
        default_folder = ROOT_DIR / "excavater"
        if not default_folder.exists():
            default_folder = INPUT_DIR

        self.txt_path = QLineEdit(str(default_folder.resolve()))
        self.txt_path.setPlaceholderText("Select or paste folder path to scan...")
        path_row.addWidget(self.txt_path, stretch=1)

        self.btn_browse = QPushButton("📁 Browse...")
        self.btn_browse.setProperty("class", "btn_secondary")
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.clicked.connect(self._browse_folder)
        path_row.addWidget(self.btn_browse)

        folder_layout.addLayout(path_row)

        # Quick Preset Shortcut Buttons Row
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)

        lbl_presets = QLabel("Presets:")
        lbl_presets.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        preset_row.addWidget(lbl_presets)

        # Workspace Excavator preset
        btn_pre_excavator = QPushButton("🚜 Workspace Excavator")
        btn_pre_excavator.setProperty("class", "btn_secondary")
        btn_pre_excavator.setCursor(Qt.PointingHandCursor)
        btn_pre_excavator.clicked.connect(lambda: self._set_folder_preset("excavater"))
        preset_row.addWidget(btn_pre_excavator)

        # Workspace Other Images preset
        btn_pre_other = QPushButton("🧱 Other Images")
        btn_pre_other.setProperty("class", "btn_secondary")
        btn_pre_other.setCursor(Qt.PointingHandCursor)
        btn_pre_other.clicked.connect(lambda: self._set_folder_preset("excavater/other images"))
        preset_row.addWidget(btn_pre_other)

        # Input Directory preset
        btn_pre_input = QPushButton("📂 Input Root")
        btn_pre_input.setProperty("class", "btn_secondary")
        btn_pre_input.setCursor(Qt.PointingHandCursor)
        btn_pre_input.clicked.connect(lambda: self._set_folder_preset(str(INPUT_DIR)))
        preset_row.addWidget(btn_pre_input)

        preset_row.addStretch()
        folder_layout.addLayout(preset_row)

        # Options & Trigger Row
        options_row = QHBoxLayout()
        options_row.setSpacing(16)

        self.chk_recursive = QCheckBox("Scan subfolders recursively")
        self.chk_recursive.setChecked(True)
        options_row.addWidget(self.chk_recursive)

        lbl_coll = QLabel("Assign Collection:")
        lbl_coll.setStyleSheet(f"color: {THEME_COLORS['text_secondary']};")
        options_row.addWidget(lbl_coll)

        self.cmb_collection = QComboBox()
        self.cmb_collection.addItem("Auto-Detect from Folder Path", None)
        self.cmb_collection.addItem("Force Excavator Collection", "excavator")
        self.cmb_collection.addItem("Force Other Game Images", "other_images")
        options_row.addWidget(self.cmb_collection)

        options_row.addStretch()

        self.btn_start = QPushButton("▶ Start Scan & Indexing")
        self.btn_start.setProperty("class", "btn_primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_scan)
        options_row.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("⏹ Cancel")
        self.btn_cancel.setProperty("class", "btn_danger")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_scan)
        options_row.addWidget(self.btn_cancel)

        folder_layout.addLayout(options_row)
        main_layout.addWidget(folder_card)

        # 3. Progress Card
        self.progress_card = QFrame()
        self.progress_card.setProperty("class", "card")
        prog_layout = QVBoxLayout(self.progress_card)
        prog_layout.setContentsMargins(16, 12, 16, 12)
        prog_layout.setSpacing(8)

        prog_top_row = QHBoxLayout()
        self.lbl_progress_status = QLabel("Ready to scan.")
        self.lbl_progress_status.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_primary']};")
        prog_top_row.addWidget(self.lbl_progress_status)
        prog_top_row.addStretch()

        self.lbl_file_counts = QLabel("0 / 0 images")
        self.lbl_file_counts.setStyleSheet(f"color: {THEME_COLORS['accent_primary']}; font-weight: 600;")
        prog_top_row.addWidget(self.lbl_file_counts)
        prog_layout.addLayout(prog_top_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        prog_layout.addWidget(self.progress_bar)

        self.lbl_current_file = QLabel("Idle")
        self.lbl_current_file.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        prog_layout.addWidget(self.lbl_current_file)

        main_layout.addWidget(self.progress_card)

        # 4. Results & Logs Tabs / Grid
        split_layout = QHBoxLayout()
        split_layout.setSpacing(14)

        # Left: Discovered / Imported Assets Table
        table_card = QFrame()
        table_card.setProperty("class", "card")
        t_layout = QVBoxLayout(table_card)
        t_layout.setContentsMargins(14, 12, 14, 12)
        t_layout.setSpacing(8)

        t_title = QLabel("IMPORTED ASSETS STREAM")
        t_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
            letter-spacing: 0.5px;
        """)
        t_layout.addWidget(t_title)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Filename", "Collection", "Dimensions", "Size", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for c in [0, 2, 3, 4, 5]:
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellClicked.connect(self._on_table_row_clicked)
        t_layout.addWidget(self.table)

        split_layout.addWidget(table_card, stretch=3)

        # Right: Live Terminal Log
        log_card = QFrame()
        log_card.setProperty("class", "card")
        l_layout = QVBoxLayout(log_card)
        l_layout.setContentsMargins(14, 12, 14, 12)
        l_layout.setSpacing(8)

        l_title = QLabel("SCAN & SYSTEM LOG")
        l_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
            letter-spacing: 0.5px;
        """)
        l_layout.addWidget(l_title)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        l_layout.addWidget(self.log_view)

        split_layout.addWidget(log_card, stretch=2)
        main_layout.addLayout(split_layout, stretch=1)

    def _browse_folder(self):
        """Open native directory selection dialog."""
        current = self.txt_path.text() or str(ROOT_DIR)
        selected_dir = QFileDialog.getExistingDirectory(self, "Select Image Asset Folder", current)
        if selected_dir:
            self.txt_path.setText(selected_dir)

    def _set_folder_preset(self, relative_or_absolute: str):
        """Apply a preset shortcut path."""
        p = Path(relative_or_absolute)
        if not p.is_absolute():
            p = ROOT_DIR / p
        self.txt_path.setText(str(p.resolve()))

    def append_log(self, action: str, message: str, level: str = "info"):
        """Add formatted timestamped log message."""
        time_str = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{time_str}] [{action}]"
        self.log_view.appendPlainText(f"{prefix} {message}")

    def start_scan(self):
        """Initiate background folder scanning thread."""
        folder_str = self.txt_path.text().strip()
        folder = Path(folder_str)

        if not folder.exists() or not folder.is_dir():
            QMessageBox.warning(
                self,
                "Invalid Directory",
                f"The selected folder does not exist or is not a directory:\n\n{folder_str}\n\nPlease choose a valid path."
            )
            return

        # Disable start, enable cancel
        self.btn_start.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        recursive = self.chk_recursive.isChecked()
        coll_override = self.cmb_collection.currentData()

        self.table.setRowCount(0)
        self.imported_assets.clear()
        self.progress_bar.setValue(0)
        self.lbl_progress_status.setText(f"Scanning folder: {folder.name}...")

        # Initialize background worker thread
        self.worker = ScanWorker(
            folder_path=str(folder),
            recursive=recursive,
            collection_override=coll_override
        )
        self.worker.scan_started.connect(self._on_scan_started)
        self.worker.progress.connect(self._on_scan_progress)
        self.worker.asset_imported.connect(self._on_asset_imported)
        self.worker.log_message.connect(self.append_log)
        self.worker.scan_finished.connect(self._on_scan_finished)
        self.worker.scan_error.connect(self._on_scan_error)
        self.worker.start()

    def cancel_scan(self):
        """Request graceful halt of background scanner."""
        if self.worker and self.worker.isRunning():
            self.lbl_progress_status.setText("Cancelling scan...")
            self.worker.request_cancel()
            self.btn_cancel.setEnabled(False)

    def _on_scan_started(self, total_files: int):
        self.lbl_file_counts.setText(f"0 / {total_files} images")
        self.append_log("Scan Started", f"Found {total_files} candidate image files.")

    def _on_scan_progress(self, current: int, total: int, filename: str):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.lbl_file_counts.setText(f"{current} / {total} images ({pct}%)")
        self.lbl_current_file.setText(f"Indexing: {filename}")

    def _on_asset_imported(self, asset: Dict[str, Any]):
        """Append newly indexed asset into table view."""
        self.imported_assets.append(asset)
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(str(asset["id"])))
        self.table.setItem(row, 1, QTableWidgetItem(asset["filename"]))
        self.table.setItem(row, 2, QTableWidgetItem(asset["collection"].replace("_", " ").title()))
        dim_str = f"{asset['width']} × {asset['height']}" if asset['width'] else "—"
        self.table.setItem(row, 3, QTableWidgetItem(dim_str))
        self.table.setItem(row, 4, QTableWidgetItem(format_bytes(asset["file_size"])))
        self.table.setItem(row, 5, QTableWidgetItem(asset["status"].capitalize()))

        # Auto-scroll to latest
        self.table.scrollToBottom()

    def _on_scan_finished(self, summary: Dict[str, Any]):
        """Handler for scan completion."""
        self.btn_start.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_current_file.setText("Scan completed.")
        self.lbl_progress_status.setText(
            f"Done! {summary['new_imported']} new imported, {summary['updated']} updated, {summary['errors']} errors."
        )
        self.import_completed.emit(summary)

    def _on_scan_error(self, err_msg: str):
        """Handler for scanner errors."""
        self.btn_start.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_progress_status.setText("Scan failed with error.")
        self.append_log("Error", err_msg, "error")
        QMessageBox.critical(self, "Scan Error", err_msg)

    def _on_table_row_clicked(self, row: int, col: int):
        """Transmit selected asset to inspector."""
        if 0 <= row < len(self.imported_assets):
            self.asset_selected.emit(self.imported_assets[row])
