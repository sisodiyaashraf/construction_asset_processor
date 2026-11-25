"""
Optimization Inspector Component (Stage 10)
Construction Asset Processor

Right-side inspector panel for the Asset Optimization & Flutter Export pipeline.
Features:
- Asset metadata & dimensions inspection
- Target format selection (Lossless PNG, Lossless WebP, Lossy WebP, Progressive JPEG)
- Compression quality sliders and scaling options with aspect ratio lock
- Transparent margin detection and trimming controls with padding
- Single-asset optimization runner and export approval toggling
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QVBoxLayout, QWidget
)

from app.config import OUTPUT_OPTIMIZED_DIR, THEME_COLORS, format_bytes
from core.asset_optimizer import asset_optimizer
from core.asset_validator import asset_validator
from core.database import db

logger = logging.getLogger("AssetProcessor.OptimizationInspector")


class OptimizationInspector(QWidget):
    """Right-side inspector dedicated to Stage 10 asset optimization controls."""

    asset_optimized = Signal(int, dict)
    export_approval_changed = Signal(int, bool)
    validation_requested = Signal(int)
    refresh_needed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("optimization_inspector")
        self.current_asset: Optional[Dict[str, Any]] = None
        self._updating_dimensions = False

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 1. Header
        header_layout = QHBoxLayout()
        header_title = QLabel("OPTIMIZATION INSPECTOR")
        header_title.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        header_layout.addWidget(header_title)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # 2. Scroll Area for Inspector Sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # A. Asset Metadata Box
        meta_box = QGroupBox("Selected Asset")
        meta_box.setStyleSheet(f"""
            QGroupBox {{
                font-weight: 700;
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        meta_layout = QGridLayout(meta_box)
        meta_layout.setSpacing(6)

        self.lbl_name = QLabel("No asset selected")
        self.lbl_name.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 600; font-size: 11px;")
        self.lbl_name.setWordWrap(True)
        meta_layout.addWidget(QLabel("Name:"), 0, 0)
        meta_layout.addWidget(self.lbl_name, 0, 1)

        self.lbl_res = QLabel("—")
        self.lbl_res.setStyleSheet(f"color: {THEME_COLORS['text_secondary']};")
        meta_layout.addWidget(QLabel("Original:"), 1, 0)
        meta_layout.addWidget(self.lbl_res, 1, 1)

        self.lbl_size = QLabel("—")
        self.lbl_size.setStyleSheet(f"color: {THEME_COLORS['text_secondary']};")
        meta_layout.addWidget(QLabel("Size:"), 2, 0)
        meta_layout.addWidget(self.lbl_size, 2, 1)

        self.lbl_opt_size = QLabel("Not optimized")
        self.lbl_opt_size.setStyleSheet("color: #10B981; font-weight: 600;")
        meta_layout.addWidget(QLabel("Optimized:"), 3, 0)
        meta_layout.addWidget(self.lbl_opt_size, 3, 1)

        layout.addWidget(meta_box)

        # B. Optimization Settings Box
        opt_box = QGroupBox("Optimization Parameters")
        opt_box.setStyleSheet(meta_box.styleSheet())
        opt_layout = QVBoxLayout(opt_box)
        opt_layout.setSpacing(8)

        # Target Format
        opt_layout.addWidget(QLabel("Target Format:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems([
            "PNG (Lossless)",
            "WebP (Lossless)",
            "WebP (Lossy Quality)",
            "JPEG (Progressive)",
        ])
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        opt_layout.addWidget(self.combo_format)

        # Quality Slider (for Lossy WebP and JPEG)
        self.quality_container = QWidget()
        q_layout = QVBoxLayout(self.quality_container)
        q_layout.setContentsMargins(0, 0, 0, 0)
        q_layout.setSpacing(2)

        q_label_row = QHBoxLayout()
        q_label_row.addWidget(QLabel("Quality Level:"))
        self.lbl_quality_val = QLabel("85%")
        self.lbl_quality_val.setStyleSheet(f"color: {THEME_COLORS['accent_primary']}; font-weight: 700;")
        q_label_row.addStretch()
        q_label_row.addWidget(self.lbl_quality_val)
        q_layout.addLayout(q_label_row)

        self.slider_quality = QSlider(Qt.Horizontal)
        self.slider_quality.setRange(10, 100)
        self.slider_quality.setValue(85)
        self.slider_quality.valueChanged.connect(lambda v: self.lbl_quality_val.setText(f"{v}%"))
        q_layout.addWidget(self.slider_quality)
        self.quality_container.setEnabled(False)  # Disabled for default PNG lossless
        opt_layout.addWidget(self.quality_container)

        # Scale Presets
        opt_layout.addWidget(QLabel("Resolution Scaling:"))
        self.combo_scale = QComboBox()
        self.combo_scale.addItems([
            "100% (Original Resolution)",
            "75% Scale",
            "50% Scale",
            "25% Scale",
            "Custom Dimensions",
        ])
        self.combo_scale.currentIndexChanged.connect(self._on_scale_changed)
        opt_layout.addWidget(self.combo_scale)

        # Custom Dimensions Row
        self.custom_dim_widget = QWidget()
        cd_layout = QHBoxLayout(self.custom_dim_widget)
        cd_layout.setContentsMargins(0, 0, 0, 0)
        cd_layout.setSpacing(4)

        cd_layout.addWidget(QLabel("W:"))
        self.spin_width = QSpinBox()
        self.spin_width.setRange(16, 8192)
        self.spin_width.setValue(1024)
        self.spin_width.valueChanged.connect(self._on_width_changed)
        cd_layout.addWidget(self.spin_width)

        cd_layout.addWidget(QLabel("H:"))
        self.spin_height = QSpinBox()
        self.spin_height.setRange(16, 8192)
        self.spin_height.setValue(1024)
        self.spin_height.valueChanged.connect(self._on_height_changed)
        cd_layout.addWidget(self.spin_height)

        self.chk_lock_aspect = QCheckBox("Lock")
        self.chk_lock_aspect.setChecked(True)
        cd_layout.addWidget(self.chk_lock_aspect)
        self.custom_dim_widget.setVisible(False)
        opt_layout.addWidget(self.custom_dim_widget)

        # C. Transparent Margin Trimming
        self.chk_trim_margin = QCheckBox("Trim Transparent Margins")
        self.chk_trim_margin.setToolTip("Crop surrounding transparent pixels while preserving object content and shifting pivot points")
        self.chk_trim_margin.toggled.connect(self._on_trim_toggled)
        opt_layout.addWidget(self.chk_trim_margin)

        self.margin_container = QWidget()
        mc_layout = QVBoxLayout(self.margin_container)
        mc_layout.setContentsMargins(0, 0, 0, 0)
        mc_layout.setSpacing(4)

        pad_row = QHBoxLayout()
        pad_row.addWidget(QLabel("Extra Margin Padding:"))
        self.spin_padding = QSpinBox()
        self.spin_padding.setRange(0, 64)
        self.spin_padding.setValue(2)
        self.spin_padding.setSuffix(" px")
        pad_row.addWidget(self.spin_padding)
        mc_layout.addLayout(pad_row)

        self.lbl_margin_offsets = QLabel("Margin: Not calculated")
        self.lbl_margin_offsets.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 10px;")
        mc_layout.addWidget(self.lbl_margin_offsets)
        self.margin_container.setVisible(False)
        opt_layout.addWidget(self.margin_container)

        layout.addWidget(opt_box)

        # D. Actions Group
        act_box = QGroupBox("Actions")
        act_box.setStyleSheet(meta_box.styleSheet())
        act_layout = QVBoxLayout(act_box)
        act_layout.setSpacing(8)

        self.btn_optimize = QPushButton("⚡ Optimize Asset Copy")
        self.btn_optimize.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                font-size: 11px;
                padding: 8px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
        """)
        self.btn_optimize.clicked.connect(self._optimize_current_asset)
        act_layout.addWidget(self.btn_optimize)

        self.btn_toggle_approval = QPushButton("✓ Approve for Flutter Export")
        self.btn_toggle_approval.setStyleSheet(f"""
            QPushButton {{
                background-color: #10B981;
                color: #FFFFFF;
                font-weight: 700;
                font-size: 11px;
                padding: 6px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #059669;
            }}
        """)
        self.btn_toggle_approval.clicked.connect(self._toggle_export_approval)
        act_layout.addWidget(self.btn_toggle_approval)

        self.btn_validate = QPushButton("🔍 Validate Asset Quality")
        self.btn_validate.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_card_hover']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                font-weight: 600;
                font-size: 11px;
                padding: 6px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_secondary']};
            }}
        """)
        self.btn_validate.clicked.connect(self._validate_current_asset)
        act_layout.addWidget(self.btn_validate)

        layout.addWidget(act_box)
        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def load_asset(self, asset: Optional[Dict[str, Any]]):
        """Load asset data into inspector controls."""
        self.current_asset = asset
        if not asset:
            self.lbl_name.setText("No asset selected")
            self.lbl_res.setText("—")
            self.lbl_size.setText("—")
            self.lbl_opt_size.setText("Not optimized")
            self.btn_optimize.setEnabled(False)
            self.btn_toggle_approval.setEnabled(False)
            self.btn_validate.setEnabled(False)
            return

        self.btn_optimize.setEnabled(True)
        self.btn_toggle_approval.setEnabled(True)
        self.btn_validate.setEnabled(True)

        fname = asset.get("smart_filename") or asset.get("filename") or f"Asset_{asset['id']}"
        self.lbl_name.setText(fname)

        w = asset.get("width") or 0
        h = asset.get("height") or 0
        fmt = (asset.get("format") or "PNG").upper().replace(".", "")
        self.lbl_res.setText(f"{w}x{h} ({fmt})")

        orig_sz = asset.get("file_size") or 0
        self.lbl_size.setText(format_bytes(orig_sz))

        opt_sz = asset.get("optimized_size") or 0
        if opt_sz > 0 and orig_sz > 0:
            saved = max(0.0, (orig_sz - opt_sz) / orig_sz * 100.0)
            self.lbl_opt_size.setText(f"{format_bytes(opt_sz)} (-{saved:.1f}%)")
        else:
            self.lbl_opt_size.setText("Not optimized yet")

        # Update export button text
        is_appr = bool(asset.get("is_approved_for_export", 0) or asset.get("status") == "approved")
        if is_appr:
            self.btn_toggle_approval.setText("✕ Revoke Export Approval")
            self.btn_toggle_approval.setStyleSheet("background-color: #EF4444; color: white; padding: 6px; border-radius: 4px; font-weight: 700;")
        else:
            self.btn_toggle_approval.setText("✓ Approve for Flutter Export")
            self.btn_toggle_approval.setStyleSheet("background-color: #10B981; color: white; padding: 6px; border-radius: 4px; font-weight: 700;")

        # Set spin dimensions
        self._updating_dimensions = True
        self.spin_width.setValue(w if w > 0 else 1024)
        self.spin_height.setValue(h if h > 0 else 1024)
        self._updating_dimensions = False

        # Preview transparent margins
        self._check_margins(asset)

    def _check_margins(self, asset: Dict[str, Any]):
        """Calculate and display transparent margins."""
        path_str = asset.get("original_path") or asset.get("filepath")
        if not path_str or not Path(path_str).exists():
            self.lbl_margin_offsets.setText("Margin: Source file missing")
            return

        try:
            margin_info = asset_optimizer.detect_transparent_margins(path_str)
            if margin_info.get("has_transparency"):
                l = margin_info.get("margin_left", 0)
                t = margin_info.get("margin_top", 0)
                r = margin_info.get("margin_right", 0)
                b = margin_info.get("margin_bottom", 0)
                cw = margin_info.get("content_width", 0)
                ch = margin_info.get("content_height", 0)
                self.lbl_margin_offsets.setText(f"Trim: L:{l} T:{t} R:{r} B:{b} -> {cw}x{ch}")
            else:
                self.lbl_margin_offsets.setText("No alpha transparency detected")
        except Exception as e:
            self.lbl_margin_offsets.setText(f"Margin check error: {str(e)[:30]}")

    def _on_format_changed(self, idx: int):
        """Enable quality slider when lossy formats are chosen."""
        is_lossy = idx in (2, 3)  # WebP lossy or JPEG
        self.quality_container.setEnabled(is_lossy)

    def _on_scale_changed(self, idx: int):
        """Show or hide custom dimensions row."""
        self.custom_dim_widget.setVisible(idx == 4)
        if not self.current_asset:
            return
        orig_w = self.current_asset.get("width") or 1024
        orig_h = self.current_asset.get("height") or 1024

        scales = {0: 1.0, 1: 0.75, 2: 0.5, 3: 0.25}
        if idx in scales:
            factor = scales[idx]
            self._updating_dimensions = True
            self.spin_width.setValue(max(16, int(orig_w * factor)))
            self.spin_height.setValue(max(16, int(orig_h * factor)))
            self._updating_dimensions = False

    def _on_width_changed(self, val: int):
        if self._updating_dimensions or not self.chk_lock_aspect.isChecked() or not self.current_asset:
            return
        orig_w = self.current_asset.get("width") or 1
        orig_h = self.current_asset.get("height") or 1
        aspect = orig_h / orig_w
        self._updating_dimensions = True
        self.spin_height.setValue(max(16, int(val * aspect)))
        self._updating_dimensions = False

    def _on_height_changed(self, val: int):
        if self._updating_dimensions or not self.chk_lock_aspect.isChecked() or not self.current_asset:
            return
        orig_w = self.current_asset.get("width") or 1
        orig_h = self.current_asset.get("height") or 1
        aspect = orig_w / orig_h
        self._updating_dimensions = True
        self.spin_width.setValue(max(16, int(val * aspect)))
        self._updating_dimensions = False

    def _on_trim_toggled(self, checked: bool):
        self.margin_container.setVisible(checked)

    def _optimize_current_asset(self):
        """Execute single-asset optimization copy."""
        if not self.current_asset:
            return

        fmt_idx = self.combo_format.currentIndex()
        fmt_map = {0: "png", 1: "webp", 2: "webp", 3: "jpg"}
        lossless_map = {0: True, 1: True, 2: False, 3: False}
        target_fmt = fmt_map[fmt_idx]
        lossless = lossless_map[fmt_idx]
        quality = self.slider_quality.value()

        # Dimension options
        scale_idx = self.combo_scale.currentIndex()
        custom_w = None
        custom_h = None
        if scale_idx != 0:
            custom_w = self.spin_width.value()
            custom_h = self.spin_height.value()

        trim = self.chk_trim_margin.isChecked()
        pad = self.spin_padding.value() if trim else 0

        path_str = self.current_asset.get("original_path") or self.current_asset.get("filepath")
        if not path_str or not Path(path_str).exists():
            QMessageBox.warning(self, "Missing Asset", "The original asset file could not be located.")
            return

        # Prepare destination copy path
        stem = Path(path_str).stem
        ext = f".{target_fmt}" if target_fmt != "jpg" else ".jpg"
        dest_path = OUTPUT_OPTIMIZED_DIR / f"{stem}_opt{ext}"

        res = asset_optimizer.optimize_asset(
            src_path=path_str,
            dest_path=dest_path,
            target_format=target_fmt,
            quality=quality,
            lossless=lossless,
            max_width=custom_w,
            max_height=custom_h,
            trim_transparent_margin=trim,
            margin_padding=pad,
        )

        if res.get("success"):
            # Update database
            db.update_asset(
                self.current_asset["id"],
                optimization_status="optimized",
                optimized_size=res["output_size"],
            )
            db.record_optimization_history(
                asset_id=self.current_asset["id"],
                source_path=path_str,
                optimized_path=str(dest_path),
                original_size=res["input_size"],
                optimized_size=res["output_size"],
                target_format=target_fmt,
                quality=quality,
                scale_factor=res.get("scale_factor", 1.0),
                trimmed_margins=trim,
            )

            # Update view
            self.lbl_opt_size.setText(
                f"{format_bytes(res['output_size'])} (-{res['savings_percent']:.1f}%)"
            )
            self.asset_optimized.emit(self.current_asset["id"], res)
            self.refresh_needed.emit()
            QMessageBox.information(
                self,
                "Optimization Complete",
                f"Asset optimized successfully!\nSaved: {res['savings_percent']:.1f}% ({format_bytes(res['savings_bytes'])})\nOutput: {dest_path.name}"
            )
        else:
            QMessageBox.critical(self, "Optimization Failed", f"Error optimizing asset:\n{res.get('error')}")

    def _toggle_export_approval(self):
        """Toggle approval status for Flutter export."""
        if not self.current_asset:
            return
        curr = bool(self.current_asset.get("is_approved_for_export", 0) or self.current_asset.get("status") == "approved")
        new_val = not curr
        db.set_asset_export_approval(self.current_asset["id"], new_val)
        self.current_asset["is_approved_for_export"] = 1 if new_val else 0
        self.export_approval_changed.emit(self.current_asset["id"], new_val)
        self.load_asset(self.current_asset)
        self.refresh_needed.emit()

    def _validate_current_asset(self):
        """Run validation on current asset."""
        if not self.current_asset:
            return
        path_str = self.current_asset.get("original_path") or self.current_asset.get("filepath")
        if not path_str or not Path(path_str).exists():
            QMessageBox.warning(self, "Missing Asset", "The original asset file could not be located.")
            return

        res = asset_validator.validate_asset(path_str, asset_id=self.current_asset["id"])
        overall = res.get("overall_status", "unchecked")
        issues = res.get("issues", [])

        # Save to database
        db.save_asset_validation_results(
            asset_id=self.current_asset["id"],
            overall_status=overall,
            issues=issues,
        )

        self.validation_requested.emit(self.current_asset["id"])
        self.refresh_needed.emit()

        msg = f"Validation result: {overall.upper()}\nIssues found: {len(issues)}"
        if issues:
            msg += "\n\n" + "\n".join(f"• [{i['severity'].upper()}] {i['message']}" for i in issues[:5])
        QMessageBox.information(self, "Validation Completed", msg)
