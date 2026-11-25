"""
Game Asset Preview Engine (Stage 11)
Construction Asset Processor

Manages interactive rendering data and playback state for Flutter + Flame game assets:
- Mode 1: Individual Asset inspection (dimensions, format, alpha channel, file size, pivot).
- Mode 2: Texture Atlas / Sprite Sheet inspection (frame bounds, sprite tags, selection, pivot markers).
- Mode 3: Animation sequence playback controller (play, pause, step forward/backward, loop/once, FPS controls).
- Strictly authentic: never invents missing frames or silently modifies sequence ordering.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image

logger = logging.getLogger("AssetProcessor.GameAssetPreviewEngine")

ENGINE_VERSION = "1.0.0"


class AnimationPlaybackState:
    """Manages timer-independent animation playback state and frame stepping."""

    def __init__(self, frames: Optional[List[Dict[str, Any]]] = None, fps: int = 10, loop: bool = True):
        self.frames: List[Dict[str, Any]] = frames or []
        self.fps: int = max(1, min(60, fps))
        self.loop: bool = loop
        self.current_frame_index: int = 0
        self.is_playing: bool = False

    def set_frames(self, frames: List[Dict[str, Any]], fps: int = 10, loop: bool = True):
        self.frames = frames
        self.fps = max(1, min(60, fps))
        self.loop = loop
        self.current_frame_index = 0
        self.is_playing = False

    @property
    def total_frames(self) -> int:
        return len(self.frames)

    @property
    def step_time_ms(self) -> int:
        return int(1000 / max(1, self.fps))

    @property
    def total_duration_ms(self) -> int:
        return self.total_frames * self.step_time_ms

    def play(self):
        if self.total_frames > 0:
            self.is_playing = True

    def pause(self):
        self.is_playing = False

    def toggle_play_pause(self) -> bool:
        if self.is_playing:
            self.pause()
        else:
            self.play()
        return self.is_playing

    def stop(self):
        self.is_playing = False
        self.current_frame_index = 0

    def restart(self):
        self.current_frame_index = 0
        self.is_playing = True

    def step_forward(self) -> int:
        if self.total_frames == 0:
            return 0
        if self.current_frame_index < self.total_frames - 1:
            self.current_frame_index += 1
        elif self.loop:
            self.current_frame_index = 0
        else:
            self.is_playing = False
        return self.current_frame_index

    def step_backward(self) -> int:
        if self.total_frames == 0:
            return 0
        if self.current_frame_index > 0:
            self.current_frame_index -= 1
        elif self.loop:
            self.current_frame_index = self.total_frames - 1
        return self.current_frame_index

    def goto_frame(self, index: int) -> int:
        if self.total_frames > 0:
            self.current_frame_index = max(0, min(self.total_frames - 1, index))
        return self.current_frame_index

    def get_active_frame(self) -> Optional[Dict[str, Any]]:
        if 0 <= self.current_frame_index < len(self.frames):
            return self.frames[self.current_frame_index]
        return None


class GameAssetPreviewEngine:
    """Core preview engine handling data ingestion for preview canvas and views."""

    def __init__(self):
        self._version = ENGINE_VERSION
        self.playback = AnimationPlaybackState()

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata."""
        return {
            "name": "Game Asset Preview Engine",
            "version": self._version,
            "offline": True,
            "modes": ["individual_asset", "sprite_sheet_atlas", "animation_sequence"],
        }

    def load_individual_asset(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Load metadata for an individual static or transparent game asset."""
        p = Path(file_path).resolve()
        if not p.exists():
            return {"success": False, "error": f"File does not exist: {p.name}"}

        try:
            with Image.open(str(p)) as im:
                w, h = im.size
                mode = im.mode
                fmt = im.format
                has_alpha = mode in ("RGBA", "LA") or (mode == "P" and "transparency" in im.info)

            file_size = p.stat().st_size
            return {
                "success": True,
                "file_path": str(p),
                "filename": p.name,
                "width": w,
                "height": h,
                "format": fmt,
                "mode": mode,
                "has_alpha": has_alpha,
                "file_size": file_size,
                "pivot": (0.5, 0.5),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def load_sprite_sheet_atlas(
        self,
        image_path: Union[str, Path],
        metadata_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Load atlas texture and parse sprite frame bounds and tags."""
        img_p = Path(image_path).resolve()
        if not img_p.exists():
            return {"success": False, "error": f"Atlas image missing: {img_p.name}"}

        with Image.open(str(img_p)) as im:
            atlas_w, atlas_h = im.size
            atlas_fmt = im.format

        frames: List[Dict[str, Any]] = []

        if metadata_path and Path(metadata_path).exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Schema A: Flame 1.x TexturePacker standard (frames: {name: {frame: {x,y,w,h}}})
                if "frames" in data and isinstance(data["frames"], dict):
                    for name, finfo in data["frames"].items():
                        rect = finfo.get("frame", {})
                        pivot = finfo.get("pivot", [0.5, 0.5])
                        frames.append({
                            "name": name,
                            "x": rect.get("x", 0),
                            "y": rect.get("y", 0),
                            "w": rect.get("w", 0),
                            "h": rect.get("h", 0),
                            "pivot_x": pivot[0] if isinstance(pivot, (list, tuple)) else 0.5,
                            "pivot_y": pivot[1] if isinstance(pivot, (list, tuple)) else 0.5,
                        })

                # Schema B: Stage 10 internal atlas (sprites: {name: {x, y, width, height}})
                elif "sprites" in data and isinstance(data["sprites"], dict):
                    for name, sinfo in data["sprites"].items():
                        frames.append({
                            "name": name,
                            "x": sinfo.get("x", 0),
                            "y": sinfo.get("y", 0),
                            "w": sinfo.get("width", 0),
                            "h": sinfo.get("height", 0),
                            "pivot_x": 0.5,
                            "pivot_y": 0.5,
                        })
            except Exception as e:
                logger.warning("Failed parsing atlas metadata %s: %s", metadata_path, e)

        return {
            "success": True,
            "image_path": str(img_p),
            "atlas_width": atlas_w,
            "atlas_height": atlas_h,
            "format": atlas_fmt,
            "frames": frames,
            "frame_count": len(frames),
        }

    def load_animation_sequence(
        self,
        animation_name: str,
        frame_images_or_rects: List[Dict[str, Any]],
        fps: int = 10,
        loop: bool = True,
    ) -> Dict[str, Any]:
        """Configure animation playback sequence."""
        self.playback.set_frames(frame_images_or_rects, fps=fps, loop=loop)
        return {
            "success": True,
            "animation_name": animation_name,
            "frame_count": len(frame_images_or_rects),
            "fps": fps,
            "loop": loop,
            "duration_ms": self.playback.total_duration_ms,
        }


# Global GameAssetPreviewEngine singleton
game_asset_preview_engine = GameAssetPreviewEngine()
