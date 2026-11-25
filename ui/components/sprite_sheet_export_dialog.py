"""
Sprite Sheet Export Dialog Component (Stage 9)
Construction Asset Processor

Modal configuration and execution dialog for exporting:
1. Individual lossless PNG frames with full alpha transparency preserved
2. Animation sequence frames organized by animation name
3. Flutter + Flame documented JSON metadata specification
4. Collision protection (auto-increment, skip, or overwrite with confirmation)

Strictly non-destructive:
- Never modifies original source images.
- Never overwrites original files without user permission.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS, format_bytes
from core.database import db
from core.sprite_sheet_engine import sprite_sheet_engine

logger = logging.getLogger("AssetProcessor.SpriteSheetExportDialog")


class SpriteSheetExportDialog(QDialog):
    """
    Modal dialog allowing users to review frames, configure export directories,
    choose naming templates, and export frames and Flame JSON metadata.
    """

    def __init__(
        self,
        sheet_def: Dict[str, Any],
        frames: List[Dict[str, Any]],
        animations: Optional[List[Dict[str, Any]]] = None,
        source_asset: Optional[Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.sheet_def = sheet_def
        self.frames = frames
        self.animations = animations or []
        self.source_asset = source_asset

        self.setWindowTitle("Export Sprite Sheet & Flame Metadata — Stage 9")
        self.setMinimumSize(560, 520)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME_COLORS['bg_main']};
                color: {THEME_COLORS['text_primary']};
            }}
        """)

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Header Card
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        hdr_layout = QVBoxLayout(hdr_frame)
        hdr_layout.setSpacing(4)

        lbl_title = QLabel("EXPORT SPRITE SHEET ASSETS")
        lbl_title.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
        """)
        hdr_layout.addWidget(lbl_title)

        source_name = self.sheet_def.get("source_filename", "sprite_sheet.png")
        sheet_w = self.sheet_def.get("sheet_width", 0)
        sheet_h = self.sheet_def.get("sheet_height", 0)
        lbl_sub = QLabel(f"Source: {source_name} ({sheet_w} × {sheet_h} px) — {len(self.frames)} frames defined")
        lbl_sub.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        hdr_layout.addWidget(lbl_sub)

        main_layout.addWidget(hdr_frame)

        # 2. Export Targets & Options
        opts_group = QGroupBox("Export Configuration")
        opts_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 11px;
                font-weight: 700;
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 10px;
                background-color: {THEME_COLORS['bg_card']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        opts_layout = QVBoxLayout(opts_group)
        opts_layout.setContentsMargins(10, 10, 10, 10)
        opts_layout.setSpacing(10)

        # A. Frames Option
        self.chk_export_frames = QCheckBox("Export Individual Lossless PNG Frames")
        self.chk_export_frames.setChecked(True)
        self.chk_export_frames.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_primary']};")
        opts_layout.addWidget(self.chk_export_frames)

        frame_opts_grid = QGridLayout()
        frame_opts_grid.setContentsMargins(16, 0, 0, 0)
        frame_opts_grid.setSpacing(6)

        frame_opts_grid.addWidget(QLabel("Frame Selection:"), 0, 0)
        self.combo_scope = QComboBox()
        self.combo_scope.addItem(f"All Frames ({len(self.frames)})", "all")
        if self.animations:
            for anim in self.animations:
                self.combo_scope.addItem(f"Animation: {anim.get('name')}", f"anim_{anim.get('name')}")
        frame_opts_grid.addWidget(self.combo_scope, 0, 1)

        frame_opts_grid.addWidget(QLabel("Filename Pattern:"), 1, 0)
        self.edit_pattern = QLineEdit("{sheet_name}_frame_{index:03d}")
        self.edit_pattern.setToolTip("Tokens available: {sheet_name}, {index:03d}, {frame_name}")
        frame_opts_grid.addWidget(self.edit_pattern, 1, 1)

        opts_layout.addLayout(frame_opts_grid)

        # B. Flame Metadata Option
        self.chk_export_metadata = QCheckBox("Export Flutter + Flame Animation JSON Metadata")
        self.chk_export_metadata.setChecked(True)
        self.chk_export_metadata.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_primary']};")
        opts_layout.addWidget(self.chk_export_metadata)

        meta_info = QLabel("Generates flame_animation.json specifying grid dimensions, individual frame coordinates, pivot anchors, and animation sequences.")
        meta_info.setWordWrap(True)
        meta_info.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']}; margin-left: 16px;")
        opts_layout.addWidget(meta_info)

        # C. Collision Resolution
        lbl_conflict = QLabel("Filename Collision Handling:")
        lbl_conflict.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_secondary']}; margin-top: 6px;")
        opts_layout.addWidget(lbl_conflict)

        conflict_layout = QHBoxLayout()
        conflict_layout.setContentsMargins(16, 0, 0, 0)

        self.btn_group_collision = QButtonGroup(self)
        self.rad_increment = QRadioButton("Auto-Increment Suffix (_01, _02)")
        self.rad_increment.setChecked(True)
        self.rad_skip = QRadioButton("Skip Existing Files")
        self.rad_overwrite = QRadioButton("Overwrite Existing")

        self.btn_group_collision.addButton(self.rad_increment)
        self.btn_group_collision.addButton(self.rad_skip)
        self.btn_group_collision.addButton(self.rad_overwrite)

        conflict_layout.addWidget(self.rad_increment)
        conflict_layout.addWidget(self.rad_skip)
        conflict_layout.addWidget(self.rad_overwrite)
        opts_layout.addLayout(conflict_layout)

        main_layout.addWidget(opts_group)

        # 3. Destination Folders Summary
        dest_group = QGroupBox("Target Directories")
        dest_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 11px;
                font-weight: 700;
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 10px;
                background-color: {THEME_COLORS['bg_card']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        dest_layout = QVBoxLayout(dest_group)
        dest_layout.setContentsMargins(10, 8, 10, 8)
        dest_layout.setSpacing(4)

        dest_frames = QLabel(f"• Frames: {sprite_sheet_engine.output_frames_dir}")
        dest_frames.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']}; font-family: Consolas;")
        dest_layout.addWidget(dest_frames)

        dest_meta = QLabel(f"• Metadata: {sprite_sheet_engine.output_meta_dir}")
        dest_meta.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']}; font-family: Consolas;")
        dest_layout.addWidget(dest_meta)

        main_layout.addWidget(dest_group)

        # 4. Progress & Status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                height: 14px;
                text-align: center;
                font-size: 10px;
                color: {THEME_COLORS['text_primary']};
            }}
            QProgressBar::chunk {{
                background-color: {THEME_COLORS['accent_primary']};
                border-radius: 3px;
            }}
        """)
        main_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ready to export.")
        self.lbl_status.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_secondary']};")
        main_layout.addWidget(self.lbl_status)

        # 5. Buttons Row
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_export = QPushButton("Export Now")
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                border: none;
                border-radius: 4px;
                padding: 6px 18px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
            QPushButton:pressed {{
                background-color: {THEME_COLORS['accent_pressed']};
            }}
        """)
        self.btn_export.clicked.connect(self._run_export)
        btn_row.addWidget(self.btn_export)

        main_layout.addLayout(btn_row)

    def _run_export(self):
        """Execute the configured export actions safely."""
        if not self.chk_export_frames.isChecked() and not self.chk_export_metadata.isChecked():
            QMessageBox.warning(self, "No Export Selected", "Please select at least one export target (Frames or Metadata).")
            return

        source_path = self.sheet_def.get("source_image_path")
        if not source_path or not Path(source_path).exists():
            QMessageBox.critical(self, "Source Not Found", f"Source sprite sheet image not found on disk:\n{source_path}")
            return

        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.lbl_status.setText("Processing frames...")

        # Determine collision mode
        if self.rad_overwrite.isChecked():
            collision_mode = "overwrite"
        elif self.rad_skip.isChecked():
            collision_mode = "skip"
        else:
            collision_mode = "increment"

        exported_frames_result = []
        exported_metadata_path = None

        try:
            # 1. Export Frames
            if self.chk_export_frames.isChecked():
                self.progress_bar.setValue(30)
                pattern = self.edit_pattern.text().strip() or "{sheet_name}_frame_{index:03d}"
                exported_frames_result = sprite_sheet_engine.export_individual_frames(
                    source_image_path=source_path,
                    frames=self.frames,
                    output_dir=sprite_sheet_engine.output_frames_dir,
                    filename_pattern=pattern,
                    collision_mode=collision_mode,
                )
                self.progress_bar.setValue(70)

            # 2. Export Metadata
            if self.chk_export_metadata.isChecked():
                self.lbl_status.setText("Writing Flutter + Flame JSON metadata...")
                exported_metadata_path = sprite_sheet_engine.export_flutter_flame_metadata(
                    sheet_def=self.sheet_def,
                    frames=self.frames,
                    animations=self.animations,
                    output_dir=sprite_sheet_engine.output_meta_dir,
                )
                self.progress_bar.setValue(95)

            # 3. Update database status
            sheet_id = self.sheet_def.get("id")
            if sheet_id:
                db.update_sprite_sheet_definition(sheet_id, status="ready")

            self.progress_bar.setValue(100)
            self.lbl_status.setText("Export completed successfully!")

            msg = f"Export finished successfully!\n\n"
            if exported_frames_result:
                msg += f"• Frames Exported: {len(exported_frames_result)} PNG images\n  Location: {sprite_sheet_engine.output_frames_dir}\n\n"
            if exported_metadata_path:
                msg += f"• Flame JSON Metadata: {Path(exported_metadata_path).name}\n  Location: {sprite_sheet_engine.output_meta_dir}\n"

            reply = QMessageBox.information(
                self,
                "Export Complete",
                msg,
                QMessageBox.Ok | QMessageBox.Open,
                QMessageBox.Ok,
            )

            if reply == QMessageBox.Open:
                target_dir = sprite_sheet_engine.output_frames_dir if exported_frames_result else sprite_sheet_engine.output_meta_dir
                self._open_in_file_explorer(target_dir)

            self.accept()

        except Exception as e:
            logger.error("Export failed with error: %s", e, exc_info=True)
            QMessageBox.critical(self, "Export Failed", f"An error occurred during export:\n{e}")
            self.lbl_status.setText("Export failed.")
        finally:
            self.btn_export.setEnabled(True)
            self.btn_cancel.setEnabled(True)

    def _open_in_file_explorer(self, folder_path: Path):
        """Open the target directory in Windows Explorer safely."""
        try:
            if folder_path.exists():
                os.startfile(folder_path)
        except Exception as e:
            logger.warning("Failed to open explorer for %s: %s", folder_path, e)
