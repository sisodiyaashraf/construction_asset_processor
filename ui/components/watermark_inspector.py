"""
Watermark Inspector Component (Stage 7)
Dedicated right-side panel for inspecting watermark candidates,
viewing interactive canvas with bounding box overlays, evaluating visual explanations,
confirming/rejecting candidates, adding reviewer notes, and managing the clean replacement workflow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.database import db
from core.watermark_engine import (
    WATERMARK_CATEGORIES, WATERMARK_CATEGORY_COLORS,
    WATERMARK_REPLACEMENT_STATUSES, WATERMARK_REVIEW_STATUSES,
    watermark_engine
)
from ui.components.watermark_canvas import WatermarkCanvas

logger = logging.getLogger("AssetProcessor.WatermarkInspector")


class WatermarkInspector(QWidget):
    """Right-side inspector dedicated to Stage 7 watermark review and replacement workflow."""

    asset_updated = Signal(int)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("watermark_inspector")
        self.current_asset: Optional[Dict[str, Any]] = None
        self.current_candidates: List[Dict[str, Any]] = []
        self.selected_candidate: Optional[Dict[str, Any]] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # 1. Header with Close Button
        header_layout = QHBoxLayout()
        header_title = QLabel("WATERMARK INSPECTOR")
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

        # 2. Scroll Area for Body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)

        # 2a. Interactive Canvas Widget
        self.canvas_card = QFrame()
        self.canvas_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        c_layout = QVBoxLayout(self.canvas_card)
        c_layout.setContentsMargins(8, 8, 8, 8)
        c_layout.setSpacing(6)

        c_header = QLabel("IMAGE WATERMARK OVERLAY")
        c_header.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        c_layout.addWidget(c_header)

        self.canvas = WatermarkCanvas()
        self.canvas.setMinimumHeight(240)
        self.canvas.candidate_selected.connect(self._on_canvas_candidate_selected)
        self.canvas.candidate_deselected.connect(self._on_canvas_candidate_deselected)
        self.canvas.new_candidate_drawn.connect(self._on_new_candidate_drawn)
        c_layout.addWidget(self.canvas)

        self.content_layout.addWidget(self.canvas_card)

        # 2b. Asset Metadata Card
        meta_card = QFrame()
        meta_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        meta_layout = QVBoxLayout(meta_card)
        meta_layout.setContentsMargins(12, 12, 12, 12)
        meta_layout.setSpacing(6)

        self.lbl_filename = QLabel("No Asset Selected")
        self.lbl_filename.setWordWrap(True)
        self.lbl_filename.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {THEME_COLORS['text_primary']};")
        meta_layout.addWidget(self.lbl_filename)

        grid = QGridLayout()
        grid.setSpacing(4)
        lbl_dim_title = QLabel("Dimensions:")
        lbl_dim_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_dim_val = QLabel("—")
        self.lbl_dim_val.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        grid.addWidget(lbl_dim_title, 0, 0)
        grid.addWidget(self.lbl_dim_val, 0, 1)

        lbl_size_title = QLabel("File Size:")
        lbl_size_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_size_val = QLabel("—")
        self.lbl_size_val.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        grid.addWidget(lbl_size_title, 1, 0)
        grid.addWidget(self.lbl_size_val, 1, 1)

        lbl_cand_title = QLabel("Watermark Candidates:")
        lbl_cand_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_cand_val = QLabel("0 candidates")
        self.lbl_cand_val.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {THEME_COLORS['status_error']};")
        grid.addWidget(lbl_cand_title, 2, 0)
        grid.addWidget(self.lbl_cand_val, 2, 1)

        lbl_repl_title = QLabel("Replacement Status:")
        lbl_repl_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        self.lbl_repl_val = QLabel("None")
        self.lbl_repl_val.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['text_secondary']};")
        grid.addWidget(lbl_repl_title, 3, 0)
        grid.addWidget(self.lbl_repl_val, 3, 1)

        meta_layout.addLayout(grid)
        self.content_layout.addWidget(meta_card)

        # 2c. Replacement Workflow Alert Card (shown when confirmed or needs replacement)
        self.replacement_alert_card = QFrame()
        self.replacement_alert_card.setVisible(False)
        self.replacement_alert_card.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(239, 68, 68, 0.12);
                border: 1px solid rgba(239, 68, 68, 0.35);
                border-radius: 6px;
            }}
        """)
        rep_layout = QVBoxLayout(self.replacement_alert_card)
        rep_layout.setContentsMargins(12, 10, 12, 10)
        rep_layout.setSpacing(6)

        lbl_rep_head = QLabel("🚨 Needs Clean Replacement")
        lbl_rep_head.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {THEME_COLORS['status_error']};")
        rep_layout.addWidget(lbl_rep_head)

        lbl_rep_msg = QLabel(
            "This asset contains a confirmed or suspected watermark. "
            "Replace it with a clean original image or regenerate the asset without a watermark. "
            "The original file has not been modified."
        )
        lbl_rep_msg.setWordWrap(True)
        lbl_rep_msg.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_primary']}; line-height: 1.4;")
        rep_layout.addWidget(lbl_rep_msg)

        rep_btn_layout = QHBoxLayout()
        self.btn_repl_pending = QPushButton("Mark Replacement Pending")
        self.btn_repl_pending.setStyleSheet(self._action_btn_style("rgba(245, 158, 11, 0.2)", THEME_COLORS["status_warning"]))
        self.btn_repl_pending.clicked.connect(lambda: self._set_replacement_status("pending"))
        rep_btn_layout.addWidget(self.btn_repl_pending)

        self.btn_repl_done = QPushButton("Mark Replacement Completed")
        self.btn_repl_done.setStyleSheet(self._action_btn_style("rgba(16, 185, 129, 0.2)", THEME_COLORS["status_success"]))
        self.btn_repl_done.clicked.connect(lambda: self._set_replacement_status("completed"))
        rep_btn_layout.addWidget(self.btn_repl_done)

        rep_layout.addLayout(rep_btn_layout)
        self.content_layout.addWidget(self.replacement_alert_card)

        # 2d. Candidates Table Card
        table_card = QFrame()
        table_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        t_layout = QVBoxLayout(table_card)
        t_layout.setContentsMargins(12, 12, 12, 12)
        t_layout.setSpacing(8)

        t_header = QLabel("DETECTED WATERMARK CANDIDATES")
        t_header.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        t_layout.addWidget(t_header)

        self.table_candidates = QTableWidget(0, 3)
        self.table_candidates.setHorizontalHeaderLabels(["Category", "Score", "Status"])
        self.table_candidates.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_candidates.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_candidates.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_candidates.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_candidates.setSelectionMode(QTableWidget.SingleSelection)
        self.table_candidates.verticalHeader().setVisible(False)
        self.table_candidates.setMaximumHeight(140)
        self.table_candidates.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
            }}
            QHeaderView::section {{
                background-color: {THEME_COLORS['bg_toolbar']};
                color: {THEME_COLORS['text_secondary']};
                padding: 4px;
                font-size: 10px;
                font-weight: 700;
                border: none;
            }}
        """)
        self.table_candidates.itemSelectionChanged.connect(self._on_table_selection_changed)
        t_layout.addWidget(self.table_candidates)

        self.content_layout.addWidget(table_card)

        # 2e. Selected Candidate Detail & Review Card
        self.detail_card = QFrame()
        self.detail_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        d_layout = QVBoxLayout(self.detail_card)
        d_layout.setContentsMargins(12, 12, 12, 12)
        d_layout.setSpacing(8)

        self.lbl_detail_title = QLabel("CANDIDATE DETAILS")
        self.lbl_detail_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        d_layout.addWidget(self.lbl_detail_title)

        # Category Selector
        lbl_cat = QLabel("Candidate Category:")
        lbl_cat.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        d_layout.addWidget(lbl_cat)

        self.combo_category = QComboBox()
        self.combo_category.addItems(WATERMARK_CATEGORIES)
        self.combo_category.setStyleSheet(f"""
            QComboBox {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
            }}
        """)
        d_layout.addWidget(self.combo_category)

        # Score Row with progress bar
        score_row = QHBoxLayout()
        self.lbl_score_text = QLabel("Candidate Score: 0%")
        self.lbl_score_text.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['accent_primary']};")
        score_row.addWidget(self.lbl_score_text)
        score_row.addStretch()

        self.lbl_method = QLabel("Method: —")
        self.lbl_method.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        score_row.addWidget(self.lbl_method)
        d_layout.addLayout(score_row)

        self.bar_score = QProgressBar()
        self.bar_score.setFixedHeight(6)
        self.bar_score.setTextVisible(False)
        self.bar_score.setStyleSheet(f"""
            QProgressBar {{
                background-color: {THEME_COLORS['bg_input']};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {THEME_COLORS['accent_primary']};
                border-radius: 3px;
            }}
        """)
        d_layout.addWidget(self.bar_score)

        # Detection Explanation
        lbl_exp_title = QLabel("Visual Signal Explanation:")
        lbl_exp_title.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        d_layout.addWidget(lbl_exp_title)

        self.lbl_explanation = QLabel("Select a candidate to view explanation.")
        self.lbl_explanation.setWordWrap(True)
        self.lbl_explanation.setStyleSheet(f"""
            font-size: 11px;
            color: {THEME_COLORS['text_primary']};
            background-color: {THEME_COLORS['bg_input']};
            padding: 6px 8px;
            border-radius: 4px;
            border: 1px solid {THEME_COLORS['border_subtle']};
        """)
        d_layout.addWidget(self.lbl_explanation)

        # Coordinates
        self.lbl_coords = QLabel("Bounding Box: X: 0, Y: 0, W: 0, H: 0")
        self.lbl_coords.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        d_layout.addWidget(self.lbl_coords)

        # Reviewer Notes
        lbl_notes = QLabel("Reviewer Notes:")
        lbl_notes.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        d_layout.addWidget(lbl_notes)

        self.txt_notes = QLineEdit()
        self.txt_notes.setPlaceholderText("Enter audit or reviewer observations...")
        self.txt_notes.setStyleSheet(f"""
            QLineEdit {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        d_layout.addWidget(self.txt_notes)

        # Candidate Review Action Buttons
        btn_grid = QGridLayout()
        btn_grid.setSpacing(6)

        self.btn_confirm = QPushButton("✓ Confirm Watermark")
        self.btn_confirm.setToolTip("Mark this region as a verified watermark")
        self.btn_confirm.setStyleSheet(self._action_btn_style("rgba(239, 68, 68, 0.2)", THEME_COLORS["status_error"]))
        self.btn_confirm.clicked.connect(self._confirm_candidate)
        btn_grid.addWidget(self.btn_confirm, 0, 0)

        self.btn_reject = QPushButton("✕ Reject Candidate")
        self.btn_reject.setToolTip("Mark candidate as false positive / clean artwork")
        self.btn_reject.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["text_secondary"]))
        self.btn_reject.clicked.connect(self._reject_candidate)
        btn_grid.addWidget(self.btn_reject, 0, 1)

        self.btn_uncertain = QPushButton("❓ Mark Uncertain")
        self.btn_uncertain.setToolTip("Flag region as requiring further human inspection")
        self.btn_uncertain.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_warning"]))
        self.btn_uncertain.clicked.connect(self._mark_uncertain)
        btn_grid.addWidget(self.btn_uncertain, 1, 0)

        self.btn_save_changes = QPushButton("💾 Save Changes")
        self.btn_save_changes.setStyleSheet(self._action_btn_style(THEME_COLORS["accent_primary"], "#111827"))
        self.btn_save_changes.clicked.connect(self._save_candidate_changes)
        btn_grid.addWidget(self.btn_save_changes, 1, 1)

        d_layout.addLayout(btn_grid)

        # Delete Box
        self.btn_delete_candidate = QPushButton("🗑 Delete Box")
        self.btn_delete_candidate.setToolTip("Remove this bounding box region")
        self.btn_delete_candidate.setStyleSheet(self._action_btn_style("transparent", THEME_COLORS["text_muted"]))
        self.btn_delete_candidate.clicked.connect(self._delete_current_candidate)
        d_layout.addWidget(self.btn_delete_candidate)

        self.content_layout.addWidget(self.detail_card)

        # 2f. Asset-Level Actions Card
        asset_act_card = QFrame()
        asset_act_card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        a_layout = QVBoxLayout(asset_act_card)
        a_layout.setContentsMargins(12, 12, 12, 12)
        a_layout.setSpacing(8)

        a_header = QLabel("ASSET-LEVEL ACTIONS")
        a_header.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        a_layout.addWidget(a_header)

        self.btn_reanalyze = QPushButton("🔍 Re-Analyze Asset")
        self.btn_reanalyze.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["text_primary"]))
        self.btn_reanalyze.clicked.connect(self._reanalyze_single_asset)
        a_layout.addWidget(self.btn_reanalyze)

        status_row = QHBoxLayout()
        self.btn_needs_replacement = QPushButton("🚨 Needs Replacement")
        self.btn_needs_replacement.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_error"]))
        self.btn_needs_replacement.clicked.connect(lambda: self._set_asset_review("needs_replacement"))
        status_row.addWidget(self.btn_needs_replacement)

        self.btn_mark_reviewed = QPushButton("⭐ Mark Reviewed")
        self.btn_mark_reviewed.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_info"]))
        self.btn_mark_reviewed.clicked.connect(lambda: self._set_asset_review("reviewed"))
        status_row.addWidget(self.btn_mark_reviewed)

        self.btn_no_watermark = QPushButton("✓ No Watermark")
        self.btn_no_watermark.setStyleSheet(self._action_btn_style(THEME_COLORS["bg_input"], THEME_COLORS["status_success"]))
        self.btn_no_watermark.clicked.connect(lambda: self._set_asset_review("no_watermark"))
        status_row.addWidget(self.btn_no_watermark)

        a_layout.addLayout(status_row)
        self.content_layout.addWidget(asset_act_card)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self._set_detail_enabled(False)

    def inspect_asset(self, asset: Dict[str, Any]):
        """Load and inspect an asset for watermark review."""
        self.current_asset = asset
        asset_id = asset["id"]

        self.lbl_filename.setText(asset.get("filename", "unknown"))
        w = asset.get("width", 0)
        h = asset.get("height", 0)
        self.lbl_dim_val.setText(f"{w} × {h} px" if w and h else "—")
        self.lbl_size_val.setText(format_bytes(asset.get("file_size_bytes", 0)))

        # Fetch real watermark candidates from database
        self.current_candidates = db.get_watermark_regions(asset_id)
        count = len(self.current_candidates)
        self.lbl_cand_val.setText(f"{count} candidate(s)" if count > 0 else "0 (Clear)")

        # Replacement status
        repl_status = asset.get("watermark_replacement_status", "none").capitalize()
        self.lbl_repl_val.setText(repl_status)

        # Show replacement alert if confirmed watermark or needs replacement
        rev_status = str(asset.get("watermark_review_status", "")).lower()
        has_confirmed = any(c.get("review_status") == "confirmed" for c in self.current_candidates)
        show_alert = (rev_status in ("needs_replacement", "confirmed") or has_confirmed)
        self.replacement_alert_card.setVisible(show_alert)

        # Load image & candidates into canvas
        orig_path = asset.get("original_path", "")
        self.canvas.load_image(orig_path, self.current_candidates)

        # Populate table
        self._populate_table()

        # Reset candidate details
        self.selected_candidate = None
        self._set_detail_enabled(False)

    def _populate_table(self):
        """Populate the candidates list table."""
        self.table_candidates.blockSignals(True)
        self.table_candidates.setRowCount(0)

        for row_idx, c in enumerate(self.current_candidates):
            self.table_candidates.insertRow(row_idx)

            # Category with color
            c_type = c.get("candidate_type", "Uncertain Mark")
            item_cat = QTableWidgetItem(c_type)
            item_cat.setForeground(QColor(WATERMARK_CATEGORY_COLORS.get(c_type, "#9CA3AF")))
            self.table_candidates.setItem(row_idx, 0, item_cat)

            # Score
            score_pct = int(float(c.get("candidate_score", 0.5)) * 100)
            item_score = QTableWidgetItem(f"{score_pct}%")
            self.table_candidates.setItem(row_idx, 1, item_score)

            # Status
            st = str(c.get("review_status", "pending")).capitalize()
            item_st = QTableWidgetItem(st)
            self.table_candidates.setItem(row_idx, 2, item_st)

        self.table_candidates.blockSignals(False)

    def _on_canvas_candidate_selected(self, candidate: Dict[str, Any]):
        """Candidate box clicked on canvas."""
        self.selected_candidate = candidate
        self._set_detail_enabled(True)

        # Select in table
        cid = candidate.get("id")
        self.table_candidates.blockSignals(True)
        for row in range(self.table_candidates.rowCount()):
            if row < len(self.current_candidates) and self.current_candidates[row].get("id") == cid:
                self.table_candidates.selectRow(row)
                break
        self.table_candidates.blockSignals(False)

        self._populate_detail(candidate)

    def _on_canvas_candidate_deselected(self):
        self.selected_candidate = None
        self._set_detail_enabled(False)
        self.table_candidates.clearSelection()

    def _on_table_selection_changed(self):
        selected_rows = self.table_candidates.selectionModel().selectedRows()
        if not selected_rows:
            self.selected_candidate = None
            self.canvas.select_candidate(None)
            self._set_detail_enabled(False)
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self.current_candidates):
            cand = self.current_candidates[row]
            self.selected_candidate = cand
            self.canvas.select_candidate(cand.get("id"))
            self._set_detail_enabled(True)
            self._populate_detail(cand)

    def _populate_detail(self, cand: Dict[str, Any]):
        """Populate detail editor card with selected candidate data."""
        cid = cand.get("id")
        self.lbl_detail_title.setText(f"CANDIDATE DETAILS — ID #{cid}")

        c_type = cand.get("candidate_type", "Uncertain Mark")
        idx = self.combo_category.findText(c_type)
        if idx >= 0:
            self.combo_category.setCurrentIndex(idx)

        score_val = float(cand.get("candidate_score", 0.5))
        score_pct = int(score_val * 100)
        self.lbl_score_text.setText(f"Candidate Score: {score_pct}%")
        self.bar_score.setValue(score_pct)

        method = cand.get("detection_method", "multi_signal_cv")
        self.lbl_method.setText(f"Method: {method}")

        reason = cand.get("detection_reason", "Detected via computer vision.")
        self.lbl_explanation.setText(reason)

        bx = cand.get("x", cand.get("box_x", 0))
        by = cand.get("y", cand.get("box_y", 0))
        bw = cand.get("width", cand.get("box_w", 0))
        bh = cand.get("height", cand.get("box_h", 0))
        self.lbl_coords.setText(f"Coordinates: X: {bx}, Y: {by} | Size: {bw} × {bh} px")

        self.txt_notes.setText(cand.get("reviewer_notes", ""))

    def _on_new_candidate_drawn(self, bx: int, by: int, bw: int, bh: int):
        """Add manually drawn candidate region."""
        if not self.current_asset:
            return

        asset_id = self.current_asset["id"]
        new_cand = {
            "x": bx,
            "y": by,
            "width": bw,
            "height": bh,
            "candidate_type": "Uncertain Mark",
            "candidate_text": "",
            "candidate_score": 1.0,
            "detection_method": "manual",
            "detection_reason": "Manually drawn by reviewer",
            "review_status": "pending",
            "reviewer_notes": "",
        }

        new_id = db.add_watermark_region(asset_id, new_cand)
        logger.info("Added manual watermark candidate #%s to asset #%s", new_id, asset_id)

        self.refresh_current_asset()
        self.asset_updated.emit(asset_id)
        self.canvas.select_candidate(new_id)

    def _confirm_candidate(self):
        """Confirm selected candidate as a verified watermark."""
        if not self.selected_candidate:
            return
        cid = self.selected_candidate.get("id")
        notes = self.txt_notes.text().strip()
        db.update_watermark_region(cid, {"review_status": "confirmed", "reviewer_notes": notes})
        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _reject_candidate(self):
        """Reject candidate as false positive (preserved in audit history)."""
        if not self.selected_candidate:
            return
        cid = self.selected_candidate.get("id")
        notes = self.txt_notes.text().strip()
        db.update_watermark_region(cid, {"review_status": "rejected", "reviewer_notes": notes})
        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _mark_uncertain(self):
        """Mark candidate as uncertain for secondary review."""
        if not self.selected_candidate:
            return
        cid = self.selected_candidate.get("id")
        notes = self.txt_notes.text().strip()
        db.update_watermark_region(cid, {"review_status": "uncertain", "reviewer_notes": notes})
        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _save_candidate_changes(self):
        """Save manual category or notes updates."""
        if not self.selected_candidate:
            return
        cid = self.selected_candidate.get("id")
        new_cat = self.combo_category.currentText()
        notes = self.txt_notes.text().strip()
        db.update_watermark_region(cid, {"candidate_type": new_cat, "reviewer_notes": notes})
        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _delete_current_candidate(self):
        """Delete selected bounding box."""
        if not self.selected_candidate:
            return
        cid = self.selected_candidate.get("id")
        db.delete_watermark_region(cid)
        self.selected_candidate = None
        self._set_detail_enabled(False)
        self.refresh_current_asset()
        if self.current_asset:
            self.asset_updated.emit(self.current_asset["id"])

    def _set_asset_review(self, status: str):
        """Set top-level asset review status."""
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        repl_st = "pending" if status == "needs_replacement" else None
        db.update_asset_watermark_review(aid, status, repl_st)
        self.refresh_current_asset()
        self.asset_updated.emit(aid)

    def _set_replacement_status(self, repl_status: str):
        """Set clean replacement status ('pending' or 'completed')."""
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        db.update_asset_watermark_review(aid, "needs_replacement", repl_status)
        self.refresh_current_asset()
        self.asset_updated.emit(aid)

    def _reanalyze_single_asset(self):
        """Re-run watermark detection on current asset."""
        if not self.current_asset:
            return
        watermark_engine.process_and_save_asset(self.current_asset)
        self.refresh_current_asset()
        self.asset_updated.emit(self.current_asset["id"])

    def refresh_current_asset(self):
        if not self.current_asset:
            return
        aid = self.current_asset["id"]
        fresh = db.get_asset(aid)
        if fresh:
            self.inspect_asset(fresh)

    def _set_detail_enabled(self, enabled: bool):
        self.combo_category.setEnabled(enabled)
        self.txt_notes.setEnabled(enabled)
        self.btn_confirm.setEnabled(enabled)
        self.btn_reject.setEnabled(enabled)
        self.btn_uncertain.setEnabled(enabled)
        self.btn_save_changes.setEnabled(enabled)
        self.btn_delete_candidate.setEnabled(enabled)
        if not enabled:
            self.lbl_detail_title.setText("CANDIDATE DETAILS (Select a candidate)")
            self.lbl_coords.setText("Coordinates: —")
            self.lbl_score_text.setText("Candidate Score: —")
            self.lbl_method.setText("Method: —")
            self.bar_score.setValue(0)
            self.lbl_explanation.setText("Select a candidate to view explanation.")
            self.txt_notes.clear()

    def _action_btn_style(self, bg: str, text: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {text};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
            QPushButton:disabled {{
                opacity: 0.4;
                color: {THEME_COLORS['text_muted']};
            }}
        """
