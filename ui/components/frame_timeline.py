"""
Frame Timeline Component (Stage 9)
Displays a horizontal scrollable strip of animation frame thumbnails,
supporting frame selection, reordering, duplication, and sequence management.
Strictly non-destructive — changing frame order affects only the working animation sequence.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS
from core.sprite_sheet_engine import sprite_sheet_engine

logger = logging.getLogger("AssetProcessor.FrameTimeline")


class TimelineFrameCard(QFrame):
    """Visual thumbnail tile representing a single animation frame in the timeline."""

    clicked = Signal(int, bool, bool)  # (sequence_index, is_ctrl, is_shift)

    CARD_WIDTH = 90
    CARD_HEIGHT = 110

    def __init__(
        self,
        sequence_index: int,
        frame_data: Dict[str, Any],
        source_pixmap: Optional[QPixmap] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.sequence_index = sequence_index
        self.frame_data = frame_data
        self.source_pixmap = source_pixmap
        self.is_selected = False

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("timeline_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Top Bar: Index & Name
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        self.lbl_idx = QLabel(f"#{self.sequence_index}")
        self.lbl_idx.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
        """)
        top_bar.addWidget(self.lbl_idx)
        top_bar.addStretch()

        dur = frame_data.get("frame_duration_ms", 100)
        self.lbl_dur = QLabel(f"{dur}ms")
        self.lbl_dur.setStyleSheet(f"font-size: 9px; color: {THEME_COLORS['text_muted']};")
        top_bar.addWidget(self.lbl_dur)
        layout.addLayout(top_bar)

        # Thumbnail Container
        self.thumb_container = QFrame()
        self.thumb_container.setFixedSize(82, 64)
        self.thumb_container.setStyleSheet(f"""
            background-color: {THEME_COLORS['bg_main']};
            border: 1px solid {THEME_COLORS['border_subtle']};
            border-radius: 3px;
        """)
        t_layout = QVBoxLayout(self.thumb_container)
        t_layout.setContentsMargins(1, 1, 1, 1)
        t_layout.setAlignment(Qt.AlignCenter)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self._render_crop_thumbnail()
        t_layout.addWidget(self.lbl_thumb)
        layout.addWidget(self.thumb_container)

        # Dimensions footer
        w = frame_data.get("width", 0)
        h = frame_data.get("height", 0)
        self.lbl_dim = QLabel(f"{w}×{h}px")
        self.lbl_dim.setAlignment(Qt.AlignCenter)
        self.lbl_dim.setStyleSheet(f"font-size: 9px; color: {THEME_COLORS['text_secondary']};")
        layout.addWidget(self.lbl_dim)

        self._update_appearance()

    def _render_crop_thumbnail(self):
        if not self.source_pixmap or self.source_pixmap.isNull():
            self.lbl_thumb.setText(f"#{self.sequence_index}")
            self.lbl_thumb.setStyleSheet(f"color: {THEME_COLORS['text_muted']}; font-size: 9px;")
            return

        bx = self.frame_data.get("x", 0)
        by = self.frame_data.get("y", 0)
        bw = self.frame_data.get("width", 10)
        bh = self.frame_data.get("height", 10)

        # Crop from full source pixmap
        crop_rect = QRect(bx, by, bw, bh).intersected(self.source_pixmap.rect())
        if crop_rect.isEmpty():
            return

        cropped = self.source_pixmap.copy(crop_rect)
        scaled = cropped.scaled(78, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Checkerboard background
        canvas = QPixmap(scaled.size())
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)

        tile = 6
        c1 = QColor(36, 42, 50)
        c2 = QColor(26, 30, 36)
        for y in range(0, canvas.height(), tile):
            for x in range(0, canvas.width(), tile):
                is_even = ((x // tile) + (y // tile)) % 2 == 0
                p.fillRect(QRect(x, y, tile, tile), c1 if is_even else c2)

        p.drawPixmap(0, 0, scaled)
        p.end()

        self.lbl_thumb.setPixmap(canvas)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_appearance()

    def _update_appearance(self):
        border_col = THEME_COLORS["accent_primary"] if self.is_selected else THEME_COLORS["border_subtle"]
        bg_col = THEME_COLORS["bg_card_hover"] if self.is_selected else THEME_COLORS["bg_card"]
        self.setStyleSheet(f"""
            QFrame#timeline_card {{
                background-color: {bg_col};
                border: {2 if self.is_selected else 1}px solid {border_col};
                border-radius: 4px;
            }}
            QFrame#timeline_card:hover {{
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
            is_shift = bool(event.modifiers() & Qt.ShiftModifier)
            self.clicked.emit(self.sequence_index, is_ctrl, is_shift)
        super().mousePressEvent(event)


class FrameTimeline(QFrame):
    """
    Horizontal timeline panel managing ordered animation frame tiles.
    Provides controls to reorder earlier/later, duplicate, delete, and select frames.
    """

    frame_selected = Signal(int)  # sequence index
    selection_changed = Signal(list)  # list of selected sequence indices
    order_changed = Signal(list)  # new list of frames
    frame_deleted = Signal(int)
    frame_duplicated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME_COLORS['bg_toolbar']};
                border-top: 1px solid {THEME_COLORS['border_medium']};
            }}
        """)
        self.setFixedHeight(160)

        self._frames: List[Dict[str, Any]] = []
        self._source_pixmap: Optional[QPixmap] = None
        self._selected_indices: set[int] = set()
        self._cards: List[TimelineFrameCard] = []

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 6, 8, 6)
        main_layout.setSpacing(6)

        # Top Control Bar
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setContentsMargins(0, 0, 0, 0)
        ctrl_bar.setSpacing(6)

        lbl_title = QLabel("ANIMATION TIMELINE")
        lbl_title.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.6px;
            color: {THEME_COLORS['accent_primary']};
        """)
        ctrl_bar.addWidget(lbl_title)

        self.lbl_count = QLabel("0 Frames")
        self.lbl_count.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_secondary']};")
        ctrl_bar.addWidget(self.lbl_count)

        ctrl_bar.addSpacing(10)

        self.btn_move_left = QPushButton("◀ Move Earlier")
        self.btn_move_left.setToolTip("Move selected frame earlier in the sequence")
        self.btn_move_left.setStyleSheet(self._btn_style())
        self.btn_move_left.clicked.connect(self._move_selected_left)
        ctrl_bar.addWidget(self.btn_move_left)

        self.btn_move_right = QPushButton("Move Later ▶")
        self.btn_move_right.setToolTip("Move selected frame later in the sequence")
        self.btn_move_right.setStyleSheet(self._btn_style())
        self.btn_move_right.clicked.connect(self._move_selected_right)
        ctrl_bar.addWidget(self.btn_move_right)

        ctrl_bar.addSpacing(6)

        self.btn_dup = QPushButton("Duplicate")
        self.btn_dup.setToolTip("Duplicate selected frame in sequence")
        self.btn_dup.setStyleSheet(self._btn_style())
        self.btn_dup.clicked.connect(self._duplicate_selected)
        ctrl_bar.addWidget(self.btn_dup)

        self.btn_del = QPushButton("Remove")
        self.btn_del.setToolTip("Remove selected frame definition from sequence")
        self.btn_del.setStyleSheet(self._btn_style())
        self.btn_del.clicked.connect(self._delete_selected)
        ctrl_bar.addWidget(self.btn_del)

        ctrl_bar.addStretch()

        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setStyleSheet(self._btn_style())
        self.btn_select_all.clicked.connect(self._select_all)
        ctrl_bar.addWidget(self.btn_select_all)

        self.btn_clear_sel = QPushButton("Clear")
        self.btn_clear_sel.setStyleSheet(self._btn_style())
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        ctrl_bar.addWidget(self.btn_clear_sel)

        main_layout.addLayout(ctrl_bar)

        # Horizontal Scroll Area for Frame Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']};")

        self.strip_widget = QWidget()
        self.strip_widget.setStyleSheet(f"background-color: {THEME_COLORS['bg_main']};")
        self.strip_layout = QHBoxLayout(self.strip_widget)
        self.strip_layout.setContentsMargins(4, 4, 4, 4)
        self.strip_layout.setSpacing(6)
        self.strip_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        scroll.setWidget(self.strip_widget)
        main_layout.addWidget(scroll, stretch=1)

    def load_frames(
        self,
        frames: List[Dict[str, Any]],
        image_path: Optional[str] = None,
        selected_index: Optional[int] = 0,
    ):
        """Populate timeline with frames and load source pixmap for thumbnails."""
        self._frames = copy.deepcopy(frames or [])
        if image_path and Path(image_path).exists():
            self._source_pixmap = QPixmap(image_path)
        else:
            self._source_pixmap = None

        self._selected_indices = {selected_index} if selected_index is not None and self._frames else set()
        self._rebuild_cards()

    def set_selected_index(self, index: Optional[int]):
        """Select a single sequence index and update visual highlight."""
        self._selected_indices.clear()
        if index is not None and 0 <= index < len(self._frames):
            self._selected_indices.add(index)

        for card in self._cards:
            card.set_selected(card.sequence_index in self._selected_indices)

    def select_frame(self, index: Optional[int]):
        """Alias for set_selected_index."""
        self.set_selected_index(index)

    def set_frames(self, frames: List[Dict[str, Any]], image_path: Optional[str] = None):
        """Alias for load_frames."""
        self.load_frames(frames, image_path=image_path)

    def set_source_image(self, pixmap: Optional[QPixmap]):
        """Set source pixmap for frame thumbnails."""
        self._source_pixmap = pixmap
        self._rebuild_cards()

    def get_selected_index(self) -> Optional[int]:
        if self._selected_indices:
            return next(iter(self._selected_indices))
        return None

    def _rebuild_cards(self):
        # Clear existing cards
        while self.strip_layout.count():
            item = self.strip_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards.clear()

        for idx, f in enumerate(self._frames):
            card = TimelineFrameCard(
                sequence_index=idx,
                frame_data=f,
                source_pixmap=self._source_pixmap,
                parent=self.strip_widget,
            )
            card.set_selected(idx in self._selected_indices)
            card.clicked.connect(self._on_card_clicked)
            self.strip_layout.addWidget(card)
            self._cards.append(card)

        self.lbl_count.setText(f"{len(self._frames)} Frames")
        self._update_button_states()

    def _on_card_clicked(self, seq_idx: int, is_ctrl: bool, is_shift: bool):
        if is_ctrl:
            if seq_idx in self._selected_indices:
                self._selected_indices.remove(seq_idx)
            else:
                self._selected_indices.add(seq_idx)
        else:
            self._selected_indices = {seq_idx}

        for card in self._cards:
            card.set_selected(card.sequence_index in self._selected_indices)

        self._update_button_states()
        self.frame_selected.emit(seq_idx)
        self.selection_changed.emit(list(self._selected_indices))

    def _move_selected_left(self):
        sel_idx = self.get_selected_index()
        if sel_idx is None or sel_idx <= 0:
            return

        # Swap frame with predecessor
        self._frames[sel_idx - 1], self._frames[sel_idx] = self._frames[sel_idx], self._frames[sel_idx - 1]
        self._selected_indices = {sel_idx - 1}
        self._rebuild_cards()
        self.order_changed.emit(copy.deepcopy(self._frames))
        self.frame_selected.emit(sel_idx - 1)

    def _move_selected_right(self):
        sel_idx = self.get_selected_index()
        if sel_idx is None or sel_idx >= len(self._frames) - 1:
            return

        # Swap frame with successor
        self._frames[sel_idx], self._frames[sel_idx + 1] = self._frames[sel_idx + 1], self._frames[sel_idx]
        self._selected_indices = {sel_idx + 1}
        self._rebuild_cards()
        self.order_changed.emit(copy.deepcopy(self._frames))
        self.frame_selected.emit(sel_idx + 1)

    def _duplicate_selected(self):
        sel_idx = self.get_selected_index()
        if sel_idx is None or sel_idx >= len(self._frames):
            return

        dup_frame = copy.deepcopy(self._frames[sel_idx])
        dup_frame["frame_name"] = f"{dup_frame.get('frame_name', 'frame')}_copy"
        self._frames.insert(sel_idx + 1, dup_frame)
        self._selected_indices = {sel_idx + 1}
        self._rebuild_cards()
        self.order_changed.emit(copy.deepcopy(self._frames))
        self.frame_duplicated.emit(sel_idx)
        self.frame_selected.emit(sel_idx + 1)

    def _delete_selected(self):
        sel_idx = self.get_selected_index()
        if sel_idx is None or sel_idx >= len(self._frames):
            return

        del self._frames[sel_idx]
        new_sel = min(sel_idx, len(self._frames) - 1) if self._frames else None
        self._selected_indices = {new_sel} if new_sel is not None else set()
        self._rebuild_cards()
        self.order_changed.emit(copy.deepcopy(self._frames))
        self.frame_deleted.emit(sel_idx)
        if new_sel is not None:
            self.frame_selected.emit(new_sel)

    def _select_all(self):
        self._selected_indices = set(range(len(self._frames)))
        for card in self._cards:
            card.set_selected(True)
        self._update_button_states()
        self.selection_changed.emit(list(self._selected_indices))

    def _clear_selection(self):
        self._selected_indices.clear()
        for card in self._cards:
            card.set_selected(False)
        self._update_button_states()
        self.selection_changed.emit([])

    def _update_button_states(self):
        sel_idx = self.get_selected_index()
        has_sel = sel_idx is not None
        self.btn_move_left.setEnabled(has_sel and sel_idx > 0)
        self.btn_move_right.setEnabled(has_sel and sel_idx < len(self._frames) - 1)
        self.btn_dup.setEnabled(has_sel)
        self.btn_del.setEnabled(has_sel)

    def _btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {THEME_COLORS['bg_input']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
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
