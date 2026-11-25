"""
Transparency & Background Removal Inspector Component (Stage 5)
Dedicated right-side panel for inspecting original vs processed transparent assets,
evaluating eligibility, running single background removal, approving/rejecting results,
and opening the Before-and-After Comparison Dialog.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.database import db
from core.transparency_engine import (
    ALL_ELIGIBILITY_LABELS, ELIGIBILITY_ALREADY_TRANSPARENT,
    ELIGIBILITY_POSSIBLY, ELIGIBILITY_PRESERVE_SCENE,
    ELIGIBILITY_SPRITE_SHEET, ELIGIBILITY_SUITABLE,
    ELIGIBILITY_UNKNOWN, transparency_engine
)
from ui.components.comparison_dialog import ComparisonDialog, create_checkerboard_pixmap

logger = logging.getLogger("AssetProcessor.TransparencyInspector")


class TransparencyInspector(QWidget):
    """Right-side inspector dedicated to Stage 5 background removal review and actions."""

    asset_updated = Signal(int)
    compare_requested = Signal(dict)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transparency_inspector")
        self.current_asset: Optional[Dict[str, Any]] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Header with Close Button
        header_layout = QHBoxLayout()
        header_title = QLabel("TRANSPARENCY INSPECTOR")
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

        # 1. Double Preview Card (Original & Transparent on Checkerboard)
        preview_card = QFrame()
        preview_card.setProperty("class", "card")
        pv_layout = QVBoxLayout(preview_card)
        pv_layout.setContentsMargins(8, 8, 8, 8)
        pv_layout.setSpacing(6)

        pv_tabs = QHBoxLayout()
        self.btn_tab_proc = QPushButton("Transparent View")
        self.btn_tab_proc.setCursor(Qt.PointingHandCursor)
        self.btn_tab_proc.setStyleSheet(f"background: {THEME_COLORS['accent_primary']}; color: #0D1117; font-weight: 700; font-size: 10px; padding: 4px 8px; border-radius: 3px;")
        self.btn_tab_proc.clicked.connect(self._show_transparent_preview)
        pv_tabs.addWidget(self.btn_tab_proc)

        self.btn_tab_orig = QPushButton("Original View")
        self.btn_tab_orig.setCursor(Qt.PointingHandCursor)
        self.btn_tab_orig.setStyleSheet("background: #1E293B; color: #94A3B8; font-weight: 600; font-size: 10px; padding: 4px 8px; border-radius: 3px;")
        self.btn_tab_orig.clicked.connect(self._show_original_preview)
        pv_tabs.addWidget(self.btn_tab_orig)
        pv_tabs.addStretch()
        pv_layout.addLayout(pv_tabs)

        self.preview_frame = QFrame()
        self.preview_frame.setFixedHeight(180)
        p_layout = QVBoxLayout(self.preview_frame)
        p_layout.setContentsMargins(2, 2, 2, 2)
        p_layout.setAlignment(Qt.AlignCenter)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        p_layout.addWidget(self.preview_label)
        pv_layout.addWidget(self.preview_frame)

        self.content_layout.addWidget(preview_card)

        # 2. Eligibility & Recommendation Card
        elig_card = QFrame()
        elig_card.setProperty("class", "card")
        elig_vbox = QVBoxLayout(elig_card)
        elig_vbox.setContentsMargins(12, 10, 12, 10)
        elig_vbox.setSpacing(6)

        lbl_sec1 = QLabel("BACKGROUND ELIGIBILITY")
        lbl_sec1.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']}; letter-spacing: 0.5px;")
        elig_vbox.addWidget(lbl_sec1)

        self.combo_eligibility = QComboBox()
        self.combo_eligibility.addItems(ALL_ELIGIBILITY_LABELS)
        self.combo_eligibility.setStyleSheet(f"""
            background: #131720;
            border: 1px solid {THEME_COLORS['border_medium']};
            color: {THEME_COLORS['text_primary']};
            padding: 5px 8px;
            font-size: 11px;
            font-weight: 600;
            border-radius: 4px;
        """)
        self.combo_eligibility.currentTextChanged.connect(self._on_eligibility_changed)
        elig_vbox.addWidget(self.combo_eligibility)

        self.lbl_elig_expl = QLabel("—")
        self.lbl_elig_expl.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']};")
        self.lbl_elig_expl.setWordWrap(True)
        elig_vbox.addWidget(self.lbl_elig_expl)

        self.content_layout.addWidget(elig_card)

        # 3. Processing Metrics & Dimension Audit Card
        audit_card = QFrame()
        audit_card.setProperty("class", "card")
        audit_grid = QGridLayout(audit_card)
        audit_grid.setContentsMargins(12, 10, 12, 10)
        audit_grid.setHorizontalSpacing(10)
        audit_grid.setVerticalSpacing(6)

        lbl_sec2 = QLabel("TRANSPARENCY AUDIT")
        lbl_sec2.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']}; letter-spacing: 0.5px;")
        audit_grid.addWidget(lbl_sec2, 0, 0, 1, 2)

        audit_grid.addWidget(QLabel("Process Status:"), 1, 0)
        self.lbl_proc_status = QLabel("Not Processed")
        self.lbl_proc_status.setStyleSheet("font-weight: 600; color: #94A3B8;")
        audit_grid.addWidget(self.lbl_proc_status, 1, 1)

        audit_grid.addWidget(QLabel("Original Size:"), 2, 0)
        self.lbl_orig_meta = QLabel("—")
        self.lbl_orig_meta.setStyleSheet(f"color: {THEME_COLORS['text_secondary']};")
        audit_grid.addWidget(self.lbl_orig_meta, 2, 1)

        audit_grid.addWidget(QLabel("Processed Size:"), 3, 0)
        self.lbl_proc_meta = QLabel("—")
        self.lbl_proc_meta.setStyleSheet("color: #10B981; font-weight: 600;")
        audit_grid.addWidget(self.lbl_proc_meta, 3, 1)

        audit_grid.addWidget(QLabel("Engine Method:"), 4, 0)
        self.lbl_method = QLabel("Local CV (OpenCV)")
        self.lbl_method.setStyleSheet(f"color: {THEME_COLORS['status_info']}; font-weight: 500;")
        audit_grid.addWidget(self.lbl_method, 4, 1)

        audit_grid.addWidget(QLabel("Quality Flag:"), 5, 0)
        self.lbl_quality = QLabel("Pending")
        self.lbl_quality.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 600;")
        audit_grid.addWidget(self.lbl_quality, 5, 1)

        audit_grid.addWidget(QLabel("Review Status:"), 6, 0)
        self.lbl_review = QLabel("Unreviewed")
        self.lbl_review.setStyleSheet("font-weight: 700; color: #F59E0B;")
        audit_grid.addWidget(self.lbl_review, 6, 1)

        self.content_layout.addWidget(audit_card)

        # 4. Action Controls
        act_card = QFrame()
        act_card.setProperty("class", "card")
        act_vbox = QVBoxLayout(act_card)
        act_vbox.setContentsMargins(12, 10, 12, 10)
        act_vbox.setSpacing(8)

        lbl_sec3 = QLabel("PROCESSING ACTIONS")
        lbl_sec3.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']}; letter-spacing: 0.5px;")
        act_vbox.addWidget(lbl_sec3)

        self.btn_run_single = QPushButton("⚡ Remove Background")
        self.btn_run_single.setCursor(Qt.PointingHandCursor)
        self.btn_run_single.setStyleSheet(f"""
            background: {THEME_COLORS['accent_primary']};
            color: #0D1117;
            font-weight: 700;
            padding: 8px;
            font-size: 11px;
            border-radius: 4px;
            border: none;
        """)
        self.btn_run_single.clicked.connect(self._on_run_single_clicked)
        act_vbox.addWidget(self.btn_run_single)

        self.btn_compare = QPushButton("🔍 Before & After Compare")
        self.btn_compare.setCursor(Qt.PointingHandCursor)
        self.btn_compare.setStyleSheet("""
            background: #1E293B;
            color: #38BDF8;
            border: 1px solid #334155;
            padding: 7px;
            font-size: 11px;
            font-weight: 600;
            border-radius: 4px;
        """)
        self.btn_compare.clicked.connect(self._on_compare_clicked)
        act_vbox.addWidget(self.btn_compare)

        btn_row_approval = QHBoxLayout()
        btn_row_approval.setSpacing(6)

        self.btn_approve = QPushButton("Approve Result")
        self.btn_approve.setCursor(Qt.PointingHandCursor)
        self.btn_approve.setStyleSheet("background: #10B981; color: white; font-weight: 700; border: none; padding: 7px; font-size: 11px; border-radius: 4px;")
        self.btn_approve.clicked.connect(self._on_approve_clicked)
        btn_row_approval.addWidget(self.btn_approve)

        self.btn_reject = QPushButton("Reject Result")
        self.btn_reject.setCursor(Qt.PointingHandCursor)
        self.btn_reject.setStyleSheet("background: #EF4444; color: white; font-weight: 700; border: none; padding: 7px; font-size: 11px; border-radius: 4px;")
        self.btn_reject.clicked.connect(self._on_reject_clicked)
        btn_row_approval.addWidget(self.btn_reject)
        act_vbox.addLayout(btn_row_approval)

        btn_row_files = QHBoxLayout()
        btn_row_files.setSpacing(6)

        self.btn_open_orig = QPushButton("Open Original")
        self.btn_open_orig.setCursor(Qt.PointingHandCursor)
        self.btn_open_orig.setStyleSheet("background: #1E293B; color: #CBD5E1; border: 1px solid #334155; padding: 6px; font-size: 10px; border-radius: 4px;")
        self.btn_open_orig.clicked.connect(self._on_open_original)
        btn_row_files.addWidget(self.btn_open_orig)

        self.btn_open_proc = QPushButton("Open Processed")
        self.btn_open_proc.setCursor(Qt.PointingHandCursor)
        self.btn_open_proc.setStyleSheet("background: #1E293B; color: #10B981; border: 1px solid #334155; padding: 6px; font-size: 10px; border-radius: 4px;")
        self.btn_open_proc.clicked.connect(self._on_open_processed)
        btn_row_files.addWidget(self.btn_open_proc)
        act_vbox.addLayout(btn_row_files)

        self.content_layout.addWidget(act_card)
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self.checker_brush = QBrush(create_checkerboard_pixmap(20))
        self.viewing_mode = "transparent"

    def load_asset(self, asset: Dict[str, Any]) -> None:
        """Populate inspector fields from asset dictionary."""
        self.current_asset = asset

        # 1. Eligibility
        elig = asset.get("background_eligibility") or ELIGIBILITY_UNKNOWN
        self.combo_eligibility.blockSignals(True)
        idx = self.combo_eligibility.findText(elig)
        if idx >= 0:
            self.combo_eligibility.setCurrentIndex(idx)
        else:
            self.combo_eligibility.setCurrentIndex(0)
        self.combo_eligibility.blockSignals(False)

        # Eligibility explanation hint
        hints = {
            ELIGIBILITY_SUITABLE: "Isolated single object with solid/uniform backdrop. Optimal for clean cutout.",
            ELIGIBILITY_POSSIBLY: "Object with textured or complex perimeter. Verify cutout edges.",
            ELIGIBILITY_PRESERVE_SCENE: "Preserved as environmental scene; sky and terrain should not be removed.",
            ELIGIBILITY_ALREADY_TRANSPARENT: "Asset already contains an active alpha transparency channel.",
            ELIGIBILITY_SPRITE_SHEET: "Multi-object sheet requiring slicing before individual transparency cutout.",
            ELIGIBILITY_UNKNOWN: "Uncertain asset composition. Manual review required.",
        }
        self.lbl_elig_expl.setText(hints.get(elig, "Manual review recommended."))

        # 2. Dimension and Size Details
        ow = asset.get("width", 0)
        oh = asset.get("height", 0)
        osize = asset.get("file_size", 0)
        self.lbl_orig_meta.setText(f"{ow} × {oh} px ({format_bytes(osize)})")

        pw = asset.get("processed_width", 0)
        ph = asset.get("processed_height", 0)
        psize = asset.get("processed_file_size", 0)
        proc_path = asset.get("processed_path", "")

        if proc_path and Path(proc_path).exists():
            self.lbl_proc_meta.setText(f"{pw} × {ph} px ({format_bytes(psize)})")
            self.btn_open_proc.setEnabled(True)
            self.btn_compare.setEnabled(True)
            self.btn_approve.setEnabled(True)
            self.btn_reject.setEnabled(True)
        else:
            self.lbl_proc_meta.setText("—")
            self.btn_open_proc.setEnabled(False)
            self.btn_compare.setEnabled(False)
            self.btn_approve.setEnabled(False)
            self.btn_reject.setEnabled(False)

        # 3. Statuses
        proc_st = asset.get("bg_processing_status", "not_processed")
        st_colors = {
            "processed": "#10B981",
            "not_processed": "#94A3B8",
            "failed": "#EF4444",
            "processing": THEME_COLORS["accent_primary"],
        }
        self.lbl_proc_status.setText(proc_st.upper().replace("_", " "))
        self.lbl_proc_status.setStyleSheet(f"font-weight: 700; color: {st_colors.get(proc_st, '#94A3B8')};")

        method = asset.get("background_method") or "local_cv"
        method_name = "rembg AI (U2-Net)" if method == "rembg_ai" else "Local CV (OpenCV)"
        self.lbl_method.setText(method_name)

        q_st = asset.get("bg_quality_status", "pending")
        self.lbl_quality.setText(q_st.upper())
        self.lbl_quality.setStyleSheet(f"font-weight: 600; color: {'#10B981' if q_st == 'valid' else ('#F59E0B' if q_st == 'suspicious' else '#94A3B8')};")

        rev_st = asset.get("bg_manual_approval", "unreviewed")
        rev_colors = {"approved": "#10B981", "rejected": "#EF4444", "unreviewed": "#F59E0B"}
        self.lbl_review.setText(rev_st.upper())
        self.lbl_review.setStyleSheet(f"font-weight: 700; color: {rev_colors.get(rev_st, '#F59E0B')};")

        # 4. Render Preview
        if proc_path and Path(proc_path).exists():
            self._show_transparent_preview()
        else:
            self._show_original_preview()

    def _show_transparent_preview(self):
        """Render processed transparent image over checkerboard pattern."""
        self.viewing_mode = "transparent"
        self.btn_tab_proc.setStyleSheet(f"background: {THEME_COLORS['accent_primary']}; color: #0D1117; font-weight: 700; font-size: 10px; padding: 4px 8px; border-radius: 3px;")
        self.btn_tab_orig.setStyleSheet("background: #1E293B; color: #94A3B8; font-weight: 600; font-size: 10px; padding: 4px 8px; border-radius: 3px;")

        if not self.current_asset:
            return

        proc_path = self.current_asset.get("processed_path")
        if proc_path and Path(proc_path).exists():
            pix = QPixmap(str(proc_path))
            if not pix.isNull():
                scaled = pix.scaled(
                    self.preview_frame.width() - 8,
                    self.preview_frame.height() - 8,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                w, h = scaled.width(), scaled.height()
                canvas = QPixmap(w, h)
                p = QPainter(canvas)
                p.fillRect(0, 0, w, h, self.checker_brush)
                p.drawPixmap(0, 0, scaled)
                p.end()
                self.preview_label.setPixmap(canvas)
                return

        self.preview_label.setText("Transparent output not generated yet.")

    def _show_original_preview(self):
        """Render original source image."""
        self.viewing_mode = "original"
        self.btn_tab_orig.setStyleSheet(f"background: {THEME_COLORS['accent_primary']}; color: #0D1117; font-weight: 700; font-size: 10px; padding: 4px 8px; border-radius: 3px;")
        self.btn_tab_proc.setStyleSheet("background: #1E293B; color: #94A3B8; font-weight: 600; font-size: 10px; padding: 4px 8px; border-radius: 3px;")

        if not self.current_asset:
            return

        orig_path = self.current_asset.get("current_path") or self.current_asset.get("original_path")
        thumb_path = self.current_asset.get("thumbnail_path")

        pix = None
        if thumb_path and Path(thumb_path).exists():
            pix = QPixmap(str(thumb_path))
        elif orig_path and Path(orig_path).exists():
            pix = QPixmap(str(orig_path))

        if pix and not pix.isNull():
            scaled = pix.scaled(
                self.preview_frame.width() - 8,
                self.preview_frame.height() - 8,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)
        else:
            self.preview_label.setText("No Preview Available")

    def _on_eligibility_changed(self, new_elig: str):
        """Handle user changing eligibility dropdown."""
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        db.update_background_eligibility(aid, new_elig)
        self.asset_updated.emit(aid)

    def _on_run_single_clicked(self):
        """Process background removal for this single asset."""
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        success, res_data, msg = transparency_engine.process_asset(self.current_asset, method="auto")

        if success:
            updated = db.get_asset(aid)
            if updated:
                self.load_asset(updated)
            self.asset_updated.emit(aid)
            QMessageBox.information(self, "Background Removed", msg)
        else:
            QMessageBox.warning(self, "Processing Failed", msg)

    def _on_compare_clicked(self):
        """Open interactive before-and-after comparison dialog."""
        if not self.current_asset:
            return
        dialog = ComparisonDialog(self.current_asset, self)
        dialog.status_changed.connect(lambda aid, st: self.asset_updated.emit(aid))
        dialog.exec()
        updated = db.get_asset(self.current_asset["id"])
        if updated:
            self.load_asset(updated)

    def _on_approve_clicked(self):
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        db.update_transparency_approval(aid, "approved")
        self.lbl_review.setText("APPROVED")
        self.lbl_review.setStyleSheet("font-weight: 700; color: #10B981;")
        self.asset_updated.emit(aid)

    def _on_reject_clicked(self):
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        db.update_transparency_approval(aid, "rejected")
        self.lbl_review.setText("REJECTED")
        self.lbl_review.setStyleSheet("font-weight: 700; color: #EF4444;")
        self.asset_updated.emit(aid)

    def _on_open_original(self):
        if not self.current_asset:
            return
        path_str = self.current_asset.get("current_path") or self.current_asset.get("original_path")
        if path_str and Path(path_str).exists():
            subprocess.run(["explorer", "/select,", os.path.normpath(path_str)], check=False)

    def _on_open_processed(self):
        if not self.current_asset:
            return
        path_str = self.current_asset.get("processed_path")
        if path_str and Path(path_str).exists():
            subprocess.run(["explorer", "/select,", os.path.normpath(path_str)], check=False)
