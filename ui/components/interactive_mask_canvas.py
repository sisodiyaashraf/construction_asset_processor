"""
Interactive Mask & Component Canvas (Stage 13.1 High-Performance Edition)
Construction Asset Processor

Optimizations:
1. Double-buffered scaled pixmap caching: eliminates repeated full-resolution re-scaling on every mouse move.
2. Rendered stroke overlay layer: completed strokes are painted onto an overlay QPixmap once, removing expensive Python point loops from paintEvent.
3. Smooth 60 FPS panning & brush movement with delta distance throttling.
4. Dark industrial checkerboard backing with zero redundant paint passes.
5. Exact coordinate conversion between screen space and image space.
6. Memory-bounded caching and automatic resource release on image switch.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter,
    QPainterPath, QPaintEvent, QPen, QPixmap, QWheelEvent, QMouseEvent
)
from PySide6.QtWidgets import QFrame, QWidget

from app.config import THEME_COLORS


class InteractiveMaskCanvas(QFrame):
    """High-performance interactive canvas widget for brush strokes, crop rectangles, and kinematic pivot editing."""

    stroke_added = Signal(list, int, bool)          # points, radius, is_fg
    crop_rect_changed = Signal(int, int, int, int)  # x, y, w, h in image pixel coordinates
    polygon_completed = Signal(list)                # list of (x, y) image coordinates
    pivot_placed = Signal(float, float, int, int)   # norm_x, norm_y, pixel_x, pixel_y
    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']}; border: 1px solid {THEME_COLORS['border_subtle']};")

        # Current image data
        self.pixmap: Optional[QPixmap] = None
        self.image_width: int = 0
        self.image_height: int = 0

        # Viewport transform
        self.scale: float = 1.0
        self.offset: QPointF = QPointF(0, 0)
        self.last_mouse_pos: QPoint = QPoint()
        self.is_panning: bool = False

        # Performance Caches
        self._cached_scaled_pixmap: Optional[QPixmap] = None
        self._cached_scale_level: float = 0.0
        self._overlay_pixmap: Optional[QPixmap] = None  # Pre-rendered stroke overlay

        # Active Tool: "pan", "fg_brush", "bg_brush", "rect_crop", "lasso", "pivot"
        self.current_tool: str = "pan"
        self.brush_radius: int = 15

        # Brush strokes storage for undo/redo & export
        self.brush_strokes: List[Dict[str, Any]] = []
        self.active_stroke_points: List[QPointF] = []
        self.is_drawing_stroke: bool = False

        # Crop rectangle: QRect in image coordinates
        self.crop_rect: Optional[QRect] = None
        self.crop_start_point: Optional[QPoint] = None
        self.is_drawing_rect: bool = False

        # Polygon / Lasso points in image coordinates
        self.polygon_points: List[Tuple[int, int]] = []
        self.is_drawing_lasso: bool = False

        # Kinematic pivot in normalized coordinates (0.0 - 1.0)
        self.pivot_norm: Optional[Tuple[float, float]] = None

        # Checkerboard brush
        self._checker_brush = self._create_checkerboard_brush()

    def _create_checkerboard_brush(self, square_size: int = 12) -> QBrush:
        """Create high-contrast dark industrial checkerboard pattern."""
        pix = QPixmap(square_size * 2, square_size * 2)
        pix.fill(QColor("#181B1F"))
        painter = QPainter(pix)
        alt_color = QColor("#22272E")
        painter.fillRect(0, 0, square_size, square_size, alt_color)
        painter.fillRect(square_size, square_size, square_size, square_size, alt_color)
        painter.end()
        return QBrush(pix)

    def set_image(self, pixmap_or_path: QPixmap | str | None):
        """Load new image into canvas, invalidate display caches, and fit to view."""
        # Release old scaled pixmap cache to free memory
        self._cached_scaled_pixmap = None
        self._cached_scale_level = 0.0

        if isinstance(pixmap_or_path, str):
            p = QPixmap(pixmap_or_path)
            self.pixmap = p if not p.isNull() else None
        elif isinstance(pixmap_or_path, QPixmap):
            self.pixmap = pixmap_or_path if not pixmap_or_path.isNull() else None
        else:
            self.pixmap = None

        if self.pixmap and not self.pixmap.isNull():
            self.image_width = self.pixmap.width()
            self.image_height = self.pixmap.height()
            self._init_overlay_pixmap()
            self.fit_to_view()
        else:
            self.image_width = 0
            self.image_height = 0
            self.pixmap = None
            self._overlay_pixmap = None

        self.clear_overlays()
        self.update()

    def _init_overlay_pixmap(self):
        """Initialize transparent overlay pixmap for strokes."""
        if self.image_width > 0 and self.image_height > 0:
            self._overlay_pixmap = QPixmap(self.image_width, self.image_height)
            self._overlay_pixmap.fill(Qt.transparent)
        else:
            self._overlay_pixmap = None

    def _update_scaled_cache(self):
        """Update cached scaled pixmap if scale changed significantly."""
        if not self.pixmap or self.image_width == 0 or self.image_height == 0:
            self._cached_scaled_pixmap = None
            self._cached_scale_level = 0.0
            return

        target_w = max(1, int(self.image_width * self.scale))
        target_h = max(1, int(self.image_height * self.scale))

        # Re-scale only when scale level changes
        if self._cached_scaled_pixmap is None or abs(self._cached_scale_level - self.scale) > 0.001:
            self._cached_scaled_pixmap = self.pixmap.scaled(
                target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._cached_scale_level = self.scale

    def clear_overlays(self):
        """Reset brush strokes, crop rectangles, and lasso points."""
        self.brush_strokes.clear()
        self.active_stroke_points.clear()
        self.crop_rect = None
        self.polygon_points.clear()
        self._init_overlay_pixmap()
        self.update()

    def set_tool(self, tool_name: str):
        """Set active interaction mode."""
        self.current_tool = tool_name
        if tool_name == "pan":
            self.setCursor(Qt.OpenHandCursor)
        elif tool_name in ("fg_brush", "bg_brush", "rect_crop", "lasso"):
            self.setCursor(Qt.CrossCursor)
        elif tool_name == "pivot":
            self.setCursor(Qt.PointingHandCursor)
        self.update()

    def set_brush_radius(self, radius: int):
        self.brush_radius = max(2, min(100, radius))
        self.update()

    def set_pivot(self, norm_x: float, norm_y: float):
        """Manually update displayed pivot point."""
        self.pivot_norm = (norm_x, norm_y)
        self.update()

    def set_crop_rect(self, x: int, y: int, w: int, h: int):
        """Set crop rectangle programmatically."""
        self.crop_rect = QRect(x, y, w, h)
        self.update()

    def fit_to_view(self):
        """Scale and center image within canvas dimensions."""
        if not self.pixmap or self.image_width == 0 or self.image_height == 0:
            return

        w_canvas = max(100, self.width() - 40)
        h_canvas = max(100, self.height() - 40)

        scale_w = w_canvas / self.image_width
        scale_h = h_canvas / self.image_height
        self.scale = min(scale_w, scale_h, 1.0)
        self.scale = max(0.05, min(10.0, self.scale))

        # Center in canvas
        scaled_w = self.image_width * self.scale
        scaled_h = self.image_height * self.scale
        self.offset = QPointF(
            (self.width() - scaled_w) / 2.0,
            (self.height() - scaled_h) / 2.0
        )
        self._update_scaled_cache()
        self.zoom_changed.emit(self.scale)
        self.update()

    def set_zoom_1_to_1(self):
        """Set zoom to exact 1:1 original pixel scale."""
        if not self.pixmap:
            return
        self.scale = 1.0
        scaled_w = self.image_width
        scaled_h = self.image_height
        self.offset = QPointF(
            (self.width() - scaled_w) / 2.0,
            (self.height() - scaled_h) / 2.0
        )
        self._update_scaled_cache()
        self.zoom_changed.emit(self.scale)
        self.update()

    def zoom_in(self):
        self._apply_zoom_at(1.25, QPoint(self.width() // 2, self.height() // 2))

    def zoom_out(self):
        self._apply_zoom_at(0.8, QPoint(self.width() // 2, self.height() // 2))

    def _apply_zoom_at(self, factor: float, center_pos: QPoint):
        new_scale = max(0.05, min(10.0, self.scale * factor))
        if new_scale == self.scale:
            return

        mouse_f = QPointF(center_pos)
        img_pos = (mouse_f - self.offset) / self.scale
        self.scale = new_scale
        self.offset = mouse_f - (img_pos * self.scale)
        self._update_scaled_cache()
        self.zoom_changed.emit(self.scale)
        self.update()

    def widget_to_image_coords(self, pos: QPoint | QPointF) -> Tuple[int, int]:
        """Convert widget canvas coordinates to source image pixel coordinates."""
        img_x = (pos.x() - self.offset.x()) / self.scale
        img_y = (pos.y() - self.offset.y()) / self.scale
        return int(round(img_x)), int(round(img_y))

    def image_to_widget_coords(self, img_x: float, img_y: float) -> QPointF:
        """Convert image coordinates to widget canvas coordinates."""
        return QPointF(
            img_x * self.scale + self.offset.x(),
            img_y * self.scale + self.offset.y()
        )

    # Mouse & Gesture Event Handlers
    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 0.85
        self._apply_zoom_at(factor, event.position().toPoint())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        img_x, img_y = self.widget_to_image_coords(pos)

        # Pan with middle button, or when pan tool is active
        if event.button() == Qt.MiddleButton or self.current_tool == "pan":
            self.is_panning = True
            self.last_mouse_pos = pos
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if not self.pixmap:
            return

        # Foreground or Background Brush
        if self.current_tool in ("fg_brush", "bg_brush") and event.button() == Qt.LeftButton:
            self.is_drawing_stroke = True
            self.active_stroke_points = [QPointF(img_x, img_y)]
            self.update()
            event.accept()
            return

        # Rectangle Crop Selection
        if self.current_tool == "rect_crop" and event.button() == Qt.LeftButton:
            self.is_drawing_rect = True
            self.crop_start_point = QPoint(img_x, img_y)
            self.crop_rect = QRect(img_x, img_y, 0, 0)
            self.update()
            event.accept()
            return

        # Polygon / Lasso Selection
        if self.current_tool == "lasso":
            if event.button() == Qt.LeftButton:
                self.is_drawing_lasso = True
                self.polygon_points.append((img_x, img_y))
                self.update()
                event.accept()
                return
            elif event.button() == Qt.RightButton and len(self.polygon_points) >= 3:
                # Close polygon on right-click
                self.polygon_completed.emit(list(self.polygon_points))
                self.is_drawing_lasso = False
                self.update()
                event.accept()
                return

        # Kinematic Pivot Placement
        if self.current_tool == "pivot" and event.button() == Qt.LeftButton:
            norm_x = min(1.0, max(0.0, img_x / self.image_width)) if self.image_width > 0 else 0.5
            norm_y = min(1.0, max(0.0, img_y / self.image_height)) if self.image_height > 0 else 0.5
            self.pivot_norm = (round(norm_x, 4), round(norm_y, 4))
            self.pivot_placed.emit(self.pivot_norm[0], self.pivot_norm[1], img_x, img_y)
            self.update()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()

        if self.is_panning:
            diff = pos - self.last_mouse_pos
            self.offset += QPointF(diff)
            self.last_mouse_pos = pos
            self.update()
            event.accept()
            return

        img_x, img_y = self.widget_to_image_coords(pos)

        # Drawing brush stroke (throttle points to avoid duplicate events within 2px)
        if self.is_drawing_stroke and self.current_tool in ("fg_brush", "bg_brush"):
            if self.active_stroke_points:
                last_pt = self.active_stroke_points[-1]
                dx = abs(last_pt.x() - img_x)
                dy = abs(last_pt.y() - img_y)
                if dx >= 2 or dy >= 2:
                    self.active_stroke_points.append(QPointF(img_x, img_y))
                    self.update()
            else:
                self.active_stroke_points.append(QPointF(img_x, img_y))
                self.update()
            event.accept()
            return

        # Drawing rectangle crop box
        if self.is_drawing_rect and self.crop_start_point:
            x1 = min(self.crop_start_point.x(), img_x)
            y1 = min(self.crop_start_point.y(), img_y)
            x2 = max(self.crop_start_point.x(), img_x)
            y2 = max(self.crop_start_point.y(), img_y)
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(self.image_width, x2)
            y2 = min(self.image_height, y2)
            self.crop_rect = QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
            self.update()
            event.accept()
            return

        # Continuous lasso dragging if mouse held down
        if self.is_drawing_lasso and (event.buttons() & Qt.LeftButton):
            if not self.polygon_points or (abs(self.polygon_points[-1][0] - img_x) > 3 or abs(self.polygon_points[-1][1] - img_y) > 3):
                self.polygon_points.append((img_x, img_y))
                self.update()
                event.accept()
                return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.is_panning:
            self.is_panning = False
            self.setCursor(Qt.OpenHandCursor if self.current_tool == "pan" else Qt.CrossCursor)
            event.accept()
            return

        if self.is_drawing_stroke:
            self.is_drawing_stroke = False
            if self.active_stroke_points:
                is_fg = (self.current_tool == "fg_brush")
                stroke_dict = {
                    "points": [(p.x(), p.y()) for p in self.active_stroke_points],
                    "radius": self.brush_radius,
                    "is_fg": is_fg,
                }
                self.brush_strokes.append(stroke_dict)
                # Render this stroke directly into the overlay pixmap buffer
                self._render_stroke_to_overlay(stroke_dict)
                self.stroke_added.emit(stroke_dict["points"], stroke_dict["radius"], is_fg)
                self.active_stroke_points = []
            self.update()
            event.accept()
            return

        if self.is_drawing_rect:
            self.is_drawing_rect = False
            if self.crop_rect and self.crop_rect.width() > 5 and self.crop_rect.height() > 5:
                self.crop_rect_changed.emit(
                    self.crop_rect.x(), self.crop_rect.y(),
                    self.crop_rect.width(), self.crop_rect.height()
                )
            self.update()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def _render_stroke_to_overlay(self, stroke: Dict[str, Any]):
        """Bake committed stroke into the persistent overlay buffer once."""
        if not self._overlay_pixmap:
            self._init_overlay_pixmap()
        if not self._overlay_pixmap:
            return

        painter = QPainter(self._overlay_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        is_fg = stroke.get("is_fg", True)
        pts = stroke.get("points", [])
        radius = stroke.get("radius", 15)
        stroke_color = QColor(16, 185, 129, 140) if is_fg else QColor(239, 68, 68, 140)

        pen = QPen(stroke_color, radius * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)

        if len(pts) == 1:
            painter.setBrush(QBrush(stroke_color))
            painter.drawEllipse(QPointF(pts[0][0], pts[0][1]), radius, radius)
        elif len(pts) > 1:
            path = QPainterPath()
            path.moveTo(QPointF(pts[0][0], pts[0][1]))
            for pt in pts[1:]:
                path.lineTo(QPointF(pt[0], pt[1]))
            painter.drawPath(path)

        painter.end()

    # Paint Event
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # Fast blit for base
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

        # 1. Fill canvas base
        painter.fillRect(self.rect(), QColor(THEME_COLORS["bg_main"]))

        if not self.pixmap or self.pixmap.isNull():
            painter.setPen(QPen(QColor(THEME_COLORS["text_muted"])))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, "Select an image from the catalog to inspect & prepare")
            painter.end()
            return

        # 2. Viewport Rectangle
        scaled_w = self.image_width * self.scale
        scaled_h = self.image_height * self.scale
        img_rect = QRectF(self.offset.x(), self.offset.y(), scaled_w, scaled_h)

        # 3. Draw Checkerboard background under image
        painter.fillRect(img_rect, self._checker_brush)

        # 4. Draw Image (use cached scaled pixmap for instant 60fps rendering)
        if self._cached_scaled_pixmap and not self._cached_scaled_pixmap.isNull():
            painter.drawPixmap(int(self.offset.x()), int(self.offset.y()), self._cached_scaled_pixmap)
        else:
            painter.drawPixmap(img_rect.toRect(), self.pixmap)

        # 5. Draw Image Border
        border_pen = QPen(QColor(THEME_COLORS["border_medium"]), 1, Qt.DashLine)
        painter.setPen(border_pen)
        painter.drawRect(img_rect)

        # 6. Render Pre-Baked Stroke Overlay (single drawPixmap call instead of looping 1000s of points!)
        if self._overlay_pixmap and not self._overlay_pixmap.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(img_rect.toRect(), self._overlay_pixmap)

        # 7. Render Active Stroke while dragging (dynamic layer)
        if self.is_drawing_stroke and self.active_stroke_points:
            painter.setRenderHint(QPainter.Antialiasing, True)
            is_fg = (self.current_tool == "fg_brush")
            stroke_color = QColor(16, 185, 129, 180) if is_fg else QColor(239, 68, 68, 180)
            radius = self.brush_radius * self.scale
            pen = QPen(stroke_color, radius * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            p0 = self.image_to_widget_coords(self.active_stroke_points[0].x(), self.active_stroke_points[0].y())
            path.moveTo(p0)
            for pt in self.active_stroke_points[1:]:
                path.lineTo(self.image_to_widget_coords(pt.x(), pt.y()))
            painter.drawPath(path)

        # 8. Render Polygon / Lasso Selection
        if self.polygon_points:
            painter.setRenderHint(QPainter.Antialiasing, True)
            lasso_pen = QPen(QColor(THEME_COLORS["accent_primary"]), 2, Qt.SolidLine)
            painter.setPen(lasso_pen)
            painter.setBrush(QBrush(QColor(229, 169, 60, 40)))
            path = QPainterPath()
            p0 = self.image_to_widget_coords(self.polygon_points[0][0], self.polygon_points[0][1])
            path.moveTo(p0)
            for pt in self.polygon_points[1:]:
                path.lineTo(self.image_to_widget_coords(pt[0], pt[1]))
            if not self.is_drawing_lasso:
                path.closeSubpath()
            painter.drawPath(path)

            painter.setBrush(QBrush(QColor(THEME_COLORS["accent_primary"])))
            for pt in self.polygon_points:
                pw = self.image_to_widget_coords(pt[0], pt[1])
                painter.drawEllipse(pw, 4, 4)

        # 9. Render Rectangle Crop Box
        if self.crop_rect and self.crop_rect.isValid():
            painter.setRenderHint(QPainter.Antialiasing, True)
            cr_x1 = self.crop_rect.x() * self.scale + self.offset.x()
            cr_y1 = self.crop_rect.y() * self.scale + self.offset.y()
            cr_w = self.crop_rect.width() * self.scale
            cr_h = self.crop_rect.height() * self.scale

            crop_draw_rect = QRectF(cr_x1, cr_y1, cr_w, cr_h)
            crop_pen = QPen(QColor(THEME_COLORS["accent_primary"]), 2, Qt.DashLine)
            painter.setPen(crop_pen)
            painter.setBrush(QBrush(QColor(229, 169, 60, 30)))
            painter.drawRect(crop_draw_rect)

            # Dimensions badge
            badge_text = f"{self.crop_rect.width()} × {self.crop_rect.height()} px"
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            painter.setPen(QColor("#111827"))
            painter.setBrush(QBrush(QColor(THEME_COLORS["accent_primary"])))
            badge_rect = QRectF(cr_x1, cr_y1 - 22, 100, 20)
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

        # 10. Render Kinematic Pivot Point Crosshair
        if self.pivot_norm:
            painter.setRenderHint(QPainter.Antialiasing, True)
            px_img = self.pivot_norm[0] * self.image_width
            py_img = self.pivot_norm[1] * self.image_height
            p_center = self.image_to_widget_coords(px_img, py_img)

            cross_radius = 12
            painter.setPen(QPen(QColor("#EF4444"), 2))
            painter.setBrush(QBrush(QColor(239, 68, 68, 60)))
            painter.drawEllipse(p_center, cross_radius, cross_radius)

            painter.setBrush(QBrush(QColor("#EF4444")))
            painter.drawEllipse(p_center, 3, 3)

            painter.drawLine(
                QPointF(p_center.x() - cross_radius - 6, p_center.y()),
                QPointF(p_center.x() + cross_radius + 6, p_center.y())
            )
            painter.drawLine(
                QPointF(p_center.x(), p_center.y() - cross_radius - 6),
                QPointF(p_center.x(), p_center.y() + cross_radius + 6)
            )

            anchor_lbl = f"Pivot ({self.pivot_norm[0]:.2f}, {self.pivot_norm[1]:.2f})"
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.setPen(QColor("#EF4444"))
            painter.drawText(
                QRectF(p_center.x() + cross_radius + 4, p_center.y() - 8, 120, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                anchor_lbl
            )

        painter.end()
