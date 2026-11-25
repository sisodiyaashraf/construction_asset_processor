"""
Animation Preview Component (Stage 9)
Construction Asset Processor

Dedicated preview widget for real-time playback of animation sequences.
Features:
- Smooth non-blocking playback driven by AnimationPlaybackController (QTimer)
- Viewport with checkerboard transparency background and pivot point centering
- Interactive frame scrubber slider
- Playback controls: Play, Pause, Stop, Step Forward, Step Backward, First/Last Frame
- Loop mode toggle and speed multiplier (0.25x, 0.5x, 1x, 1.5x, 2x)
- Frame rate selector (1, 2, 4, 6, 8, 10, 12, 15, 24, 30 FPS)
- Animation sequence manager (create, switch, delete animations)
- Frame info display: Frame index / count, duration ms, dimensions, pivot offset

Strictly non-destructive — does not modify source images or exported assets.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
    QPen, QPixmap
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QPushButton, QSlider,
    QSpinBox, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.animation_preview_engine import AnimationPlaybackController
from core.sprite_sheet_engine import (
    ANIMATION_PRESETS, STANDARD_FPS_VALUES, sprite_sheet_engine
)

logger = logging.getLogger("AssetProcessor.AnimationPreview")


class AnimationViewport(QWidget):
    """
    Viewport canvas rendering the active animation frame centered on its pivot point,
    with checkerboard transparency, scale toggles, and crosshair overlays.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 200)
        self.setStyleSheet(f"background-color: {THEME_COLORS['bg_input']}; border-radius: 4px;")

        self._frame_pixmap: Optional[QPixmap] = None
        self._pivot_x: float = 0.5
        self._pivot_y: float = 0.5
        self._scale_mode: str = "fit"  # "1x", "2x", "4x", "fit"
        self._show_pivot: bool = True
        self._show_bounds: bool = True

    def set_frame(self, pixmap: Optional[QPixmap], pivot_x: float = 0.5, pivot_y: float = 0.5):
        """Update current frame image and pivot coordinates."""
        self._frame_pixmap = pixmap
        self._pivot_x = pivot_x
        self._pivot_y = pivot_y
        self.update()

    def set_scale_mode(self, mode: str):
        self._scale_mode = mode
        self.update()

    def set_show_pivot(self, show: bool):
        self._show_pivot = show
        self.update()

    def set_show_bounds(self, show: bool):
        self._show_bounds = show
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        vw = self.width()
        vh = self.height()

        # 1. Background checkerboard pattern
        grid_size = 12
        for y in range(0, vh, grid_size):
            for x in range(0, vw, grid_size):
                col = QColor("#1D2026") if ((x // grid_size) + (y // grid_size)) % 2 == 0 else QColor("#14171B")
                painter.fillRect(QRect(x, y, grid_size, grid_size), col)

        if not self._frame_pixmap or self._frame_pixmap.isNull():
            painter.setPen(QPen(QColor(THEME_COLORS["text_muted"])))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "No Animation Frames")
            return

        fw = self._frame_pixmap.width()
        fh = self._frame_pixmap.height()

        # Calculate scale factor
        if self._scale_mode == "1x":
            scale = 1.0
        elif self._scale_mode == "2x":
            scale = 2.0
        elif self._scale_mode == "4x":
            scale = 4.0
        else:  # "fit"
            max_w = vw * 0.85
            max_h = vh * 0.85
            scale = min(max_w / max(1, fw), max_h / max(1, fh))

        draw_w = fw * scale
        draw_h = fh * scale

        # Anchor-aligned centering: place the frame's pivot point exactly at the viewport center
        center_x = vw / 2.0
        center_y = vh / 2.0

        draw_x = center_x - (self._pivot_x * draw_w)
        draw_y = center_y - (self._pivot_y * draw_h)
        target_rect = QRectF(draw_x, draw_y, draw_w, draw_h)

        # 2. Draw Frame Image
        painter.drawPixmap(target_rect.toRect(), self._frame_pixmap)

        # 3. Optional Frame Boundary Box
        if self._show_bounds:
            painter.setPen(QPen(QColor(THEME_COLORS["border_medium"]), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(target_rect)

        # 4. Center / Pivot Crosshairs
        if self._show_pivot:
            # Viewport Center (where the pivot is aligned)
            painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
            painter.drawLine(QPointF(center_x - 12, center_y), QPointF(center_x + 12, center_y))
            painter.drawLine(QPointF(center_x, center_y - 12), QPointF(center_x, center_y + 12))

            painter.setPen(QPen(QColor(THEME_COLORS["accent_primary"]), 1.5))
            painter.drawLine(QPointF(center_x - 10, center_y), QPointF(center_x + 10, center_y))
            painter.drawLine(QPointF(center_x, center_y - 10), QPointF(center_x, center_y + 10))

            painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
            painter.setBrush(QBrush(QColor(THEME_COLORS["accent_primary"])))
            painter.drawEllipse(QPointF(center_x, center_y), 3.5, 3.5)


class AnimationPreviewWidget(QWidget):
    """
    Complete Animation Preview panel providing sequence selection,
    smooth playback controls, scrubbing, speed / FPS toggles, and metadata status.
    """

    frame_requested = Signal(int)  # index requested via scrubber
    animation_changed = Signal(str)  # animation_name
    animation_created = Signal(str, str)  # name, preset_type
    animation_deleted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("animation_preview_widget")

        # Playback Controller
        self.controller = AnimationPlaybackController(self)
        self.controller.frame_changed.connect(self._on_controller_frame_changed)
        self.controller.playback_state_changed.connect(self._on_playback_state_changed)
        self.controller.animation_finished.connect(self._on_animation_finished)
        self.controller.sequence_updated.connect(self._on_sequence_updated)

        self._source_pixmap: Optional[QPixmap] = None
        self._current_sequence: List[Dict[str, Any]] = []
        self._cached_frame_pixmaps: Dict[int, QPixmap] = {}
        self._block_scrubber = False

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ---------------------------------------------------------------------
        # 1. Header & Animation Sequence Selector
        # ---------------------------------------------------------------------
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        hdr_layout = QVBoxLayout(hdr_frame)
        hdr_layout.setContentsMargins(6, 6, 6, 6)
        hdr_layout.setSpacing(6)

        title_row = QHBoxLayout()
        lbl_title = QLabel("ANIMATION PREVIEW")
        lbl_title.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        title_row.addWidget(lbl_title)
        title_row.addStretch()

        hdr_layout.addLayout(title_row)

        # Sequence Selection Dropdown & Add/Delete buttons
        seq_row = QHBoxLayout()
        seq_row.addWidget(QLabel("Sequence:"))
        self.combo_sequence = QComboBox()
        self.combo_sequence.addItem("All Frames (Default)", "default")
        self.combo_sequence.currentIndexChanged.connect(self._on_sequence_combo_changed)
        seq_row.addWidget(self.combo_sequence, 1)

        self.btn_new_anim = QPushButton("+ New")
        self.btn_new_anim.setToolTip("Create a new animation sequence from defined frames.")
        self.btn_new_anim.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_new_anim.clicked.connect(self._on_new_animation_clicked)
        seq_row.addWidget(self.btn_new_anim)

        self.btn_del_anim = QPushButton("✕")
        self.btn_del_anim.setToolTip("Delete current animation sequence.")
        self.btn_del_anim.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['status_error']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['status_error']};
            }}
        """)
        self.btn_del_anim.clicked.connect(self._on_delete_animation_clicked)
        seq_row.addWidget(self.btn_del_anim)

        hdr_layout.addLayout(seq_row)
        main_layout.addWidget(hdr_frame)

        # ---------------------------------------------------------------------
        # 2. Viewport & View Options
        # ---------------------------------------------------------------------
        viewport_frame = QFrame()
        viewport_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)
        viewport_layout = QVBoxLayout(viewport_frame)
        viewport_layout.setContentsMargins(6, 6, 6, 6)
        viewport_layout.setSpacing(6)

        # Viewport Canvas
        self.viewport = AnimationViewport()
        viewport_layout.addWidget(self.viewport, 1)

        # Viewport Toolbar: Zoom, Pivot Toggle, Info
        vp_tool_row = QHBoxLayout()
        vp_tool_row.addWidget(QLabel("Scale:"))
        self.combo_scale = QComboBox()
        self.combo_scale.addItems(["Fit", "1x", "2x", "4x"])
        self.combo_scale.currentTextChanged.connect(lambda t: self.viewport.set_scale_mode(t.lower()))
        vp_tool_row.addWidget(self.combo_scale)

        self.btn_toggle_pivot = QPushButton("Anchor ⊕")
        self.btn_toggle_pivot.setCheckable(True)
        self.btn_toggle_pivot.setChecked(True)
        self.btn_toggle_pivot.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_secondary']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 10px;
            }}
            QPushButton:checked {{
                color: {THEME_COLORS['accent_primary']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_toggle_pivot.toggled.connect(self.viewport.set_show_pivot)
        vp_tool_row.addWidget(self.btn_toggle_pivot)

        vp_tool_row.addStretch()

        self.lbl_frame_info = QLabel("Frame 0 / 0 (0 ms)")
        self.lbl_frame_info.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']}; font-weight: 600;")
        vp_tool_row.addWidget(self.lbl_frame_info)

        viewport_layout.addLayout(vp_tool_row)
        main_layout.addWidget(viewport_frame, 1)

        # ---------------------------------------------------------------------
        # 3. Interactive Frame Scrubber Slider
        # ---------------------------------------------------------------------
        scrubber_row = QHBoxLayout()
        self.slider_scrubber = QSlider(Qt.Horizontal)
        self.slider_scrubber.setRange(0, 0)
        self.slider_scrubber.setValue(0)
        self.slider_scrubber.valueChanged.connect(self._on_scrubber_value_changed)
        self.slider_scrubber.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: {THEME_COLORS['bg_input']};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {THEME_COLORS['accent_primary']};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: 1px solid {THEME_COLORS['accent_primary']};
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {THEME_COLORS['accent_primary']};
            }}
        """)
        scrubber_row.addWidget(self.slider_scrubber)
        main_layout.addLayout(scrubber_row)

        # ---------------------------------------------------------------------
        # 4. Playback Controls Toolbar
        # ---------------------------------------------------------------------
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        ctrl_layout = QVBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(6, 6, 6, 6)
        ctrl_layout.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        btn_style = f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 5px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """

        # First frame
        self.btn_first = QPushButton("⏮")
        self.btn_first.setToolTip("Jump to first frame (Home)")
        self.btn_first.setStyleSheet(btn_style)
        self.btn_first.clicked.connect(self.controller.first_frame)
        btn_row.addWidget(self.btn_first)

        # Previous frame
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setToolTip("Previous frame (Left arrow)")
        self.btn_prev.setStyleSheet(btn_style)
        self.btn_prev.clicked.connect(self.controller.step_backward)
        btn_row.addWidget(self.btn_prev)

        # Play / Pause Toggle Button (Prominent)
        self.btn_play_pause = QPushButton("▶ Play")
        self.btn_play_pause.setToolTip("Play or Pause animation (Space)")
        self.btn_play_pause.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                font-size: 12px;
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
        """)
        self.btn_play_pause.clicked.connect(self.controller.toggle_play_pause)
        btn_row.addWidget(self.btn_play_pause, 1)

        # Stop Button
        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setToolTip("Stop and rewind to frame 0")
        self.btn_stop.setStyleSheet(btn_style)
        self.btn_stop.clicked.connect(self.controller.stop)
        btn_row.addWidget(self.btn_stop)

        # Next frame
        self.btn_next = QPushButton("▶")
        self.btn_next.setToolTip("Next frame (Right arrow)")
        self.btn_next.setStyleSheet(btn_style)
        self.btn_next.clicked.connect(self.controller.step_forward)
        btn_row.addWidget(self.btn_next)

        # Loop toggle
        self.btn_loop = QPushButton("🔁")
        self.btn_loop.setToolTip("Toggle continuous looping")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setChecked(True)
        self.btn_loop.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_muted']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                padding: 5px;
                font-size: 11px;
            }}
            QPushButton:checked {{
                color: {THEME_COLORS['accent_primary']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_loop.toggled.connect(self.controller.set_loop_enabled)
        btn_row.addWidget(self.btn_loop)

        ctrl_layout.addLayout(btn_row)

        # Speed & FPS Row
        rate_row = QHBoxLayout()

        rate_row.addWidget(QLabel("FPS:"))
        self.combo_fps = QComboBox()
        for f in STANDARD_FPS_VALUES:
            self.combo_fps.addItem(f"{f} fps", f)
        self.combo_fps.setCurrentText("10 fps")
        self.combo_fps.currentIndexChanged.connect(self._on_fps_changed)
        rate_row.addWidget(self.combo_fps)

        rate_row.addWidget(QLabel("Speed:"))
        self.combo_speed = QComboBox()
        for s_lbl, s_val in [("0.25x", 0.25), ("0.5x", 0.5), ("1.0x", 1.0), ("1.5x", 1.5), ("2.0x", 2.0)]:
            self.combo_speed.addItem(s_lbl, s_val)
        self.combo_speed.setCurrentText("1.0x")
        self.combo_speed.currentIndexChanged.connect(self._on_speed_changed)
        rate_row.addWidget(self.combo_speed)

        ctrl_layout.addLayout(rate_row)
        main_layout.addWidget(ctrl_frame)

    # -------------------------------------------------------------------------
    # Public Configuration Methods
    # -------------------------------------------------------------------------

    def set_source_image(self, pixmap: Optional[QPixmap]):
        """Set the active source sprite sheet pixmap to crop frames from."""
        self._source_pixmap = pixmap
        self._cached_frame_pixmaps.clear()
        self._refresh_current_frame()

    def set_sequence(self, frames: List[Dict[str, Any]], animations: Optional[List[Dict[str, Any]]] = None):
        """Update active sequence of frames to preview."""
        self._current_sequence = list(frames or [])
        self._cached_frame_pixmaps.clear()

        # Update animations dropdown
        if animations is not None:
            curr_data = self.combo_sequence.currentData()
            self.combo_sequence.blockSignals(True)
            self.combo_sequence.clear()
            self.combo_sequence.addItem("All Frames (Default)", "default")
            for anim in animations:
                self.combo_sequence.addItem(f"🎬 {anim.get('name')}", anim.get("name"))

            # restore selection if possible
            idx = self.combo_sequence.findData(curr_data)
            if idx >= 0:
                self.combo_sequence.setCurrentIndex(idx)
            else:
                self.combo_sequence.setCurrentIndex(0)
            self.combo_sequence.blockSignals(False)

        self.controller.set_sequence(self._current_sequence)
        self._update_slider_range()
        self._refresh_current_frame()

    def update_frame_data(self, index: int, updated_frame: Dict[str, Any]):
        """Update a specific frame's coordinates or pivot in the sequence."""
        if 0 <= index < len(self._current_sequence):
            self._current_sequence[index] = updated_frame
            # Invalidate cached cropped pixmap
            if index in self._cached_frame_pixmaps:
                del self._cached_frame_pixmaps[index]

            if self.controller.current_index == index:
                self._refresh_current_frame()

    # -------------------------------------------------------------------------
    # Internal Slots & Handlers
    # -------------------------------------------------------------------------

    def _get_frame_pixmap(self, frame_data: Dict[str, Any], index: int) -> Optional[QPixmap]:
        if index in self._cached_frame_pixmaps:
            return self._cached_frame_pixmaps[index]

        if not self._source_pixmap or self._source_pixmap.isNull():
            return None

        x = frame_data.get("x", 0)
        y = frame_data.get("y", 0)
        w = frame_data.get("width", 64)
        h = frame_data.get("height", 64)

        crop_rect = QRect(x, y, w, h).intersected(self._source_pixmap.rect())
        if crop_rect.isValid() and not crop_rect.isEmpty():
            cropped = self._source_pixmap.copy(crop_rect)
            self._cached_frame_pixmaps[index] = cropped
            return cropped
        return None

    def _refresh_current_frame(self):
        cur_frame = self.controller.get_current_frame()
        idx = self.controller.current_index
        tot = self.controller.get_sequence_length()

        if cur_frame:
            pixmap = self._get_frame_pixmap(cur_frame, idx)
            px = float(cur_frame.get("pivot_x", 0.5))
            py = float(cur_frame.get("pivot_y", 0.5))
            self.viewport.set_frame(pixmap, px, py)

            dur = cur_frame.get("duration_ms", 100)
            w = cur_frame.get("width", 0)
            h = cur_frame.get("height", 0)
            self.lbl_frame_info.setText(f"Frame {idx + 1} / {tot} ({dur} ms) | {w}×{h} px")
        else:
            self.viewport.set_frame(None)
            self.lbl_frame_info.setText(f"Frame 0 / {tot} (0 ms)")

    def _on_controller_frame_changed(self, index: int, frame_dict: dict):
        self._block_scrubber = True
        try:
            self.slider_scrubber.setValue(index)
        finally:
            self._block_scrubber = False
        self._refresh_current_frame()

    def _on_playback_state_changed(self, is_playing: bool):
        if is_playing:
            self.btn_play_pause.setText("⏸ Pause")
            self.btn_play_pause.setStyleSheet(f"""
                QPushButton {{
                    background-color: {THEME_COLORS['status_warning']};
                    color: {THEME_COLORS['text_inverse']};
                    font-weight: 700;
                    font-size: 12px;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 14px;
                }}
            """)
        else:
            self.btn_play_pause.setText("▶ Play")
            self.btn_play_pause.setStyleSheet(f"""
                QPushButton {{
                    background-color: {THEME_COLORS['accent_primary']};
                    color: {THEME_COLORS['text_inverse']};
                    font-weight: 700;
                    font-size: 12px;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 14px;
                }}
                QPushButton:hover {{
                    background-color: {THEME_COLORS['accent_hover']};
                }}
            """)

    def _on_animation_finished(self):
        logger.debug("Non-looping animation sequence reached the end.")

    def _on_sequence_updated(self, count: int):
        self._update_slider_range()
        self._refresh_current_frame()

    def _update_slider_range(self):
        tot = len(self._current_sequence)
        self.slider_scrubber.setRange(0, max(0, tot - 1))
        self.slider_scrubber.setEnabled(tot > 1)

    def _on_scrubber_value_changed(self, value: int):
        if self._block_scrubber:
            return
        self.controller.goto_frame(value)
        self.frame_requested.emit(value)

    def _on_fps_changed(self, idx: int):
        fps_val = self.combo_fps.currentData()
        if fps_val:
            self.controller.set_fps(int(fps_val))

    def _on_speed_changed(self, idx: int):
        speed_val = self.combo_speed.currentData()
        if speed_val:
            self.controller.set_speed_multiplier(float(speed_val))

    def _on_sequence_combo_changed(self, idx: int):
        anim_data = self.combo_sequence.currentData()
        if anim_data:
            self.animation_changed.emit(anim_data)

    def _on_new_animation_clicked(self):
        name, ok = QInputDialog.getItem(
            self,
            "Create Animation Sequence",
            "Select or enter an animation sequence preset:",
            ANIMATION_PRESETS,
            0,
            True,
        )
        if ok and name.strip():
            clean_name = name.strip()
            self.animation_created.emit(clean_name, clean_name)

    def _on_delete_animation_clicked(self):
        curr_anim = self.combo_sequence.currentData()
        if curr_anim == "default":
            QMessageBox.information(self, "Cannot Delete", "The default 'All Frames' sequence cannot be deleted.")
            return

        res = QMessageBox.question(
            self,
            "Delete Animation",
            f"Are you sure you want to delete animation sequence '{curr_anim}'?\nDefined frames on the sprite sheet will remain intact.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if res == QMessageBox.Yes:
            self.animation_deleted.emit(curr_anim)
