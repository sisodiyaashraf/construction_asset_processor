"""
Sprite Sheet Engine (Stage 9)
Construction Asset Processor

Manages sprite sheet definitions, uniform grid calculations, irregular manual frames,
pivot/anchor assignments, animation sequencing, and safe export of individual frames
and Flutter + Flame animation metadata.

Strictly non-destructive:
- Never modifies original source images.
- Never overwrites original sprite sheets.
- Preserves full resolution and transparency.
- Never automatically discards frames.
- Reuses Stage 8 sprite sheet classifications and candidate boxes where available.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from app.config import OUTPUT_SPRITES_DIR
from core.database import db

logger = logging.getLogger("AssetProcessor.SpriteSheetEngine")

ENGINE_VERSION = "1.0.0"

SUPPORTED_SPRITE_FORMATS = {".png", ".jpg", ".jpeg", ".webp"}

ANIMATION_PRESETS = [
    "Idle",
    "Working",
    "Digging",
    "Driving",
    "Wheel Rotation",
    "Hydraulic Movement",
    "Construction Effect",
    "Custom",
]

PIVOT_PRESETS = {
    "Center": (0.5, 0.5),
    "Bottom Center": (0.5, 1.0),
    "Bottom Left": (0.0, 1.0),
    "Bottom Right": (1.0, 1.0),
    "Top Center": (0.5, 0.0),
    "Top Left": (0.0, 0.0),
    "Top Right": (1.0, 0.0),
    "Custom": (0.5, 0.5),
}

STANDARD_FPS_VALUES = [1, 2, 4, 6, 8, 10, 12, 15, 24, 30]


class SpriteSheetEngine:
    """
    Core engine managing sprite sheet layout analysis, uniform grid generation,
    manual frame definitions, pivot coordinate assignment, and export processing.
    """

    def __init__(self):
        self._version = ENGINE_VERSION
        self.output_frames_dir = OUTPUT_SPRITES_DIR / "frames"
        self.output_anims_dir = OUTPUT_SPRITES_DIR / "animations"
        self.output_meta_dir = OUTPUT_SPRITES_DIR / "metadata"

        for p in [self.output_frames_dir, self.output_anims_dir, self.output_meta_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata and local capabilities."""
        return {
            "name": "Sprite Sheet Editor & Animation Frame Manager",
            "version": self._version,
            "offline": True,
            "capabilities": [
                "Uniform Grid Calculation with Margins and Spacing",
                "Irregular Manual Frame Definition & Coordinate Editing",
                "Per-Frame Pivot & Anchor Presets for Machinery Joint Kinematics",
                "Multi-Sequence Animation Definitions with Reusable Frames",
                "Lossless PNG Frame Extraction with Transparency Retention",
                "Flutter + Flame Documented JSON Metadata Export",
            ],
        }

    # -------------------------------------------------------------------------
    # Import & Inspection
    # -------------------------------------------------------------------------

    def inspect_image_source(self, file_path: str) -> Dict[str, Any]:
        """
        Inspect a sprite sheet image file without modifying it.
        Returns file info, dimensions, transparency status, and format.
        """
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        ext = p.suffix.lower()
        if ext not in SUPPORTED_SPRITE_FORMATS:
            raise ValueError(f"Unsupported format '{ext}'. Must be PNG, JPG, JPEG, or WebP.")

        file_size = p.stat().st_size

        with Image.open(str(p)) as im:
            w, h = im.size
            mode = im.mode
            has_alpha = False
            if mode in ("RGBA", "LA") or (mode == "P" and "transparency" in im.info):
                # Check if there are actual non-opaque pixels
                if mode != "RGBA":
                    im_rgba = im.convert("RGBA")
                else:
                    im_rgba = im
                alpha = np.array(im_rgba)[:, :, 3]
                has_alpha = bool(np.any(alpha < 250))

        return {
            "valid": True,
            "image_path": str(p.resolve()),
            "filename": p.name,
            "width": w,
            "height": h,
            "aspect_ratio": round(w / max(1, h), 2),
            "channels": 4 if mode in ("RGBA", "LA") or has_alpha else 3,
            "format": ext.replace(".", "").upper(),
            "file_size": file_size,
            "has_transparency": has_alpha,
            "transparency_status": "transparent" if has_alpha else "opaque",
        }

    # -------------------------------------------------------------------------
    # Grid Calculation (Mode A)
    # -------------------------------------------------------------------------

    def calculate_uniform_grid(
        self,
        image_width: int,
        image_height: int,
        cols: int = 1,
        rows: int = 1,
        frame_width: int = 0,
        frame_height: int = 0,
        h_spacing: int = 0,
        v_spacing: int = 0,
        margin_left: int = 0,
        margin_right: int = 0,
        margin_top: int = 0,
        margin_bottom: int = 0,
        default_pivot: Tuple[float, float] = (0.5, 0.5),
        default_duration_ms: int = 100,
        base_name: str = "frame",
        return_telemetry: bool = False,
        **kwargs,
    ) -> Any:
        """
        Calculate uniform grid frames with margins and spacing.
        Never discards remaining pixels silently; reports unused border geometry.
        Returns: frames_list (or (frames_list, grid_telemetry) if return_telemetry=True)
        """
        if "columns" in kwargs:
            cols = kwargs["columns"]
        if "spacing_x" in kwargs:
            h_spacing = kwargs["spacing_x"]
        if "spacing_y" in kwargs:
            v_spacing = kwargs["spacing_y"]
        if "name_prefix" in kwargs:
            base_name = kwargs["name_prefix"]

        cols = max(1, cols)
        rows = max(1, rows)
        h_spacing = max(0, h_spacing)
        v_spacing = max(0, v_spacing)
        margin_left = max(0, margin_left)
        margin_right = max(0, margin_right)
        margin_top = max(0, margin_top)
        margin_bottom = max(0, margin_bottom)

        avail_w = image_width - margin_left - margin_right - ((cols - 1) * h_spacing)
        avail_h = image_height - margin_top - margin_bottom - ((rows - 1) * v_spacing)

        if frame_width <= 0:
            frame_width = max(1, avail_w // cols)
        if frame_height <= 0:
            frame_height = max(1, avail_h // rows)

        frames = []
        frame_idx = 0

        allow_partial = kwargs.get("allow_partial", False)

        for r in range(rows):
            for c in range(cols):
                fx = margin_left + c * (frame_width + h_spacing)
                fy = margin_top + r * (frame_height + v_spacing)

                # Skip if box completely or partially exceeds boundary (when strict bounds)
                if not allow_partial and (fx + frame_width > image_width or fy + frame_height > image_height):
                    continue
                if fx >= image_width or fy >= image_height:
                    continue

                actual_w = min(frame_width, image_width - fx)
                actual_h = min(frame_height, image_height - fy)

                frames.append({
                    "frame_index": frame_idx,
                    "sequence_order": frame_idx,
                    "x": int(fx),
                    "y": int(fy),
                    "width": int(actual_w),
                    "height": int(actual_h),
                    "pivot_x": float(default_pivot[0]),
                    "pivot_y": float(default_pivot[1]),
                    "duration_ms": int(default_duration_ms),
                    "frame_duration_ms": int(default_duration_ms),
                    "frame_name": f"{base_name}_{frame_idx:03d}",
                    "transparency_status": "unknown",
                })
                frame_idx += 1

        used_right = margin_left + cols * frame_width + (cols - 1) * h_spacing
        used_bottom = margin_top + rows * frame_height + (rows - 1) * v_spacing
        remainder_w = max(0, image_width - used_right)
        remainder_h = max(0, image_height - used_bottom)

        telemetry = {
            "cols": cols,
            "rows": rows,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "h_spacing": h_spacing,
            "v_spacing": v_spacing,
            "margin_left": margin_left,
            "margin_right": margin_right,
            "margin_top": margin_top,
            "margin_bottom": margin_bottom,
            "total_frames": len(frames),
            "remainder_w": remainder_w,
            "remainder_h": remainder_h,
            "is_exact_fit": (remainder_w == 0 and remainder_h == 0),
        }

        if return_telemetry:
            return frames, telemetry
        return frames

    # -------------------------------------------------------------------------
    # Manual Frame Management (Mode B)
    # -------------------------------------------------------------------------

    def create_manual_frame(
        self,
        image_width: int = 10000,
        image_height: int = 10000,
        x: int = 0,
        y: int = 0,
        width: int = 64,
        height: int = 64,
        frame_index: int = 0,
        frame_name: str = "",
        pivot: Tuple[float, float] = (0.5, 0.5),
        duration_ms: int = 100,
        **kwargs,
    ) -> Dict[str, Any]:
        """Create a single clamped frame definition for irregular layouts."""
        if "index" in kwargs:
            frame_index = kwargs["index"]
        if "w" in kwargs:
            width = kwargs["w"]
        if "h" in kwargs:
            height = kwargs["h"]

        clamped_x = max(0, min(image_width - 1, x))
        clamped_y = max(0, min(image_height - 1, y))
        clamped_w = max(4, min(image_width - clamped_x, width))
        clamped_h = max(4, min(image_height - clamped_y, height))

        if not frame_name:
            frame_name = f"frame_{frame_index:03d}"

        return {
            "frame_index": frame_index,
            "sequence_order": frame_index,
            "x": int(clamped_x),
            "y": int(clamped_y),
            "width": int(clamped_w),
            "height": int(clamped_h),
            "pivot_x": float(pivot[0]),
            "pivot_y": float(pivot[1]),
            "duration_ms": int(duration_ms),
            "frame_duration_ms": int(duration_ms),
            "frame_name": frame_name,
            "transparency_status": "unknown",
        }

    def renumber_frames(self, frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Renumber a list of frames sequentially 0..N-1."""
        reordered = []
        for idx, f in enumerate(frames):
            copy_f = dict(f)
            copy_f["frame_index"] = idx
            copy_f["sequence_order"] = idx
            reordered.append(copy_f)
        return reordered
        reordered = []
        for idx, f in enumerate(frames):
            copy_f = dict(f)
            copy_f["frame_index"] = idx
            reordered.append(copy_f)
        return reordered

    # -------------------------------------------------------------------------
    # Stage 8 Integration
    # -------------------------------------------------------------------------

    def import_stage8_candidate_regions(self, asset_id: int) -> List[Dict[str, Any]]:
        """
        Import existing candidate regions recorded during Stage 8 Collection Splitter.
        Converts collection regions into initial sprite frames.
        """
        regions = db.get_collection_regions(asset_id)
        if not regions:
            return []

        # Filter sprite_frame or candidate regions
        frames = []
        for idx, r in enumerate(regions):
            frames.append({
                "frame_index": idx,
                "x": int(r.get("x", 0)),
                "y": int(r.get("y", 0)),
                "width": int(r.get("width", 50)),
                "height": int(r.get("height", 50)),
                "pivot_x": 0.5,
                "pivot_y": 0.5,
                "frame_duration_ms": 100,
                "frame_name": f"stage8_frame_{idx:03d}",
                "transparency_status": "unknown",
            })
        return frames

    # -------------------------------------------------------------------------
    # Frame Cropping & Pivot Utilities
    # -------------------------------------------------------------------------

    def crop_frame(
        self, img_pil: Image.Image, x: int, y: int, width: int, height: int
    ) -> Image.Image:
        """
        Crop an individual frame from a PIL image without altering source pixels.
        Preserves original resolution and transparency.
        """
        img_w, img_h = img_pil.size
        cx1 = max(0, min(img_w, x))
        cy1 = max(0, min(img_h, y))
        cx2 = max(cx1, min(img_w, x + width))
        cy2 = max(cy1, min(img_h, y + height))

        if cx2 <= cx1 or cy2 <= cy1:
            raise ValueError(f"Invalid crop bounds ({cx1}, {cy1}, {cx2}, {cy2})")

        return img_pil.crop((cx1, cy1, cx2, cy2))

    def resolve_pivot_coordinates(
        self,
        frame_or_width: Any,
        frame_height: Optional[int] = None,
        pivot_x_ratio: float = 0.5,
        pivot_y_ratio: float = 0.5,
    ) -> Any:
        """
        Convert relative pivot ratios (0.0–1.0) into pixel coordinates.
        Supports:
        - resolve_pivot_coordinates(frame_dict) -> (px_offset, py_offset, abs_x, abs_y)
        - resolve_pivot_coordinates(w, h, px_ratio, py_ratio) -> (px_offset, py_offset)
        """
        if isinstance(frame_or_width, dict):
            w = frame_or_width.get("width", 0)
            h = frame_or_width.get("height", 0)
            px_r = float(frame_or_width.get("pivot_x", 0.5))
            py_r = float(frame_or_width.get("pivot_y", 0.5))
            fx = frame_or_width.get("x", 0)
            fy = frame_or_width.get("y", 0)
            px = int(round(px_r * w))
            py = int(round(py_r * h))
            return px, py, fx + px, fy + py
        else:
            w = frame_or_width
            h = frame_height or 0
            px = int(round(pivot_x_ratio * w))
            py = int(round(pivot_y_ratio * h))
            return px, py

    # -------------------------------------------------------------------------
    # Export Engine
    # -------------------------------------------------------------------------

    def export_individual_frames(
        self,
        image_path: str = "",
        frames: Optional[List[Dict[str, Any]]] = None,
        output_dir: Optional[Any] = None,
        filename_prefix: str = "frame",
        collision_mode: str = "increment",
        **kwargs,
    ) -> List[str]:
        """
        Export individual frames as lossless PNG files.
        collision_mode: 'increment' (resolves collisions with _01, _02), 'overwrite', or 'skip'
        """
        if "source_image_path" in kwargs:
            image_path = kwargs["source_image_path"]
        if "filename_pattern" in kwargs:
            filename_prefix = kwargs["filename_pattern"]

        frames = frames or []
        dest_dir = Path(output_dir) if output_dir else self.output_frames_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        exported_paths = []

        with Image.open(image_path) as src_img:
            for idx, frame in enumerate(frames):
                crop = self.crop_frame(
                    src_img,
                    x=frame["x"],
                    y=frame["y"],
                    width=frame["width"],
                    height=frame["height"],
                )

                # Determine base name
                custom_name = frame.get("frame_name", "").strip()
                if "{index" in filename_prefix or "{sheet_name" in filename_prefix or "{frame_name" in filename_prefix:
                    sheet_name = Path(image_path).stem
                    f_name = custom_name or f"frame_{idx:03d}"
                    try:
                        base_name = filename_prefix.format(
                            index=idx,
                            sheet_name=sheet_name,
                            frame_name=f_name,
                        )
                    except Exception:
                        base_name = f"{sheet_name}_{idx:03d}"
                    if not base_name.lower().endswith(".png"):
                        base_name += ".png"
                elif filename_prefix and filename_prefix != "frame":
                    base_name = f"{filename_prefix}_{idx:02d}.png" if len(frames) > 1 else f"{filename_prefix}.png"
                    if not base_name.lower().endswith(".png"):
                        base_name += ".png"
                elif custom_name:
                    base_name = f"{custom_name}.png" if not custom_name.lower().endswith(".png") else custom_name
                else:
                    base_name = f"{filename_prefix}_{idx:03d}.png"

                target_file = dest_dir / base_name

                if target_file.exists():
                    if collision_mode == "skip":
                        continue
                    elif collision_mode == "increment":
                        col_idx = 1
                        stem = target_file.stem
                        ext = target_file.suffix
                        stem_clean = re.sub(r'_\d+$', '', stem)
                        while target_file.exists():
                            target_file = dest_dir / f"{stem_clean}_{col_idx:02d}{ext}"
                            col_idx += 1

                crop.save(str(target_file), format="PNG", optimize=True)
                exported_paths.append(str(target_file.resolve()))

        return exported_paths

    def export_flutter_flame_metadata(
        self,
        source_image_name: Any = None,
        image_width: int = 0,
        image_height: int = 0,
        frames: Optional[List[Dict[str, Any]]] = None,
        animations: Optional[List[Dict[str, Any]]] = None,
        output_file_path: Optional[Any] = None,
        **kwargs,
    ) -> str:
        """
        Export animation configuration and frame metadata in a documented JSON format
        designed for Flutter + Flame SpriteAnimation and SpriteSheet integration.
        """
        if source_image_name is None and "sheet_def" in kwargs:
            source_image_name = kwargs["sheet_def"]
        if frames is None and "frames" in kwargs:
            frames = kwargs["frames"]
        if animations is None and "animations" in kwargs:
            animations = kwargs["animations"]
        if isinstance(source_image_name, dict):
            sheet_def = source_image_name
            source_name = sheet_def.get("source_filename") or sheet_def.get("name", "sprite_sheet.png")
            image_width = sheet_def.get("sheet_width", 0)
            image_height = sheet_def.get("sheet_height", 0)
            frames = frames if frames is not None else []
            animations = animations if animations is not None else []
            out_dir = kwargs.get("output_dir")
            if out_dir:
                target_path = Path(out_dir) / f"{sheet_def.get('name', 'sprite')}_flame_metadata.json"
            elif output_file_path:
                target_path = Path(output_file_path)
            else:
                target_path = self.output_meta_dir / f"{Path(source_name).stem}_flame_metadata.json"
        else:
            source_name = str(source_image_name)
            frames = frames or []
            animations = animations or []
            target_path = Path(output_file_path) if output_file_path else (self.output_meta_dir / f"{Path(source_name).stem}_flame_metadata.json")

        target_path.parent.mkdir(parents=True, exist_ok=True)

        meta = {
            "generator": "Construction Asset Processor — Sprite Sheet Engine",
            "format_version": "1.0.0",
            "version": self._version,
            "target_engine": "Flutter + Flame",
            "flame_integration": {
                "dart_sample": (
                    "// Flutter + Flame SpriteAnimation integration sample:\n"
                    "// final spriteAnimation = SpriteAnimation.fromFrameData(\n"
                    "//   game.images.fromCache('spritesheet.png'),\n"
                    "//   SpriteAnimationData(...),\n"
                    "// );"
                ),
            },
            "image": {
                "source_file": source_name,
                "width": image_width,
                "height": image_height,
            },
            "frames": [],
            "animations": {},
        }

        # Add frames
        for f in frames:
            px, py = self.resolve_pivot_coordinates(f["width"], f["height"], f.get("pivot_x", 0.5), f.get("pivot_y", 0.5))
            meta["frames"].append({
                "id": f.get("id"),
                "index": f.get("frame_index"),
                "name": f.get("frame_name", ""),
                "rect": {
                    "x": f["x"],
                    "y": f["y"],
                    "width": f["width"],
                    "height": f["height"],
                },
                "pivot": {
                    "normalized_x": round(float(f.get("pivot_x", 0.5)), 4),
                    "normalized_y": round(float(f.get("pivot_y", 0.5)), 4),
                    "pixel_offset_x": px,
                    "pixel_offset_y": py,
                },
                "duration_ms": f.get("duration_ms", f.get("frame_duration_ms", 100)),
            })

        # Add animations
        for a in animations:
            anim_name = a.get("name") or a.get("animation_name", "unnamed_animation")
            seq_frames = a.get("sequence", a.get("frames", []))
            meta["animations"][anim_name] = {
                "fps": a.get("fps", 10),
                "step_time_seconds": round(1.0 / max(1, a.get("fps", 10)), 4),
                "loop": bool(a.get("loop", a.get("loop_enabled", True))),
                "frame_count": len(seq_frames),
                "sequence": seq_frames,
            }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return str(target_path.resolve())

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return str(target_path.resolve())


# Global singleton sprite sheet engine
sprite_sheet_engine = SpriteSheetEngine()
