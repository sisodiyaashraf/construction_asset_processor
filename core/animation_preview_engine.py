"""
Animation Preview Engine (Stage 9)
Construction Asset Processor

Controls real-time frame playback for previewing sprite animations.
Uses QTimer to ensure smooth, non-blocking playback on the Qt event loop
without freezing the desktop UI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger("AssetProcessor.AnimationPreview")


class AnimationPlaybackController(QObject):
    """
    Playback controller for sprite sheet animation frame sequences.
    Drives smooth stepping through ordered frame dictionaries.
    """

    frame_changed = Signal(int, dict)  # (sequence_index, frame_dict)
    playback_state_changed = Signal(bool)  # is_playing
    animation_finished = Signal()  # emitted when non-looping sequence completes
    sequence_updated = Signal(int)  # total_frames

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._sequence: List[Dict[str, Any]] = []
        self._current_index: int = 0
        self._fps: int = 10
        self._speed_multiplier: float = 1.0
        self._loop_enabled: bool = True
        self._is_playing: bool = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer_tick)

    # -------------------------------------------------------------------------
    # Properties & Setters
    # -------------------------------------------------------------------------

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def fps(self) -> int:
        return self._fps

    @property
    def loop_enabled(self) -> bool:
        return self._loop_enabled

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    def get_sequence_length(self) -> int:
        return len(self._sequence)

    def get_current_frame(self) -> Optional[Dict[str, Any]]:
        if 0 <= self._current_index < len(self._sequence):
            return self._sequence[self._current_index]
        return None

    def set_sequence(self, sequence: List[Dict[str, Any]], reset_index: bool = True):
        """Set the active list of frames for animation playback."""
        was_playing = self._is_playing
        if was_playing:
            self.pause()

        self._sequence = list(sequence or [])
        if reset_index or self._current_index >= len(self._sequence):
            self._current_index = 0

        self.sequence_updated.emit(len(self._sequence))

        if self._sequence:
            self.frame_changed.emit(self._current_index, self._sequence[self._current_index])

        if was_playing and self._sequence:
            self.play()

    def set_fps(self, fps: int):
        """Set playback frames per second."""
        self._fps = max(1, min(fps, 120))
        if self._is_playing:
            self._schedule_next_tick()

    def set_speed_multiplier(self, multiplier: float):
        """Set speed factor (e.g. 0.5x, 1.0x, 2.0x)."""
        self._speed_multiplier = max(0.1, min(multiplier, 5.0))
        if self._is_playing:
            self._schedule_next_tick()

    def set_loop_enabled(self, loop: bool):
        """Enable or disable animation looping."""
        self._loop_enabled = loop

    # -------------------------------------------------------------------------
    # Playback Controls
    # -------------------------------------------------------------------------

    def play(self):
        """Start or resume animation playback."""
        if not self._sequence:
            return

        if not self._is_playing:
            # If at the end and non-looping, restart from beginning
            if not self._loop_enabled and self._current_index >= len(self._sequence) - 1:
                self._current_index = 0

            self._is_playing = True
            self.playback_state_changed.emit(True)
            self._schedule_next_tick()

    def pause(self):
        """Pause playback at current frame."""
        if self._is_playing:
            self._is_playing = False
            self._timer.stop()
            self.playback_state_changed.emit(False)

    def stop(self):
        """Stop playback and rewind to the first frame."""
        self.pause()
        self.goto_frame(0)

    def first_frame(self):
        """Rewind to the first frame."""
        self.goto_frame(0)

    def last_frame(self):
        """Jump to the last frame."""
        if self._sequence:
            self.goto_frame(len(self._sequence) - 1)

    def toggle_play(self):
        """Toggle between play and pause."""
        if self._is_playing:
            self.pause()
        else:
            self.play()

    def toggle_play_pause(self):
        """Alias for toggle_play."""
        self.toggle_play()

    def step_forward(self):
        """Advance one frame in sequence."""
        if not self._sequence:
            return
        self.pause()
        next_idx = self._current_index + 1
        if next_idx >= len(self._sequence):
            next_idx = 0 if self._loop_enabled else len(self._sequence) - 1
        self.goto_frame(next_idx)

    def step_backward(self):
        """Step back one frame in sequence."""
        if not self._sequence:
            return
        self.pause()
        prev_idx = self._current_index - 1
        if prev_idx < 0:
            prev_idx = len(self._sequence) - 1 if self._loop_enabled else 0
        self.goto_frame(prev_idx)

    def goto_frame(self, index: int):
        """Jump to specific frame index in sequence."""
        if not self._sequence:
            return
        clamped = max(0, min(index, len(self._sequence) - 1))
        self._current_index = clamped
        self.frame_changed.emit(self._current_index, self._sequence[self._current_index])

    # -------------------------------------------------------------------------
    # Internal Timer Stepping
    # -------------------------------------------------------------------------

    def _schedule_next_tick(self):
        """Calculate millisecond delay for current frame and start single-shot timer."""
        if not self._is_playing or not self._sequence:
            return

        current_frame = self.get_current_frame()
        # Per-frame duration override or fallback to 1000 / fps
        frame_dur = current_frame.get("frame_duration_ms", 0) if current_frame else 0
        if frame_dur <= 0:
            frame_dur = int(round(1000.0 / float(self._fps)))

        # Apply speed multiplier
        actual_interval = max(5, int(round(frame_dur / self._speed_multiplier)))
        self._timer.start(actual_interval)

    def _on_timer_tick(self):
        """Timer fired: advance to next frame."""
        if not self._is_playing or not self._sequence:
            return

        next_idx = self._current_index + 1
        if next_idx >= len(self._sequence):
            if self._loop_enabled:
                next_idx = 0
            else:
                self.pause()
                self.animation_finished.emit()
                return

        self._current_index = next_idx
        self.frame_changed.emit(self._current_index, self._sequence[self._current_index])
        self._schedule_next_tick()
