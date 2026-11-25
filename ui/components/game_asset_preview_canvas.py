"""
Game Asset Preview Canvas Component (Stage 11)
Construction Asset Processor

Interactive canvas supporting:
- Mode 1: Individual asset display over dark checkerboard with pivot crosshair.
- Mode 2: Texture atlas display with sprite bounding boxes, labels, and selection highlight.
- Mode 3: Animation playback frame rendering centered on kinematic pivot point.
- Interactive pan, smooth zoom (0.1x to 8.0x), 100% reset, and fit-to-view.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QMouseEvent, QPainter,
    QPen, QPixmap, QWheelEvent
)
from PySide6.QtWidgets import QFrame, QWidget

from app.config import THEME_COLORS
from ui.components.comparison_dialog import create_checkerboard_pixmap

logger = logging.getLogger("AssetProcessor.GameAssetPreviewCanvas")


class GameAssetPreviewCanvas(QWidget):
    """Interactive canvas rendering static assets, texture atlases, and animation frames."""

    sprite_clicked = Signal(str, dict)
    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._pixmap: Optional[QPixmap] = None
        self._mode: str = "individual"  # "individual", "atlas", "animation"

        # Atlas data
        self._frames: List[Dict[str, Any]] = []
        self._selected_frame_name: str = ""
        self._hovered_frame: Optional[Dict[str, Any]] = None

        # Pivot point (normalized 0.0 to 1.0)
        self._pivot: Tuple[float, float] = (0.5, 0.5)
        self._show_pivot: bool = True

        # Pan & Zoom transform state
        self._zoom: float = 1.0
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0
        self._is_panning: bool = False
        self._last_mouse_pos: QPoint = QPoint()

        # Checkerboard tile
        self._checker_tile = create_checkerboard_pixmap(24)

    # -------------------------------------------------------------------------
    # Data Loading
    # -------------------------------------------------------------------------

    def set_individual_image(
        self,
        image_path: str,
        pivot: Tuple[float, float] = (0.5, 0.5),
    ):
        """Display an individual static or transparent asset."""
        self._mode = "individual"
        self._pivot = pivot
        self._frames = []
        self._load_pixmap(image_path)
        self.fit_to_view()

    def set_atlas_data(
        self,
        image_path: str,
        frames: List[Dict[str, Any]],
        selected_name: str = "",
    ):
        """Display texture atlas with bounding boxes and sprite selection."""
        self._mode = "atlas"
        self._frames = frames
        self._selected_frame_name = selected_name
        self._load_pixmap(image_path)
        self.fit_to_view()

    def set_animation_frame(
        self,
        frame_pixmap_or_path: Any,
        pivot: Tuple[float, float] = (0.5, 0.5),
    ):
        """Display current frame of an active animation sequence."""
        self._mode = "animation"
        self._pivot = pivot
        self._frames = []

        if isinstance(frame_pixmap_or_path, QPixmap):
            self._pixmap = frame_pixmap_or_path
            self.update()
        elif isinstance(frame_pixmap_or_path, (str, Path)):
            self._load_pixmap(str(frame_pixmap_or_path))

    def _load_pixmap(self, path: str):
        if Path(path).exists():
            self._pixmap = QPixmap(path)
        else:
            self._pixmap = None
        self.update()

    def select_atlas_sprite(self, sprite_name: str):
        """Highlight a specific sprite rectangle in atlas mode."""
        self._selected_frame_name = sprite_name
        self.update()

    # -------------------------------------------------------------------------
    # View & Transform Controls
    # -------------------------------------------------------------------------

    def set_zoom(self, zoom: float):
        """Set zoom scale factor clamped between 0.05x and 10.0x."""
        self._zoom = max(0.05, min(10.0, zoom))
        self.zoom_changed.emit(self._zoom)
        self.update()

    def zoom_in(self):
        self.set_zoom(self._zoom * 1.25)

    def zoom_out(self):
        self.set_zoom(self._zoom / 1.25)

    def zoom_100(self):
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.set_zoom(1.0)

    def fit_to_view(self):
        """Fit image inside canvas viewport with margin."""
        if not self._pixmap or self._pixmap.isNull():
            return
        w = max(10, self.width() - 40)
        h = max(10, self.height() - 40)
        scale_w = w / max(1, self._pixmap.width())
        scale_h = h / max(1, self._pixmap.height())
        fit_zoom = min(scale_w, scale_h, 1.5)
        self._pan_x = (self.width() - (self._pixmap.width() * fit_zoom)) / 2.0
        self._pan_y = (self.height() - (self._pixmap.height() * fit_zoom)) / 2.0
        self.set_zoom(fit_zoom)

    # -------------------------------------------------------------------------
    # Painting
    # -------------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 1. Dark charcoal base
        painter.fillRect(self.rect(), QColor("#121417"))

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(THEME_COLORS["text_muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "No Asset Loaded in Preview")
            painter.end()
            return

        pw = self._pixmap.width() * self._zoom
        ph = self._pixmap.height() * self._zoom
        ox = self._pan_x
        oy = self._pan_y

        # 2. Draw industrial checkerboard transparency under image rect
        painter.drawTiledPixmap(int(ox), int(oy), int(pw), int(ph), self._checker_tile)

        # 3. Draw image
        painter.drawPixmap(int(ox), int(oy), int(pw), int(ph), self._pixmap)

        # 4. Mode-specific overlays
        if self._mode == "atlas":
            self._paint_atlas_overlays(painter, ox, oy)
        elif self._mode in ("individual", "animation") and self._show_pivot:
            self._paint_pivot_crosshair(painter, ox, oy, pw, ph)

        painter.end()

    def _paint_atlas_overlays(self, painter: QPainter, ox: float, oy: float):
        """Render sprite bounding boxes, tags, and selection outlines."""
        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)

        for f in self._frames:
            fx = ox + (f["x"] * self._zoom)
            fy = oy + (f["y"] * self._zoom)
            fw = f["w"] * self._zoom
            fh = f["h"] * self._zoom

            name = f.get("name", "")
            is_selected = (name == self._selected_frame_name)
            is_hovered = (self._hovered_frame == f)

            if is_selected:
                pen = QPen(QColor(THEME_COLORS["accent_primary"]), 2)
                bg_color = QColor(229, 169, 60, 40)
            elif is_hovered:
                pen = QPen(QColor("#38BDF8"), 2)
                bg_color = QColor(56, 189, 248, 30)
            else:
                pen = QPen(QColor(56, 189, 248, 160), 1)
                bg_color = QColor(0, 0, 0, 0)

            painter.setPen(pen)
            if bg_color.alpha() > 0:
                painter.fillRect(QRectF(fx, fy, fw, fh), bg_color)
            painter.drawRect(QRectF(fx, fy, fw, fh))

            # Draw sprite tag
            if name and fw > 20 and fh > 14:
                tag_w = min(fw, 140)
                tag_h = 16
                painter.fillRect(QRectF(fx, fy, tag_w, tag_h), QColor(18, 20, 23, 200))
                painter.setPen(QColor("#FFFFFF") if is_selected else QColor("#94A3B8"))
                painter.drawText(QRectF(fx + 3, fy, tag_w - 6, tag_h), Qt.AlignVCenter | Qt.AlignLeft, name[:18])

    def _paint_pivot_crosshair(self, painter: QPainter, ox: float, oy: float, pw: float, ph: float):
        """Draw normalized kinematic pivot point marker."""
        px_rel = self._pivot[0] * pw
        py_rel = self._pivot[1] * ph
        cx = ox + px_rel
        cy = oy + py_rel

        # Crosshair lines
        pen = QPen(QColor(THEME_COLORS["accent_primary"]), 1.5, Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(int(ox), int(cy), int(ox + pw), int(cy))
        painter.drawLine(int(cx), int(oy), int(cx), int(oy + ph))

        # Center target ring
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(QColor(THEME_COLORS["accent_primary"]))
        painter.drawEllipse(int(cx - 5), int(cy - 5), 10, 10)

    # -------------------------------------------------------------------------
    # Mouse & Interactive Events
    # -------------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent):
        """Zoom toward mouse cursor on wheel delta."""
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else (1.0 / 1.15)

        old_zoom = self._zoom
        new_zoom = max(0.05, min(10.0, old_zoom * factor))

        # Center zoom around mouse position
        mouse_pos = event.position()
        mx = mouse_pos.x()
        my = mouse_pos.y()

        self._pan_x = mx - (mx - self._pan_x) * (new_zoom / old_zoom)
        self._pan_y = my - (my - self._pan_y) * (new_zoom / old_zoom)
        self.set_zoom(new_zoom)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

            # In atlas mode: check if sprite was clicked
            if self._mode == "atlas" and self._pixmap:
                clicked_sprite = self._find_sprite_at_pos(event.pos())
                if clicked_sprite:
                    self._selected_frame_name = clicked_sprite.get("name", "")
                    self.sprite_clicked.emit(self._selected_frame_name, clicked_sprite)
                    self.update()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_panning:
            delta = event.pos() - self._last_mouse_pos
            self._pan_x += delta.x()
            self._pan_y += delta.y()
            self._last_mouse_pos = event.pos()
            self.update()
        elif self._mode == "atlas":
            hov = self._find_sprite_at_pos(event.pos())
            if hov != self._hovered_frame:
                self._hovered_frame = hov
                self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _find_sprite_at_pos(self, pos: QPoint) -> Optional[Dict[str, Any]]:
        """Map canvas point to atlas sprite rect."""
        if not self._pixmap or not self._frames:
            return None
        lx = (pos.x() - self._pan_x) / self._zoom
        ly = (pos.y() - self._pan_y) / self._zoom

        for f in self._frames:
            if f["x"] <= lx <= (f["x"] + f["w"]) and f["y"] <= ly <= (f["y"] + f["h"]):
                return f
        return None
