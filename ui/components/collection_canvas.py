"""
Interactive Collection Canvas Component (Stage 8)
Displays the full original source image intact beneath candidate bounding box overlays.
Supports zoom, pan, fit to screen, 1:1, hover tooltips, manual region drawing,
interactive move/resize bounding boxes, undo/redo history, and coordinate readout.
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
from core.collection_splitter_engine import COMPOSITION_COLORS, COMPOSITION_TYPES

logger = logging.getLogger("AssetProcessor.CollectionCanvas")

REGION_TYPE_COLORS = {
    "isolated_asset": "#10B981",    # Emerald green
    "sprite_frame": "#8B5CF6",      # Purple
    "candidate_region": "#F59E0B",  # Amber
    "overlapping_part": "#EC4899",  # Pink
    "background_scene": "#64748B",  # Slate
    "manual_box": "#3B82F6",        # Blue
}


class CollectionCanvasWidget(QWidget):
    """
    Interactive image canvas drawing image and collection region bounding box overlays.
    Preserves original image pixels intact without any modification.
    """

    region_selected = Signal(dict)
    region_deselected = Signal()
    new_region_drawn = Signal(int, int, int, int)  # x, y, w, h in image pixel coordinates
    region_modified = Signal(int, int, int, int, int)  # id, x, y, w, h in image pixel coordinates
    region_deleted = Signal(int)  # region_id
    history_changed = Signal(bool, bool)  # can_undo, can_redo
    coordinates_changed = Signal(int, int, int, int)  # x, y, w, h of hovered or selected

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._pixmap: Optional[QPixmap] = None
        self._image_path: Optional[str] = None
        self._regions: List[Dict[str, Any]] = []
        self._selected_id: Optional[int] = None
        self._hovered_id: Optional[int] = None

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
        self._active_handle: Optional[str] = None  # "tl", "tr", "bl", "br", "move"
        self._drag_start_box: Optional[Tuple[int, int, int, int]] = None
        self._drag_start_mouse_img: Optional[QPoint] = None
        self._is_modifying: bool = False

        # Undo / Redo history stacks (stores deep copies of self._regions)
        self._undo_stack: List[List[Dict[str, Any]]] = []
        self._redo_stack: List[List[Dict[str, Any]]] = []

    def set_draw_mode(self, enabled: bool):
        """Toggle manual candidate region drawing mode."""
        self._draw_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.update()

    def is_draw_mode(self) -> bool:
        return self._draw_mode

    def load_image(self, file_path: str, regions: Optional[List[Dict[str, Any]]] = None):
        """Load an image and its detected collection regions."""
        self._image_path = file_path
        self._regions = copy.deepcopy(regions or [])
        self._selected_id = None
        self._hovered_id = None
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

    def set_regions(self, regions: List[Dict[str, Any]], record_history: bool = True):
        """Update active candidate region overlays."""
        if record_history and self._regions != regions:
            self._push_undo()
        self._regions = copy.deepcopy(regions or [])
        self.update()

    def get_regions(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._regions)

    def select_region(self, region_id: Optional[int]):
        """Highlight a specific region by ID."""
        self._selected_id = region_id
        selected_obj = next((r for r in self._regions if r.get("id") == region_id), None)
        if selected_obj:
            bx = selected_obj.get("x", 0)
            by = selected_obj.get("y", 0)
            bw = selected_obj.get("width", 0)
            bh = selected_obj.get("height", 0)
            self.coordinates_changed.emit(bx, by, bw, bh)
        self.update()

    def delete_selected_region(self):
        """Delete currently selected region."""
        if self._selected_id is None:
            return
        target_id = self._selected_id
        self._push_undo()
        self._regions = [r for r in self._regions if r.get("id") != target_id]
        self._selected_id = None
        self.region_deleted.emit(target_id)
        self.region_deselected.emit()
        self.update()

    def undo(self):
        """Undo last region modification or addition."""
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.deepcopy(self._regions))
        self._regions = self._undo_stack.pop()
        self._selected_id = None
        self._emit_history_state()
        self.update()

    def redo(self):
        """Redo last undone operation."""
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.deepcopy(self._regions))
        self._regions = self._redo_stack.pop()
        self._selected_id = None
        self._emit_history_state()
        self.update()

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self._regions))
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._emit_history_state()

    def _emit_history_state(self):
        self.history_changed.emit(len(self._undo_stack) > 0, len(self._redo_stack) > 0)

    def fit_to_screen(self):
        """Scale and center image within canvas boundaries."""
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

        scaled_w = pw * self._scale
        scaled_h = ph * self._scale
        self._offset = QPointF((vw - scaled_w) / 2.0, (vh - scaled_h) / 2.0)
        self.update()

    def reset_100(self):
        """Reset zoom to 100% (1:1 pixel scale)."""
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
        self._scale = max(0.05, min(factor, 10.0))
        self.update()

    def get_zoom(self) -> float:
        return self._scale

    # Coordinate mapping utilities
    def img_to_canvas(self, ix: float, iy: float) -> QPointF:
        """Map image pixel coordinates to canvas widget coordinates."""
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

        # Dark industrial canvas background
        painter.fillRect(self.rect(), QColor(THEME_COLORS["bg_main"]))

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(THEME_COLORS["text_muted"]))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "No collection image loaded or file not found")
            return

        pw = self._pixmap.width()
        ph = self._pixmap.height()
        dest_rect = QRectF(self._offset.x(), self._offset.y(), pw * self._scale, ph * self._scale)

        # Draw subtle checkerboard behind image for alpha transparency visualization
        self._draw_transparency_checkerboard(painter, dest_rect)

        # Image border
        painter.setPen(QPen(QColor(THEME_COLORS["border_medium"]), 1))
        painter.drawRect(dest_rect)

        # Draw original image completely unmodified
        painter.drawPixmap(dest_rect.toRect(), self._pixmap)

        # Draw candidate bounding box overlays
        for idx, reg in enumerate(self._regions, start=1):
            self._draw_region(painter, reg, idx)

        # Draw in-progress manual box creation
        if self._is_drawing and self._draw_start_img and self._draw_current_img:
            self._draw_draft_box(painter)

    def _draw_transparency_checkerboard(self, painter: QPainter, rect: QRectF):
        """Render a subtle checkerboard pattern to visualize PNG transparency."""
        tile_size = 12
        light_color = QColor(36, 42, 50)
        dark_color = QColor(26, 30, 36)

        painter.save()
        painter.setClipRect(rect)
        x_start = int(rect.x())
        y_start = int(rect.y())
        x_end = int(rect.right())
        y_end = int(rect.bottom())

        for y in range(y_start, y_end, tile_size):
            for x in range(x_start, x_end, tile_size):
                is_even = ((x // tile_size) + (y // tile_size)) % 2 == 0
                painter.fillRect(
                    QRect(x, y, tile_size, tile_size),
                    light_color if is_even else dark_color
                )
        painter.restore()

    def _draw_region(self, painter: QPainter, reg: Dict[str, Any], index: int):
        """Render a single collection region bounding box with color and label."""
        bx = reg.get("x", 0)
        by = reg.get("y", 0)
        bw = reg.get("width", 0)
        bh = reg.get("height", 0)
        reg_id = reg.get("id")
        reg_type = reg.get("region_type", "isolated_asset")
        conf_score = float(reg.get("confidence_score", 0.85))
        review_status = reg.get("review_status", "pending")

        is_selected = (reg_id == self._selected_id)
        is_hovered = (reg_id == self._hovered_id)

        top_left = self.img_to_canvas(bx, by)
        c_w = bw * self._scale
        c_h = bh * self._scale
        rect = QRectF(top_left.x(), top_left.y(), c_w, c_h)

        # Base category color
        cat_hex = REGION_TYPE_COLORS.get(reg_type, "#10B981")
        base_color = QColor(cat_hex)

        if is_selected:
            border_color = QColor(THEME_COLORS["accent_primary"])  # Vibrant yellow-gold
            fill_color = QColor(border_color.red(), border_color.green(), border_color.blue(), 50)
            pen_width = max(2.5, 3.0 / max(0.1, self._scale))
        elif is_hovered:
            border_color = base_color.lighter(130)
            fill_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 40)
            pen_width = max(2.0, 2.5 / max(0.1, self._scale))
        else:
            border_color = base_color
            fill_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 25)
            pen_width = max(1.5, 2.0 / max(0.1, self._scale))

        # Fill semi-transparent interior
        painter.fillRect(rect, fill_color)

        # Draw border
        pen = QPen(border_color, min(4.0, pen_width))
        if reg_type == "overlapping_part":
            pen.setStyle(Qt.DashLine)
        else:
            pen.setStyle(Qt.SolidLine)
        painter.setPen(pen)
        painter.drawRect(rect)

        # Draw label pill
        label_text = f"#{index} {reg_type.replace('_', ' ').title()} ({bw}×{bh})"
        font = QFont("Segoe UI", 9, QFont.Bold if is_selected else QFont.Normal)
        painter.setFont(font)

        pill_h = 18
        pill_w = max(80, len(label_text) * 7 + 14)
        pill_rect = QRectF(rect.x(), max(0, rect.y() - pill_h), pill_w, pill_h)

        painter.fillRect(pill_rect, border_color)
        painter.setPen(QColor("#111827"))  # Dark contrasting text
        painter.drawText(pill_rect, Qt.AlignCenter, label_text)

        # Draw corner grab handles if selected
        if is_selected:
            handle_size = 7
            painter.setBrush(QBrush(QColor(THEME_COLORS["accent_primary"])))
            painter.setPen(QPen(QColor("#000000"), 1))
            # 4 Corners
            painter.drawRect(QRectF(rect.x() - handle_size / 2, rect.y() - handle_size / 2, handle_size, handle_size))
            painter.drawRect(QRectF(rect.right() - handle_size / 2, rect.y() - handle_size / 2, handle_size, handle_size))
            painter.drawRect(QRectF(rect.x() - handle_size / 2, rect.bottom() - handle_size / 2, handle_size, handle_size))
            painter.drawRect(QRectF(rect.right() - handle_size / 2, rect.bottom() - handle_size / 2, handle_size, handle_size))

    def _draw_draft_box(self, painter: QPainter):
        """Draw manual region box currently being dragged by user."""
        p1 = self.img_to_canvas(self._draw_start_img.x(), self._draw_start_img.y())
        p2 = self.img_to_canvas(self._draw_current_img.x(), self._draw_current_img.y())

        rx = min(p1.x(), p2.x())
        ry = min(p1.y(), p2.y())
        rw = abs(p2.x() - p1.x())
        rh = abs(p2.y() - p1.y())
        rect = QRectF(rx, ry, rw, rh)

        painter.fillRect(rect, QColor(59, 130, 246, 45))
        pen = QPen(QColor(THEME_COLORS["accent_primary"]), 2, Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

        # Draw dimensions tag
        img_w = abs(self._draw_current_img.x() - self._draw_start_img.x())
        img_h = abs(self._draw_current_img.y() - self._draw_start_img.y())
        dim_str = f"{img_w} × {img_h} px"
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.fillRect(QRectF(rx, max(0, ry - 18), 90, 18), QColor(THEME_COLORS["accent_primary"]))
        painter.setPen(QColor("#111827"))
        painter.drawText(QRectF(rx, max(0, ry - 18), 90, 18), Qt.AlignCenter, dim_str)

    # Mouse & Keyboard Events
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
            # Check if clicked on a handle of the selected box
            if self._selected_id is not None:
                handle = self._hit_test_handle(c_pos)
                if handle:
                    self._active_handle = handle
                    self._is_modifying = True
                    sel_reg = next((r for r in self._regions if r.get("id") == self._selected_id), None)
                    if sel_reg:
                        self._drag_start_box = (sel_reg["x"], sel_reg["y"], sel_reg["width"], sel_reg["height"])
                        self._drag_start_mouse_img = self.canvas_to_img(c_pos.x(), c_pos.y())
                        self._push_undo()
                    return

            # Check if clicked on any region
            hit_reg = self._hit_test_region(c_pos)
            if hit_reg:
                self._selected_id = hit_reg.get("id")
                bx = hit_reg.get("x", 0)
                by = hit_reg.get("y", 0)
                bw = hit_reg.get("width", 0)
                bh = hit_reg.get("height", 0)
                self.coordinates_changed.emit(bx, by, bw, bh)
                self.region_selected.emit(hit_reg)
                self.update()
                return
            else:
                if self._selected_id is not None:
                    self._selected_id = None
                    self.region_deselected.emit()
                    self.update()

        # Middle click or Left click on background -> Pan
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
            dx = abs(ix - self._draw_start_img.x())
            dy = abs(iy - self._draw_start_img.y())
            self.coordinates_changed.emit(min(ix, self._draw_start_img.x()), min(iy, self._draw_start_img.y()), dx, dy)
            self.update()
            return

        # In-progress moving / resizing
        if self._is_modifying and self._selected_id and self._drag_start_box and self._drag_start_mouse_img:
            current_mouse_img = self.canvas_to_img(c_pos.x(), c_pos.y())
            dx = current_mouse_img.x() - self._drag_start_mouse_img.x()
            dy = current_mouse_img.y() - self._drag_start_mouse_img.y()

            orig_x, orig_y, orig_w, orig_h = self._drag_start_box
            pw = self._pixmap.width()
            ph = self._pixmap.height()

            sel_reg = next((r for r in self._regions if r.get("id") == self._selected_id), None)
            if sel_reg:
                if self._active_handle == "move":
                    nx = max(0, min(pw - orig_w, orig_x + dx))
                    ny = max(0, min(ph - orig_h, orig_y + dy))
                    sel_reg["x"] = nx
                    sel_reg["y"] = ny
                elif self._active_handle == "br":
                    sel_reg["width"] = max(10, min(pw - orig_x, orig_w + dx))
                    sel_reg["height"] = max(10, min(ph - orig_y, orig_h + dy))
                elif self._active_handle == "tl":
                    nx = max(0, min(orig_x + orig_w - 10, orig_x + dx))
                    ny = max(0, min(orig_y + orig_h - 10, orig_y + dy))
                    sel_reg["width"] = orig_w - (nx - orig_x)
                    sel_reg["height"] = orig_h - (ny - orig_y)
                    sel_reg["x"] = nx
                    sel_reg["y"] = ny
                elif self._active_handle == "tr":
                    ny = max(0, min(orig_y + orig_h - 10, orig_y + dy))
                    sel_reg["width"] = max(10, min(pw - orig_x, orig_w + dx))
                    sel_reg["height"] = orig_h - (ny - orig_y)
                    sel_reg["y"] = ny
                elif self._active_handle == "bl":
                    nx = max(0, min(orig_x + orig_w - 10, orig_x + dx))
                    sel_reg["width"] = orig_w - (nx - orig_x)
                    sel_reg["height"] = max(10, min(ph - orig_y, orig_h + dy))
                    sel_reg["x"] = nx

                self.coordinates_changed.emit(sel_reg["x"], sel_reg["y"], sel_reg["width"], sel_reg["height"])
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
        old_hover = self._hovered_id
        hit_reg = self._hit_test_region(c_pos)
        self._hovered_id = hit_reg.get("id") if hit_reg else None
        if old_hover != self._hovered_id:
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
            elif hit_reg:
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

                if rw >= 8 and rh >= 8:
                    self._push_undo()
                    self.new_region_drawn.emit(rx, ry, rw, rh)
            self._draw_start_img = None
            self._draw_current_img = None
            self.update()
            return

        if self._is_modifying:
            self._is_modifying = False
            self._active_handle = None
            if self._selected_id:
                sel_reg = next((r for r in self._regions if r.get("id") == self._selected_id), None)
                if sel_reg:
                    self.region_modified.emit(
                        sel_reg["id"], sel_reg["x"], sel_reg["y"], sel_reg["width"], sel_reg["height"]
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
        new_scale = max(0.05, min(old_scale * zoom_factor, 10.0))

        # Zoom centering at cursor position
        self._offset = c_pos - (c_pos - self._offset) * (new_scale / old_scale)
        self._scale = new_scale
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_region()
        elif event.key() == Qt.Key_Z and (event.modifiers() & Qt.ControlModifier):
            if event.modifiers() & Qt.ShiftModifier:
                self.redo()
            else:
                self.undo()
        elif event.key() == Qt.Key_Y and (event.modifiers() & Qt.ControlModifier):
            self.redo()
        super().keyPressEvent(event)

    # Hit testing helpers
    def _hit_test_region(self, canvas_pt: QPointF) -> Optional[Dict[str, Any]]:
        """Check if canvas position falls inside any region."""
        for reg in reversed(self._regions):
            bx = reg.get("x", 0)
            by = reg.get("y", 0)
            bw = reg.get("width", 0)
            bh = reg.get("height", 0)

            tl = self.img_to_canvas(bx, by)
            c_rect = QRectF(tl.x(), tl.y(), bw * self._scale, bh * self._scale)
            if c_rect.contains(canvas_pt):
                return reg
        return None

    def _hit_test_handle(self, canvas_pt: QPointF) -> Optional[str]:
        """Check if canvas position hits a handle of the selected region."""
        if self._selected_id is None:
            return None

        sel_reg = next((r for r in self._regions if r.get("id") == self._selected_id), None)
        if not sel_reg:
            return None

        bx = sel_reg.get("x", 0)
        by = sel_reg.get("y", 0)
        bw = sel_reg.get("width", 0)
        bh = sel_reg.get("height", 0)

        tl = self.img_to_canvas(bx, by)
        c_w = bw * self._scale
        c_h = bh * self._scale
        r = QRectF(tl.x(), tl.y(), c_w, c_h)

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


class CollectionCanvasContainer(QFrame):
    """
    Container frame embedding CollectionCanvasWidget with dedicated top controls toolbar:
    Fit to screen, 100%, Zoom In/Out, Draw Box mode, Delete Box, Undo, Redo,
    and live coordinate information.
    """

    region_selected = Signal(dict)
    region_deselected = Signal()
    new_region_drawn = Signal(int, int, int, int)
    region_modified = Signal(int, int, int, int, int)
    region_deleted = Signal(int)

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
        self.btn_fit.setToolTip("Fit image to screen (Ctrl+0)")
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

        self.btn_draw = QPushButton("Draw Box")
        self.btn_draw.setCheckable(True)
        self.btn_draw.setToolTip("Click and drag to manually outline an asset region")
        self.btn_draw.setStyleSheet(self._toggle_btn_style())
        self.btn_draw.toggled.connect(self._toggle_draw_mode)
        toolbar.addWidget(self.btn_draw)

        self.btn_delete = QPushButton("Delete Box")
        self.btn_delete.setToolTip("Delete selected bounding box (Del)")
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

        toolbar.addStretch()

        self.lbl_coords = QLabel("X: - | Y: - | W: - | H: -")
        self.lbl_coords.setStyleSheet(f"color: {THEME_COLORS['accent_primary']}; font-size: 11px; font-weight: 600;")
        toolbar.addWidget(self.lbl_coords)

        toolbar.addSpacing(10)

        self.lbl_info = QLabel("Scroll to zoom • Drag to pan • Click box to inspect/resize")
        self.lbl_info.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 11px;")
        toolbar.addWidget(self.lbl_info)

        layout.addLayout(toolbar)

        # Main Canvas
        self.canvas = CollectionCanvasWidget(self)
        self.canvas.region_selected.connect(self.region_selected.emit)
        self.canvas.region_deselected.connect(self.region_deselected.emit)
        self.canvas.new_region_drawn.connect(self.new_region_drawn.emit)
        self.canvas.region_modified.connect(self.region_modified.emit)
        self.canvas.region_deleted.connect(self.region_deleted.emit)
        self.canvas.history_changed.connect(self._on_history_changed)
        self.canvas.coordinates_changed.connect(self._on_coordinates_changed)
        layout.addWidget(self.canvas, stretch=1)

    def load_image(self, file_path: str, regions: Optional[List[Dict[str, Any]]] = None):
        self.canvas.load_image(file_path, regions)
        self.lbl_coords.setText("X: - | Y: - | W: - | H: -")

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
            self.lbl_info.setText("Drawing Mode: Drag rectangle on image to create candidate region")
        else:
            self.lbl_info.setText("Scroll to zoom • Drag to pan • Click box to inspect/resize")

    def _delete_selected(self):
        self.canvas.delete_selected_region()

    def _undo(self):
        self.canvas.undo()

    def _redo(self):
        self.canvas.redo()

    def _on_history_changed(self, can_undo: bool, can_redo: bool):
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)

    def _on_coordinates_changed(self, x: int, y: int, w: int, h: int):
        self.lbl_coords.setText(f"X: {x} | Y: {y} | W: {w}px | H: {h}px (Area: {w * h:,}px²)")

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
