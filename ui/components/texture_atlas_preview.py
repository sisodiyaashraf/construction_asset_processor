"""
Texture Atlas Preview Component (Stage 10)
Construction Asset Processor

Interactive dialog and previewer for MaxRects Texture Atlas generation.
Displays the packed atlas with checkerboard transparency, outlines bounding boxes,
displays sprite labels and metrics (efficiency %, unused area %, resolution),
and exports the atlas image copy and Flutter + Flame JSON metadata.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QVBoxLayout, QWidget
)

from app.config import OUTPUT_OPTIMIZED_DIR, THEME_COLORS, format_bytes
from core.database import db
from core.texture_atlas_engine import texture_atlas_engine
from ui.components.comparison_dialog import create_checkerboard_pixmap

logger = logging.getLogger("AssetProcessor.TextureAtlasPreview")


class AtlasCanvasWidget(QWidget):
    """Custom canvas rendering the generated texture atlas with checkerboard and sprite rects."""

    sprite_selected = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.atlas_pixmap: Optional[QPixmap] = None
        self.sprites: List[Dict[str, Any]] = []
        self.zoom: float = 1.0
        self.setMouseTracking(True)
        self.hovered_sprite: Optional[Dict[str, Any]] = None

    def set_atlas_data(self, image_path: str, sprites: List[Dict[str, Any]]):
        """Load atlas image and sprite rectangles."""
        if Path(image_path).exists():
            self.atlas_pixmap = QPixmap(image_path)
            self.sprites = sprites
            self.update_geometry()
            self.update()

    def update_geometry(self):
        if self.atlas_pixmap:
            w = int(self.atlas_pixmap.width() * self.zoom)
            h = int(self.atlas_pixmap.height() * self.zoom)
            self.setFixedSize(w, h)

    def set_zoom(self, zoom: float):
        self.zoom = max(0.1, min(4.0, zoom))
        self.update_geometry()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.atlas_pixmap or self.atlas_pixmap.isNull():
            painter.fillRect(self.rect(), QColor("#121417"))
            painter.setPen(QColor(THEME_COLORS["text_muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "No Atlas Loaded")
            painter.end()
            return

        w = int(self.atlas_pixmap.width() * self.zoom)
        h = int(self.atlas_pixmap.height() * self.zoom)

        # 1. Dark checkerboard
        checker = create_checkerboard_pixmap(20)
        painter.drawTiledPixmap(0, 0, w, h, checker)

        # 2. Draw atlas image
        painter.drawPixmap(0, 0, self.atlas_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        # 3. Draw sprite bounding boxes
        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)

        for s in self.sprites:
            sx = int(s["x"] * self.zoom)
            sy = int(s["y"] * self.zoom)
            sw = int(s["w"] * self.zoom)
            sh = int(s["h"] * self.zoom)

            is_hov = (self.hovered_sprite == s)
            pen_color = QColor(THEME_COLORS["accent_primary"]) if is_hov else QColor("#38BDF8")
            pen = QPen(pen_color, 2 if is_hov else 1)
            painter.setPen(pen)
            painter.drawRect(sx, sy, sw, sh)

            # Draw name tag
            tag_name = s.get("name", "")
            if tag_name:
                painter.fillRect(sx, sy, min(sw, 120), 16, QColor(18, 20, 23, 190))
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(sx + 3, sy + 12, tag_name[:16])

        painter.end()

    def mouseMoveEvent(self, event):
        pos = event.position()
        curr_x = pos.x() / self.zoom
        curr_y = pos.y() / self.zoom

        found = None
        for s in self.sprites:
            if s["x"] <= curr_x <= s["x"] + s["w"] and s["y"] <= curr_y <= s["y"] + s["h"]:
                found = s
                break

        if found != self.hovered_sprite:
            self.hovered_sprite = found
            self.update()
            if found:
                self.sprite_selected.emit(found.get("name", ""), found)
        super().mouseMoveEvent(event)


class TextureAtlasPreviewDialog(QDialog):
    """Dialog to configure, generate, preview, and export a MaxRects Texture Atlas."""

    atlas_created = Signal(dict)

    def __init__(self, candidate_assets: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.candidate_assets = candidate_assets
        self.generated_result: Optional[Dict[str, Any]] = None

        self.setWindowTitle("Generate Texture Atlas — Stage 10")
        self.setMinimumSize(850, 680)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME_COLORS['bg_main']};
                color: {THEME_COLORS['text_primary']};
            }}
        """)

        self._build_ui()

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Left Controls Panel
        left_panel = QFrame()
        left_panel.setFixedWidth(280)
        left_panel.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_sidebar']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)

        left_layout.addWidget(QLabel("Atlas Name:"))
        self.txt_atlas_name = QLineEdit("construction_atlas_1")
        self.txt_atlas_name.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border: 1px solid {THEME_COLORS['border_medium']}; padding: 4px; border-radius: 4px; color: white;")
        left_layout.addWidget(self.txt_atlas_name)

        left_layout.addWidget(QLabel("Max Atlas Dimensions:"))
        self.combo_size = QComboBox()
        self.combo_size.addItems(["512 x 512", "1024 x 1024", "2048 x 2048", "4096 x 4096"])
        self.combo_size.setCurrentIndex(2)  # 2048 default
        left_layout.addWidget(self.combo_size)

        pad_row = QHBoxLayout()
        pad_row.addWidget(QLabel("Padding (px):"))
        self.spin_pad = QSpinBox()
        self.spin_pad.setRange(0, 32)
        self.spin_pad.setValue(2)
        pad_row.addWidget(self.spin_pad)
        left_layout.addLayout(pad_row)

        space_row = QHBoxLayout()
        space_row.addWidget(QLabel("Spacing (px):"))
        self.spin_space = QSpinBox()
        self.spin_space.setRange(0, 32)
        self.spin_space.setValue(2)
        space_row.addWidget(self.spin_space)
        left_layout.addLayout(space_row)

        self.chk_pot = QCheckBox("Force Power-of-Two")
        self.chk_pot.setChecked(True)
        left_layout.addWidget(self.chk_pot)

        self.lbl_item_count = QLabel(f"Selected Assets: {len(self.candidate_assets)}")
        self.lbl_item_count.setStyleSheet(f"color: {THEME_COLORS['accent_secondary']}; font-weight: 700;")
        left_layout.addWidget(self.lbl_item_count)

        btn_pack = QPushButton("⚡ Pack Atlas Preview")
        btn_pack.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                padding: 8px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
        """)
        btn_pack.clicked.connect(self._pack_atlas)
        left_layout.addWidget(btn_pack)

        # Statistics Group
        stats_box = QGroupBox("Atlas Packing Stats")
        stats_box.setStyleSheet(f"color: {THEME_COLORS['text_primary']}; font-weight: 700;")
        s_layout = QVBoxLayout(stats_box)
        s_layout.setSpacing(4)

        self.lbl_stat_res = QLabel("Resolution: —")
        s_layout.addWidget(self.lbl_stat_res)

        self.lbl_stat_count = QLabel("Sprites Packed: 0 / 0")
        s_layout.addWidget(self.lbl_stat_count)

        self.lbl_stat_eff = QLabel("Efficiency: 0.0%")
        self.lbl_stat_eff.setStyleSheet("color: #10B981; font-weight: 700;")
        s_layout.addWidget(self.lbl_stat_eff)

        self.lbl_stat_unused = QLabel("Unused Space: 100.0%")
        s_layout.addWidget(self.lbl_stat_unused)

        left_layout.addWidget(stats_box)
        left_layout.addStretch()

        self.btn_export = QPushButton("✓ Save Atlas & Flame JSON")
        self.btn_export.setEnabled(False)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                font-weight: 700;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9CA3AF;
            }
        """)
        self.btn_export.clicked.connect(self._save_atlas)
        left_layout.addWidget(self.btn_export)

        main_layout.addWidget(left_panel)

        # Right Preview Area
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Zoom Controls
        zoom_bar = QHBoxLayout()
        zoom_bar.addWidget(QLabel("Zoom Preview:"))
        self.slider_zoom = QSlider(Qt.Horizontal)
        self.slider_zoom.setRange(10, 200)
        self.slider_zoom.setValue(50)
        self.slider_zoom.valueChanged.connect(lambda v: self.canvas.set_zoom(v / 100.0))
        zoom_bar.addWidget(self.slider_zoom)
        right_layout.addLayout(zoom_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        self.canvas = AtlasCanvasWidget()
        scroll.setWidget(self.canvas)
        right_layout.addWidget(scroll)

        main_layout.addWidget(right_panel, stretch=1)

    def _pack_atlas(self):
        """Execute texture atlas packing."""
        if not self.candidate_assets:
            QMessageBox.warning(self, "No Assets", "No candidate assets provided to pack.")
            return

        size_map = {0: 512, 1: 1024, 2: 2048, 3: 4096}
        max_dim = size_map.get(self.combo_size.currentIndex(), 2048)
        padding = self.spin_pad.value()
        spacing = self.spin_space.value()
        force_pot = self.chk_pot.isChecked()
        atlas_name = self.txt_atlas_name.text().strip() or "atlas_preview"

        # Prepare sprite inputs
        sprites_input = []
        for a in self.candidate_assets:
            p = a.get("original_path") or a.get("filepath")
            name = a.get("smart_filename") or a.get("filename") or f"sprite_{a['id']}"
            if p and Path(p).exists():
                sprites_input.append({
                    "id": a["id"],
                    "name": Path(name).stem,
                    "path": p,
                })

        # Pack to temporary/preview path in output directory
        preview_img = OUTPUT_OPTIMIZED_DIR / f"{atlas_name}.png"
        preview_json = OUTPUT_OPTIMIZED_DIR / f"{atlas_name}.json"

        res = texture_atlas_engine.pack_sprites_into_atlas(
            sprites=sprites_input,
            output_image_path=preview_img,
            output_json_path=preview_json,
            max_width=max_dim,
            max_height=max_dim,
            padding=padding,
            spacing=spacing,
            force_power_of_two=force_pot,
        )

        if not res.get("success"):
            QMessageBox.critical(self, "Packing Failed", f"Atlas packing failed:\n{res.get('error')}")
            return

        self.generated_result = res
        self.btn_export.setEnabled(True)

        # Update stats
        aw = res["atlas_width"]
        ah = res["atlas_height"]
        self.lbl_stat_res.setText(f"Resolution: {aw} x {ah}")
        self.lbl_stat_count.setText(f"Sprites Packed: {res['packed_count']} / {res['total_count']}")
        self.lbl_stat_eff.setText(f"Efficiency: {res['efficiency_percent']:.1f}%")
        self.lbl_stat_unused.setText(f"Unused Space: {res['unused_area_percent']:.1f}%")

        # Load to canvas
        self.canvas.set_atlas_data(str(preview_img), res.get("sprites", []))

    def _save_atlas(self):
        """Save atlas record to database."""
        if not self.generated_result:
            return

        res = self.generated_result
        atlas_id = db.create_texture_atlas_definition(
            atlas_name=self.txt_atlas_name.text().strip() or "atlas",
            texture_path=res["output_image_path"],
            json_manifest_path=res["output_json_path"],
            width=res["atlas_width"],
            height=res["atlas_height"],
            sprite_count=res["packed_count"],
            file_size=res.get("file_size", 0),
            efficiency_percent=res.get("efficiency_percent", 0.0),
        )

        # Add entries
        entries = []
        for s in res.get("sprites", []):
            entries.append({
                "sprite_name": s["name"],
                "source_asset_id": s.get("id"),
                "rect_x": s["x"],
                "rect_y": s["y"],
                "rect_w": s["w"],
                "rect_h": s["h"],
                "rotated": 0,
            })
        db.add_texture_atlas_entries(atlas_id, entries)

        self.atlas_created.emit(res)
        QMessageBox.information(
            self,
            "Atlas Saved",
            f"Texture Atlas '{self.txt_atlas_name.text()}' created and registered successfully!\nImage: {res['output_image_path']}\nJSON: {res['output_json_path']}"
        )
        self.accept()
