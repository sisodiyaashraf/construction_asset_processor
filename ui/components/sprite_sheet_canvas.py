"""
Interactive Sprite Sheet Canvas Component (Stage 9)
Displays the full original sprite sheet intact beneath frame bounding box overlays.
Supports zoom, pan, fit to screen, 1:1, grid overlay toggle, frame numbering toggle,
interactive move/resize bounding boxes, manual rectangle drawing, pivot crosshairs,
undo/redo history, and coordinate readout.
Strictly non-destructive — does not alter or re-encode source image pixels.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPainterPath,
    QPen, QPixmap, QWheelEvent
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QToolTip,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS

logger = logging.getLogger("AssetProcessor.SpriteSheetCanvas")


class SpriteSheetCanvasWidget(QWidget):
    """
    Interactive image canvas drawing sprite sheet and frame boundary overlays.
    Preserves original image pixels intact without modification.
    """

    frame_selected = Signal(int)  # frame_index
    frame_deselected = Signal()
    frame_drawn = Signal(int, int, int, int)  # x, y, w, h in image pixel coordinates
    frame_modified = Signal(int, int, int, int, int)  # index, x, y, w, h in image pixel coordinates
    frame_deleted = Signal(int)  # frame_index
    pivot_selected = Signal(int, float, float)  # frame_index, pivot_x_ratio, pivot_y_ratio
    history_changed = Signal(bool, bool)  # can_undo, can_redo
    coordinates_changed = Signal(int, int, int, int, int)  # index, x, y, w, h

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._pixmap: Optional[QPixmap] = None
        self._image_path: Optional[str] = None
        self._frames: List[Dict[str, Any]] = []
        self._selected_index: Optional[int] = None
        self._hovered_index: Optional[int] = None

        # Display Toggles
        self._show_grid: bool = True
        self._show_numbers: bool = True
        self._show_pivots: bool = True

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

        # Resize / Move Handle State
        self._active_handle: Optional[str] = None  # "tl", "tr", "bl", "br", "move", "pivot"
        self._drag_start_box: Optional[Tuple[int, int, int, int]] = None
        self._drag_start_mouse_img: Optional[QPoint] = None
        self._is_modifying: bool = False

        # Undo / Redo history stacks
        self._undo_stack: List[List[Dict[str, Any]]] = []
        self._redo_stack: List[List[Dict[str, Any]]] = []

    # -------------------------------------------------------------------------
    # Public Configuration & Toggles
    # -------------------------------------------------------------------------

    def set_draw_mode(self, enabled: bool):
        """Toggle manual frame creation drawing mode."""
        self._draw_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.update()

    def is_draw_mode(self) -> bool:
        return self._draw_mode

    def toggle_grid(self, visible: bool):
        self._show_grid = visible
        self.update()

    def toggle_numbers(self, visible: bool):
        self._show_numbers = visible
        self.update()

    def toggle_pivots(self, visible: bool):
        self._show_pivots = visible
        self.update()

    def load_image(self, file_path: str, frames: Optional[List[Dict[str, Any]]] = None):
        """Load an image and its defined frames."""
        self._image_path = file_path
        self._frames = copy.deepcopy(frames or [])
        self._selected_index = 0 if self._frames else None
        self._hovered_index = None
        self._is_drawing = False
        self._is_modifying = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._emit_history_state()

        if file_path and Path(file_path).exists():
            self._pixmap = QPixmap(file_path)
            self.fit_to_screen()
        else:
            self._pixmap = None
            self.update()

    def set_image(self, file_path: str, frames: Optional[List[Dict[str, Any]]] = None):
        """Alias for load_image."""
        self.load_image(file_path, frames)

    def set_frames(self, frames: List[Dict[str, Any]], record_history: bool = True):
        """Update active frame definitions."""
        if record_history and self._frames != frames:
            self._push_undo()
        self._frames = copy.deepcopy(frames or [])
        if self._selected_index is not None and self._selected_index >= len(self._frames):
            self._selected_index = max(0, len(self._frames) - 1) if self._frames else None
        self.update()

    def get_frames(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._frames)

    def select_frame(self, frame_index: Optional[int]):
        """Highlight a specific frame by index."""
        self._selected_index = frame_index
        sel_obj = self._get_frame_by_index(frame_index)
        if sel_obj:
            self.coordinates_changed.emit(
                sel_obj.get("frame_index", 0),
                sel_obj.get("x", 0),
                sel_obj.get("y", 0),
                sel_obj.get("width", 0),
                sel_obj.get("height", 0)
            )
        self.update()

    def delete_selected_frame(self):
        """Delete currently selected frame definition without modifying source image."""
        if self._selected_index is None:
            return
        target_idx = self._selected_index
        self._push_undo()
        self._frames = [f for f in self._frames if f.get("frame_index") != target_idx]
        # Re-number remaining
        for i, f in enumerate(self._frames):
            f["frame_index"] = i

        self._selected_index = min(target_idx, len(self._frames) - 1) if self._frames else None
        self.frame_deleted.emit(target_idx)
        if self._selected_index is not None:
            self.frame_selected.emit(self._selected_index)
        else:
            self.frame_deselected.emit()
        self.update()

    # -------------------------------------------------------------------------
    # Undo / Redo
    # -------------------------------------------------------------------------

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.deepcopy(self._frames))
        self._frames = self._undo_stack.pop()
        self._emit_history_state()
        self.update()

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.deepcopy(self._frames))
        self._frames = self._redo_stack.pop()
        self._emit_history_state()
        self.update()

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self._frames))
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._emit_history_state()

    def push_undo_snapshot(self):
        """Public alias for recording undo history snapshot."""
        self._push_undo()

    def _emit_history_state(self):
        self.history_changed.emit(len(self._undo_stack) > 0, len(self._redo_stack) > 0)

    # -------------------------------------------------------------------------
    # Zoom & Pan Navigation
    # -------------------------------------------------------------------------

    def fit_to_screen(self):
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
        self._scale = max(0.05, min(scale_x, scale_y, 2.5))

        scaled_w = pw * self._scale
        scaled_h = ph * self._scale
        self._offset = QPointF((vw - scaled_w) / 2.0, (vh - scaled_h) / 2.0)
        self.update()

    def reset_100(self):
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
        self._scale = max(0.05, min(factor, 12.0))
        self.update()

    def get_zoom(self) -> float:
        return self._scale

    def zoom_in(self):
        """Zoom in by 25%."""
        self.set_zoom(self._scale * 1.25)

    def zoom_out(self):
        """Zoom out by 25%."""
        self.set_zoom(self._scale / 1.25)

    def zoom_100(self):
        """Reset zoom to 100%."""
        self.reset_100()

    # -------------------------------------------------------------------------
    # Coordinate Mapping
    # -------------------------------------------------------------------------

    def img_to_canvas(self, ix: float, iy: float) -> QPointF:
        return QPointF(self._offset.x() + ix * self._scale, self._offset.y() + iy * self._scale)

    def canvas_to_img(self, cx: float, cy: float) -> QPoint:
        if self._scale <= 0:
            return QPoint(0, 0)
        ix = (cx - self._offset.x()) / self._scale
        iy = (cy - self._offset.y()) / self._scale
        return QPoint(int(round(ix)), int(round(iy)))

    # -------------------------------------------------------------------------
    # Paint Event
    # -------------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Dark industrial background
        painter.fillRect(self.rect(), QColor(THEME_COLORS["bg_main"]))

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(THEME_COLORS["text_muted"]))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "No sprite sheet loaded\nOpen an image or select from asset catalog")
            return

        pw = self._pixmap.width()
        ph = self._pixmap.height()
        dest_rect = QRectF(self._offset.x(), self._offset.y(), pw * self._scale, ph * self._scale)

        # Checkerboard transparency backing
        self._draw_transparency_checkerboard(painter, dest_rect)

        # Image border
        painter.setPen(QPen(QColor(THEME_COLORS["border_medium"]), 1))
        painter.drawRect(dest_rect)

        # Draw original sprite sheet completely unmodified
        painter.drawPixmap(dest_rect.toRect(), self._pixmap)

        # Draw frame boundaries
        if self._show_grid:
            for frame in self._frames:
                self._draw_frame_box(painter, frame)

        # Draw in-progress manual frame creation
        if self._is_drawing and self._draw_start_img and self._draw_current_img:
            self._draw_draft_box(painter)

    def _draw_transparency_checkerboard(self, painter: QPainter, rect: QRectF):
        tile_size = 12
        c1 = QColor(36, 42, 50)
        c2 = QColor(26, 30, 36)
        painter.save()
        painter.setClipRect(rect)
        x_start = int(rect.x())
        y_start = int(rect.y())
        x_end = int(rect.right())
        y_end = int(rect.bottom())

        for y in range(y_start, y_end, tile_size):
            for x in range(x_start, x_end, tile_size):
                is_even = ((x // tile_size) + (y // tile_size)) % 2 == 0
                painter.fillRect(QRect(x, y, tile_size, tile_size), c1 if is_even else c2)
        painter.restore()

    def _draw_frame_box(self, painter: QPainter, frame: Dict[str, Any]):
        f_idx = frame.get("frame_index", 0)
        bx = frame.get("x", 0)
        by = frame.get("y", 0)
        bw = frame.get("width", 0)
        bh = frame.get("height", 0)
        pivot_x = float(frame.get("pivot_x", 0.5))
        pivot_y = float(frame.get("pivot_y", 0.5))

        is_selected = (f_idx == self._selected_index)
        is_hovered = (f_idx == self._hovered_index)

        tl = self.img_to_canvas(bx, by)
        c_w = bw * self._scale
        c_h = bh * self._scale
        rect = QRectF(tl.x(), tl.y(), c_w, c_h)

        if is_selected:
            border_color = QColor(THEME_COLORS["accent_primary"])  # Construction Amber
            fill_color = QColor(border_color.red(), border_color.green(), border_color.blue(), 50)
            pen_width = max(2.5, 3.0 / max(0.1, self._scale))
        elif is_hovered:
            border_color = QColor("#3B82F6")  # Blue hover
            fill_color = QColor(59, 130, 246, 35)
            pen_width = max(1.8, 2.2 / max(0.1, self._scale))
        else:
            border_color = QColor(139, 92, 246, 200)  # Violet
            fill_color = QColor(139, 92, 246, 20)
            pen_width = max(1.2, 1.5 / max(0.1, self._scale))

        # Fill & Border
        painter.fillRect(rect, fill_color)
        pen = QPen(border_color, min(4.0, pen_width))
        painter.setPen(pen)
        painter.drawRect(rect)

        # Frame Numbering Badge
        if self._show_numbers:
            f_name = frame.get("frame_name", "")
            badge_text = f"#{f_idx}" if not f_name else f"#{f_idx} {f_name}"
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold if is_selected else QFont.Normal))

            badge_h = 16
            badge_w = max(30, len(badge_text) * 7 + 8)
            badge_rect = QRectF(rect.x(), max(0, rect.y() - badge_h), badge_w, badge_h)

            painter.fillRect(badge_rect, border_color)
            painter.setPen(QColor("#111827"))
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

        # Draw Pivot Point Crosshair
        if self._show_pivots:
            p_img_x = bx + pivot_x * bw
            p_img_y = by + pivot_y * bh
            p_c = self.img_to_canvas(p_img_x, p_img_y)

            cross_size = 6
            p_pen = QPen(QColor("#EF4444") if is_selected else QColor("#F59E0B"), 2)
            painter.setPen(p_pen)
            painter.drawLine(int(p_c.x() - cross_size), int(p_c.y()), int(p_c.x() + cross_size), int(p_c.y()))
            painter.drawLine(int(p_c.x()), int(p_c.y() - cross_size), int(p_c.x()), int(p_c.y() + cross_size))

        # Corner handles when selected
        if is_selected:
            h_size = 7
            painter.setBrush(QBrush(QColor(THEME_COLORS["accent_primary"])))
            painter.setPen(QPen(QColor("#000000"), 1))
            painter.drawRect(QRectF(rect.x() - h_size / 2, rect.y() - h_size / 2, h_size, h_size))
            painter.drawRect(QRectF(rect.right() - h_size / 2, rect.y() - h_size / 2, h_size, h_size))
            painter.drawRect(QRectF(rect.x() - h_size / 2, rect.bottom() - h_size / 2, h_size, h_size))
            painter.drawRect(QRectF(rect.right() - h_size / 2, rect.bottom() - h_size / 2, h_size, h_size))

    def _draw_draft_box(self, painter: QPainter):
        p1 = self.img_to_canvas(self._draw_start_img.x(), self._draw_start_img.y())
        p2 = self.img_to_canvas(self._draw_current_img.x(), self._draw_current_img.y())

        rx = min(p1.x(), p2.x())
        ry = min(p1.y(), p2.y())
        rw = abs(p2.x() - p1.x())
        rh = abs(p2.y() - p1.y())
        rect = QRectF(rx, ry, rw, rh)

        painter.fillRect(rect, QColor(59, 130, 246, 40))
        pen = QPen(QColor(THEME_COLORS["accent_primary"]), 2, Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

        img_w = abs(self._draw_current_img.x() - self._draw_start_img.x())
        img_h = abs(self._draw_current_img.y() - self._draw_start_img.y())
        dim_str = f"{img_w} × {img_h} px"
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.fillRect(QRectF(rx, max(0, ry - 18), 90, 18), QColor(THEME_COLORS["accent_primary"]))
        painter.setPen(QColor("#111827"))
        painter.drawText(QRectF(rx, max(0, ry - 18), 90, 18), Qt.AlignCenter, dim_str)

    # -------------------------------------------------------------------------
    # Mouse & Keyboard Events
    # -------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):
        if not self._pixmap:
            return

        if self._draw_mode and event.button() == Qt.LeftButton:
            img_pt = self.canvas_to_img(event.position().x(), event.position().y())
            ix = max(0, min(img_pt.x(), self._pixmap.width()))
            iy = max(0, min(img_pt.y(), self._pixmap.height()))
            self._is_drawing = True
            self._draw_start_img = QPoint(ix, iy)
            self._draw_current_img = QPoint(ix, iy)
            self.update()
            return

        if event.button() == Qt.LeftButton:
            c_pos = event.position()
            # Check handles on selected frame
            if self._selected_index is not None:
                handle = self._hit_test_handle(c_pos)
                if handle:
                    self._active_handle = handle
                    self._is_modifying = True
                    sel_f = self._get_frame_by_index(self._selected_index)
                    if sel_f:
                        self._drag_start_box = (sel_f["x"], sel_f["y"], sel_f["width"], sel_f["height"])
                        self._drag_start_mouse_img = self.canvas_to_img(c_pos.x(), c_pos.y())
                        self._push_undo()
                    return

            # Check if clicked on any frame box
            hit_frame = self._hit_test_frame(c_pos)
            if hit_frame:
                idx = hit_frame.get("frame_index", 0)
                self.select_frame(idx)
                self.frame_selected.emit(idx)
                return
            else:
                if self._selected_index is not None:
                    self._selected_index = None
                    self.frame_deselected.emit()
                    self.update()

        # Pan on middle or left-click background
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._pixmap:
            return

        c_pos = event.position()

        # In-progress drawing
        if self._is_drawing and self._draw_start_img:
            img_pt = self.canvas_to_img(c_pos.x(), c_pos.y())
            ix = max(0, min(img_pt.x(), self._pixmap.width()))
            iy = max(0, min(img_pt.y(), self._pixmap.height()))
            self._draw_current_img = QPoint(ix, iy)
            self.update()
            return

        # In-progress moving / resizing
        if self._is_modifying and self._selected_index is not None and self._drag_start_box and self._drag_start_mouse_img:
            cur_mouse = self.canvas_to_img(c_pos.x(), c_pos.y())
            dx = cur_mouse.x() - self._drag_start_mouse_img.x()
            dy = cur_mouse.y() - self._drag_start_mouse_img.y()

            orig_x, orig_y, orig_w, orig_h = self._drag_start_box
            pw = self._pixmap.width()
            ph = self._pixmap.height()

            sel_f = self._get_frame_by_index(self._selected_index)
            if sel_f:
                if self._active_handle == "move":
                    sel_f["x"] = max(0, min(pw - orig_w, orig_x + dx))
                    sel_f["y"] = max(0, min(ph - orig_h, orig_y + dy))
                elif self._active_handle == "br":
                    sel_f["width"] = max(4, min(pw - orig_x, orig_w + dx))
                    sel_f["height"] = max(4, min(ph - orig_y, orig_h + dy))
                elif self._active_handle == "tl":
                    nx = max(0, min(orig_x + orig_w - 4, orig_x + dx))
                    ny = max(0, min(orig_y + orig_h - 4, orig_y + dy))
                    sel_f["width"] = orig_w - (nx - orig_x)
                    sel_f["height"] = orig_h - (ny - orig_y)
                    sel_f["x"] = nx
                    sel_f["y"] = ny
                elif self._active_handle == "tr":
                    ny = max(0, min(orig_y + orig_h - 4, orig_y + dy))
                    sel_f["width"] = max(4, min(pw - orig_x, orig_w + dx))
                    sel_f["height"] = orig_h - (ny - orig_y)
                    sel_f["y"] = ny
                elif self._active_handle == "bl":
                    nx = max(0, min(orig_x + orig_w - 4, orig_x + dx))
                    sel_f["width"] = orig_w - (nx - orig_x)
                    sel_f["height"] = max(4, min(ph - orig_y, orig_h + dy))
                    sel_f["x"] = nx

                self.coordinates_changed.emit(
                    sel_f["frame_index"], sel_f["x"], sel_f["y"], sel_f["width"], sel_f["height"]
                )
                self.update()
            return

        # Panning
        if self._is_panning:
            delta = event.pos() - self._last_mouse_pos
            self._last_mouse_pos = event.pos()
            self._offset += QPointF(delta.x(), delta.y())
            self.update()
            return

        # Hover test
        old_hover = self._hovered_index
        hit_f = self._hit_test_frame(c_pos)
        self._hovered_index = hit_f.get("frame_index") if hit_f else None
        if old_hover != self._hovered_index:
            self.update()

        # Update cursor based on hover handle
        if not self._draw_mode:
            handle = self._hit_test_handle(c_pos)
            if handle in ("tl", "br"):
                self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ("tr", "bl"):
                self.setCursor(Qt.SizeBDiagCursor)
            elif handle == "move":
                self.setCursor(Qt.SizeAllCursor)
            elif hit_f:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._is_drawing:
            self._is_drawing = False
            if self._draw_start_img and self._draw_current_img:
                x1 = self._draw_start_img.x()
                y1 = self._draw_start_img.y()
                x2 = self._draw_current_img.x()
                y2 = self._draw_current_img.y()
                rx = min(x1, x2)
                ry = min(y1, y2)
                rw = abs(x2 - x1)
                rh = abs(y2 - y1)

                if rw >= 4 and rh >= 4:
                    self._push_undo()
                    self.frame_drawn.emit(rx, ry, rw, rh)
            self._draw_start_img = None
            self._draw_current_img = None
            self.update()
            return

        if self._is_modifying:
            self._is_modifying = False
            self._active_handle = None
            if self._selected_index is not None:
                sel_f = self._get_frame_by_index(self._selected_index)
                if sel_f:
                    self.frame_modified.emit(
                        sel_f["frame_index"], sel_f["x"], sel_f["y"], sel_f["width"], sel_f["height"]
                    )
            self._drag_start_box = None
            self._drag_start_mouse_img = None
            self.update()
            return

        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CrossCursor if self._draw_mode else Qt.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent):
        if not self._pixmap:
            return

        zoom_in = event.angleDelta().y() > 0
        zoom_factor = 1.15 if zoom_in else 0.85

        c_pos = event.position()
        old_scale = self._scale
        new_scale = max(0.05, min(old_scale * zoom_factor, 12.0))

        self._offset = c_pos - (c_pos - self._offset) * (new_scale / old_scale)
        self._scale = new_scale
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_frame()
        elif event.key() == Qt.Key_Z and (event.modifiers() & Qt.ControlModifier):
            if event.modifiers() & Qt.ShiftModifier:
                self.redo()
            else:
                self.undo()
        elif event.key() == Qt.Key_Y and (event.modifiers() & Qt.ControlModifier):
            self.redo()
        super().keyPressEvent(event)

    # -------------------------------------------------------------------------
    # Hit Testing Helpers
    # -------------------------------------------------------------------------

    def _get_frame_by_index(self, index: Optional[int]) -> Optional[Dict[str, Any]]:
        if index is None:
            return None
        return next((f for f in self._frames if f.get("frame_index") == index), None)

    def _hit_test_frame(self, canvas_pt: QPointF) -> Optional[Dict[str, Any]]:
        for frame in reversed(self._frames):
            tl = self.img_to_canvas(frame.get("x", 0), frame.get("y", 0))
            rect = QRectF(tl.x(), tl.y(), frame.get("width", 0) * self._scale, frame.get("height", 0) * self._scale)
            if rect.contains(canvas_pt):
                return frame
        return None

    def _hit_test_handle(self, canvas_pt: QPointF) -> Optional[str]:
        if self._selected_index is None:
            return None

        sel_f = self._get_frame_by_index(self._selected_index)
        if not sel_f:
            return None

        tl = self.img_to_canvas(sel_f.get("x", 0), sel_f.get("y", 0))
        r = QRectF(tl.x(), tl.y(), sel_f.get("width", 0) * self._scale, sel_f.get("height", 0) * self._scale)
        h_size = 9.0

        if QRectF(r.x() - h_size / 2, r.y() - h_size / 2, h_size, h_size).contains(canvas_pt):
            return "tl"
        if QRectF(r.right() - h_size / 2, r.y() - h_size / 2, h_size, h_size).contains(canvas_pt):
            return "tr"
        if QRectF(r.x() - h_size / 2, r.bottom() - h_size / 2, h_size, h_size).contains(canvas_pt):
            return "bl"
        if QRectF(r.right() - h_size / 2, r.bottom() - h_size / 2, h_size, h_size).contains(canvas_pt):
            return "br"

        if r.contains(canvas_pt):
            return "move"

        return None


class SpriteSheetCanvasContainer(QFrame):
    """
    Container frame embedding SpriteSheetCanvasWidget with dedicated top controls toolbar:
    Fit, 100%, Zoom, Draw Frame, Delete Frame, Undo, Redo, Grid Toggle, Numbering Toggle,
    Pivot Toggle, and live coordinate telemetry.
    """

    frame_selected = Signal(int)
    frame_deselected = Signal()
    frame_drawn = Signal(int, int, int, int)
    frame_modified = Signal(int, int, int, int, int)
    frame_deleted = Signal(int)
    pivot_selected = Signal(int, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_main']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.btn_fit = QPushButton("Fit")
        self.btn_fit.setToolTip("Fit sprite sheet to screen")
        self.btn_fit.setStyleSheet(self._btn_style())
        self.btn_fit.clicked.connect(self._on_fit_clicked)
        toolbar.addWidget(self.btn_fit)

        self.btn_100 = QPushButton("1:1")
        self.btn_100.setToolTip("View at 100% actual pixel resolution")
        self.btn_100.setStyleSheet(self._btn_style())
        self.btn_100.clicked.connect(self._on_100_clicked)
        toolbar.addWidget(self.btn_100)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setToolTip("Zoom in")
        self.btn_zoom_in.setFixedWidth(28)
        self.btn_zoom_in.setStyleSheet(self._btn_style())
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        toolbar.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setToolTip("Zoom out")
        self.btn_zoom_out.setFixedWidth(28)
        self.btn_zoom_out.setStyleSheet(self._btn_style())
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        toolbar.addWidget(self.btn_zoom_out)

        toolbar.addSpacing(6)

        self.btn_draw = QPushButton("Draw Frame")
        self.btn_draw.setCheckable(True)
        self.btn_draw.setToolTip("Click and drag to manually outline a new animation frame")
        self.btn_draw.setStyleSheet(self._toggle_btn_style())
        self.btn_draw.toggled.connect(self._toggle_draw_mode)
        toolbar.addWidget(self.btn_draw)

        self.btn_delete = QPushButton("Delete Frame")
        self.btn_delete.setToolTip("Delete selected frame definition (Del)")
        self.btn_delete.setStyleSheet(self._btn_style())
        self.btn_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(self.btn_delete)

        toolbar.addSpacing(6)

        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setEnabled(False)
        self.btn_undo.setStyleSheet(self._btn_style())
        self.btn_undo.clicked.connect(self._undo)
        toolbar.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("Redo")
        self.btn_redo.setEnabled(False)
        self.btn_redo.setStyleSheet(self._btn_style())
        self.btn_redo.clicked.connect(self._redo)
        toolbar.addWidget(self.btn_redo)

        toolbar.addSpacing(6)

        self.btn_grid_toggle = QPushButton("Grid")
        self.btn_grid_toggle.setCheckable(True)
        self.btn_grid_toggle.setChecked(True)
        self.btn_grid_toggle.setToolTip("Toggle frame boundary grid overlay")
        self.btn_grid_toggle.setStyleSheet(self._toggle_btn_style())
        self.btn_grid_toggle.toggled.connect(self._toggle_grid)
        toolbar.addWidget(self.btn_grid_toggle)

        self.btn_num_toggle = QPushButton("# Num")
        self.btn_num_toggle.setCheckable(True)
        self.btn_num_toggle.setChecked(True)
        self.btn_num_toggle.setToolTip("Toggle frame index numbering badges")
        self.btn_num_toggle.setStyleSheet(self._toggle_btn_style())
        self.btn_num_toggle.toggled.connect(self._toggle_numbers)
        toolbar.addWidget(self.btn_num_toggle)

        self.btn_pivot_toggle = QPushButton("Pivots")
        self.btn_pivot_toggle.setCheckable(True)
        self.btn_pivot_toggle.setChecked(True)
        self.btn_pivot_toggle.setToolTip("Toggle pivot crosshair markers")
        self.btn_pivot_toggle.setStyleSheet(self._toggle_btn_style())
        self.btn_pivot_toggle.toggled.connect(self._toggle_pivots)
        toolbar.addWidget(self.btn_pivot_toggle)

        toolbar.addStretch()

        self.lbl_coords = QLabel("Frame: - | X: - | Y: - | W: - | H: -")
        self.lbl_coords.setStyleSheet(f"color: {THEME_COLORS['accent_primary']}; font-size: 11px; font-weight: 600;")
        toolbar.addWidget(self.lbl_coords)

        layout.addLayout(toolbar)

        # Main Canvas
        self.canvas = SpriteSheetCanvasWidget(self)
        self.canvas.frame_selected.connect(self.frame_selected.emit)
        self.canvas.frame_deselected.connect(self.frame_deselected.emit)
        self.canvas.frame_drawn.connect(self.frame_drawn.emit)
        self.canvas.frame_modified.connect(self.frame_modified.emit)
        self.canvas.frame_deleted.connect(self.frame_deleted.emit)
        self.canvas.pivot_selected.connect(self.pivot_selected.emit)
        self.canvas.history_changed.connect(self._on_history_changed)
        self.canvas.coordinates_changed.connect(self._on_coordinates_changed)
        layout.addWidget(self.canvas, stretch=1)

    def load_image(self, file_path: str, frames: Optional[List[Dict[str, Any]]] = None):
        self.canvas.load_image(file_path, frames)
        self.lbl_coords.setText("Frame: - | X: - | Y: - | W: - | H: -")

    def set_frames(self, frames: List[Dict[str, Any]]):
        self.canvas.set_frames(frames)

    def select_frame(self, frame_index: Optional[int]):
        self.canvas.select_frame(frame_index)

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

    def _toggle_grid(self, checked: bool):
        self.canvas.toggle_grid(checked)

    def _toggle_numbers(self, checked: bool):
        self.canvas.toggle_numbers(checked)

    def _toggle_pivots(self, checked: bool):
        self.canvas.toggle_pivots(checked)

    def _delete_selected(self):
        self.canvas.delete_selected_frame()

    def _undo(self):
        self.canvas.undo()

    def _redo(self):
        self.canvas.redo()

    def _on_history_changed(self, can_undo: bool, can_redo: bool):
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)

    def _on_coordinates_changed(self, idx: int, x: int, y: int, w: int, h: int):
        self.lbl_coords.setText(f"Frame #{idx} | X: {x} | Y: {y} | W: {w}px | H: {h}px")

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
            QPushButton:disabled {{
                color: {THEME_COLORS['text_muted']};
                border-color: {THEME_COLORS['border_subtle']};
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
