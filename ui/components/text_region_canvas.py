"""
Interactive Text Region Canvas Component (Stage 6)
Renders image with category-colored bounding boxes, zoom, pan, hover inspection,
box selection, and manual bounding box drawing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QMouseEvent, QPainter, QPainterPath,
    QPen, QPixmap, QWheelEvent
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
    QToolTip, QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.text_engine import CATEGORY_COLORS

logger = logging.getLogger("AssetProcessor.TextRegionCanvas")


class TextCanvasWidget(QWidget):
    """
    Core interactive canvas widget drawing image and bounding box overlays.
    Supports zoom, pan, selection, hover tooltips, and manual bounding box creation.
    """

    region_selected = Signal(dict)
    region_deselected = Signal()
    new_region_drawn = Signal(int, int, int, int)  # x, y, w, h in image pixel coordinates

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._pixmap: Optional[QPixmap] = None
        self._image_path: Optional[str] = None
        self._regions: List[Dict[str, Any]] = []
        self._selected_region_id: Optional[int] = None
        self._hovered_region_id: Optional[int] = None

        # Zoom & Pan State
        self._scale: float = 1.0
        self._offset: QPointF = QPointF(0, 0)
        self._is_panning: bool = False
        self._last_mouse_pos: QPoint = QPoint()

        # Drawing Mode State
        self._draw_mode: bool = False
        self._is_drawing: bool = False
        self._draw_start_img: Optional[QPoint] = None
        self._draw_current_img: Optional[QPoint] = None

    def set_draw_mode(self, enabled: bool):
        """Toggle manual bounding box creation mode."""
        self._draw_mode = enabled
        if enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def is_draw_mode(self) -> bool:
        return self._draw_mode

    def load_image(self, file_path: str, regions: Optional[List[Dict[str, Any]]] = None):
        """Load an image and its detected text regions."""
        self._image_path = file_path
        self._regions = regions or []
        self._selected_region_id = None
        self._hovered_region_id = None
        self._is_drawing = False

        if file_path and Path(file_path).exists():
            self._pixmap = QPixmap(file_path)
            self.fit_to_screen()
        else:
            self._pixmap = None
            self.update()

    def set_regions(self, regions: List[Dict[str, Any]]):
        """Update active region overlays."""
        self._regions = regions or []
        self.update()

    def select_region(self, region_id: Optional[int]):
        """Highlight a specific region by ID."""
        self._selected_region_id = region_id
        self.update()

    def fit_to_screen(self):
        """Scale and center image within widget boundaries."""
        if not self._pixmap or self._pixmap.isNull():
            self.update()
            return

        vw = max(100, self.width())
        vh = max(100, self.height())
        pw = self._pixmap.width()
        ph = self._pixmap.height()

        if pw <= 0 or ph <= 0:
            return

        scale_x = (vw - 30) / float(pw)
        scale_y = (vh - 30) / float(ph)
        self._scale = max(0.05, min(scale_x, scale_y, 1.5))

        # Center in canvas
        scaled_w = pw * self._scale
        scaled_h = ph * self._scale
        self._offset = QPointF((vw - scaled_w) / 2.0, (vh - scaled_h) / 2.0)
        self.update()

    def reset_100(self):
        """Reset zoom to 100% (1:1 scale)."""
        if not self._pixmap:
            return
        self._scale = 1.0
        vw = self.width()
        vh = self.height()
        pw = self._pixmap.width()
        ph = self._pixmap.height()
        self._offset = QPointF((vw - pw) / 2.0, (vh - ph) / 2.0)
        self.update()

    def set_zoom(self, factor: float):
        """Set zoom scale factor directly."""
        self._scale = max(0.1, min(factor, 8.0))
        self.update()

    def get_zoom(self) -> float:
        return self._scale

    # Coordinate mapping utilities
    def img_to_canvas(self, ix: float, iy: float) -> QPointF:
        """Map image coordinates to canvas widget coordinates."""
        return QPointF(self._offset.x() + ix * self._scale, self._offset.y() + iy * self._scale)

    def canvas_to_img(self, cx: float, cy: float) -> QPoint:
        """Map canvas widget coordinates to image pixel coordinates."""
        if self._scale <= 0:
            return QPoint(0, 0)
        ix = (cx - self._offset.x()) / self._scale
        iy = (cy - self._offset.y()) / self._scale
        return QPoint(int(round(ix)), int(round(iy)))

    # Paint event
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Background canvas fill
        painter.fillRect(self.rect(), QColor(THEME_COLORS["bg_main"]))

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(THEME_COLORS["text_muted"]))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "No image loaded or file not found")
            return

        pw = self._pixmap.width()
        ph = self._pixmap.height()
        dest_rect = QRectF(self._offset.x(), self._offset.y(), pw * self._scale, ph * self._scale)

        # Draw dark border around image
        painter.setPen(QPen(QColor(THEME_COLORS["border_medium"]), 1))
        painter.drawRect(dest_rect)

        # Draw image
        painter.drawPixmap(dest_rect.toRect(), self._pixmap)

        # Draw detected text regions
        for region in self._regions:
            self._draw_region(painter, region)

        # Draw in-progress manual box creation
        if self._is_drawing and self._draw_start_img and self._draw_current_img:
            self._draw_draft_box(painter)

    def _draw_region(self, painter: QPainter, region: Dict[str, Any]):
        """Draw an individual detected text bounding box with category styling."""
        bx = region.get("box_x", 0)
        by = region.get("box_y", 0)
        bw = region.get("box_w", 0)
        bh = region.get("box_h", 0)
        category = region.get("category", "Unknown writing")
        reg_id = region.get("id")
        is_selected = (reg_id == self._selected_region_id)
        is_hovered = (reg_id == self._hovered_region_id)
        is_wm = region.get("is_watermark_candidate", 0) == 1

        # Calculate canvas rectangle
        top_left = self.img_to_canvas(bx, by)
        c_w = bw * self._scale
        c_h = bh * self._scale
        rect = QRectF(top_left.x(), top_left.y(), c_w, c_h)

        # Determine color
        cat_hex = CATEGORY_COLORS.get(category, "#9CA3AF")
        base_color = QColor(cat_hex)

        if is_selected:
            border_color = QColor(THEME_COLORS["accent_primary"])  # Bright Amber
            fill_color = QColor(border_color.red(), border_color.green(), border_color.blue(), 65)
            pen_width = max(2.5, 3.0 / self._scale)
        elif is_hovered:
            border_color = base_color.lighter(130)
            fill_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 50)
            pen_width = max(2.0, 2.5 / self._scale)
        else:
            border_color = base_color
            fill_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 28)
            pen_width = max(1.5, 2.0 / self._scale)

        # Draw semi-transparent fill
        painter.fillRect(rect, fill_color)

        # Draw border
        pen = QPen(border_color, min(4.0, pen_width))
        if is_wm:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

        # Draw label pill if zoom permits
        if c_h >= 14 or is_selected or is_hovered:
            display_text = region.get("recognized_text") or category
            if len(display_text) > 24:
                display_text = display_text[:21] + "..."

            font = QFont("Segoe UI", 9, QFont.Bold if is_selected else QFont.Normal)
            painter.setFont(font)

            pill_h = 16
            pill_w = max(50, len(display_text) * 7 + 10)
            pill_rect = QRectF(rect.x(), max(0, rect.y() - pill_h), pill_w, pill_h)

            painter.fillRect(pill_rect, border_color)
            painter.setPen(QColor("#111827"))  # Dark text on bright badge
            painter.drawText(pill_rect, Qt.AlignCenter, display_text)

        # Draw corner grab handles if selected
        if is_selected:
            handle_size = 6
            painter.setBrush(QBrush(QColor(THEME_COLORS["accent_primary"])))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(rect.x() - handle_size / 2, rect.y() - handle_size / 2, handle_size, handle_size))
            painter.drawRect(QRectF(rect.right() - handle_size / 2, rect.y() - handle_size / 2, handle_size, handle_size))
            painter.drawRect(QRectF(rect.x() - handle_size / 2, rect.bottom() - handle_size / 2, handle_size, handle_size))
            painter.drawRect(QRectF(rect.right() - handle_size / 2, rect.bottom() - handle_size / 2, handle_size, handle_size))

    def _draw_draft_box(self, painter: QPainter):
        """Draw the manual rectangle currently being dragged by user."""
        p1 = self.img_to_canvas(self._draw_start_img.x(), self._draw_start_img.y())
        p2 = self.img_to_canvas(self._draw_current_img.x(), self._draw_current_img.y())

        rx = min(p1.x(), p2.x())
        ry = min(p1.y(), p2.y())
        rw = abs(p2.x() - p1.x())
        rh = abs(p2.y() - p1.y())
        rect = QRectF(rx, ry, rw, rh)

        painter.fillRect(rect, QColor(229, 169, 60, 40))
        pen = QPen(QColor(THEME_COLORS["accent_primary"]), 2, Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

    # Mouse & Keyboard Events
    def mousePressEvent(self, event: QMouseEvent):
        if not self._pixmap:
            return

        if self._draw_mode and event.button() == Qt.LeftButton:
            img_pt = self.canvas_to_img(event.position().x(), event.position().y())
            # Clamp to image bounds
            ix = max(0, min(img_pt.x(), self._pixmap.width()))
            iy = max(0, min(img_pt.y(), self._pixmap.height()))
            self._is_drawing = True
            self._draw_start_img = QPoint(ix, iy)
            self._draw_current_img = QPoint(ix, iy)
            self.update()
            return

        if event.button() == Qt.LeftButton:
            # Check if clicked inside any bounding box
            img_pt = self.canvas_to_img(event.position().x(), event.position().y())
            clicked_region = None

            # Reverse search to pick topmost box
            for r in reversed(self._regions):
                rx = r.get("box_x", 0)
                ry = r.get("box_y", 0)
                rw = r.get("box_w", 0)
                rh = r.get("box_h", 0)
                if rx <= img_pt.x() <= (rx + rw) and ry <= img_pt.y() <= (ry + rh):
                    clicked_region = r
                    break

            if clicked_region:
                self._selected_region_id = clicked_region.get("id")
                self.region_selected.emit(clicked_region)
            else:
                self._selected_region_id = None
                self.region_deselected.emit()

            self.update()

        elif event.button() in (Qt.MiddleButton, Qt.RightButton):
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._pixmap:
            return

        # Panning
        if self._is_panning:
            delta = event.pos() - self._last_mouse_pos
            self._offset += QPointF(delta.x(), delta.y())
            self._last_mouse_pos = event.pos()
            self.update()
            return

        # Drawing box
        if self._is_drawing and self._draw_start_img:
            img_pt = self.canvas_to_img(event.position().x(), event.position().y())
            ix = max(0, min(img_pt.x(), self._pixmap.width()))
            iy = max(0, min(img_pt.y(), self._pixmap.height()))
            self._draw_current_img = QPoint(ix, iy)
            self.update()
            return

        # Hover detection
        img_pt = self.canvas_to_img(event.position().x(), event.position().y())
        hovered = None
        for r in reversed(self._regions):
            rx = r.get("box_x", 0)
            ry = r.get("box_y", 0)
            rw = r.get("box_w", 0)
            rh = r.get("box_h", 0)
            if rx <= img_pt.x() <= (rx + rw) and ry <= img_pt.y() <= (ry + rh):
                hovered = r
                break

        old_hovered = self._hovered_region_id
        self._hovered_region_id = hovered.get("id") if hovered else None

        if self._hovered_region_id != old_hovered:
            self.update()

        if hovered:
            tip = f"<b>{hovered.get('category')}</b><br>"
            if hovered.get("recognized_text"):
                tip += f"Text: {hovered.get('recognized_text')}<br>"
            tip += f"Conf: {int(hovered.get('confidence', 0) * 100)}%<br>"
            tip += f"Box: {hovered.get('box_w')}×{hovered.get('box_h')} px"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CrossCursor if self._draw_mode else Qt.ArrowCursor)

        if self._is_drawing:
            self._is_drawing = False
            if self._draw_start_img and self._draw_current_img:
                x1 = self._draw_start_img.x()
                y1 = self._draw_start_img.y()
                x2 = self._draw_current_img.x()
                y2 = self._draw_current_img.y()

                bx = min(x1, x2)
                by = min(y1, y2)
                bw = abs(x2 - x1)
                bh = abs(y2 - y1)

                if bw >= 8 and bh >= 8:
                    self.new_region_drawn.emit(bx, by, bw, bh)

            self._draw_start_img = None
            self._draw_current_img = None
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        """Zoom in and out centered on mouse cursor position."""
        if not self._pixmap:
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        old_scale = self._scale
        new_scale = max(0.08, min(old_scale * factor, 8.0))

        if abs(new_scale - old_scale) < 1e-4:
            return

        # Zoom toward cursor
        mouse_pos = event.position()
        self._offset = mouse_pos - (mouse_pos - self._offset) * (new_scale / old_scale)
        self._scale = new_scale
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep centered if first resize
        if self._pixmap and self._scale == 1.0:
            self.fit_to_screen()


class TextRegionCanvas(QFrame):
    """
    Complete composite canvas widget with toolbar controls (zoom, pan, 1:1, fit, draw mode).
    """

    region_selected = Signal(dict)
    region_deselected = Signal()
    new_region_drawn = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 1. Canvas Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 4)
        toolbar.setSpacing(6)

        self.btn_fit = QPushButton("Fit")
        self.btn_fit.setToolTip("Fit image to screen")
        self.btn_fit.setStyleSheet(self._btn_style())
        self.btn_fit.clicked.connect(self._on_fit_clicked)
        toolbar.addWidget(self.btn_fit)

        self.btn_100 = QPushButton("100%")
        self.btn_100.setToolTip("View at 1:1 scale")
        self.btn_100.setStyleSheet(self._btn_style())
        self.btn_100.clicked.connect(self._on_100_clicked)
        toolbar.addWidget(self.btn_100)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setToolTip("Zoom In")
        self.btn_zoom_in.setFixedSize(26, 24)
        self.btn_zoom_in.setStyleSheet(self._btn_style())
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        toolbar.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setToolTip("Zoom Out")
        self.btn_zoom_out.setFixedSize(26, 24)
        self.btn_zoom_out.setStyleSheet(self._btn_style())
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        toolbar.addWidget(self.btn_zoom_out)

        toolbar.addSpacing(10)

        self.btn_draw = QPushButton("✏️ Draw Box")
        self.btn_draw.setCheckable(True)
        self.btn_draw.setToolTip("Toggle manual bounding box creation mode (click & drag on image)")
        self.btn_draw.setStyleSheet(self._toggle_btn_style())
        self.btn_draw.toggled.connect(self._toggle_draw_mode)
        toolbar.addWidget(self.btn_draw)

        toolbar.addStretch()

        self.lbl_info = QLabel("Scroll to zoom • Drag to pan • Click box to inspect")
        self.lbl_info.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px;")
        toolbar.addWidget(self.lbl_info)

        layout.addLayout(toolbar)

        # 2. Main Canvas
        self.canvas = TextCanvasWidget(self)
        self.canvas.region_selected.connect(self.region_selected.emit)
        self.canvas.region_deselected.connect(self.region_deselected.emit)
        self.canvas.new_region_drawn.connect(self.new_region_drawn.emit)
        layout.addWidget(self.canvas, stretch=1)

    def load_image(self, file_path: str, regions: Optional[List[Dict[str, Any]]] = None):
        self.canvas.load_image(file_path, regions)

    def set_regions(self, regions: List[Dict[str, Any]]):
        self.canvas.set_regions(regions)

    def select_region(self, region_id: Optional[int]):
        self.canvas.select_region(region_id)

    def set_draw_mode(self, enabled: bool):
        self.btn_draw.setChecked(enabled)
        self.canvas.set_draw_mode(enabled)

    def _on_fit_clicked(self):
        self.canvas.fit_to_screen()

    def _on_100_clicked(self):
        self.canvas.reset_100()

    def _zoom_in(self):
        self.canvas.set_zoom(self.canvas.get_zoom() * 1.25)

    def _zoom_out(self):
        self.canvas.set_zoom(self.canvas.get_zoom() / 1.25)

    def _toggle_draw_mode(self, checked: bool):
        self.canvas.set_draw_mode(checked)
        if checked:
            self.lbl_info.setText("Drawing Mode: Click and drag on image to create a new text box")
        else:
            self.lbl_info.setText("Scroll to zoom • Drag to pan • Click box to inspect")

    def _btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['bg_card_hover']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """

    def _toggle_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {THEME_COLORS['bg_card_hover']};
            }}
            QPushButton:checked {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                border-color: {THEME_COLORS['accent_hover']};
            }}
        """
