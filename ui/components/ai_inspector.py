"""
AI Classification Inspector Component
Dedicated right-side inspector panel for reviewing, modifying, approving,
and fine-tuning AI image classification suggestions.
Never modifies original files.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.ai_engine import CATEGORIES, COMPOSITION_TYPES
from core.database import db


class AIInspector(QWidget):
    """Right-side inspector dedicated to reviewing and editing AI classification results."""

    classification_approved = Signal(int)
    classification_saved = Signal(int, dict)
    classification_rejected = Signal(int)
    reanalyze_requested = Signal(int)
    mark_unknown_requested = Signal(int)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ai_inspector")
        self.current_asset: Optional[Dict[str, Any]] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Header with Close Button
        header_layout = QHBoxLayout()
        header_title = QLabel("AI CLASSIFICATION INSPECTOR")
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

        # Scroll area for inspector body
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

        # 2. Confidence Card
        conf_card = QFrame()
        conf_card.setProperty("class", "card")
        conf_vbox = QVBoxLayout(conf_card)
        conf_vbox.setContentsMargins(10, 8, 10, 8)
        conf_vbox.setSpacing(6)

        conf_top_row = QHBoxLayout()
        lbl_conf_title = QLabel("CLASSIFICATION CONFIDENCE")
        lbl_conf_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        conf_top_row.addWidget(lbl_conf_title)
        conf_top_row.addStretch()

        self.lbl_conf_val = QLabel("0%")
        self.lbl_conf_val.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {THEME_COLORS['accent_primary']};")
        conf_top_row.addWidget(self.lbl_conf_val)
        conf_vbox.addLayout(conf_top_row)

        self.conf_bar = QProgressBar()
        self.conf_bar.setRange(0, 100)
        self.conf_bar.setValue(0)
        self.conf_bar.setFixedHeight(8)
        self.conf_bar.setTextVisible(False)
        conf_vbox.addWidget(self.conf_bar)

        self.lbl_recommendation = QLabel("Awaiting analysis.")
        self.lbl_recommendation.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        conf_vbox.addWidget(self.lbl_recommendation)
        self.content_layout.addWidget(conf_card)

        # 3. Editable Classification Metadata Form
        form_card = QFrame()
        form_card.setProperty("class", "card")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(12, 10, 12, 10)
        form_layout.setSpacing(8)

        lbl_form_title = QLabel("SUGGESTED CLASSIFICATION (EDITABLE)")
        lbl_form_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['accent_primary']}; letter-spacing: 0.5px;")
        form_layout.addWidget(lbl_form_title)

        # Object Name
        form_layout.addWidget(self._make_label("Object Name:"))
        self.txt_object_name = QLineEdit()
        form_layout.addWidget(self.txt_object_name)

        # Main Category
        form_layout.addWidget(self._make_label("Main Category:"))
        self.cmb_category = QComboBox()
        for cat in CATEGORIES.keys():
            self.cmb_category.addItem(cat)
        self.cmb_category.currentIndexChanged.connect(self._on_category_changed)
        form_layout.addWidget(self.cmb_category)

        # Subcategory
        form_layout.addWidget(self._make_label("Subcategory:"))
        self.cmb_subcategory = QComboBox()
        form_layout.addWidget(self.cmb_subcategory)
        self._on_category_changed(0)

        # Composition Type
        form_layout.addWidget(self._make_label("Composition Type:"))
        self.cmb_composition = QComboBox()
        for comp in COMPOSITION_TYPES:
            self.cmb_composition.addItem(comp)
        form_layout.addWidget(self.cmb_composition)

        # Visual Tags
        form_layout.addWidget(self._make_label("Visual Tags (comma separated):"))
        self.txt_tags = QLineEdit()
        form_layout.addWidget(self.txt_tags)

        # Suggested Filename (Stage 4 preview)
        form_layout.addWidget(self._make_label("Suggested Filename (Stage 4):"))
        self.txt_suggested_fname = QLineEdit()
        form_layout.addWidget(self.txt_suggested_fname)

        self.content_layout.addWidget(form_card)

        # 4. Special Detection Flags Card
        flags_card = QFrame()
        flags_card.setProperty("class", "card")
        flags_vbox = QVBoxLayout(flags_card)
        flags_vbox.setContentsMargins(10, 8, 10, 8)
        flags_vbox.setSpacing(4)

        lbl_flags_title = QLabel("PIPELINE STAGE CANDIDATES")
        lbl_flags_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        flags_vbox.addWidget(lbl_flags_title)

        self.lbl_flag_multi = QLabel("• Multiple Objects: No")
        self.lbl_flag_sheet = QLabel("• Sprite Sheet: No")
        self.lbl_flag_text = QLabel("• Possible Text / Label: No")
        self.lbl_flag_watermark = QLabel("• Possible Watermark: No")

        for f_lbl in [self.lbl_flag_multi, self.lbl_flag_sheet, self.lbl_flag_text, self.lbl_flag_watermark]:
            f_lbl.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
            flags_vbox.addWidget(f_lbl)

        self.content_layout.addWidget(flags_card)

        # 5. AI Reasoning & Telemetry
        ai_card = QFrame()
        ai_card.setProperty("class", "card")
        ai_vbox = QVBoxLayout(ai_card)
        ai_vbox.setContentsMargins(10, 8, 10, 8)
        ai_vbox.setSpacing(6)

        lbl_reason_title = QLabel("AI VISUAL REASONING")
        lbl_reason_title.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {THEME_COLORS['text_muted']};")
        ai_vbox.addWidget(lbl_reason_title)

        self.txt_explanation = QPlainTextEdit()
        self.txt_explanation.setReadOnly(True)
        self.txt_explanation.setFixedHeight(75)
        ai_vbox.addWidget(self.txt_explanation)

        self.lbl_model_info = QLabel("Model: LocalVisionEngine v1.0 (OpenCV/HSV/Contour)")
        self.lbl_model_info.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        ai_vbox.addWidget(self.lbl_model_info)

        self.content_layout.addWidget(ai_card)

        # 6. Action Buttons Card
        act_card = QFrame()
        act_card.setProperty("class", "card")
        act_vbox = QVBoxLayout(act_card)
        act_vbox.setContentsMargins(10, 10, 10, 10)
        act_vbox.setSpacing(6)

        self.btn_approve = QPushButton("✓ Approve Classification")
        self.btn_approve.setProperty("class", "btn_primary")
        self.btn_approve.setCursor(Qt.PointingHandCursor)
        self.btn_approve.clicked.connect(self._on_approve)
        act_vbox.addWidget(self.btn_approve)

        self.btn_save_edit = QPushButton("✏️ Save Manual Edits")
        self.btn_save_edit.setProperty("class", "btn_secondary")
        self.btn_save_edit.setCursor(Qt.PointingHandCursor)
        self.btn_save_edit.clicked.connect(self._on_save_edits)
        act_vbox.addWidget(self.btn_save_edit)

        btn_row = QHBoxLayout()
        self.btn_reject = QPushButton("✕ Reject")
        self.btn_reject.setProperty("class", "btn_danger")
        self.btn_reject.setCursor(Qt.PointingHandCursor)
        self.btn_reject.clicked.connect(self._on_reject)
        btn_row.addWidget(self.btn_reject)

        self.btn_reanalyze = QPushButton("🔄 Re-analyze")
        self.btn_reanalyze.setProperty("class", "btn_secondary")
        self.btn_reanalyze.setCursor(Qt.PointingHandCursor)
        self.btn_reanalyze.clicked.connect(self._on_reanalyze)
        btn_row.addWidget(self.btn_reanalyze)
        act_vbox.addLayout(btn_row)

        self.content_layout.addWidget(act_card)
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

        self.clear()

    def _make_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']}; font-weight: 600;")
        return lbl

    def _on_category_changed(self, index: int):
        """Update subcategory dropdown based on active main category."""
        cat_name = self.cmb_category.currentText()
        subcats = CATEGORIES.get(cat_name, ["Other"])
        self.cmb_subcategory.clear()
        for sc in subcats:
            self.cmb_subcategory.addItem(sc)

    def clear(self):
        """Clear fields to placeholder state."""
        self.current_asset = None
        self.preview_label.setText("No Asset Selected")
        self.preview_label.setPixmap(QPixmap())
        self.lbl_conf_val.setText("0%")
        self.conf_bar.setValue(0)
        self.lbl_recommendation.setText("Select an asset card to view classification.")
        self.txt_object_name.clear()
        self.txt_tags.clear()
        self.txt_suggested_fname.clear()
        self.txt_explanation.clear()
        self.btn_approve.setEnabled(False)
        self.btn_save_edit.setEnabled(False)
        self.btn_reject.setEnabled(False)
        self.btn_reanalyze.setEnabled(False)

    def inspect_asset(self, asset: Dict[str, Any]):
        """Populate inspector with asset's classification fields."""
        self.current_asset = asset
        asset_id = asset["id"]

        # Preview Image
        thumb_path = asset.get("thumbnail_path")
        orig_path = asset.get("original_path", "")
        pixmap = None
        if thumb_path and Path(thumb_path).exists():
            pixmap = QPixmap(thumb_path)
        elif orig_path and Path(orig_path).exists():
            pixmap = QPixmap(orig_path)

        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(230, 165, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_label.setPixmap(scaled)
        else:
            self.preview_label.setText("Preview Unavailable")

        # Confidence
        conf = float(asset.get("confidence_score") or 0.0)
        pct = int(conf * 100)
        self.lbl_conf_val.setText(f"{pct}%")
        self.conf_bar.setValue(pct)

        # Recommendation rules based on prompt Section 5
        comp = asset.get("composition_type") or "Single Object"
        if comp == "Multiple Objects":
            self.lbl_recommendation.setText("⚠️ Multiple objects: flag for Collection Splitter (Stage 8).")
            self.lbl_recommendation.setStyleSheet(f"color: {THEME_COLORS['status_warning']}; font-weight: 600;")
        elif comp == "Sprite Sheet":
            self.lbl_recommendation.setText("🎞️ Sprite sheet: flag for Sprite Sheet Editor (Stage 9).")
            self.lbl_recommendation.setStyleSheet(f"color: {THEME_COLORS['status_info']}; font-weight: 600;")
        elif comp in ("Full Scene", "Background Image"):
            self.lbl_recommendation.setText("🌄 Panoramic scene: flag for background review.")
            self.lbl_recommendation.setStyleSheet(f"color: {THEME_COLORS['status_info']}; font-weight: 600;")
        elif conf >= 0.80:
            self.lbl_recommendation.setText("✓ High confidence: eligible for quick approval.")
            self.lbl_recommendation.setStyleSheet(f"color: {THEME_COLORS['status_success']}; font-weight: 600;")
        elif conf >= 0.50:
            self.lbl_recommendation.setText("▲ Medium confidence: manual inspection recommended.")
            self.lbl_recommendation.setStyleSheet(f"color: {THEME_COLORS['status_warning']}; font-weight: 600;")
        elif conf > 0:
            self.lbl_recommendation.setText("▼ Low confidence: manual classification required.")
            self.lbl_recommendation.setStyleSheet(f"color: {THEME_COLORS['status_error']}; font-weight: 600;")
        else:
            self.lbl_recommendation.setText("Unclassified. Click Re-analyze or Start Batch.")
            self.lbl_recommendation.setStyleSheet(f"color: {THEME_COLORS['text_muted']};")

        # Form fields
        self.txt_object_name.setText(asset.get("object_name") or "")

        cat = asset.get("main_category") or "Construction Vehicles"
        idx = self.cmb_category.findText(cat)
        if idx >= 0:
            self.cmb_category.setCurrentIndex(idx)
        self._on_category_changed(0)

        subcat = asset.get("subcategory") or ""
        sub_idx = self.cmb_subcategory.findText(subcat)
        if sub_idx >= 0:
            self.cmb_subcategory.setCurrentIndex(sub_idx)

        c_idx = self.cmb_composition.findText(comp)
        if c_idx >= 0:
            self.cmb_composition.setCurrentIndex(c_idx)

        # Tags
        tags_raw = asset.get("visual_tags") or []
        if isinstance(tags_raw, str):
            try:
                tags_list = json.loads(tags_raw)
            except Exception:
                tags_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
        else:
            tags_list = list(tags_raw)
        self.txt_tags.setText(", ".join(tags_list))

        self.txt_suggested_fname.setText(asset.get("suggested_filename") or "")
        self.txt_explanation.setPlainText(asset.get("ai_explanation") or "No explanation generated yet.")

        # Flags
        flags = asset.get("special_flags") or {}
        if isinstance(flags, str):
            try:
                flags = json.loads(flags)
            except Exception:
                flags = {}

        self.lbl_flag_multi.setText(f"• Multiple Objects: {'YES (Flagged)' if flags.get('multiple_objects') else 'No'}")
        self.lbl_flag_sheet.setText(f"• Sprite Sheet: {'YES (Flagged)' if flags.get('sprite_sheet') else 'No'}")
        self.lbl_flag_text.setText(f"• Possible Text / Label: {'YES (Flagged)' if flags.get('possible_text') else 'No'}")
        self.lbl_flag_watermark.setText(f"• Possible Watermark: {'YES (Flagged)' if flags.get('possible_watermark') else 'No'}")

        self.btn_approve.setEnabled(True)
        self.btn_save_edit.setEnabled(True)
        self.btn_reject.setEnabled(True)
        self.btn_reanalyze.setEnabled(True)

    def _on_approve(self):
        if self.current_asset:
            aid = self.current_asset["id"]
            db.update_classification_status(aid, "approved")
            self.current_asset["classification_status"] = "approved"
            self.classification_approved.emit(aid)

    def _on_reject(self):
        if self.current_asset:
            aid = self.current_asset["id"]
            db.update_classification_status(aid, "rejected")
            self.current_asset["classification_status"] = "rejected"
            self.classification_rejected.emit(aid)

    def _on_save_edits(self):
        if self.current_asset:
            aid = self.current_asset["id"]
            tags = [t.strip() for t in self.txt_tags.text().split(",") if t.strip()]
            edits = {
                "object_name": self.txt_object_name.text().strip(),
                "main_category": self.cmb_category.currentText(),
                "subcategory": self.cmb_subcategory.currentText(),
                "composition_type": self.cmb_composition.currentText(),
                "visual_tags": tags,
                "suggested_filename": self.txt_suggested_fname.text().strip(),
                "confidence_score": 1.0,  # manual override is 100% user verified
                "classification_status": "manual",
                "ai_explanation": f"User manual verification & edit.",
            }
            db.save_classification(aid, edits, action="manual_edit", is_manual=True)
            self.classification_saved.emit(aid, edits)

    def _on_reanalyze(self):
        if self.current_asset:
            self.reanalyze_requested.emit(self.current_asset["id"])
