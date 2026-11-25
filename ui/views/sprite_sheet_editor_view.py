"""
Sprite Sheet Editor & Animation Frame Management Master View (Stage 9)
Construction Asset Processor

Comprehensive workspace integrating:
1. Top Toolbar (Open file, Select catalog candidate, Mode A/B toggle, Save, Export, Refresh)
2. 6 Real-time SQLite statistics metric cards
3. Interactive Zoomable Sprite Sheet Canvas with interactive grab handles & drawing overlays
4. Horizontal Frame Timeline with sequence reordering, thumbnail cards, and card actions
5. Frame & Grid Inspector with visual Kinematic Pivot Point Picker
6. Animation Preview with smooth QTimer-driven playback and sequence management
7. Non-destructive Export Dialog for PNG frames and Flutter + Flame JSON metadata
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.database import db
from core.sprite_sheet_engine import sprite_sheet_engine
from ui.components.animation_preview import AnimationPreviewWidget
from ui.components.frame_inspector import FrameInspector
from ui.components.frame_timeline import FrameTimeline
from ui.components.sprite_sheet_canvas import (
    SpriteSheetCanvasContainer, SpriteSheetCanvasWidget
)
from ui.components.sprite_sheet_export_dialog import SpriteSheetExportDialog
from ui.components.stat_card import StatCard

logger = logging.getLogger("AssetProcessor.SpriteSheetEditorView")


class SpriteSheetEditorView(QWidget):
    """
    Primary workspace view for Stage 9: Sprite Sheet Editor & Animation Frame Management.
    """

    status_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sprite_sheet_editor_view")

        # Active Data State
        self.current_asset: Optional[Dict[str, Any]] = None
        self.current_sheet_def: Optional[Dict[str, Any]] = None
        self.current_frames: List[Dict[str, Any]] = []
        self.current_animations: List[Dict[str, Any]] = []
        self.source_pixmap: Optional[QPixmap] = None
        self.active_mode: str = "uniform"  # "uniform" or "manual"
        self.active_animation_name: str = "default"

        self._build_ui()
        self.refresh_stats()
        self.load_catalog_candidates()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Toolbar
        self._build_toolbar(main_layout)

        # 2. 6 Statistics Metric Cards
        self._build_stats_section(main_layout)

        # 3. Main Workspace Horizontal Splitter
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {THEME_COLORS['border_subtle']};
                width: 2px;
            }}
        """)

        # Left / Center Area: Canvas at top, Timeline at bottom
        left_center_widget = QWidget()
        left_layout = QVBoxLayout(left_center_widget)
        left_layout.setContentsMargins(12, 10, 10, 10)
        left_layout.setSpacing(8)

        self.canvas_timeline_splitter = QSplitter(Qt.Vertical)
        self.canvas_timeline_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {THEME_COLORS['border_subtle']};
                height: 2px;
            }}
        """)

        # Canvas Container
        self.canvas_container = SpriteSheetCanvasContainer()
        self.canvas = self.canvas_container.canvas
        self.canvas_timeline_splitter.addWidget(self.canvas_container)

        # Timeline
        self.timeline = FrameTimeline()
        self.canvas_timeline_splitter.addWidget(self.timeline)

        # Proportions: 72% canvas, 28% timeline
        self.canvas_timeline_splitter.setStretchFactor(0, 7)
        self.canvas_timeline_splitter.setStretchFactor(1, 3)

        left_layout.addWidget(self.canvas_timeline_splitter)
        self.main_splitter.addWidget(left_center_widget)

        # Right Area: Frame Inspector at top, Animation Preview at bottom
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 10, 12, 10)
        right_layout.setSpacing(8)

        self.inspector_preview_splitter = QSplitter(Qt.Vertical)
        self.inspector_preview_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {THEME_COLORS['border_subtle']};
                height: 2px;
            }}
        """)

        # Inspector
        self.inspector = FrameInspector()
        self.inspector_preview_splitter.addWidget(self.inspector)

        # Preview Widget
        self.preview = AnimationPreviewWidget()
        self.inspector_preview_splitter.addWidget(self.preview)

        # Proportions: 55% inspector, 45% preview
        self.inspector_preview_splitter.setStretchFactor(0, 5)
        self.inspector_preview_splitter.setStretchFactor(1, 4)

        right_layout.addWidget(self.inspector_preview_splitter)
        self.main_splitter.addWidget(right_widget)

        # Main splitter proportions: 68% workspace, 32% panels
        self.main_splitter.setStretchFactor(0, 7)
        self.main_splitter.setStretchFactor(1, 3)

        main_layout.addWidget(self.main_splitter, 1)

        # 4. Wire Two-Way State Synchronization Signals
        self._wire_signals()

    # -------------------------------------------------------------------------
    # UI Sections
    # -------------------------------------------------------------------------

    def _build_toolbar(self, parent_layout: QVBoxLayout):
        toolbar_frame = QFrame()
        toolbar_frame.setFixedHeight(56)
        toolbar_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_toolbar']};
                border-bottom: 1px solid {THEME_COLORS['border_subtle']};
            }}
        """)
        tb_layout = QHBoxLayout(toolbar_frame)
        tb_layout.setContentsMargins(16, 8, 16, 8)
        tb_layout.setSpacing(10)

        # Title & Active Sheet Label
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel("SPRITE SHEET EDITOR")
        lbl_title.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        title_box.addWidget(lbl_title)

        self.lbl_active_source = QLabel("No sprite sheet loaded")
        self.lbl_active_source.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']};")
        title_box.addWidget(self.lbl_active_source)
        tb_layout.addLayout(title_box)

        tb_layout.addSpacing(16)

        # Action: Open File
        self.btn_open_file = QPushButton("📂 Open Image...")
        self.btn_open_file.setStyleSheet(self._btn_secondary_style())
        self.btn_open_file.clicked.connect(self._on_open_file_clicked)
        tb_layout.addWidget(self.btn_open_file)

        # Action: Catalog Candidate Selector
        self.combo_candidates = QComboBox()
        self.combo_candidates.addItem("Select from Catalog...", None)
        self.combo_candidates.setStyleSheet(self._input_style())
        self.combo_candidates.setMinimumWidth(220)
        self.combo_candidates.currentIndexChanged.connect(self._on_candidate_selected)
        tb_layout.addWidget(self.combo_candidates)

        tb_layout.addSpacing(10)

        # Mode Toggle Buttons
        lbl_mode = QLabel("Mode:")
        lbl_mode.setStyleSheet(f"font-weight: 600; color: {THEME_COLORS['text_secondary']};")
        tb_layout.addWidget(lbl_mode)

        self.btn_mode_uniform = QPushButton("Mode A: Uniform Grid")
        self.btn_mode_uniform.setCheckable(True)
        self.btn_mode_uniform.setChecked(True)
        self.btn_mode_uniform.setStyleSheet(self._mode_btn_style())
        self.btn_mode_uniform.clicked.connect(lambda: self._set_mode("uniform"))
        tb_layout.addWidget(self.btn_mode_uniform)

        self.btn_mode_manual = QPushButton("Mode B: Manual")
        self.btn_mode_manual.setCheckable(True)
        self.btn_mode_manual.setStyleSheet(self._mode_btn_style())
        self.btn_mode_manual.clicked.connect(lambda: self._set_mode("manual"))
        tb_layout.addWidget(self.btn_mode_manual)

        tb_layout.addStretch()

        # Action: Save Definitions
        self.btn_save_def = QPushButton("💾 Save Sheet")
        self.btn_save_def.setToolTip("Save sheet definition, frames, and pivot data to SQLite database.")
        self.btn_save_def.setStyleSheet(self._btn_secondary_style())
        self.btn_save_def.clicked.connect(self._on_save_definitions_clicked)
        tb_layout.addWidget(self.btn_save_def)

        # Action: Export Assets
        self.btn_export = QPushButton("📤 Export Assets...")
        self.btn_export.setToolTip("Export PNG frames and Flutter + Flame JSON metadata.")
        self.btn_export.setStyleSheet(self._btn_primary_style())
        self.btn_export.clicked.connect(self._on_export_clicked)
        tb_layout.addWidget(self.btn_export)

        # Action: Refresh
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setFixedSize(32, 32)
        self.btn_refresh.setToolTip("Refresh view and stats")
        self.btn_refresh.setStyleSheet(self._btn_secondary_style())
        self.btn_refresh.clicked.connect(self.refresh)
        tb_layout.addWidget(self.btn_refresh)

        parent_layout.addWidget(toolbar_frame)

    def _build_stats_section(self, parent_layout: QVBoxLayout):
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_main']};
                border-bottom: 1px solid {THEME_COLORS['border_subtle']};
            }}
        """)
        s_layout = QHBoxLayout(stats_frame)
        s_layout.setContentsMargins(16, 8, 16, 8)
        s_layout.setSpacing(12)

        self.card_sheets = StatCard("TOTAL SPRITE SHEETS", "0", "Configured in database", "🎞️")
        self.card_frames = StatCard("DEFINED FRAMES", "0", "Total animation frames", "🖼️")
        self.card_anims = StatCard("ANIMATIONS", "0", "Named motion sequences", "🎬")
        self.card_uniform = StatCard("UNIFORM GRIDS", "0", "Mode A grid definitions", "📐")
        self.card_manual = StatCard("MANUAL SHEETS", "0", "Mode B irregular frame sheets", "✏️")
        self.card_candidates = StatCard("CATALOG CANDIDATES", "0", "Sprite sheets from Stage 8", "🎯")

        for c in [
            self.card_sheets, self.card_frames, self.card_anims,
            self.card_uniform, self.card_manual, self.card_candidates
        ]:
            s_layout.addWidget(c)

        parent_layout.addWidget(stats_frame)

    # -------------------------------------------------------------------------
    # Signal Wiring & State Synchronization
    # -------------------------------------------------------------------------

    def _wire_signals(self):
        # 1. Canvas -> View & Other Panels
        self.canvas.frame_selected.connect(self._on_canvas_frame_selected)
        self.canvas.frame_deselected.connect(self._on_canvas_frame_deselected)
        self.canvas.frame_drawn.connect(self._on_canvas_frame_drawn)
        self.canvas.frame_modified.connect(self._on_canvas_frame_modified)
        self.canvas.frame_deleted.connect(self._on_frame_deleted)
        self.canvas.pivot_selected.connect(self._on_canvas_pivot_selected)
        self.canvas.coordinates_changed.connect(self._on_canvas_coords_dragged)

        # 2. Timeline -> View & Canvas
        self.timeline.frame_selected.connect(self._on_timeline_frame_selected)
        self.timeline.order_changed.connect(self._on_timeline_order_changed)
        self.timeline.frame_deleted.connect(self._on_frame_deleted)
        self.timeline.frame_duplicated.connect(self._on_frame_duplicated)

        # 3. Inspector -> View & Canvas
        self.inspector.frame_updated.connect(self._on_inspector_frame_updated)
        self.inspector.coordinates_edited.connect(self._on_inspector_coords_edited)
        self.inspector.pivot_updated.connect(self._on_inspector_pivot_updated)
        self.inspector.grid_apply_requested.connect(self._on_inspector_grid_apply)
        self.inspector.draw_mode_toggled.connect(self._on_inspector_draw_toggled)
        self.inspector.delete_frame_requested.connect(self._on_frame_deleted)
        self.inspector.duplicate_frame_requested.connect(self._on_frame_duplicated)

        # 4. Preview -> Timeline & View
        self.preview.frame_requested.connect(self._on_preview_frame_requested)
        self.preview.animation_changed.connect(self._on_preview_animation_changed)
        self.preview.animation_created.connect(self._on_preview_animation_created)
        self.preview.animation_deleted.connect(self._on_preview_animation_deleted)

    # -------------------------------------------------------------------------
    # Mode Management
    # -------------------------------------------------------------------------

    def _set_mode(self, mode: str):
        self.active_mode = mode
        if mode == "uniform":
            self.btn_mode_uniform.setChecked(True)
            self.btn_mode_manual.setChecked(False)
            self.canvas.set_draw_mode(False)
            self.inspector.set_draw_mode_active(False)
        else:
            self.btn_mode_uniform.setChecked(False)
            self.btn_mode_manual.setChecked(True)

        self.inspector.set_mode(mode)

    # -------------------------------------------------------------------------
    # Loading & Inspection
    # -------------------------------------------------------------------------

    def refresh(self):
        """Reload statistics and catalog candidate list."""
        self.refresh_stats()
        self.load_catalog_candidates()

    def refresh_stats(self):
        """Query real SQLite stats and update cards."""
        stats = db.get_sprite_sheet_stats()
        self.card_sheets.set_value(str(stats.get("total_sheets", 0)))
        self.card_frames.set_value(str(stats.get("total_frames", 0)))
        self.card_anims.set_value(str(stats.get("total_animations", 0)))
        self.card_uniform.set_value(str(stats.get("uniform_grid_sheets", 0)))
        self.card_manual.set_value(str(stats.get("manual_sheets", 0)))
        self.card_candidates.set_value(str(stats.get("catalog_candidates", 0)))

    def load_catalog_candidates(self):
        """Populate catalog dropdown with sprite sheets and Stage 8 candidates."""
        self.combo_candidates.blockSignals(True)
        self.combo_candidates.clear()
        self.combo_candidates.addItem("Select from Catalog...", None)

        # 1. Existing sprite sheet definitions in SQLite
        existing_sheets = db.get_all_sprite_sheets()
        if existing_sheets:
            for s in existing_sheets:
                name = s.get("name") or Path(s.get("source_image_path", "")).name
                cnt = s.get("frames_count", 0)
                self.combo_candidates.addItem(f"🎞️ {name} ({cnt} frames)", {"type": "sheet", "id": s.get("id"), "data": s})

        # 2. Stage 8 Sprite Sheet Candidates
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, filename, original_path, collection, width, height, composition_type
                FROM assets
                WHERE composition_type IN ('Sprite Sheet', 'Animation Frame Grid')
                ORDER BY filename ASC
            """)
            candidates = [dict(r) for r in cursor.fetchall()]

        if candidates:
            for c in candidates:
                self.combo_candidates.addItem(
                    f"🎯 {c['filename']} ({c['width']}×{c['height']} - {c['composition_type']})",
                    {"type": "candidate", "id": c["id"], "data": c}
                )

        self.combo_candidates.blockSignals(False)

    def load_sprite_sheet_image(self, file_path: str, asset_data: Optional[Dict[str, Any]] = None):
        """Load an image into the editor, initialize definitions and sync panels."""
        p = Path(file_path)
        if not p.exists():
            QMessageBox.critical(self, "File Not Found", f"Image file not found:\n{file_path}")
            return

        pixmap = QPixmap(str(p))
        if pixmap.isNull():
            QMessageBox.critical(self, "Invalid Image", f"Failed to load image pixmap:\n{file_path}")
            return

        self.source_pixmap = pixmap
        self.current_asset = asset_data
        img_w = pixmap.width()
        img_h = pixmap.height()

        self.lbl_active_source.setText(f"{p.name} ({img_w} × {img_h} px)")

        # Inspect image source via engine
        insp_info = sprite_sheet_engine.inspect_image_source(str(p))

        # Check if existing definition exists in SQLite
        sheet_def = None
        asset_id = asset_data.get("id") if asset_data else None
        if asset_id:
            sheet_def = db.get_sprite_sheet_by_asset(asset_id)

        if not sheet_def:
            # Create working definition
            sheet_def = {
                "asset_id": asset_id,
                "name": p.stem,
                "source_image_path": str(p),
                "source_filename": p.name,
                "sheet_width": img_w,
                "sheet_height": img_h,
                "layout_mode": self.active_mode,
                "columns": 4,
                "rows": 2,
                "frame_width": max(1, img_w // 4),
                "frame_height": max(1, img_h // 2),
                "spacing_x": 0,
                "spacing_y": 0,
                "margin_left": 0,
                "margin_top": 0,
                "margin_right": 0,
                "margin_bottom": 0,
                "default_fps": 10,
                "loop_default": 1,
                "status": "draft",
            }

        self.current_sheet_def = sheet_def

        # Load frames if saved in DB
        frames = []
        if sheet_def.get("id"):
            frames = db.get_sprite_frames(sheet_def["id"])

        # If no saved frames, check if Stage 8 candidate regions can be imported
        if not frames and asset_id:
            candidate_frames = sprite_sheet_engine.import_stage8_candidate_regions(asset_id)
            if candidate_frames:
                frames = candidate_frames

        # If still no frames, generate default uniform grid frames
        if not frames:
            cols = sheet_def.get("columns", 4)
            rows = sheet_def.get("rows", 2)
            fw = max(1, img_w // cols)
            fh = max(1, img_h // rows)
            sheet_def["frame_width"] = fw
            sheet_def["frame_height"] = fh
            frames = sprite_sheet_engine.calculate_uniform_grid(
                image_width=img_w,
                image_height=img_h,
                columns=cols,
                rows=rows,
                frame_width=fw,
                frame_height=fh,
                name_prefix=p.stem,
            )

        self.current_frames = frames

        # Load animations
        animations = []
        if sheet_def.get("id"):
            animations = db.get_sprite_animations(sheet_def["id"])
        self.current_animations = animations

        # Update Canvas
        self.canvas.set_image(str(p), self.current_frames)

        # Update Inspector
        self.inspector.set_source_image(self.source_pixmap, (img_w, img_h))
        self.inspector.set_selected_frame(None, None)

        # Update Timeline
        self.timeline.set_source_image(self.source_pixmap)
        self.timeline.set_frames(self.current_frames)

        # Update Preview
        self.preview.set_source_image(self.source_pixmap)
        self.preview.set_sequence(self.current_frames, self.current_animations)

        self.refresh_stats()

    # -------------------------------------------------------------------------
    # Event Handlers & State Synchronization
    # -------------------------------------------------------------------------

    def _on_open_file_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Sprite Sheet Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp)",
        )
        if file_path:
            self.load_sprite_sheet_image(file_path)

    def _on_candidate_selected(self, index: int):
        data = self.combo_candidates.currentData()
        if not data:
            return

        item_type = data.get("type")
        item_data = data.get("data")

        if item_type == "sheet":
            img_path = item_data.get("source_image_path")
            self.load_sprite_sheet_image(img_path)
        elif item_type == "candidate":
            img_path = item_data.get("original_path") or item_data.get("filepath")
            self.load_sprite_sheet_image(img_path, asset_data=item_data)

    def _on_canvas_frame_selected(self, index: int):
        """Canvas frame selected -> update timeline, inspector, and preview."""
        if 0 <= index < len(self.current_frames):
            frame = self.current_frames[index]
            self.inspector.set_selected_frame(index, frame)
            self.timeline.select_frame(index)
            if not self.preview.controller.is_playing:
                self.preview.controller.goto_frame(index)

    def _on_canvas_frame_deselected(self):
        self.inspector.set_selected_frame(None, None)
        self.timeline.clear_selection()

    def _on_canvas_frame_drawn(self, x: int, y: int, w: int, h: int):
        """Mode B: Manual rectangle drawn on canvas -> create new frame."""
        idx = len(self.current_frames)
        new_frame = sprite_sheet_engine.create_manual_frame(
            index=idx,
            x=x,
            y=y,
            w=w,
            h=h,
            frame_name=f"frame_{idx:03d}",
            pivot=(0.5, 0.5),
            duration_ms=100,
        )
        self.current_frames.append(new_frame)
        self.canvas.set_frames(self.current_frames)
        self.timeline.set_frames(self.current_frames)
        self.preview.set_sequence(self.current_frames, self.current_animations)
        self.canvas.select_frame(idx)

    def _on_canvas_frame_modified(self, index: int, x: int, y: int, w: int, h: int):
        """User dragged or resized frame box on canvas -> update inspector and timeline."""
        if 0 <= index < len(self.current_frames):
            frame = self.current_frames[index]
            frame["x"] = x
            frame["y"] = y
            frame["width"] = w
            frame["height"] = h
            self.inspector.update_frame_coordinates(index, x, y, w, h)
            self.timeline.update_frame_card(index, frame)
            self.preview.update_frame_data(index, frame)

    def _on_canvas_coords_dragged(self, index: int, x: int, y: int, w: int, h: int):
        """Live coordinate feedback during drag."""
        self.inspector.update_frame_coordinates(index, x, y, w, h)

    def _on_canvas_pivot_selected(self, index: int, px: float, py: float):
        """Pivot point changed on canvas."""
        if 0 <= index < len(self.current_frames):
            frame = self.current_frames[index]
            frame["pivot_x"] = px
            frame["pivot_y"] = py
            self.inspector.set_selected_frame(index, frame)
            self.preview.update_frame_data(index, frame)

    def _on_timeline_frame_selected(self, index: int):
        """Timeline card clicked -> select on canvas and inspector."""
        if 0 <= index < len(self.current_frames):
            self.canvas.select_frame(index)
            frame = self.current_frames[index]
            self.inspector.set_selected_frame(index, frame)
            if not self.preview.controller.is_playing:
                self.preview.controller.goto_frame(index)

    def _on_timeline_order_changed(self, new_order: List[Dict[str, Any]]):
        """Timeline frames reordered -> update sequence order."""
        self.current_frames = sprite_sheet_engine.renumber_frames(new_order)
        self.canvas.set_frames(self.current_frames)
        self.preview.set_sequence(self.current_frames, self.current_animations)

    def _on_inspector_frame_updated(self, index: int, updated_frame: Dict[str, Any]):
        """Frame name or duration edited in inspector."""
        if 0 <= index < len(self.current_frames):
            self.current_frames[index] = updated_frame
            self.timeline.update_frame_card(index, updated_frame)
            self.preview.update_frame_data(index, updated_frame)

    def _on_inspector_coords_edited(self, index: int, x: int, y: int, w: int, h: int):
        """Numerical spinboxes edited in inspector -> update canvas and timeline."""
        if 0 <= index < len(self.current_frames):
            frame = self.current_frames[index]
            frame["x"] = x
            frame["y"] = y
            frame["width"] = w
            frame["height"] = h
            self.canvas.update_frame_box(index, x, y, w, h)
            self.timeline.update_frame_card(index, frame)
            self.preview.update_frame_data(index, frame)

    def _on_inspector_pivot_updated(self, index: int, px: float, py: float):
        """Pivot updated via visual picker or presets in inspector."""
        if 0 <= index < len(self.current_frames):
            frame = self.current_frames[index]
            frame["pivot_x"] = px
            frame["pivot_y"] = py
            self.canvas.update()
            self.preview.update_frame_data(index, frame)

    def _on_inspector_grid_apply(self, params: Dict[str, Any]):
        """Apply Uniform Grid button clicked in inspector."""
        if not self.source_pixmap or self.source_pixmap.isNull():
            QMessageBox.warning(self, "No Image", "Please load a sprite sheet image before applying a grid.")
            return

        img_w = self.source_pixmap.width()
        img_h = self.source_pixmap.height()
        sheet_name = self.current_sheet_def.get("name", "sprite") if self.current_sheet_def else "sprite"

        new_frames = sprite_sheet_engine.calculate_uniform_grid(
            image_width=img_w,
            image_height=img_h,
            columns=params["columns"],
            rows=params["rows"],
            frame_width=params["frame_width"],
            frame_height=params["frame_height"],
            spacing_x=params["spacing_x"],
            spacing_y=params["spacing_y"],
            margin_left=params["margin_left"],
            margin_top=params["margin_top"],
            margin_right=params["margin_right"],
            margin_bottom=params["margin_bottom"],
            name_prefix=sheet_name,
        )

        if not new_frames:
            QMessageBox.warning(self, "Grid Calculation Error", "No valid frames could be generated with the given dimensions.")
            return

        self.current_frames = new_frames
        self.canvas.set_frames(self.current_frames)
        self.timeline.set_frames(self.current_frames)
        self.preview.set_sequence(self.current_frames, self.current_animations)
        self.inspector.set_selected_frame(None, None)

    def _on_inspector_draw_toggled(self, is_active: bool):
        self.canvas.set_draw_mode(is_active)

    def _on_frame_deleted(self, index: int):
        if 0 <= index < len(self.current_frames):
            del self.current_frames[index]
            self.current_frames = sprite_sheet_engine.renumber_frames(self.current_frames)
            self.canvas.set_frames(self.current_frames)
            self.timeline.set_frames(self.current_frames)
            self.preview.set_sequence(self.current_frames, self.current_animations)
            self.inspector.set_selected_frame(None, None)

    def _on_frame_duplicated(self, index: int):
        if 0 <= index < len(self.current_frames):
            src = self.current_frames[index]
            new_f = dict(src)
            new_f["frame_name"] = f"{src.get('frame_name', 'frame')}_copy"
            new_f["sequence_order"] = len(self.current_frames)
            self.current_frames.append(new_f)
            self.current_frames = sprite_sheet_engine.renumber_frames(self.current_frames)
            self.canvas.set_frames(self.current_frames)
            self.timeline.set_frames(self.current_frames)
            self.preview.set_sequence(self.current_frames, self.current_animations)
            self.canvas.select_frame(len(self.current_frames) - 1)

    def _on_preview_frame_requested(self, index: int):
        if 0 <= index < len(self.current_frames):
            self.timeline.select_frame(index)
            self.canvas.select_frame(index)

    def _on_preview_animation_changed(self, anim_name: str):
        self.active_animation_name = anim_name
        if anim_name == "default":
            self.preview.set_sequence(self.current_frames)
        else:
            # Filter sequence for this animation
            matched_anim = next((a for a in self.current_animations if a.get("name") == anim_name), None)
            if matched_anim and matched_anim.get("id"):
                seq = db.get_animation_frame_sequence(matched_anim["id"])
                if seq:
                    self.preview.set_sequence(seq)
                else:
                    self.preview.set_sequence(self.current_frames)

    def _on_preview_animation_created(self, anim_name: str, preset_type: str):
        if not self.current_sheet_def:
            QMessageBox.warning(self, "No Sheet", "Please load a sprite sheet before creating animations.")
            return

        sheet_id = self.current_sheet_def.get("id")
        if not sheet_id:
            # Save definition first
            self._save_definitions()
            sheet_id = self.current_sheet_def.get("id")

        if sheet_id:
            fps = self.preview.controller.fps
            anim_id = db.create_sprite_animation(
                sheet_id=sheet_id,
                name=anim_name,
                animation_type=preset_type,
                fps=fps,
                loop=1,
            )
            # Add all current frames to sequence by default
            frame_ids = [f["id"] for f in self.current_frames if f.get("id")]
            if frame_ids:
                db.set_animation_frame_sequence(anim_id, frame_ids)

            self.current_animations = db.get_sprite_animations(sheet_id)
            self.preview.set_sequence(self.current_frames, self.current_animations)
            self.refresh_stats()

    def _on_preview_animation_deleted(self, anim_name: str):
        matched = next((a for a in self.current_animations if a.get("name") == anim_name), None)
        if matched and matched.get("id"):
            db.delete_sprite_animation(matched["id"])
            sheet_id = self.current_sheet_def.get("id")
            if sheet_id:
                self.current_animations = db.get_sprite_animations(sheet_id)
            self.preview.set_sequence(self.current_frames, self.current_animations)
            self.refresh_stats()

    # -------------------------------------------------------------------------
    # Saving & Export
    # -------------------------------------------------------------------------

    def _on_save_definitions_clicked(self):
        saved = self._save_definitions()
        if saved:
            QMessageBox.information(
                self,
                "Saved",
                f"Sprite sheet definition and {len(self.current_frames)} frames successfully saved to database.",
            )

    def _save_definitions(self) -> bool:
        if not self.current_sheet_def or not self.current_frames:
            QMessageBox.warning(self, "Nothing to Save", "No sprite sheet or frames currently loaded.")
            return False

        try:
            asset_id = self.current_sheet_def.get("asset_id")
            name = self.current_sheet_def.get("name", "sprite_sheet")
            img_path = self.current_sheet_def.get("source_image_path")
            img_fn = self.current_sheet_def.get("source_filename")
            sheet_w = self.current_sheet_def.get("sheet_width", 0)
            sheet_h = self.current_sheet_def.get("sheet_height", 0)

            sheet_id = db.create_or_update_sprite_sheet_definition(
                asset_id=asset_id,
                name=name,
                source_image_path=img_path,
                source_filename=img_fn,
                sheet_width=sheet_w,
                sheet_height=sheet_h,
                layout_mode=self.active_mode,
                columns=self.inspector.spin_cols.value(),
                rows=self.inspector.spin_rows.value(),
                frame_width=self.inspector.spin_fw.value(),
                frame_height=self.inspector.spin_fh.value(),
                spacing_x=self.inspector.spin_sp_x.value(),
                spacing_y=self.inspector.spin_sp_y.value(),
                margin_left=self.inspector.spin_ml.value(),
                margin_top=self.inspector.spin_mt.value(),
                margin_right=self.inspector.spin_mr.value(),
                margin_bottom=self.inspector.spin_mb.value(),
                default_fps=self.preview.controller.fps,
                loop_default=1 if self.preview.controller.loop_enabled else 0,
                status="ready",
            )
            self.current_sheet_def["id"] = sheet_id

            # Save frames
            db.save_sprite_frames(sheet_id, self.current_frames)
            # Re-read frames to get assigned IDs
            self.current_frames = db.get_sprite_frames(sheet_id)

            self.refresh_stats()
            return True

        except Exception as e:
            logger.error("Failed to save sprite sheet definitions: %s", e, exc_info=True)
            QMessageBox.critical(self, "Save Error", f"Failed to save definitions:\n{e}")
            return False

    def _on_export_clicked(self):
        if not self.current_sheet_def or not self.current_frames:
            QMessageBox.warning(self, "Nothing to Export", "No sprite sheet or frames currently loaded.")
            return

        # Ensure sheet is saved so IDs are present
        if not self.current_sheet_def.get("id"):
            self._save_definitions()

        dialog = SpriteSheetExportDialog(
            sheet_def=self.current_sheet_def,
            frames=self.current_frames,
            animations=self.current_animations,
            source_asset=self.current_asset,
            parent=self,
        )
        if dialog.exec():
            self.refresh_stats()

    # -------------------------------------------------------------------------
    # Styles
    # -------------------------------------------------------------------------

    def _btn_primary_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                font-size: 11px;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
            QPushButton:pressed {{
                background-color: {THEME_COLORS['accent_pressed']};
            }}
        """

    def _btn_secondary_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """

    def _mode_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_secondary']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 11px;
            }}
            QPushButton:checked {{
                background-color: {THEME_COLORS['bg_card_hover']};
                color: {THEME_COLORS['accent_primary']};
                border-color: {THEME_COLORS['accent_primary']};
                font-weight: 700;
            }}
            QPushButton:hover:!checked {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """

    def _input_style(self) -> str:
        return f"""
            QComboBox {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QComboBox:focus {{
                border-color: {THEME_COLORS['border_focus']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_primary']};
                selection-background-color: {THEME_COLORS['accent_primary']};
                selection-color: {THEME_COLORS['text_inverse']};
                border: 1px solid {THEME_COLORS['border_medium']};
            }}
        """
