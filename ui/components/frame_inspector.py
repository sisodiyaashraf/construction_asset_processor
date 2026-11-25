"""
Frame Inspector Component (Stage 9)
Construction Asset Processor

Right-side panel for:
- Mode A Uniform Grid parameters (Columns, Rows, Dimensions, Spacing, Margins)
- Frame Metadata display and numerical coordinate fine-tuning (X, Y, W, H)
- Frame order and duration ms customization
- Visual Pivot Point Picker widget (direct click/drag to place anchor point)
- Kinematic Pivot Presets (Center, Bottom Center, Bottom Left/Right, Top, Custom)
- Manual Frame actions (Draw, Duplicate, Delete)

Strictly non-destructive — does not alter or re-encode source image files.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QMouseEvent, QPainter, QPainterPath,
    QPen, QPixmap
)
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout,
    QWidget
)

from app.config import THEME_COLORS
from core.sprite_sheet_engine import PIVOT_PRESETS, sprite_sheet_engine

logger = logging.getLogger("AssetProcessor.FrameInspector")


class PivotPickerWidget(QFrame):
    """
    Interactive square preview displaying the selected frame's cropped thumbnail
    with an interactive pivot crosshair that can be clicked or dragged directly.
    """

    pivot_changed = Signal(float, float)  # (pivot_x_ratio, pivot_y_ratio)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 140)
        self.setCursor(Qt.CrossCursor)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
            }}
        """)

        self._frame_pixmap: Optional[QPixmap] = None
        self._pivot_x: float = 0.5
        self._pivot_y: float = 0.5
        self._is_dragging: bool = False

    def set_frame_pixmap(self, pixmap: Optional[QPixmap]):
        self._frame_pixmap = pixmap
        self.update()

    def set_pivot(self, px: float, py: float):
        self._pivot_x = max(0.0, min(1.0, float(px)))
        self._pivot_y = max(0.0, min(1.0, float(py)))
        self.update()

    def get_pivot(self) -> Tuple[float, float]:
        return (self._pivot_x, self._pivot_y)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._update_pivot_from_pos(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging:
            self._update_pivot_from_pos(event.position().x(), event.position().y())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._is_dragging:
            self._is_dragging = False
            self._update_pivot_from_pos(event.position().x(), event.position().y())

    def _update_pivot_from_pos(self, mx: float, my: float):
        target_rect = self._get_image_rect()
        if target_rect.width() <= 0 or target_rect.height() <= 0:
            return

        rx = (mx - target_rect.left()) / target_rect.width()
        ry = (my - target_rect.top()) / target_rect.height()

        self._pivot_x = round(max(0.0, min(1.0, rx)), 4)
        self._pivot_y = round(max(0.0, min(1.0, ry)), 4)
        self.update()
        self.pivot_changed.emit(self._pivot_x, self._pivot_y)

    def _get_image_rect(self) -> QRectF:
        inner_w = self.width() - 8
        inner_h = self.height() - 8
        if not self._frame_pixmap or self._frame_pixmap.isNull():
            return QRectF(4, 4, inner_w, inner_h)

        pw = self._frame_pixmap.width()
        ph = self._frame_pixmap.height()
        scale = min(inner_w / max(1, pw), inner_h / max(1, ph))
        draw_w = pw * scale
        draw_h = ph * scale
        draw_x = (self.width() - draw_w) / 2
        draw_y = (self.height() - draw_h) / 2
        return QRectF(draw_x, draw_y, draw_w, draw_h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        img_rect = self._get_image_rect()

        # Draw checkerboard pattern behind image
        grid_size = 8
        for y in range(int(img_rect.top()), int(img_rect.bottom()), grid_size):
            for x in range(int(img_rect.left()), int(img_rect.right()), grid_size):
                col = QColor("#22262C") if ((x // grid_size) + (y // grid_size)) % 2 == 0 else QColor("#1A1D22")
                painter.fillRect(
                    QRectF(x, y, min(grid_size, img_rect.right() - x), min(grid_size, img_rect.bottom() - y)),
                    col
                )

        # Draw frame thumbnail
        if self._frame_pixmap and not self._frame_pixmap.isNull():
            painter.drawPixmap(img_rect.toRect(), self._frame_pixmap)
        else:
            painter.setPen(QPen(QColor(THEME_COLORS["text_muted"])))
            painter.drawText(self.rect(), Qt.AlignCenter, "Frame Preview")

        # Draw border around frame area
        painter.setPen(QPen(QColor(THEME_COLORS["border_subtle"]), 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(img_rect)

        # Draw pivot crosshair
        px_canvas = img_rect.left() + (self._pivot_x * img_rect.width())
        py_canvas = img_rect.top() + (self._pivot_y * img_rect.height())

        # Crosshair lines
        painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
        painter.drawLine(QPointF(px_canvas - 10, py_canvas), QPointF(px_canvas + 10, py_canvas))
        painter.drawLine(QPointF(px_canvas, py_canvas - 10), QPointF(px_canvas, py_canvas + 10))

        painter.setPen(QPen(QColor(THEME_COLORS["accent_primary"]), 1.5))
        painter.drawLine(QPointF(px_canvas - 9, py_canvas), QPointF(px_canvas + 9, py_canvas))
        painter.drawLine(QPointF(px_canvas, py_canvas - 9), QPointF(px_canvas, py_canvas + 9))

        # Anchor ring
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
        painter.setBrush(QBrush(QColor(THEME_COLORS["accent_primary"])))
        painter.drawEllipse(QPointF(px_canvas, py_canvas), 4, 4)


class FrameInspector(QWidget):
    """
    Inspector panel hosting Mode A Uniform Grid tools, Frame Details,
    Visual Pivot Configuration, and Mode B Manual Frame actions.
    """

    frame_updated = Signal(int, dict)  # (index, updated_frame_dict)
    coordinates_edited = Signal(int, int, int, int, int)  # (index, x, y, w, h)
    pivot_updated = Signal(int, float, float)  # (index, pivot_x, pivot_y)
    grid_apply_requested = Signal(dict)  # grid_parameters
    draw_mode_toggled = Signal(bool)
    delete_frame_requested = Signal(int)
    duplicate_frame_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("frame_inspector")
        self._block_signals = False

        self._current_frame: Optional[Dict[str, Any]] = None
        self._current_frame_index: Optional[int] = None
        self._source_pixmap: Optional[QPixmap] = None
        self._source_dimensions: Tuple[int, int] = (0, 0)  # (width, height)
        self._mode: str = "uniform"  # "uniform" or "manual"

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Scroll Area for clean fits on lower resolutions
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ---------------------------------------------------------------------
        # 1. Header & Mode Switcher
        # ---------------------------------------------------------------------
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(6, 6, 6, 6)
        header_layout.setSpacing(6)

        title_row = QHBoxLayout()
        lbl_title = QLabel("FRAME & GRID INSPECTOR")
        lbl_title.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        title_row.addWidget(lbl_title)
        title_row.addStretch()

        self.lbl_mode_badge = QLabel("Mode A: Uniform Grid")
        self.lbl_mode_badge.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 600;
            color: {THEME_COLORS['text_primary']};
            background-color: {THEME_COLORS['bg_input']};
            border: 1px solid {THEME_COLORS['border_medium']};
            border-radius: 3px;
            padding: 2px 6px;
        """)
        title_row.addWidget(self.lbl_mode_badge)
        header_layout.addLayout(title_row)

        layout.addWidget(header_frame)

        # ---------------------------------------------------------------------
        # 2. Mode A: Uniform Grid Configuration Card
        # ---------------------------------------------------------------------
        self.grid_group = QGroupBox("Mode A: Uniform Grid Parameters")
        self.grid_group.setStyleSheet(f"""
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
        grid_box_layout = QVBoxLayout(self.grid_group)
        grid_box_layout.setContentsMargins(8, 8, 8, 8)
        grid_box_layout.setSpacing(6)

        grid_inputs = QGridLayout()
        grid_inputs.setHorizontalSpacing(8)
        grid_inputs.setVerticalSpacing(6)

        # Columns & Rows
        grid_inputs.addWidget(QLabel("Columns:"), 0, 0)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 64)
        self.spin_cols.setValue(4)
        grid_inputs.addWidget(self.spin_cols, 0, 1)

        grid_inputs.addWidget(QLabel("Rows:"), 0, 2)
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 64)
        self.spin_rows.setValue(2)
        grid_inputs.addWidget(self.spin_rows, 0, 3)

        # Frame Width & Height
        grid_inputs.addWidget(QLabel("Width (px):"), 1, 0)
        self.spin_fw = QSpinBox()
        self.spin_fw.setRange(1, 4096)
        self.spin_fw.setValue(64)
        grid_inputs.addWidget(self.spin_fw, 1, 1)

        grid_inputs.addWidget(QLabel("Height (px):"), 1, 2)
        self.spin_fh = QSpinBox()
        self.spin_fh.setRange(1, 4096)
        self.spin_fh.setValue(64)
        grid_inputs.addWidget(self.spin_fh, 1, 3)

        # Spacing
        grid_inputs.addWidget(QLabel("H-Spacing:"), 2, 0)
        self.spin_sp_x = QSpinBox()
        self.spin_sp_x.setRange(0, 256)
        self.spin_sp_x.setValue(0)
        grid_inputs.addWidget(self.spin_sp_x, 2, 1)

        grid_inputs.addWidget(QLabel("V-Spacing:"), 2, 2)
        self.spin_sp_y = QSpinBox()
        self.spin_sp_y.setRange(0, 256)
        self.spin_sp_y.setValue(0)
        grid_inputs.addWidget(self.spin_sp_y, 2, 3)

        # Margins
        grid_inputs.addWidget(QLabel("Margin L / T:"), 3, 0)
        margin_lt_layout = QHBoxLayout()
        self.spin_ml = QSpinBox()
        self.spin_ml.setRange(0, 256)
        self.spin_ml.setValue(0)
        self.spin_mt = QSpinBox()
        self.spin_mt.setRange(0, 256)
        self.spin_mt.setValue(0)
        margin_lt_layout.addWidget(self.spin_ml)
        margin_lt_layout.addWidget(self.spin_mt)
        grid_inputs.addLayout(margin_lt_layout, 3, 1)

        grid_inputs.addWidget(QLabel("Margin R / B:"), 3, 2)
        margin_rb_layout = QHBoxLayout()
        self.spin_mr = QSpinBox()
        self.spin_mr.setRange(0, 256)
        self.spin_mr.setValue(0)
        self.spin_mb = QSpinBox()
        self.spin_mb.setRange(0, 256)
        self.spin_mb.setValue(0)
        margin_rb_layout.addWidget(self.spin_mr)
        margin_rb_layout.addWidget(self.spin_mb)
        grid_inputs.addLayout(margin_rb_layout, 3, 3)

        grid_box_layout.addLayout(grid_inputs)

        # Grid Action Buttons
        btn_grid_actions = QHBoxLayout()
        self.btn_auto_calc = QPushButton("Auto-Fit Grid")
        self.btn_auto_calc.setToolTip("Auto-calculate frame width & height from columns/rows to fit image bounds exactly.")
        self.btn_auto_calc.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_auto_calc.clicked.connect(self._on_auto_calc_clicked)
        btn_grid_actions.addWidget(self.btn_auto_calc)

        self.btn_apply_grid = QPushButton("Apply Uniform Grid")
        self.btn_apply_grid.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                border: none;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['accent_hover']};
            }}
            QPushButton:pressed {{
                background-color: {THEME_COLORS['accent_pressed']};
            }}
        """)
        self.btn_apply_grid.clicked.connect(self._on_apply_grid_clicked)
        btn_grid_actions.addWidget(self.btn_apply_grid)

        grid_box_layout.addLayout(btn_grid_actions)
        layout.addWidget(self.grid_group)

        # ---------------------------------------------------------------------
        # 3. Selected Frame Details Card
        # ---------------------------------------------------------------------
        self.frame_details_group = QGroupBox("Selected Frame Properties")
        self.frame_details_group.setStyleSheet(f"""
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
        frame_box_layout = QVBoxLayout(self.frame_details_group)
        frame_box_layout.setContentsMargins(8, 8, 8, 8)
        frame_box_layout.setSpacing(6)

        # Placeholder message when no frame is selected
        self.lbl_no_frame = QLabel("No frame selected.\nClick a frame box on the canvas or timeline card below.")
        self.lbl_no_frame.setAlignment(Qt.AlignCenter)
        self.lbl_no_frame.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px; padding: 12px;")
        frame_box_layout.addWidget(self.lbl_no_frame)

        # Container for actual controls
        self.frame_editor_widget = QWidget()
        editor_layout = QVBoxLayout(self.frame_editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(6)

        # Header Info Row
        hdr_row = QHBoxLayout()
        self.lbl_frame_idx = QLabel("Frame #0")
        self.lbl_frame_idx.setStyleSheet(f"font-weight: 700; color: {THEME_COLORS['accent_primary']}; font-size: 12px;")
        hdr_row.addWidget(self.lbl_frame_idx)

        hdr_row.addStretch()

        self.lbl_transparency = QLabel("RGBA Transparent")
        self.lbl_transparency.setStyleSheet(f"color: {THEME_COLORS['status_success']}; font-size: 10px;")
        hdr_row.addWidget(self.lbl_transparency)
        editor_layout.addLayout(hdr_row)

        # Frame Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.edit_frame_name = QLineEdit()
        self.edit_frame_name.setPlaceholderText("frame_000")
        self.edit_frame_name.textEdited.connect(self._on_frame_name_edited)
        name_row.addWidget(self.edit_frame_name)
        editor_layout.addLayout(name_row)

        # Frame Duration & Sequence Order
        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duration (ms):"))
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(10, 5000)
        self.spin_duration.setValue(100)
        self.spin_duration.setSingleStep(10)
        self.spin_duration.valueChanged.connect(self._on_duration_changed)
        dur_row.addWidget(self.spin_duration)

        dur_row.addWidget(QLabel("Order Index:"))
        self.spin_order = QSpinBox()
        self.spin_order.setRange(0, 999)
        self.spin_order.setValue(0)
        self.spin_order.valueChanged.connect(self._on_order_changed)
        dur_row.addWidget(self.spin_order)
        editor_layout.addLayout(dur_row)

        # Fine-Tuning Coordinates (2x2 Grid)
        coord_grid = QGridLayout()
        coord_grid.setHorizontalSpacing(8)
        coord_grid.setVerticalSpacing(4)

        coord_grid.addWidget(QLabel("X:"), 0, 0)
        self.spin_coord_x = QSpinBox()
        self.spin_coord_x.setRange(0, 20000)
        self.spin_coord_x.valueChanged.connect(self._on_coords_spinbox_changed)
        coord_grid.addWidget(self.spin_coord_x, 0, 1)

        coord_grid.addWidget(QLabel("Y:"), 0, 2)
        self.spin_coord_y = QSpinBox()
        self.spin_coord_y.setRange(0, 20000)
        self.spin_coord_y.valueChanged.connect(self._on_coords_spinbox_changed)
        coord_grid.addWidget(self.spin_coord_y, 0, 3)

        coord_grid.addWidget(QLabel("W:"), 1, 0)
        self.spin_coord_w = QSpinBox()
        self.spin_coord_w.setRange(1, 20000)
        self.spin_coord_w.valueChanged.connect(self._on_coords_spinbox_changed)
        coord_grid.addWidget(self.spin_coord_w, 1, 1)

        coord_grid.addWidget(QLabel("H:"), 1, 2)
        self.spin_coord_h = QSpinBox()
        self.spin_coord_h.setRange(1, 20000)
        self.spin_coord_h.valueChanged.connect(self._on_coords_spinbox_changed)
        coord_grid.addWidget(self.spin_coord_h, 1, 3)

        editor_layout.addLayout(coord_grid)

        frame_box_layout.addWidget(self.frame_editor_widget)
        self.frame_editor_widget.setVisible(False)

        layout.addWidget(self.frame_details_group)

        # ---------------------------------------------------------------------
        # 4. Visual Pivot & Kinematic Anchor Picker
        # ---------------------------------------------------------------------
        self.pivot_group = QGroupBox("Kinematic Pivot / Joint Anchor")
        self.pivot_group.setStyleSheet(f"""
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
        pivot_layout = QVBoxLayout(self.pivot_group)
        pivot_layout.setContentsMargins(8, 8, 8, 8)
        pivot_layout.setSpacing(6)

        pivot_tip = QLabel("Click or drag inside preview to position pivot anchor for Flame physics & rotation joints.")
        pivot_tip.setWordWrap(True)
        pivot_tip.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']};")
        pivot_layout.addWidget(pivot_tip)

        # Picker center area
        picker_center = QHBoxLayout()
        picker_center.addStretch()
        self.pivot_picker = PivotPickerWidget()
        self.pivot_picker.pivot_changed.connect(self._on_visual_pivot_changed)
        picker_center.addWidget(self.pivot_picker)
        picker_center.addStretch()
        pivot_layout.addLayout(picker_center)

        # Pivot readout label
        self.lbl_pivot_readout = QLabel("Normalized: (0.50, 0.50)  |  Offset: (0px, 0px)")
        self.lbl_pivot_readout.setAlignment(Qt.AlignCenter)
        self.lbl_pivot_readout.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {THEME_COLORS['accent_primary']};")
        pivot_layout.addWidget(self.lbl_pivot_readout)

        # Quick Preset Buttons
        lbl_presets = QLabel("Kinematic Presets:")
        lbl_presets.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {THEME_COLORS['text_secondary']};")
        pivot_layout.addWidget(lbl_presets)

        preset_grid = QGridLayout()
        preset_grid.setSpacing(4)

        presets = [
            ("Top Left", "Top Left", 0, 0),
            ("Top Center", "Top Center", 0, 1),
            ("Top Right", "Top Right", 0, 2),
            ("Center", "Center", 1, 0),
            ("Bottom Left", "Bottom Left", 1, 1),
            ("Bottom Center", "Bottom Center", 1, 2),
            ("Bottom Right", "Bottom Right", 2, 0),
        ]

        for name, preset_key, r, c in presets:
            btn = QPushButton(name)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {THEME_COLORS['bg_input']};
                    color: {THEME_COLORS['text_secondary']};
                    border: 1px solid {THEME_COLORS['border_subtle']};
                    border-radius: 3px;
                    padding: 3px;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    border-color: {THEME_COLORS['accent_primary']};
                    color: {THEME_COLORS['text_primary']};
                }}
            """)
            btn.clicked.connect(lambda ch=False, key=preset_key: self._apply_pivot_preset(key))
            preset_grid.addWidget(btn, r, c)

        # Custom numerical inputs
        custom_layout = QHBoxLayout()
        custom_layout.addWidget(QLabel("Custom X:"))
        self.spin_pivot_x = QDoubleSpinBox()
        self.spin_pivot_x.setRange(0.0, 1.0)
        self.spin_pivot_x.setSingleStep(0.05)
        self.spin_pivot_x.setValue(0.5)
        self.spin_pivot_x.valueChanged.connect(self._on_custom_pivot_spin_changed)
        custom_layout.addWidget(self.spin_pivot_x)

        custom_layout.addWidget(QLabel("Y:"))
        self.spin_pivot_y = QDoubleSpinBox()
        self.spin_pivot_y.setRange(0.0, 1.0)
        self.spin_pivot_y.setSingleStep(0.05)
        self.spin_pivot_y.setValue(0.5)
        self.spin_pivot_y.valueChanged.connect(self._on_custom_pivot_spin_changed)
        custom_layout.addWidget(self.spin_pivot_y)

        preset_grid.addLayout(custom_layout, 2, 1, 1, 2)
        pivot_layout.addLayout(preset_grid)

        layout.addWidget(self.pivot_group)

        # ---------------------------------------------------------------------
        # 5. Mode B: Manual Frame Controls
        # ---------------------------------------------------------------------
        self.manual_group = QGroupBox("Mode B: Manual Frame Actions")
        self.manual_group.setStyleSheet(f"""
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
        manual_layout = QVBoxLayout(self.manual_group)
        manual_layout.setContentsMargins(8, 8, 8, 8)
        manual_layout.setSpacing(6)

        self.btn_toggle_draw = QPushButton("✏️ Draw New Frame Box")
        self.btn_toggle_draw.setCheckable(True)
        self.btn_toggle_draw.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:checked {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                border-color: {THEME_COLORS['accent_hover']};
            }}
            QPushButton:hover:!checked {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_toggle_draw.toggled.connect(self.draw_mode_toggled.emit)
        manual_layout.addWidget(self.btn_toggle_draw)

        btn_row_ops = QHBoxLayout()
        self.btn_dup_frame = QPushButton("Duplicate")
        self.btn_dup_frame.setStyleSheet(f"""
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
        """)
        self.btn_dup_frame.clicked.connect(self._on_duplicate_clicked)
        btn_row_ops.addWidget(self.btn_dup_frame)

        self.btn_del_frame = QPushButton("Delete Frame")
        self.btn_del_frame.setStyleSheet(f"""
            QPushButton {{
                background-color: #3b181b;
                color: {THEME_COLORS['status_error']};
                border: 1px solid {THEME_COLORS['status_error']};
                border-radius: 4px;
                padding: 5px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['status_error']};
                color: #ffffff;
            }}
        """)
        self.btn_del_frame.clicked.connect(self._on_delete_clicked)
        btn_row_ops.addWidget(self.btn_del_frame)

        manual_layout.addLayout(btn_row_ops)
        layout.addWidget(self.manual_group)

        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    # -------------------------------------------------------------------------
    # Public Configuration Methods
    # -------------------------------------------------------------------------

    def set_source_image(self, pixmap: Optional[QPixmap], dimensions: Tuple[int, int]):
        """Store reference pixmap and image dimensions for calculations."""
        self._source_pixmap = pixmap
        self._source_dimensions = dimensions
        if dimensions[0] > 0 and dimensions[1] > 0:
            # Set intelligent defaults
            self.spin_fw.setValue(min(128, dimensions[0] // max(1, self.spin_cols.value())))
            self.spin_fh.setValue(min(128, dimensions[1] // max(1, self.spin_rows.value())))

    def set_mode(self, mode: str):
        """Set active layout mode: 'uniform' or 'manual'."""
        self._mode = mode
        if mode == "uniform":
            self.lbl_mode_badge.setText("Mode A: Uniform Grid")
            self.grid_group.setEnabled(True)
        else:
            self.lbl_mode_badge.setText("Mode B: Manual Selection")
            self.grid_group.setEnabled(False)

    def set_draw_mode_active(self, is_active: bool):
        """Sync button state when draw mode changes from canvas."""
        self.btn_toggle_draw.setChecked(is_active)

    def set_selected_frame(self, index: Optional[int], frame_data: Optional[Dict[str, Any]]):
        """Update inspector with selected frame data."""
        self._current_frame_index = index
        self._current_frame = frame_data

        if index is None or frame_data is None:
            self.lbl_no_frame.setVisible(True)
            self.frame_editor_widget.setVisible(False)
            self.pivot_group.setEnabled(False)
            self.btn_dup_frame.setEnabled(False)
            self.btn_del_frame.setEnabled(False)
            self.pivot_picker.set_frame_pixmap(None)
            self.lbl_pivot_readout.setText("Normalized: (0.50, 0.50)  |  Offset: (0px, 0px)")
            return

        self._block_signals = True
        try:
            self.lbl_no_frame.setVisible(False)
            self.frame_editor_widget.setVisible(True)
            self.pivot_group.setEnabled(True)
            self.btn_dup_frame.setEnabled(True)
            self.btn_del_frame.setEnabled(True)

            self.lbl_frame_idx.setText(f"Frame #{index} ({frame_data.get('width', 0)} × {frame_data.get('height', 0)} px)")
            self.edit_frame_name.setText(frame_data.get("frame_name", f"frame_{index:03d}"))
            self.spin_duration.setValue(frame_data.get("duration_ms", 100))
            self.spin_order.setValue(frame_data.get("sequence_order", index))

            x = frame_data.get("x", 0)
            y = frame_data.get("y", 0)
            w = frame_data.get("width", 64)
            h = frame_data.get("height", 64)

            self.spin_coord_x.setValue(x)
            self.spin_coord_y.setValue(y)
            self.spin_coord_w.setValue(w)
            self.spin_coord_h.setValue(h)

            px = float(frame_data.get("pivot_x", 0.5))
            py = float(frame_data.get("pivot_y", 0.5))
            self.spin_pivot_x.setValue(px)
            self.spin_pivot_y.setValue(py)
            self.pivot_picker.set_pivot(px, py)
            self._update_pivot_readout(px, py, w, h)

            # Crop thumbnail for pivot picker
            if self._source_pixmap and not self._source_pixmap.isNull():
                crop_rect = QRect(x, y, w, h).intersected(self._source_pixmap.rect())
                if crop_rect.isValid() and not crop_rect.isEmpty():
                    cropped = self._source_pixmap.copy(crop_rect)
                    self.pivot_picker.set_frame_pixmap(cropped)
                else:
                    self.pivot_picker.set_frame_pixmap(None)
            else:
                self.pivot_picker.set_frame_pixmap(None)

            has_transparency = frame_data.get("has_transparency", 0)
            if has_transparency:
                self.lbl_transparency.setText("RGBA Transparent")
                self.lbl_transparency.setStyleSheet(f"color: {THEME_COLORS['status_success']}; font-size: 10px;")
            else:
                self.lbl_transparency.setText("RGB Opaque")
                self.lbl_transparency.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 10px;")

        finally:
            self._block_signals = False

    def update_frame_coordinates(self, index: int, x: int, y: int, w: int, h: int):
        """Update numerical spinboxes when user modifies box via canvas handles."""
        if self._current_frame_index != index:
            return

        self._block_signals = True
        try:
            self.spin_coord_x.setValue(x)
            self.spin_coord_y.setValue(y)
            self.spin_coord_w.setValue(w)
            self.spin_coord_h.setValue(h)
            self.lbl_frame_idx.setText(f"Frame #{index} ({w} × {h} px)")

            if self._current_frame:
                self._current_frame["x"] = x
                self._current_frame["y"] = y
                self._current_frame["width"] = w
                self._current_frame["height"] = h

            px = self.spin_pivot_x.value()
            py = self.spin_pivot_y.value()
            self._update_pivot_readout(px, py, w, h)

            if self._source_pixmap and not self._source_pixmap.isNull():
                crop_rect = QRect(x, y, w, h).intersected(self._source_pixmap.rect())
                if crop_rect.isValid() and not crop_rect.isEmpty():
                    cropped = self._source_pixmap.copy(crop_rect)
                    self.pivot_picker.set_frame_pixmap(cropped)
        finally:
            self._block_signals = False

    # -------------------------------------------------------------------------
    # Internal Slots & Event Handlers
    # -------------------------------------------------------------------------

    def _on_auto_calc_clicked(self):
        """Auto-calculate frame width & height from dimensions and grid counts."""
        img_w, img_h = self._source_dimensions
        if img_w <= 0 or img_h <= 0:
            return

        cols = self.spin_cols.value()
        rows = self.spin_rows.value()
        sp_x = self.spin_sp_x.value()
        sp_y = self.spin_sp_y.value()
        ml = self.spin_ml.value()
        mr = self.spin_mr.value()
        mt = self.spin_mt.value()
        mb = self.spin_mb.value()

        avail_w = img_w - ml - mr - ((cols - 1) * sp_x)
        avail_h = img_h - mt - mb - ((rows - 1) * sp_y)

        fw = max(1, avail_w // cols)
        fh = max(1, avail_h // rows)

        self.spin_fw.setValue(fw)
        self.spin_fh.setValue(fh)

    def _on_apply_grid_clicked(self):
        """Package parameters and request grid generation."""
        params = {
            "columns": self.spin_cols.value(),
            "rows": self.spin_rows.value(),
            "frame_width": self.spin_fw.value(),
            "frame_height": self.spin_fh.value(),
            "spacing_x": self.spin_sp_x.value(),
            "spacing_y": self.spin_sp_y.value(),
            "margin_left": self.spin_ml.value(),
            "margin_top": self.spin_mt.value(),
            "margin_right": self.spin_mr.value(),
            "margin_bottom": self.spin_mb.value(),
        }
        self.grid_apply_requested.emit(params)

    def _on_frame_name_edited(self, text: str):
        if self._block_signals or self._current_frame_index is None or not self._current_frame:
            return
        self._current_frame["frame_name"] = text.strip()
        self.frame_updated.emit(self._current_frame_index, self._current_frame)

    def _on_duration_changed(self, val: int):
        if self._block_signals or self._current_frame_index is None or not self._current_frame:
            return
        self._current_frame["duration_ms"] = val
        self.frame_updated.emit(self._current_frame_index, self._current_frame)

    def _on_order_changed(self, val: int):
        if self._block_signals or self._current_frame_index is None or not self._current_frame:
            return
        self._current_frame["sequence_order"] = val
        self.frame_updated.emit(self._current_frame_index, self._current_frame)

    def _on_coords_spinbox_changed(self):
        if self._block_signals or self._current_frame_index is None:
            return

        x = self.spin_coord_x.value()
        y = self.spin_coord_y.value()
        w = self.spin_coord_w.value()
        h = self.spin_coord_h.value()

        if self._current_frame:
            self._current_frame["x"] = x
            self._current_frame["y"] = y
            self._current_frame["width"] = w
            self._current_frame["height"] = h

        self.coordinates_edited.emit(self._current_frame_index, x, y, w, h)

    def _on_visual_pivot_changed(self, px: float, py: float):
        if self._block_signals or self._current_frame_index is None:
            return

        self._block_signals = True
        try:
            self.spin_pivot_x.setValue(px)
            self.spin_pivot_y.setValue(py)
            w = self.spin_coord_w.value()
            h = self.spin_coord_h.value()
            self._update_pivot_readout(px, py, w, h)

            if self._current_frame:
                self._current_frame["pivot_x"] = px
                self._current_frame["pivot_y"] = py
        finally:
            self._block_signals = False

        self.pivot_updated.emit(self._current_frame_index, px, py)

    def _on_custom_pivot_spin_changed(self):
        if self._block_signals or self._current_frame_index is None:
            return

        px = self.spin_pivot_x.value()
        py = self.spin_pivot_y.value()
        self.pivot_picker.set_pivot(px, py)
        w = self.spin_coord_w.value()
        h = self.spin_coord_h.value()
        self._update_pivot_readout(px, py, w, h)

        if self._current_frame:
            self._current_frame["pivot_x"] = px
            self._current_frame["pivot_y"] = py

        self.pivot_updated.emit(self._current_frame_index, px, py)

    def _apply_pivot_preset(self, preset_name: str):
        preset = PIVOT_PRESETS.get(preset_name)
        if not preset or self._current_frame_index is None:
            return

        px, py = preset
        self._block_signals = True
        try:
            self.spin_pivot_x.setValue(px)
            self.spin_pivot_y.setValue(py)
            self.pivot_picker.set_pivot(px, py)
            w = self.spin_coord_w.value()
            h = self.spin_coord_h.value()
            self._update_pivot_readout(px, py, w, h)

            if self._current_frame:
                self._current_frame["pivot_x"] = px
                self._current_frame["pivot_y"] = py
        finally:
            self._block_signals = False

        self.pivot_updated.emit(self._current_frame_index, px, py)

    def _update_pivot_readout(self, px: float, py: float, w: int, h: int):
        off_x = int(round(px * w))
        off_y = int(round(py * h))
        self.lbl_pivot_readout.setText(f"Normalized: ({px:.2f}, {py:.2f})  |  Offset: ({off_x}px, {off_y}px)")

    def _on_duplicate_clicked(self):
        if self._current_frame_index is not None:
            self.duplicate_frame_requested.emit(self._current_frame_index)

    def _on_delete_clicked(self):
        if self._current_frame_index is not None:
            self.delete_frame_requested.emit(self._current_frame_index)
