"""
Dashboard View
Construction Asset Processor
Displays real database statistics: total assets, storage footprints,
collection counts, review statuses, and recent scan logs.
"""

from typing import Any, Dict
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db, format_bytes
from ui.components.stat_card import StatCard


class DashboardView(QWidget):
    """Main dashboard screen with 8 live metric cards and real database summaries."""

    navigate_to_import = Signal()
    navigate_to_gallery = Signal()
    asset_selected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Scroll Area for comfortable high-DPI scaling
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        # Header Section
        header_row = QHBoxLayout()
        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(4)

        title = QLabel("CONSTRUCTION ASSET DASHBOARD")
        title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 700;
            color: {THEME_COLORS['text_primary']};
            letter-spacing: 0.5px;
        """)
        header_text_layout.addWidget(title)

        subtitle = QLabel("2D Side-View Simulator Asset Pipeline • Real Database Telemetry")
        subtitle.setStyleSheet(f"font-size: 13px; color: {THEME_COLORS['text_secondary']};")
        header_text_layout.addWidget(subtitle)
        header_row.addLayout(header_text_layout)

        header_row.addStretch()

        btn_gallery_shortcut = QPushButton("🖼️ View Gallery")
        btn_gallery_shortcut.setProperty("class", "btn_primary")
        btn_gallery_shortcut.setCursor(Qt.PointingHandCursor)
        btn_gallery_shortcut.clicked.connect(self.navigate_to_gallery.emit)
        header_row.addWidget(btn_gallery_shortcut)

        btn_import_shortcut = QPushButton("📥 Import Assets")
        btn_import_shortcut.setProperty("class", "btn_secondary")
        btn_import_shortcut.setCursor(Qt.PointingHandCursor)
        btn_import_shortcut.clicked.connect(self.navigate_to_import.emit)
        header_row.addWidget(btn_import_shortcut)

        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.setProperty("class", "btn_secondary")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.reload_data)
        header_row.addWidget(btn_refresh)

        layout.addLayout(header_row)

        # 8 Core Metric Cards Grid
        grid = QGridLayout()
        grid.setSpacing(14)

        # Row 0: Inventory & Storage
        self.card_total = StatCard("Total Images", "0", "Indexed in catalog", "🖼️")
        self.card_size = StatCard("Storage Size", "0 B", "Uncompressed source files", "💾")
        self.card_excavator = StatCard("Excavator Collection", "0", "Primary vehicle assets", "🚜")
        self.card_other = StatCard("Other Game Images", "0", "Props, environment & UI", "🧱")

        grid.addWidget(self.card_total, 0, 0)
        grid.addWidget(self.card_size, 0, 1)
        grid.addWidget(self.card_excavator, 0, 2)
        grid.addWidget(self.card_other, 0, 3)

        # Row 1: Processing & Workflow States
        self.card_processed = StatCard("Images Processed", "0", "Completed stages", "⚡")
        self.card_pending = StatCard("Pending Review", "0", "Awaiting inspection", "⏳", accent_color=THEME_COLORS['status_warning'])
        self.card_approved = StatCard("Approved Assets", "0", "Ready for Flame engine", "✅", accent_color=THEME_COLORS['status_success'])
        self.card_progress = StatCard("Processing Progress", "0.0%", "Pipeline completion", "📈", show_progress=True)

        grid.addWidget(self.card_processed, 1, 0)
        grid.addWidget(self.card_pending, 1, 1)
        grid.addWidget(self.card_approved, 1, 2)
        grid.addWidget(self.card_progress, 1, 3)

        layout.addLayout(grid)

        # Middle Row: Detailed Breakdown Cards
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(14)

        # Collection & Format Summary Card
        format_card = QFrame()
        format_card.setProperty("class", "card")
        format_vbox = QVBoxLayout(format_card)
        format_vbox.setContentsMargins(16, 14, 16, 14)
        format_vbox.setSpacing(10)

        format_title = QLabel("FORMAT & COLLECTION BREAKDOWN")
        format_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
            letter-spacing: 0.5px;
        """)
        format_vbox.addWidget(format_title)

        self.lbl_format_breakdown = QLabel("No images cataloged yet.")
        self.lbl_format_breakdown.setStyleSheet(f"font-size: 13px; color: {THEME_COLORS['text_secondary']};")
        self.lbl_format_breakdown.setWordWrap(True)
        format_vbox.addWidget(self.lbl_format_breakdown)

        self.lbl_collection_breakdown = QLabel("")
        self.lbl_collection_breakdown.setStyleSheet(f"font-size: 13px; color: {THEME_COLORS['text_secondary']};")
        self.lbl_collection_breakdown.setWordWrap(True)
        format_vbox.addWidget(self.lbl_collection_breakdown)

        format_vbox.addStretch()
        middle_layout.addWidget(format_card, stretch=1)

        # Recent Scans Table Card
        history_card = QFrame()
        history_card.setProperty("class", "card")
        history_vbox = QVBoxLayout(history_card)
        history_vbox.setContentsMargins(16, 14, 16, 14)
        history_vbox.setSpacing(10)

        history_title = QLabel("RECENT FOLDER SCANS")
        history_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
            letter-spacing: 0.5px;
        """)
        history_vbox.addWidget(history_title)

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(4)
        self.table_history.setHorizontalHeaderLabels(["Folder Path", "Scanned", "New Added", "Size"])
        self.table_history.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_history.verticalHeader().setVisible(False)
        self.table_history.setFixedHeight(140)
        history_vbox.addWidget(self.table_history)

        middle_layout.addWidget(history_card, stretch=2)
        layout.addLayout(middle_layout)

        # Quick Overview Table (Sample Assets)
        assets_card = QFrame()
        assets_card.setProperty("class", "card")
        assets_vbox = QVBoxLayout(assets_card)
        assets_vbox.setContentsMargins(16, 14, 16, 14)
        assets_vbox.setSpacing(10)

        assets_header_row = QHBoxLayout()
        assets_title = QLabel("CATALOG OVERVIEW (RECENT ASSETS)")
        assets_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
            letter-spacing: 0.5px;
        """)
        assets_header_row.addWidget(assets_title)
        assets_header_row.addStretch()

        lbl_hint = QLabel("Click any asset to inspect on the right panel")
        lbl_hint.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        assets_header_row.addWidget(lbl_hint)
        assets_vbox.addLayout(assets_header_row)

        self.table_assets = QTableWidget()
        self.table_assets.setColumnCount(6)
        self.table_assets.setHorizontalHeaderLabels(["ID", "Filename", "Collection", "Dimensions", "Size", "Status"])
        self.table_assets.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in [0, 2, 3, 4, 5]:
            self.table_assets.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table_assets.verticalHeader().setVisible(False)
        self.table_assets.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_assets.setSelectionMode(QTableWidget.SingleSelection)
        self.table_assets.setFixedHeight(220)
        self.table_assets.cellClicked.connect(self._on_asset_clicked)
        assets_vbox.addWidget(self.table_assets)

        layout.addWidget(assets_card)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # Initial data load
        self.reload_data()

    def reload_data(self):
        """Fetch fresh values from SQLite and update cards."""
        stats = db.get_dashboard_stats()

        # Update 8 stat cards with real database values
        self.card_total.update_data(
            str(stats["total_images"]),
            f"{stats['total_images']} assets cataloged"
        )
        self.card_size.update_data(
            stats["total_storage_formatted"],
            "Total disk footprint"
        )
        self.card_excavator.update_data(
            str(stats["excavator_images"]),
            f"Size: {stats['excavator_size_formatted']}"
        )
        self.card_other.update_data(
            str(stats["other_game_images"]),
            f"Size: {stats['other_size_formatted']}"
        )
        self.card_processed.update_data(
            str(stats["images_processed"]),
            f"{stats['images_processed']} assets completed"
        )
        self.card_pending.update_data(
            str(stats["images_pending_review"]),
            f"{stats['images_pending_review']} awaiting review"
        )
        self.card_approved.update_data(
            str(stats["approved_assets"]),
            f"{stats['approved_assets']} engine approved"
        )
        self.card_progress.update_data(
            f"{stats['processing_progress']:.1f}%",
            f"{stats['approved_assets'] + stats['images_processed']} of {stats['total_images']} processed",
            progress=int(stats["processing_progress"])
        )

        # Update Format Breakdown Text
        formats = stats["format_breakdown"]
        if formats:
            format_lines = [f"• <b>{fmt}</b>: {count} images ({round(count/stats['total_images']*100, 1)}%)" for fmt, count in formats.items()]
            self.lbl_format_breakdown.setText("<br>".join(format_lines))
        else:
            self.lbl_format_breakdown.setText("No format data yet. Use Asset Import to index files.")

        # Update Collection Details & AI Telemetry
        ai_stats = db.get_classification_stats()
        self.lbl_collection_breakdown.setText(
            f"<b>Excavator:</b> {stats['excavator_images']} images ({stats['excavator_size_formatted']})<br>"
            f"<b>Other Game:</b> {stats['other_game_images']} images ({stats['other_size_formatted']})<br>"
            f"<b>AI Classified:</b> {ai_stats['analyzed_images']}/{ai_stats['total_images']} ({ai_stats['successfully_classified']} high confidence)"
        )

        # Populate Recent Scans Table
        recent_scans = db.get_recent_scans(limit=5)
        self.table_history.setRowCount(len(recent_scans))
        for row_idx, scan in enumerate(recent_scans):
            self.table_history.setItem(row_idx, 0, QTableWidgetItem(str(scan["folder_path"])))
            self.table_history.setItem(row_idx, 1, QTableWidgetItem(str(scan["scanned_count"])))
            self.table_history.setItem(row_idx, 2, QTableWidgetItem(str(scan["new_imported_count"])))
            self.table_history.setItem(row_idx, 3, QTableWidgetItem(format_bytes(scan["total_bytes"])))

        # Populate Catalog Table (Latest 15 assets)
        recent_assets = db.get_assets(limit=15, sort_by="id", ascending=False)
        self.table_assets.setRowCount(len(recent_assets))
        self._cached_assets = recent_assets
        for row_idx, asset in enumerate(recent_assets):
            self.table_assets.setItem(row_idx, 0, QTableWidgetItem(str(asset["id"])))
            self.table_assets.setItem(row_idx, 1, QTableWidgetItem(asset["filename"]))
            self.table_assets.setItem(row_idx, 2, QTableWidgetItem(asset["collection"].replace("_", " ").title()))
            dim_str = f"{asset['width']} × {asset['height']}" if asset['width'] else "—"
            self.table_assets.setItem(row_idx, 3, QTableWidgetItem(dim_str))
            self.table_assets.setItem(row_idx, 4, QTableWidgetItem(format_bytes(asset["file_size"])))
            self.table_assets.setItem(row_idx, 5, QTableWidgetItem(asset["status"].capitalize()))

    def _on_asset_clicked(self, row: int, col: int):
        """Transmit selected asset dictionary to the right inspector."""
        if hasattr(self, "_cached_assets") and 0 <= row < len(self._cached_assets):
            self.asset_selected.emit(self._cached_assets[row])
