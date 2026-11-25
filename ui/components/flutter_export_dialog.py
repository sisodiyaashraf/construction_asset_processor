"""
Flutter Export Dialog Component (Stage 10)
Construction Asset Processor

Modal configuration and execution dialog for deploying assets to a Flutter + Flame project:
1. Validates Flutter project directory (detects pubspec.yaml)
2. Configures hierarchical asset export folders (assets/images, assets/spritesheets, assets/atlases, assets/metadata)
3. Generates Flame unified asset manifest
4. Updates pubspec.yaml with automated timestamped backup or generates standalone snippet
5. Staging-based atomic file transfer with rollback protection
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QTextEdit, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db
from core.export_manifest_engine import export_manifest_engine
from core.flutter_export_engine import flutter_export_engine

logger = logging.getLogger("AssetProcessor.FlutterExportDialog")


class PubspecPreviewDialog(QDialog):
    """Simple dialog showing preview of pubspec.yaml modifications."""

    def __init__(self, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview pubspec.yaml Asset Declarations")
        self.setMinimumSize(550, 420)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME_COLORS['bg_main']};
                color: {THEME_COLORS['text_primary']};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        lbl = QLabel("Asset declarations that will be inserted under 'flutter: -> assets:'")
        lbl.setStyleSheet(f"color: {THEME_COLORS['text_secondary']}; font-size: 11px;")
        layout.addWidget(lbl)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(content)
        txt.setStyleSheet(f"""
            QTextEdit {{
                background-color: {THEME_COLORS['bg_input']};
                color: #A7F3D0;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(txt)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


class FlutterExportDialog(QDialog):
    """Modal dialog allowing users to deploy approved assets into a Flutter project."""

    export_completed = Signal(dict)

    def __init__(self, candidate_assets: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.candidate_assets = candidate_assets
        self.flutter_root: Optional[Path] = None

        self.setWindowTitle("Export to Flutter + Flame Pipeline — Stage 10")
        self.setMinimumSize(600, 520)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME_COLORS['bg_main']};
                color: {THEME_COLORS['text_primary']};
            }}
        """)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Header Card
        header = QLabel("DEPLOY ASSETS TO FLUTTER + FLAME")
        header.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        layout.addWidget(header)

        # 2. Project Directory Selector
        dir_box = QGroupBox("Target Flutter Project Directory")
        dir_box.setStyleSheet(f"""
            QGroupBox {{
                color: {THEME_COLORS['text_primary']};
                font-weight: 700;
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 10px;
            }}
        """)
        dir_layout = QVBoxLayout(dir_box)

        picker_layout = QHBoxLayout()
        self.txt_project_path = QLineEdit()
        self.txt_project_path.setPlaceholderText("Select root directory of your Flutter application...")
        self.txt_project_path.textChanged.connect(self._validate_flutter_directory)
        self.txt_project_path.setStyleSheet(f"""
            QLineEdit {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                color: white;
                padding: 6px;
                font-size: 11px;
            }}
        """)
        picker_layout.addWidget(self.txt_project_path)

        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_card_hover']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                padding: 6px 12px;
                border-radius: 4px;
            }}
        """)
        btn_browse.clicked.connect(self._browse_directory)
        picker_layout.addWidget(btn_browse)
        dir_layout.addLayout(picker_layout)

        # Status badge for flutter project
        self.lbl_dir_status = QLabel("⚠️ Please select a Flutter project containing pubspec.yaml")
        self.lbl_dir_status.setStyleSheet("color: #F59E0B; font-size: 10px; font-weight: 600;")
        dir_layout.addWidget(self.lbl_dir_status)

        layout.addWidget(dir_box)

        # 3. Content Selection Group
        content_box = QGroupBox("Assets to Deploy")
        content_box.setStyleSheet(dir_box.styleSheet())
        c_layout = QVBoxLayout(content_box)

        self.chk_images = QCheckBox(f"Approved Game Images ({len(self.candidate_assets)} assets ready)")
        self.chk_images.setChecked(True)
        c_layout.addWidget(self.chk_images)

        self.chk_atlases = QCheckBox("Texture Atlases & Sprite Coordinates")
        self.chk_atlases.setChecked(True)
        c_layout.addWidget(self.chk_atlases)

        self.chk_manifest = QCheckBox("Flame Unified Asset Manifest (flame_asset_manifest.json)")
        self.chk_manifest.setChecked(True)
        c_layout.addWidget(self.chk_manifest)

        layout.addWidget(content_box)

        # 4. pubspec.yaml Integration Options
        pub_box = QGroupBox("pubspec.yaml Integration")
        pub_box.setStyleSheet(dir_box.styleSheet())
        p_layout = QVBoxLayout(pub_box)

        self.radio_update_pubspec = QRadioButton("Automatically update pubspec.yaml (Creates timestamped backup first)")
        self.radio_update_pubspec.setChecked(True)
        p_layout.addWidget(self.radio_update_pubspec)

        self.radio_snippet_only = QRadioButton("Generate standalone pubspec_assets_snippet.yaml (No pubspec edit)")
        p_layout.addWidget(self.radio_snippet_only)

        btn_preview_pub = QPushButton("Preview Asset Declarations")
        btn_preview_pub.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {THEME_COLORS['accent_secondary']};
                text-decoration: underline;
                font-size: 11px;
                text-align: left;
                padding: 2px 0;
            }}
        """)
        btn_preview_pub.clicked.connect(self._preview_pubspec)
        p_layout.addWidget(btn_preview_pub)

        layout.addWidget(pub_box)

        # 5. Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_progress_msg = QLabel("")
        self.lbl_progress_msg.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 10px;")
        layout.addWidget(self.lbl_progress_msg)

        # 6. Action Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_deploy = QPushButton("🚀 Deploy to Flutter")
        self.btn_deploy.setEnabled(False)
        self.btn_deploy.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                padding: 8px 18px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: #374151;
                color: #9CA3AF;
            }}
        """)
        self.btn_deploy.clicked.connect(self._execute_deployment)
        btn_row.addWidget(self.btn_deploy)

        layout.addLayout(btn_row)

    def _browse_directory(self):
        """Pick a folder from file dialog."""
        folder = QFileDialog.getExistingDirectory(self, "Select Flutter Project Directory")
        if folder:
            self.txt_project_path.setText(folder)

    def _validate_flutter_directory(self, path_str: str):
        """Validate if directory contains a Flutter pubspec.yaml file."""
        p = Path(path_str.strip())
        if not p.exists() or not p.is_dir():
            self.lbl_dir_status.setText("⚠️ Invalid directory path")
            self.lbl_dir_status.setStyleSheet("color: #EF4444; font-size: 10px; font-weight: 600;")
            self.btn_deploy.setEnabled(False)
            self.flutter_root = None
            return

        pubspec = p / "pubspec.yaml"
        if not pubspec.exists():
            self.lbl_dir_status.setText("⚠️ No pubspec.yaml found in selected folder. (Must be a Flutter project root)")
            self.lbl_dir_status.setStyleSheet("color: #F59E0B; font-size: 10px; font-weight: 600;")
            self.btn_deploy.setEnabled(False)
            self.flutter_root = None
            return

        self.lbl_dir_status.setText(f"✓ Valid Flutter Project: {p.name}")
        self.lbl_dir_status.setStyleSheet("color: #10B981; font-size: 10px; font-weight: 600;")
        self.btn_deploy.setEnabled(True)
        self.flutter_root = p

    def _preview_pubspec(self):
        """Preview pubspec asset declarations snippet."""
        snippet = export_manifest_engine.generate_pubspec_snippet()
        dlg = PubspecPreviewDialog(snippet, self)
        dlg.exec()

    def _execute_deployment(self):
        """Deploy assets atomically to Flutter project."""
        if not self.flutter_root:
            return

        self.btn_deploy.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.lbl_progress_msg.setText("Preparing asset deployment staging...")

        # 1. Prepare asset payload
        asset_payload = []
        for a in self.candidate_assets:
            p = a.get("original_path") or a.get("filepath")
            cat = a.get("category") or "objects"
            name = a.get("smart_filename") or a.get("filename") or f"asset_{a['id']}.png"
            if p and Path(p).exists():
                asset_payload.append({
                    "id": a["id"],
                    "path": p,
                    "target_name": name,
                    "category": cat,
                    "sub_folder": "images",
                })

        # 2. Add texture atlases if requested
        if self.chk_atlases.isChecked():
            atlases = db.get_all_texture_atlases()
            for atl in atlases:
                tex = atl.get("texture_path")
                man = atl.get("json_manifest_path")
                if tex and Path(tex).exists():
                    asset_payload.append({
                        "path": tex,
                        "target_name": Path(tex).name,
                        "sub_folder": "atlases",
                    })
                if man and Path(man).exists():
                    asset_payload.append({
                        "path": man,
                        "target_name": Path(man).name,
                        "sub_folder": "atlases",
                    })

        self.progress_bar.setValue(35)
        self.lbl_progress_msg.setText(f"Staging {len(asset_payload)} assets...")

        # 3. Create job in database
        job_id = db.create_flutter_export_job(
            flutter_project_path=str(self.flutter_root),
            target_asset_folder="assets",
            total_assets=len(asset_payload),
        )

        # 4. Deploy via FlutterExportEngine
        update_pub = self.radio_update_pubspec.isChecked()
        res = flutter_export_engine.deploy_assets_to_flutter(
            flutter_root=self.flutter_root,
            assets_to_deploy=asset_payload,
            update_pubspec=update_pub,
            collision_strategy="increment",
        )

        self.progress_bar.setValue(75)

        # 5. Generate flame manifest if checked
        if self.chk_manifest.isChecked() and res.get("success"):
            flame_man_path = self.flutter_root / "assets" / "metadata" / "flame_asset_manifest.json"
            flame_man_path.parent.mkdir(parents=True, exist_ok=True)
            export_manifest_engine.generate_flame_manifest(
                output_path=flame_man_path,
                exported_assets=asset_payload,
                version="1.0.0",
            )

        self.progress_bar.setValue(100)

        # 6. Update database job
        status = "completed" if res.get("success") else "failed"
        db.update_flutter_export_job(
            job_id=job_id,
            status=status,
            exported_count=res.get("deployed_count", 0),
            pubspec_updated=update_pub and res.get("pubspec_updated", False),
            backup_path=res.get("pubspec_backup"),
            error_message=res.get("error"),
        )

        self.export_completed.emit(res)

        if res.get("success"):
            msg = (
                f"Successfully exported {res['deployed_count']} assets to {self.flutter_root.name}!\n\n"
                f"Assets directory: assets/\n"
            )
            if res.get("pubspec_updated"):
                msg += f"pubspec.yaml updated (Backup: {Path(res['pubspec_backup']).name})\n"
            elif not update_pub:
                msg += "Standalone snippet saved to assets/pubspec_assets_snippet.yaml\n"

            QMessageBox.information(self, "Export Complete", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "Export Failed", f"Asset deployment failed:\n{res.get('error')}")
            self.btn_deploy.setEnabled(True)
