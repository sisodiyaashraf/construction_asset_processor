"""
Texture Atlas Packing & Generation Engine (Stage 10)
Construction Asset Processor

Packs multiple individual game sprites into memory-efficient texture atlases:
- MaxRects / Shelf Best-Fit-Decreasing rectangle packing algorithm.
- Configurable atlas dimensions (512x512, 1024x1024, 2048x2048, 4096x4096, power-of-two support).
- Configurable sprite spacing (gutters) and atlas boundary padding.
- Transparent RGBA canvas with alpha preservation.
- Rotation disabled by default (strictly preserves sprite orientation).
- Detailed packing telemetry: packing efficiency %, unused area %, packed sprite count.
- Documented Flame-compatible JSON atlas metadata generation.

Strictly non-destructive:
- Never alters source images.
- Generated atlases are saved to output/atlases/ or target Flutter project.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from PIL import Image

from app.config import OUTPUT_DIR

logger = logging.getLogger("AssetProcessor.TextureAtlasEngine")

ENGINE_VERSION = "1.0.0"

ATLAS_CATEGORIES = [
    "excavator",
    "vehicles",
    "components",
    "tools",
    "environment",
    "effects",
    "ui",
    "general",
]

STANDARD_ATLAS_SIZES = [512, 1024, 2048, 4096]


class RectNode:
    """Free rectangle node for MaxRects-style 2D packing."""

    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def contains(self, other: RectNode) -> bool:
        return (
            other.x >= self.x
            and other.y >= self.y
            and (other.x + other.w) <= (self.x + self.w)
            and (other.y + other.h) <= (self.y + self.h)
        )


class MaxRectsPacker:
    """
    Maximal Rectangles (MaxRects) 2D bin packing implementation.
    Packs rectangular items with Best-Short-Side-Fit heuristic.
    """

    def __init__(self, width: int, height: int, spacing: int = 2, padding: int = 2):
        self.width = width
        self.height = height
        self.spacing = spacing
        self.padding = padding
        self.free_rects: List[RectNode] = [
            RectNode(padding, padding, width - 2 * padding, height - 2 * padding)
        ]
        self.used_rects: List[RectNode] = []

    def pack(self, w: int, h: int) -> Optional[Tuple[int, int]]:
        """
        Find best location for an item of dimension (w, h).
        Returns (x, y) if packed, or None if it doesn't fit.
        """
        req_w = w + self.spacing
        req_h = h + self.spacing

        best_node: Optional[RectNode] = None
        best_short_side = float("inf")
        best_long_side = float("inf")

        for free in self.free_rects:
            if free.w >= req_w and free.h >= req_h:
                leftover_horiz = abs(free.w - req_w)
                leftover_vert = abs(free.h - req_h)
                short_side = min(leftover_horiz, leftover_vert)
                long_side = max(leftover_horiz, leftover_vert)

                if short_side < best_short_side or (short_side == best_short_side and long_side < best_long_side):
                    best_node = RectNode(free.x, free.y, req_w, req_h)
                    best_short_side = short_side
                    best_long_side = long_side

        if best_node is None:
            return None

        # Split free rects against placed node
        self._split_free_rects(best_node)
        self._prune_free_rects()
        self.used_rects.append(best_node)

        return (best_node.x, best_node.y)

    def _split_free_rects(self, placed: RectNode):
        new_free: List[RectNode] = []
        for free in self.free_rects:
            # Check for overlap
            if not (placed.x >= free.x + free.w or placed.x + placed.w <= free.x or
                    placed.y >= free.y + free.h or placed.y + placed.h <= free.y):

                # New rect on left
                if placed.x > free.x and placed.x < free.x + free.w:
                    new_free.append(RectNode(free.x, free.y, placed.x - free.x, free.h))

                # New rect on right
                if placed.x + placed.w < free.x + free.w:
                    new_free.append(RectNode(placed.x + placed.w, free.y, free.x + free.w - (placed.x + placed.w), free.h))

                # New rect on top
                if placed.y > free.y and placed.y < free.y + free.h:
                    new_free.append(RectNode(free.x, free.y, free.w, placed.y - free.y))

                # New rect on bottom
                if placed.y + placed.h < free.y + free.h:
                    new_free.append(RectNode(free.x, placed.y + placed.h, free.w, free.y + free.h - (placed.y + placed.h)))
            else:
                new_free.append(free)

        self.free_rects = new_free

    def _prune_free_rects(self):
        # Remove any free rect that is completely contained in another
        pruned: List[RectNode] = []
        for i, r1 in enumerate(self.free_rects):
            is_contained = False
            for j, r2 in enumerate(self.free_rects):
                if i != j and r2.contains(r1):
                    is_contained = True
                    break
            if not is_contained:
                pruned.append(r1)
        self.free_rects = pruned


class TextureAtlasEngine:
    """
    Engine managing texture atlas layout packing, image blitting, and Flame metadata export.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else (OUTPUT_DIR / "atlases")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata."""
        return {
            "name": "Texture Atlas Generator",
            "version": ENGINE_VERSION,
            "offline": True,
            "packing_algorithm": "MaxRects (Best-Short-Side-Fit)",
            "capabilities": [
                "Rectangle packing with configurable padding and spacing",
                "Power-of-two square or rectangular textures",
                "Lossless RGBA composition with transparency retention",
                "Category-based asset clustering",
                "Flame-ready JSON sprite atlas metadata export",
            ],
        }

    def generate_atlas(
        self,
        atlas_name: str,
        asset_items: List[Dict[str, Any]],
        max_width: int = 2048,
        max_height: int = 2048,
        spacing: int = 2,
        padding: int = 2,
        power_of_two: bool = True,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Pack sprites into a single texture atlas.
        asset_items: List of dicts with keys: 'path', 'name' (optional), 'source_id' (optional).
        Returns telemetry dictionary containing atlas image path, metadata path, packed items, and efficiency.
        """
        dest_dir = Path(output_dir) if output_dir else self.output_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        clean_name = atlas_name.lower().replace(" ", "_")
        if not clean_name.endswith("_atlas"):
            clean_name = f"{clean_name}_atlas"

        # 1. Load image dimensions and sort by descending height/area for packing optimality
        items_to_pack = []
        for idx, item in enumerate(asset_items):
            p = Path(item["path"]).resolve()
            if not p.exists():
                continue

            with Image.open(str(p)) as im:
                w, h = im.size

            sprite_name = item.get("name") or p.stem
            items_to_pack.append({
                "source_id": item.get("source_id"),
                "path": str(p),
                "name": sprite_name,
                "width": w,
                "height": h,
                "area": w * h,
                "index": idx,
            })

        # Sort descending by height, then area
        items_to_pack.sort(key=lambda x: (x["height"], x["area"]), reverse=True)

        # 2. Determine Atlas Dimensions
        atlas_w = max_width
        atlas_h = max_height
        if power_of_two:
            atlas_w = 2 ** math.ceil(math.log2(max_width))
            atlas_h = 2 ** math.ceil(math.log2(max_height))

        packer = MaxRectsPacker(atlas_w, atlas_h, spacing=spacing, padding=padding)

        packed_entries = []
        unpacked_entries = []
        used_pixels = 0

        # 3. Pack Sprites
        for it in items_to_pack:
            pos = packer.pack(it["width"], it["height"])
            if pos is not None:
                px, py = pos
                packed_entries.append({
                    "source_id": it["source_id"],
                    "path": it["path"],
                    "name": it["name"],
                    "x": px,
                    "y": py,
                    "width": it["width"],
                    "height": it["height"],
                    "is_rotated": False,
                })
                used_pixels += (it["width"] * it["height"])
            else:
                unpacked_entries.append(it)

        # 4. Composite Sprites onto Transparent Canvas
        atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))

        for entry in packed_entries:
            with Image.open(entry["path"]) as src_im:
                rgba_im = src_im.convert("RGBA") if src_im.mode != "RGBA" else src_im
                atlas_img.paste(rgba_im, (entry["x"], entry["y"]), mask=rgba_im)

        # 5. Save Atlas PNG and Metadata JSON
        out_image_path = dest_dir / f"{clean_name}.png"
        out_meta_path = dest_dir / f"{clean_name}.json"

        atlas_img.save(str(out_image_path), format="PNG", optimize=True)

        total_pixels = atlas_w * atlas_h
        packing_efficiency = round((used_pixels / max(1, total_pixels)) * 100.0, 1)
        unused_pct = round(100.0 - packing_efficiency, 1)

        # Build Flame-compatible metadata
        metadata = {
            "generator": "Construction Asset Processor — Texture Atlas Engine",
            "format_version": "1.0.0",
            "atlas": {
                "name": clean_name,
                "image_file": out_image_path.name,
                "width": atlas_w,
                "height": atlas_h,
                "sprite_count": len(packed_entries),
                "packing_efficiency_pct": packing_efficiency,
                "spacing": spacing,
                "padding": padding,
            },
            "sprites": {},
        }

        for e in packed_entries:
            metadata["sprites"][e["name"]] = {
                "x": e["x"],
                "y": e["y"],
                "width": e["width"],
                "height": e["height"],
                "source_file": Path(e["path"]).name,
            }

        with open(out_meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        telemetry = {
            "atlas_name": clean_name,
            "image_path": str(out_image_path.resolve()),
            "metadata_path": str(out_meta_path.resolve()),
            "width": atlas_w,
            "height": atlas_h,
            "total_sprites": len(asset_items),
            "packed_count": len(packed_entries),
            "unpacked_count": len(unpacked_entries),
            "packed_entries": packed_entries,
            "unpacked_entries": unpacked_entries,
            "packing_efficiency": packing_efficiency,
            "unused_percentage": unused_pct,
        }

        logger.info(
            "Atlas '%s' packed: %d/%d sprites (%0.1f%% efficiency, %dx%d)",
            clean_name, len(packed_entries), len(asset_items), packing_efficiency, atlas_w, atlas_h
        )

        return telemetry

    def pack_sprites_into_atlas(
        self,
        sprites: List[Dict[str, Any]],
        output_image_path: Union[str, Path],
        output_json_path: Union[str, Path],
        max_width: int = 2048,
        max_height: int = 2048,
        padding: int = 2,
        spacing: int = 2,
        force_power_of_two: bool = True,
    ) -> Dict[str, Any]:
        """Convenience wrapper packing sprites into designated image & JSON files."""
        out_img = Path(output_image_path).resolve()
        out_json = Path(output_json_path).resolve()
        out_img.parent.mkdir(parents=True, exist_ok=True)
        out_json.parent.mkdir(parents=True, exist_ok=True)

        atlas_name = out_img.stem.replace("_atlas", "")
        res = self.generate_atlas(
            atlas_name=atlas_name,
            asset_items=sprites,
            max_width=max_width,
            max_height=max_height,
            spacing=spacing,
            padding=padding,
            power_of_two=force_power_of_two,
            output_dir=out_img.parent,
        )

        generated_img = Path(res["image_path"])
        generated_json = Path(res["metadata_path"])
        if generated_img != out_img and generated_img.exists():
            shutil.copy2(str(generated_img), str(out_img))
        if generated_json != out_json and generated_json.exists():
            shutil.copy2(str(generated_json), str(out_json))

        # Build Flame frames metadata format as well into out_json
        flame_meta = {
            "meta": {
                "app": "Construction Asset Processor",
                "version": "1.0.0",
                "target_engine": "Flame",
                "image": out_img.name,
                "size": {"w": res["width"], "h": res["height"]},
                "scale": "1",
            },
            "frames": {},
        }
        for e in res.get("packed_entries", []):
            flame_meta["frames"][e["name"]] = {
                "frame": {"x": e["x"], "y": e["y"], "w": e["width"], "h": e["height"]},
                "rotated": e.get("is_rotated", False),
                "trimmed": False,
                "spriteSourceSize": {"x": 0, "y": 0, "w": e["width"], "h": e["height"]},
                "sourceSize": {"w": e["width"], "h": e["height"]},
            }

        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(flame_meta, f, indent=2)

        return {
            "success": True,
            "output_image_path": str(out_img),
            "output_json_path": str(out_json),
            "atlas_width": res["width"],
            "atlas_height": res["height"],
            "packed_count": res["packed_count"],
            "total_count": len(sprites),
            "efficiency_percent": res["packing_efficiency"],
            "unused_area_percent": res["unused_percentage"],
            "sprites": [
                {"name": e["name"], "x": e["x"], "y": e["y"], "w": e["width"], "h": e["height"], "id": e.get("source_id")}
                for e in res.get("packed_entries", [])
            ],
        }


# Global TextureAtlasEngine singleton
texture_atlas_engine = TextureAtlasEngine()
