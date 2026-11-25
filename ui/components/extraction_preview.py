"""
Extraction Preview Dialog Component (Stage 8)
Presents a modal grid preview of all proposed extracted assets before any files are written to disk.
Allows users to inspect crops, edit proposed filenames, adjust padding, exclude unwanted items,
reorder frames, and approve extraction to output/separated/.
Preserves links to source image provenance and respects non-destructive safety rules.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.collection_splitter_engine import collection_splitter_engine
from core.database import db

logger = logging.getLogger("AssetProcessor.ExtractionPreview")


class ExtractedAssetPreviewCard(QFrame):
    """Card showing an individual proposed extracted asset candidate inside the preview grid."""

    approved_toggled = Signal(int, bool)
    name_changed = Signal(int, str)

    def __init__(
        self,
        index: int,
        source_asset: Dict[str, Any],
        region: Dict[str, Any],
        cropped_img: Image.Image,
        proposed_filename: str,
        padding: int = 8,
        parent=None,
    ):
        super().__init__(parent)
        self.index = index
        self.source_asset = source_asset
        self.region = region
        self.cropped_img = cropped_img
        self.proposed_filename = proposed_filename
        self.padding = padding
        self.is_approved = True

        self.setFixedSize(220, 310)
        self.setObjectName("preview_card")
        self._setup_ui()
        self._update_style()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Top Bar: Approval Checkbox & Frame Index
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self.chk_approve = QCheckBox(f"#{self.index + 1}")
        self.chk_approve.setChecked(True)
        self.chk_approve.setToolTip("Include this extracted asset in export")
        self.chk_approve.setStyleSheet(f"""
            QCheckBox {{
                color: {THEME_COLORS['text_primary']};
                font-size: 11px;
                font-weight: 700;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 3px;
                background-color: {THEME_COLORS['bg_input']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {THEME_COLORS['accent_primary']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.chk_approve.toggled.connect(self._on_approve_toggled)
        top_bar.addWidget(self.chk_approve)

        top_bar.addStretch()

        # Type Badge
        reg_type = self.region.get("region_type", "isolated_asset")
        lbl_type = QLabel(reg_type.replace("_", " ").title())
        lbl_type.setStyleSheet(f"""
            font-size: 9px;
            font-weight: 600;
            color: #10B981;
            background-color: rgba(16, 185, 129, 0.15);
            padding: 2px 5px;
            border-radius: 3px;
        """)
        top_bar.addWidget(lbl_type)

        layout.addLayout(top_bar)

        # Thumbnail Container with Transparency Pattern
        self.thumb_container = QFrame()
        self.thumb_container.setFixedSize(204, 130)
        self.thumb_container.setStyleSheet(f"""
            background-color: {THEME_COLORS['bg_main']};
            border: 1px solid {THEME_COLORS['border_subtle']};
            border-radius: 4px;
        """)
        t_layout = QVBoxLayout(self.thumb_container)
        t_layout.setContentsMargins(2, 2, 2, 2)
        t_layout.setAlignment(Qt.AlignCenter)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self._load_crop_preview()
        t_layout.addWidget(self.lbl_thumb)
        layout.addWidget(self.thumb_container)

        # Dimensions & Metadata
        w, h = self.cropped_img.size
        orig_x = self.region.get("x", 0)
        orig_y = self.region.get("y", 0)
        is_rgba = (self.cropped_img.mode == "RGBA")

        lbl_meta = QLabel(f"{w}×{h} px • ({orig_x},{orig_y}) • {'RGBA' if is_rgba else 'RGB'}")
        lbl_meta.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        layout.addWidget(lbl_meta)

        # Proposed Filename Input (Editable)
        lbl_name_tag = QLabel("Export Filename:")
        lbl_name_tag.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {THEME_COLORS['text_secondary']};")
        layout.addWidget(lbl_name_tag)

        self.txt_filename = QLineEdit(self.proposed_filename)
        self.txt_filename.setStyleSheet(f"""
            QLineEdit {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 10px;
                font-family: Consolas, monospace;
            }}
            QLineEdit:focus {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.txt_filename.textChanged.connect(self._on_name_changed)
        layout.addWidget(self.txt_filename)

    def _load_crop_preview(self):
        """Convert PIL crop to QPixmap with checkerboard transparency background."""
        if not self.cropped_img:
            return

        img = self.cropped_img
        if img.mode != "RGBA":
            img_rgba = img.convert("RGBA")
        else:
            img_rgba = img

        data = img_rgba.tobytes("raw", "RGBA")
        qim = QImage(data, img_rgba.width, img_rgba.height, QImage.Format_RGBA8888)
        pix = QPixmap.fromImage(qim)

        # Scale pixmap smoothly to fit container
        scaled_pix = pix.scaled(196, 122, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Create checkerboard backing
        canvas = QPixmap(scaled_pix.size())
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)

        tile = 8
        c1 = QColor(36, 42, 50)
        c2 = QColor(26, 30, 36)
        for y in range(0, canvas.height(), tile):
            for x in range(0, canvas.width(), tile):
                is_even = ((x // tile) + (y // tile)) % 2 == 0
                painter.fillRect(QRect(x, y, tile, tile), c1 if is_even else c2)

        painter.drawPixmap(0, 0, scaled_pix)
        painter.end()

        self.lbl_thumb.setPixmap(canvas)

    def _on_approve_toggled(self, checked: bool):
        self.is_approved = checked
        self._update_style()
        self.approved_toggled.emit(self.index, checked)

    def _on_name_changed(self, text: str):
        self.proposed_filename = text.strip()
        self.name_changed.emit(self.index, self.proposed_filename)

    def _update_style(self):
        border_col = THEME_COLORS["accent_primary"] if self.is_approved else THEME_COLORS["border_subtle"]
        bg_col = THEME_COLORS["bg_card"] if self.is_approved else THEME_COLORS["bg_main"]
        opacity = "1.0" if self.is_approved else "0.5"

        self.setStyleSheet(f"""
            QFrame#preview_card {{
                background-color: {bg_col};
                border: 1px solid {border_col};
                border-radius: 6px;
                opacity: {opacity};
            }}
        """)

    def get_export_info(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "region": self.region,
            "filename": self.txt_filename.text().strip(),
            "cropped_img": self.cropped_img,
            "approved": self.is_approved,
            "padding": self.padding,
        }


class ExtractionPreviewDialog(QDialog):
    """
    Modal dialog displaying all proposed crops before writing any file to disk.
    Allows approval, filename adjustments, padding modification, and safe extraction.
    """

    extraction_completed = Signal(dict)  # summary dict

    def __init__(
        self,
        source_asset: Dict[str, Any],
        regions: List[Dict[str, Any]],
        default_padding: int = 8,
        parent=None,
    ):
        super().__init__(parent)
        self.source_asset = source_asset
        self.regions = regions or []
        self.padding = default_padding
        self.cards: List[ExtractedAssetPreviewCard] = []

        self.setWindowTitle("Extraction Preview & Export Approval — Construction Asset Processor")
        self.resize(960, 680)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME_COLORS['bg_main']};
                color: {THEME_COLORS['text_primary']};
            }}
        """)

        # Ensure output folder
        self.output_dir = Path("output/separated").resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._setup_ui()
        self._generate_previews()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Header
        header = QHBoxLayout()
        v_title = QVBoxLayout()
        lbl_title = QLabel("EXTRACTION PREVIEW & APPROVAL")
        lbl_title.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        v_title.addWidget(lbl_title)

        src_name = self.source_asset.get("filename", "unknown.png")
        comp_type = self.source_asset.get("splitter_composition_type", "Collection")
        self.lbl_subtitle = QLabel(
            f"Source: {src_name} • Composition: {comp_type} • {len(self.regions)} Candidate Regions"
        )
        self.lbl_subtitle.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        v_title.addWidget(self.lbl_subtitle)
        header.addLayout(v_title)

        header.addStretch()

        # Destination Folder Selector
        v_dest = QVBoxLayout()
        lbl_dest_tag = QLabel("Export Destination Folder:")
        lbl_dest_tag.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {THEME_COLORS['text_muted']};")
        v_dest.addWidget(lbl_dest_tag)

        h_dest = QHBoxLayout()
        self.lbl_dest_path = QLabel(str(self.output_dir))
        self.lbl_dest_path.setStyleSheet(f"""
            font-size: 11px;
            color: {THEME_COLORS['text_primary']};
            background-color: {THEME_COLORS['bg_input']};
            border: 1px solid {THEME_COLORS['border_medium']};
            border-radius: 4px;
            padding: 4px 8px;
        """)
        h_dest.addWidget(self.lbl_dest_path)

        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet(self._btn_secondary_style())
        btn_browse.clicked.connect(self._browse_output_dir)
        h_dest.addWidget(btn_browse)
        v_dest.addLayout(h_dest)
        header.addLayout(v_dest)

        main_layout.addLayout(header)

        # 2. Controls Toolbar
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(8)

        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setStyleSheet(self._btn_secondary_style())
        self.btn_select_all.clicked.connect(self._select_all)
        ctrl_bar.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_deselect_all.setStyleSheet(self._btn_secondary_style())
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        ctrl_bar.addWidget(self.btn_deselect_all)

        ctrl_bar.addSpacing(12)

        lbl_pad = QLabel("Padding:")
        lbl_pad.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['text_secondary']};")
        ctrl_bar.addWidget(lbl_pad)

        self.cmb_padding = QComboBox()
        self.cmb_padding.addItems(["0 px", "4 px", "8 px", "16 px", "32 px"])
        # Set default index
        pad_map = {0: 0, 4: 1, 8: 2, 16: 3, 32: 4}
        self.cmb_padding.setCurrentIndex(pad_map.get(self.padding, 2))
        self.cmb_padding.setStyleSheet(self._combo_style())
        self.cmb_padding.currentIndexChanged.connect(self._on_padding_changed)
        ctrl_bar.addWidget(self.cmb_padding)

        ctrl_bar.addSpacing(12)

        lbl_fmt = QLabel("Format:")
        lbl_fmt.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {THEME_COLORS['text_secondary']};")
        ctrl_bar.addWidget(lbl_fmt)

        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["PNG (Lossless)", "WebP (Lossless)"])
        self.cmb_format.setStyleSheet(self._combo_style())
        ctrl_bar.addWidget(self.cmb_format)

        ctrl_bar.addStretch()

        self.lbl_selected_summary = QLabel(f"Approved: {len(self.regions)} / {len(self.regions)}")
        self.lbl_selected_summary.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
        """)
        ctrl_bar.addWidget(self.lbl_selected_summary)

        main_layout.addLayout(ctrl_bar)

        # 3. Scrollable Grid Area for Asset Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']};")

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']};")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(6, 6, 6, 6)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        scroll.setWidget(self.grid_container)
        main_layout.addWidget(scroll, stretch=1)

        # 4. Bottom Action Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(10)

        lbl_safety = QLabel("🛡️ Source files remain 100% untouched. Exports are saved to output/separated/.")
        lbl_safety.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        bottom_bar.addWidget(lbl_safety)

        bottom_bar.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(self._btn_secondary_style())
        btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_cancel)

        self.btn_export = QPushButton("✂️ Export Approved Assets")
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                border: none;
                border-radius: 4px;
                padding: 8px 18px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_muted']};
            }}
        """)
        self.btn_export.clicked.connect(self._do_export)
        bottom_bar.addWidget(self.btn_export)

        main_layout.addLayout(bottom_bar)

    def _generate_previews(self):
        """Generate cropped previews for all regions."""
        # Clear existing cards
        for card in self.cards:
            card.deleteLater()
        self.cards.clear()

        orig_path = self.source_asset.get("original_path")
        if not orig_path or not Path(orig_path).exists():
            QMessageBox.warning(self, "Image Missing", "Original image file could not be found.")
            return

        try:
            with Image.open(orig_path) as full_img:
                src_stem = Path(orig_path).stem
                ext = ".png"

                cols_per_row = 4
                for idx, reg in enumerate(self.regions):
                    # Crop region using engine's extract_region logic
                    bx = reg.get("x", 0)
                    by = reg.get("y", 0)
                    bw = reg.get("width", 0)
                    bh = reg.get("height", 0)

                    cropped = collection_splitter_engine.extract_region(
                        full_img, bx, by, bw, bh, padding=self.padding
                    )

                    reg_type = reg.get("region_type", "isolated_asset")
                    if reg_type == "sprite_frame":
                        p_name = f"{src_stem}_frame_{idx + 1:02d}{ext}"
                    else:
                        p_name = f"{src_stem}_part_{idx + 1:02d}{ext}"

                    card = ExtractedAssetPreviewCard(
                        index=idx,
                        source_asset=self.source_asset,
                        region=reg,
                        cropped_img=cropped,
                        proposed_filename=p_name,
                        padding=self.padding,
                        parent=self.grid_container,
                    )
                    card.approved_toggled.connect(self._on_card_approval_toggled)

                    row = idx // cols_per_row
                    col = idx % cols_per_row
                    self.grid_layout.addWidget(card, row, col)
                    self.cards.append(card)

            self._update_approval_summary()

        except Exception as e:
            logger.error("Failed to generate extraction preview: %s", e)
            QMessageBox.critical(self, "Preview Error", f"Failed generating crop preview: {e}")

    def _on_padding_changed(self, index: int):
        pad_values = [0, 4, 8, 16, 32]
        self.padding = pad_values[index]
        self._generate_previews()

    def _on_card_approval_toggled(self, idx: int, checked: bool):
        self._update_approval_summary()

    def _select_all(self):
        for card in self.cards:
            card.chk_approve.setChecked(True)
        self._update_approval_summary()

    def _deselect_all(self):
        for card in self.cards:
            card.chk_approve.setChecked(False)
        self._update_approval_summary()

    def _update_approval_summary(self):
        approved_count = sum(1 for c in self.cards if c.is_approved)
        total = len(self.cards)
        self.lbl_selected_summary.setText(f"Approved: {approved_count} / {total}")
        self.btn_export.setEnabled(approved_count > 0)

    def _browse_output_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Destination Folder for Extracted Assets", str(self.output_dir)
        )
        if folder:
            self.output_dir = Path(folder)
            self.lbl_dest_path.setText(str(self.output_dir))

    def _do_export(self):
        """Export all approved crops to output folder and record provenance in SQLite."""
        approved_cards = [c for c in self.cards if c.is_approved]
        if not approved_cards:
            QMessageBox.information(self, "No Assets Approved", "Please approve at least one asset to export.")
            return

        fmt_choice = self.cmb_format.currentText()
        use_webp = "WebP" in fmt_choice

        exported_files = []
        errors = []

        for card in approved_cards:
            info = card.get_export_info()
            crop = info["cropped_img"]
            reg = info["region"]
            base_fname = info["filename"]

            if use_webp and not base_fname.lower().endswith(".webp"):
                base_fname = Path(base_fname).stem + ".webp"
            elif not use_webp and not base_fname.lower().endswith(".png"):
                base_fname = Path(base_fname).stem + ".png"

            success, out_path, err = collection_splitter_engine.export_extracted_asset(
                cropped_img=crop,
                source_asset_id=self.source_asset["id"],
                source_region_id=reg.get("id"),
                proposed_filename=base_fname,
                output_folder=str(self.output_dir),
                frame_index=info["index"],
                padding=info["padding"],
            )

            if success and out_path:
                exported_files.append(out_path)
            else:
                errors.append(f"{base_fname}: {err}")

        # Update source asset extraction status in SQLite
        db.update_asset(self.source_asset["id"], {
            "splitter_extraction_status": "extracted",
            "extracted_assets_count": len(exported_files),
        })

        summary = {
            "source_asset_id": self.source_asset["id"],
            "total_approved": len(approved_cards),
            "exported_count": len(exported_files),
            "errors": errors,
            "output_folder": str(self.output_dir),
            "exported_files": exported_files,
        }

        self.extraction_completed.emit(summary)

        msg = f"Successfully exported {len(exported_files)} asset{'s' if len(exported_files) != 1 else ''} to:\n{self.output_dir}"
        if errors:
            msg += f"\n\nEncountered {len(errors)} error(s):\n" + "\n".join(errors[:5])

        reply = QMessageBox.information(
            self,
            "Export Completed",
            msg,
            QMessageBox.Open | QMessageBox.Ok,
            QMessageBox.Ok,
        )

        if reply == QMessageBox.Open:
            try:
                os.startfile(str(self.output_dir))
            except Exception:
                pass

        self.accept()

    def _btn_secondary_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['bg_card_hover']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_primary']};
                selection-background-color: {THEME_COLORS['accent_primary']};
                selection-color: {THEME_COLORS['text_inverse']};
            }}
        """
