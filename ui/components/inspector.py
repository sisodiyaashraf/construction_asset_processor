"""
Right Inspector Component
Inspects the currently selected image asset, displays full metadata,
renders high-resolution cached thumbnail preview, and provides quick actions.
Never modifies original source files.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QClipboard, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db, format_bytes


class ImageInspector(QWidget):
    """Right-side image inspector displaying metadata and image preview."""

    asset_status_updated = Signal(int, str)  # asset_id, new_status
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspector")
        self.current_asset: Optional[Dict[str, Any]] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # Header with Close Button
        header_layout = QHBoxLayout()
        header_title = QLabel("ASSET INSPECTOR")
        header_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        header_layout.addWidget(header_title)
        header_layout.addStretch()

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet(f"""
            border: none;
            color: {THEME_COLORS['text_secondary']};
            font-weight: bold;
            font-size: 13px;
            background: transparent;
        """)
        self.btn_close.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(self.btn_close)

        main_layout.addLayout(header_layout)

        # Scroll area for inspector body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(14)

        # Thumbnail Container
        self.preview_frame = QFrame()
        self.preview_frame.setProperty("class", "card")
        self.preview_frame.setFixedHeight(210)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setAlignment(Qt.AlignCenter)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background: transparent;")
        preview_layout.addWidget(self.preview_label)

        self.content_layout.addWidget(self.preview_frame)

        # Metadata Card
        meta_card = QFrame()
        meta_card.setProperty("class", "card")
        meta_layout = QGridLayout(meta_card)
        meta_layout.setContentsMargins(12, 12, 12, 12)
        meta_layout.setSpacing(8)

        # Metadata Labels
        self.labels: Dict[str, QLabel] = {}
        fields = [
            ("Filename", "lbl_filename"),
            ("Collection", "lbl_collection"),
            ("Dimensions", "lbl_dimensions"),
            ("Aspect Ratio", "lbl_aspect"),
            ("File Size", "lbl_size"),
            ("Format", "lbl_format"),
            ("Color Mode", "lbl_color"),
            ("Transparency", "lbl_transparency"),
            ("Status", "lbl_status"),
            ("SHA-256", "lbl_hash"),
            ("Full Path", "lbl_path"),
        ]

        for row, (label_text, key) in enumerate(fields):
            lbl_name = QLabel(label_text)
            lbl_name.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 12px; font-weight: 500;")
            lbl_val = QLabel("—")
            lbl_val.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-size: 12px; font-weight: 600;")
            lbl_val.setWordWrap(True)
            self.labels[key] = lbl_val

            meta_layout.addWidget(lbl_name, row, 0)
            meta_layout.addWidget(lbl_val, row, 1)

        self.content_layout.addWidget(meta_card)

        # Review & Status Actions Card
        review_card = QFrame()
        review_card.setProperty("class", "card")
        review_layout = QVBoxLayout(review_card)
        review_layout.setContentsMargins(12, 12, 12, 12)
        review_layout.setSpacing(8)

        rev_title = QLabel("REVIEW ACTIONS")
        rev_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']}; letter-spacing: 0.5px;")
        review_layout.addWidget(rev_title)

        status_btns_row = QHBoxLayout()
        status_btns_row.setSpacing(6)

        self.btn_approve = QPushButton("✓ Approve")
        self.btn_approve.setProperty("class", "btn_primary")
        self.btn_approve.setCursor(Qt.PointingHandCursor)
        self.btn_approve.clicked.connect(self._mark_approved)
        status_btns_row.addWidget(self.btn_approve)

        self.btn_pending = QPushButton("⏳ Pending")
        self.btn_pending.setProperty("class", "btn_secondary")
        self.btn_pending.setCursor(Qt.PointingHandCursor)
        self.btn_pending.clicked.connect(self._mark_pending)
        status_btns_row.addWidget(self.btn_pending)

        self.btn_reject = QPushButton("✕ Reject")
        self.btn_reject.setProperty("class", "btn_danger")
        self.btn_reject.setCursor(Qt.PointingHandCursor)
        self.btn_reject.clicked.connect(self._mark_rejected)
        status_btns_row.addWidget(self.btn_reject)

        review_layout.addLayout(status_btns_row)
        self.content_layout.addWidget(review_card)

        # File Operations Actions Card
        file_card = QFrame()
        file_card.setProperty("class", "card")
        file_layout = QVBoxLayout(file_card)
        file_layout.setContentsMargins(12, 12, 12, 12)
        file_layout.setSpacing(8)

        file_title = QLabel("FILE ACTIONS")
        file_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['accent_primary']}; letter-spacing: 0.5px;")
        file_layout.addWidget(file_title)

        self.btn_open_image = QPushButton("🖼️ Open Original Image")
        self.btn_open_image.setProperty("class", "btn_secondary")
        self.btn_open_image.setCursor(Qt.PointingHandCursor)
        self.btn_open_image.clicked.connect(self._open_original_image)
        file_layout.addWidget(self.btn_open_image)

        self.btn_open_folder = QPushButton("📁 Open Containing Folder")
        self.btn_open_folder.setProperty("class", "btn_secondary")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.clicked.connect(self._open_in_explorer)
        file_layout.addWidget(self.btn_open_folder)

        self.btn_copy_path = QPushButton("📋 Copy Full Path")
        self.btn_copy_path.setProperty("class", "btn_secondary")
        self.btn_copy_path.setCursor(Qt.PointingHandCursor)
        self.btn_copy_path.clicked.connect(self._copy_path)
        file_layout.addWidget(self.btn_copy_path)

        self.content_layout.addWidget(file_card)
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

        # Show empty state initially
        self.clear()

    def clear(self):
        """Reset inspector to empty placeholder state."""
        self.current_asset = None
        self.preview_label.setText("No Asset Selected\n\nClick an image card or row to inspect.")
        self.preview_label.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 12px; text-align: center;")
        self.preview_label.setPixmap(QPixmap())
        for lbl in self.labels.values():
            lbl.setText("—")
            lbl.setToolTip("")
        self.btn_approve.setEnabled(False)
        self.btn_pending.setEnabled(False)
        self.btn_reject.setEnabled(False)
        self.btn_open_image.setEnabled(False)
        self.btn_open_folder.setEnabled(False)
        self.btn_copy_path.setEnabled(False)

    def inspect_asset(self, asset: Dict[str, Any]):
        """Load asset record into the inspector."""
        self.current_asset = asset
        orig_path = asset.get("original_path", "")
        self.labels["lbl_filename"].setText(asset.get("filename", "Unknown"))
        self.labels["lbl_filename"].setToolTip(orig_path)
        
        # Path
        if orig_path:
            p = Path(orig_path)
            elided_path = f".../{p.parent.name}/{p.name}" if len(orig_path) > 30 else orig_path
            self.labels["lbl_path"].setText(elided_path)
            self.labels["lbl_path"].setToolTip(orig_path)
        else:
            self.labels["lbl_path"].setText("—")

        self.labels["lbl_collection"].setText(asset.get("collection", "other_images").replace("_", " ").title())
        self.labels["lbl_dimensions"].setText(f"{asset.get('width', 0)} × {asset.get('height', 0)} px")
        self.labels["lbl_aspect"].setText(f"{asset.get('aspect_ratio', 0.0)}:1")
        self.labels["lbl_size"].setText(format_bytes(asset.get("file_size", 0)))
        self.labels["lbl_format"].setText(str(asset.get("format", "PNG")).upper())
        self.labels["lbl_color"].setText(str(asset.get("color_mode", "RGB")))
        
        has_trans = "Yes (Alpha)" if asset.get("has_transparency", 0) else "No (Opaque)"
        self.labels["lbl_transparency"].setText(has_trans)

        status = str(asset.get("status", "pending")).capitalize()
        status_color = THEME_COLORS['status_success'] if status == "Approved" else (
            THEME_COLORS['status_error'] if status == "Rejected" else (
                THEME_COLORS['accent_primary'] if status == "Processed" else THEME_COLORS['status_warning']
            )
        )
        self.labels["lbl_status"].setText(f"<font color='{status_color}'>{status}</font>")

        # SHA-256 Hash
        fhash = asset.get("file_hash", "")
        if fhash:
            self.labels["lbl_hash"].setText(f"{fhash[:12]}…")
            self.labels["lbl_hash"].setToolTip(fhash)
        else:
            self.labels["lbl_hash"].setText("—")

        # Load Preview Thumbnail
        thumb_path = asset.get("thumbnail_path")
        pixmap = None
        if thumb_path and Path(thumb_path).exists():
            pixmap = QPixmap(thumb_path)
        elif orig_path and Path(orig_path).exists():
            pixmap = QPixmap(orig_path)

        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(240, 190, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_label.setPixmap(scaled)
        else:
            self.preview_label.setText("Preview Unavailable")
            self.preview_label.setPixmap(QPixmap())

        self.btn_approve.setEnabled(True)
        self.btn_pending.setEnabled(True)
        self.btn_reject.setEnabled(True)
        self.btn_open_image.setEnabled(True)
        self.btn_open_folder.setEnabled(True)
        self.btn_copy_path.setEnabled(True)

    def _mark_approved(self):
        if self.current_asset:
            asset_id = self.current_asset["id"]
            db.update_asset_status(asset_id, "approved")
            self.current_asset["status"] = "approved"
            self.inspect_asset(self.current_asset)
            self.asset_status_updated.emit(asset_id, "approved")

    def _mark_pending(self):
        if self.current_asset:
            asset_id = self.current_asset["id"]
            db.update_asset_status(asset_id, "pending")
            self.current_asset["status"] = "pending"
            self.inspect_asset(self.current_asset)
            self.asset_status_updated.emit(asset_id, "pending")

    def _mark_rejected(self):
        if self.current_asset:
            asset_id = self.current_asset["id"]
            db.update_asset_status(asset_id, "rejected")
            self.current_asset["status"] = "rejected"
            self.inspect_asset(self.current_asset)
            self.asset_status_updated.emit(asset_id, "rejected")

    def _open_original_image(self):
        """Open the original image in OS default photo viewer."""
        if self.current_asset:
            path = self.current_asset.get("original_path")
            if path and os.path.exists(path):
                try:
                    os.startfile(os.path.normpath(path))
                except Exception as e:
                    subprocess.run(["explorer", os.path.normpath(path)], check=False)

    def _open_in_explorer(self):
        """Open containing folder in explorer and select the file."""
        if self.current_asset:
            path = self.current_asset.get("original_path")
            if path and os.path.exists(path):
                subprocess.run(["explorer", "/select,", os.path.normpath(path)], check=False)

    def _copy_path(self):
        """Copy full file path to system clipboard."""
        if self.current_asset:
            path = self.current_asset.get("original_path", "")
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(path, QClipboard.Clipboard)
