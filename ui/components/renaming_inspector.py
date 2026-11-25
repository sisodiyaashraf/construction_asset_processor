"""
Smart Renaming Inspector Component
Dedicated right-side panel for inspecting, modifying, generating,
and approving standardized filenames for individual assets.
Never modifies original files on disk directly from this panel.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db
from core.naming_engine import clean_filename, naming_engine

logger = logging.getLogger("AssetProcessor.RenamingInspector")


class RenamingInspector(QWidget):
    """Right-side inspector dedicated to reviewing and editing smart filenames."""

    name_approved = Signal(int, str)
    name_saved = Signal(int, str)
    name_rejected = Signal(int)
    name_regenerated = Signal(int)
    name_restored = Signal(int)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("renaming_inspector")
        self.current_asset: Optional[Dict[str, Any]] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Header with Close Button
        header_layout = QHBoxLayout()
        header_title = QLabel("SMART RENAMING INSPECTOR")
        header_title.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        header_layout.addWidget(header_title)
        header_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(22, 22)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            border: none;
            color: {THEME_COLORS['text_secondary']};
            font-weight: bold;
            font-size: 12px;
            background: transparent;
        """)
        btn_close.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(btn_close)
        main_layout.addLayout(header_layout)

        # Scroll area for body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)

        # 1. Preview Container
        self.preview_frame = QFrame()
        self.preview_frame.setProperty("class", "card")
        self.preview_frame.setFixedHeight(180)
        p_layout = QVBoxLayout(self.preview_frame)
        p_layout.setContentsMargins(4, 4, 4, 4)
        p_layout.setAlignment(Qt.AlignCenter)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background: transparent;")
        p_layout.addWidget(self.preview_label)
        self.content_layout.addWidget(self.preview_frame)

        # 2. Collision Warning / Status Banner
        self.status_banner = QFrame()
        self.status_banner.setProperty("class", "card")
        self.status_banner_layout = QVBoxLayout(self.status_banner)
        self.status_banner_layout.setContentsMargins(10, 8, 10, 8)
        self.status_banner_layout.setSpacing(4)

        self.status_label = QLabel("Status: Pending Review")
        self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['accent_primary']};")
        self.conflict_label = QLabel("")
        self.conflict_label.setStyleSheet("font-size: 10px; color: #EF4444;")
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setVisible(False)

        self.status_banner_layout.addWidget(self.status_label)
        self.status_banner_layout.addWidget(self.conflict_label)
        self.content_layout.addWidget(self.status_banner)

        # 3. Filename Details Card
        fn_card = QFrame()
        fn_card.setProperty("class", "card")
        fn_vbox = QVBoxLayout(fn_card)
        fn_vbox.setContentsMargins(12, 10, 12, 10)
        fn_vbox.setSpacing(8)

        lbl_sec1 = QLabel("FILENAME CONFIGURATION")
        lbl_sec1.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']}; letter-spacing: 0.5px;")
        fn_vbox.addWidget(lbl_sec1)

        # Original Filename
        fn_vbox.addWidget(QLabel("Original Filename:"))
        self.lbl_orig_name = QLabel("—")
        self.lbl_orig_name.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']}; background: #131720; padding: 4px 6px; border-radius: 4px;")
        self.lbl_orig_name.setWordWrap(True)
        fn_vbox.addWidget(self.lbl_orig_name)

        # Original Path
        fn_vbox.addWidget(QLabel("Original Path:"))
        self.lbl_orig_path = QLabel("—")
        self.lbl_orig_path.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']}; background: #131720; padding: 4px 6px; border-radius: 4px;")
        self.lbl_orig_path.setWordWrap(True)
        fn_vbox.addWidget(self.lbl_orig_path)

        # Proposed Filename (Editable)
        fn_vbox.addWidget(QLabel("Proposed Filename (Editable):"))
        self.edit_proposed_name = QLineEdit()
        self.edit_proposed_name.setPlaceholderText("e.g. excavator_yellow_side_view.png")
        self.edit_proposed_name.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            border-radius: 4px;
            color: {THEME_COLORS['text_primary']};
            padding: 6px;
            font-size: 12px;
            font-weight: 600;
        """)
        self.edit_proposed_name.textChanged.connect(self._on_name_text_changed)
        fn_vbox.addWidget(self.edit_proposed_name)

        # Proposed Destination Path
        fn_vbox.addWidget(QLabel("Proposed Destination Path:"))
        self.lbl_dest_path = QLabel("—")
        self.lbl_dest_path.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['status_info']}; background: #131720; padding: 4px 6px; border-radius: 4px;")
        self.lbl_dest_path.setWordWrap(True)
        fn_vbox.addWidget(self.lbl_dest_path)

        self.content_layout.addWidget(fn_card)

        # 4. Context Metadata Card
        meta_card = QFrame()
        meta_card.setProperty("class", "card")
        meta_grid = QGridLayout(meta_card)
        meta_grid.setContentsMargins(12, 10, 12, 10)
        meta_grid.setHorizontalSpacing(10)
        meta_grid.setVerticalSpacing(6)

        lbl_sec2 = QLabel("CLASSIFICATION CONTEXT")
        lbl_sec2.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']}; letter-spacing: 0.5px;")
        meta_grid.addWidget(lbl_sec2, 0, 0, 1, 2)

        meta_grid.addWidget(QLabel("Category:"), 1, 0)
        self.lbl_category = QLabel("—")
        self.lbl_category.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 500;")
        meta_grid.addWidget(self.lbl_category, 1, 1)

        meta_grid.addWidget(QLabel("Subcategory:"), 2, 0)
        self.lbl_subcat = QLabel("—")
        self.lbl_subcat.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 500;")
        meta_grid.addWidget(self.lbl_subcat, 2, 1)

        meta_grid.addWidget(QLabel("Composition:"), 3, 0)
        self.lbl_comp = QLabel("—")
        self.lbl_comp.setStyleSheet(f"color: {THEME_COLORS['text_secondary']};")
        meta_grid.addWidget(self.lbl_comp, 3, 1)

        meta_grid.addWidget(QLabel("Confidence:"), 4, 0)
        self.lbl_confidence = QLabel("—")
        self.lbl_confidence.setStyleSheet(f"color: {THEME_COLORS['accent_primary']}; font-weight: 600;")
        meta_grid.addWidget(self.lbl_confidence, 4, 1)

        self.content_layout.addWidget(meta_card)

        # 5. Action Buttons
        act_card = QFrame()
        act_card.setProperty("class", "card")
        act_vbox = QVBoxLayout(act_card)
        act_vbox.setContentsMargins(12, 10, 12, 10)
        act_vbox.setSpacing(8)

        lbl_sec3 = QLabel("ACTIONS")
        lbl_sec3.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']}; letter-spacing: 0.5px;")
        act_vbox.addWidget(lbl_sec3)

        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(6)
        self.btn_gen_name = QPushButton("Generate Name")
        self.btn_gen_name.setCursor(Qt.PointingHandCursor)
        self.btn_gen_name.setStyleSheet(f"background: #1E293B; color: {THEME_COLORS['accent_primary']}; border: 1px solid #334155; padding: 6px; font-size: 11px; border-radius: 4px;")
        self.btn_gen_name.clicked.connect(self._on_regenerate_clicked)
        btn_row1.addWidget(self.btn_gen_name)

        self.btn_restore = QPushButton("Restore Original")
        self.btn_restore.setCursor(Qt.PointingHandCursor)
        self.btn_restore.setStyleSheet(f"background: #1E293B; color: {THEME_COLORS['text_secondary']}; border: 1px solid #334155; padding: 6px; font-size: 11px; border-radius: 4px;")
        self.btn_restore.clicked.connect(self._on_restore_clicked)
        btn_row1.addWidget(self.btn_restore)
        act_vbox.addLayout(btn_row1)

        self.btn_save_manual = QPushButton("Save Manual Name")
        self.btn_save_manual.setCursor(Qt.PointingHandCursor)
        self.btn_save_manual.setStyleSheet(f"background: #10B981; color: white; border: none; padding: 7px; font-size: 11px; font-weight: 600; border-radius: 4px;")
        self.btn_save_manual.clicked.connect(self._on_save_manual_clicked)
        act_vbox.addWidget(self.btn_save_manual)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(6)
        self.btn_approve = QPushButton("Approve Name")
        self.btn_approve.setCursor(Qt.PointingHandCursor)
        self.btn_approve.setStyleSheet(f"background: {THEME_COLORS['accent_primary']}; color: #0D1117; font-weight: 700; border: none; padding: 7px; font-size: 11px; border-radius: 4px;")
        self.btn_approve.clicked.connect(self._on_approve_clicked)
        btn_row2.addWidget(self.btn_approve)

        self.btn_reject = QPushButton("Reject Suggestion")
        self.btn_reject.setCursor(Qt.PointingHandCursor)
        self.btn_reject.setStyleSheet("background: #EF4444; color: white; font-weight: 600; border: none; padding: 7px; font-size: 11px; border-radius: 4px;")
        self.btn_reject.clicked.connect(self._on_reject_clicked)
        btn_row2.addWidget(self.btn_reject)
        act_vbox.addLayout(btn_row2)

        self.content_layout.addWidget(act_card)
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def load_asset(self, asset: Dict[str, Any]) -> None:
        """Populate the inspector fields with asset details."""
        self.current_asset = asset
        asset_id = asset.get("id")

        # 1. Preview
        thumb_path = asset.get("thumbnail_path")
        orig_path = asset.get("current_path") or asset.get("original_path")
        pix = None

        if thumb_path and Path(thumb_path).exists():
            pix = QPixmap(str(thumb_path))
        elif orig_path and Path(orig_path).exists():
            pix = QPixmap(str(orig_path))

        if pix and not pix.isNull():
            scaled = pix.scaled(
                self.preview_frame.width() - 10,
                self.preview_frame.height() - 10,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)
        else:
            self.preview_label.setText("No Preview")

        # 2. Filenames and Paths
        orig_name = asset.get("filename", "")
        self.lbl_orig_name.setText(orig_name)
        self.lbl_orig_path.setText(str(orig_path))

        sug_name = asset.get("approved_filename") or asset.get("suggested_filename") or ""
        if not sug_name:
            sug_name = naming_engine.generate_name_for_asset(asset)

        self.edit_proposed_name.blockSignals(True)
        self.edit_proposed_name.setText(sug_name)
        self.edit_proposed_name.blockSignals(False)

        parent_dir = Path(orig_path).parent if orig_path else Path("output")
        self.lbl_dest_path.setText(str(parent_dir / sug_name))

        # 3. Status and Conflict
        status = asset.get("naming_status", "pending")
        conflict = bool(asset.get("naming_conflict", 0))

        status_colors = {
            "approved": "#10B981",
            "pending": THEME_COLORS["accent_primary"],
            "conflict": "#EF4444",
            "manual": "#38BDF8",
            "rejected": "#64748B",
        }
        color = status_colors.get(status, THEME_COLORS["accent_primary"])
        self.status_label.setText(f"Status: {status.upper()}")
        self.status_label.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {color};")

        if conflict:
            self.conflict_label.setText("⚠ Naming collision detected. Numbered suffix assigned.")
            self.conflict_label.setVisible(True)
        else:
            self.conflict_label.setVisible(False)

        # 4. Context Metadata
        self.lbl_category.setText(asset.get("main_category") or "Unclassified")
        self.lbl_subcat.setText(asset.get("subcategory") or "—")
        self.lbl_comp.setText(asset.get("composition_type") or "Single Object")
        conf_score = asset.get("confidence_score", 0.0)
        self.lbl_confidence.setText(f"{int(float(conf_score) * 100)}%")

    def _on_name_text_changed(self, text: str) -> None:
        """Update destination path preview live as user edits."""
        if not self.current_asset:
            return
        orig_path = self.current_asset.get("current_path") or self.current_asset.get("original_path")
        parent_dir = Path(orig_path).parent if orig_path else Path("output")
        self.lbl_dest_path.setText(str(parent_dir / text.strip()))

    def _on_regenerate_clicked(self) -> None:
        """Regenerate smart filename using engine."""
        if not self.current_asset:
            return
        new_name = naming_engine.generate_name_for_asset(self.current_asset)
        self.edit_proposed_name.setText(new_name)
        self.name_regenerated.emit(self.current_asset["id"])

    def _on_restore_clicked(self) -> None:
        """Reset proposed name to original filename."""
        if not self.current_asset:
            return
        orig_name = self.current_asset.get("filename", "")
        self.edit_proposed_name.setText(orig_name)
        self.name_restored.emit(self.current_asset["id"])

    def _on_save_manual_clicked(self) -> None:
        """Commit manually edited name to database."""
        if not self.current_asset:
            return
        asset_id = self.current_asset["id"]
        raw_text = self.edit_proposed_name.text().strip()
        ext = Path(self.current_asset.get("filename", "")).suffix
        clean_name = clean_filename(Path(raw_text).stem, ext)

        db.update_naming(
            asset_id=asset_id,
            suggested_filename=clean_name,
            approved_filename=clean_name,
            naming_status="manual",
            naming_conflict=0
        )
        self.status_label.setText("Status: MANUAL")
        self.status_label.setStyleSheet("font-size: 11px; font-weight: 700; color: #38BDF8;")
        self.conflict_label.setVisible(False)
        self.name_saved.emit(asset_id, clean_name)

    def _on_approve_clicked(self) -> None:
        """Approve proposed filename."""
        if not self.current_asset:
            return
        asset_id = self.current_asset["id"]
        raw_text = self.edit_proposed_name.text().strip()
        ext = Path(self.current_asset.get("filename", "")).suffix
        clean_name = clean_filename(Path(raw_text).stem, ext)

        db.update_naming(
            asset_id=asset_id,
            approved_filename=clean_name,
            naming_status="approved",
            naming_conflict=0
        )
        self.status_label.setText("Status: APPROVED")
        self.status_label.setStyleSheet("font-size: 11px; font-weight: 700; color: #10B981;")
        self.conflict_label.setVisible(False)
        self.name_approved.emit(asset_id, clean_name)

    def _on_reject_clicked(self) -> None:
        """Reject proposed filename."""
        if not self.current_asset:
            return
        asset_id = self.current_asset["id"]
        db.update_naming(
            asset_id=asset_id,
            naming_status="rejected"
        )
        self.status_label.setText("Status: REJECTED")
        self.status_label.setStyleSheet("font-size: 11px; font-weight: 700; color: #64748B;")
        self.name_rejected.emit(asset_id)
