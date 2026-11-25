"""
Excavator Component Extractor & Kinematic Pivot Manager (Stage 13)
Construction Asset Processor

Supports:
1. Cropping individual components from full images (Rectangle, Polygon, Freehand Lasso).
2. Clean transparent canvas output preserving pixel-level alpha channels.
3. Component type taxonomy & temporary full-machine preservation.
4. Visual kinematic pivot anchor positioning (normalized 0.0-1.0 and pixel coordinates).
5. Comprehensive JSON metadata generation for Flutter + Flame game integration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.config import OUTPUT_DIR, ROOT_DIR
from core.excavator_prep_engine import compute_sha256

logger = logging.getLogger("AssetProcessor.ExcavatorComponentExtractor")

# Canonical Component Types
COMPONENT_TYPES = [
    "undercarriage",
    "chassis",
    "cabin",
    "boom",
    "stick",
    "bucket",
    "hydraulic_cylinder",
    "hydraulic_rod",
    "background",
    "terrain",
    "complete_excavator",
    "other",
]

# Kinematic Pivot Presets (normalized 0.0 - 1.0)
PIVOT_PRESETS: Dict[str, Tuple[float, float, str]] = {
    "center": (0.50, 0.50, "Center anchor (0.5, 0.5)"),
    "bottom_center": (0.50, 1.00, "Ground contact / base anchor (0.5, 1.0)"),
    "boom_base": (0.15, 0.85, "Boom base pivot on chassis (0.15, 0.85)"),
    "boom_to_stick": (0.85, 0.15, "Boom tip articulation to stick (0.85, 0.15)"),
    "stick_to_bucket": (0.85, 0.85, "Stick end articulation to bucket (0.85, 0.85)"),
    "cabin_rotation": (0.50, 0.90, "Cabin slewing ring pivot (0.5, 0.9)"),
    "undercarriage_ground": (0.50, 1.00, "Tracks ground contact line (0.5, 1.0)"),
    "cylinder_attachment": (0.10, 0.50, "Hydraulic cylinder pin pivot (0.1, 0.5)"),
}


class ExcavatorComponentExtractor:
    """Manages sprite cropping, transparent canvas assembly, and kinematic metadata."""

    def __init__(self):
        self.output_components_dir = OUTPUT_DIR / "prepared_sprites" / "components"
        self.output_components_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir = OUTPUT_DIR / "prepared_sprites" / "metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    def crop_component_rect(
        self,
        source_image: np.ndarray,
        bbox: Tuple[int, int, int, int],  # x, y, w, h
        padding: int = 4
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """
        Crop rectangular region from source RGBA/RGB image with padding.
        Returns (cropped_array, adjusted_bbox).
        """
        h, w = source_image.shape[:2]
        bx, by, bw, bh = bbox

        # Apply padding clamped to image bounds
        x1 = max(0, bx - padding)
        y1 = max(0, by - padding)
        x2 = min(w, bx + bw + padding)
        y2 = min(h, by + bh + padding)

        cropped = source_image[y1:y2, x1:x2].copy()
        actual_bbox = (x1, y1, x2 - x1, y2 - y1)
        return cropped, actual_bbox

    def crop_component_polygon(
        self,
        source_image: np.ndarray,
        polygon_points: List[Tuple[int, int]],
        padding: int = 4
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """
        Crop irregular polygon / lasso selection from source image onto a transparent canvas.
        Pixels outside the polygon are made completely transparent (alpha = 0).
        """
        h, w = source_image.shape[:2]
        pts = np.array(polygon_points, dtype=np.int32)

        # Get bounding box of polygon
        bx, by, bw, bh = cv2.boundingRect(pts)
        x1 = max(0, bx - padding)
        y1 = max(0, by - padding)
        x2 = min(w, bx + bw + padding)
        y2 = min(h, by + bh + padding)

        # Ensure RGBA image
        if source_image.shape[2] == 3:
            rgba = cv2.cvtColor(source_image, cv2.COLOR_RGB2RGBA)
        else:
            rgba = source_image.copy()

        # Shift polygon points to cropped sub-canvas
        shifted_pts = pts - np.array([x1, y1])

        # Sub-region crop
        crop_h = y2 - y1
        crop_w = x2 - x1
        sub_img = rgba[y1:y2, x1:x2].copy()

        # Create polygon mask
        poly_mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
        cv2.fillPoly(poly_mask, [shifted_pts], 255)

        # Multiply alpha channel by polygon mask
        sub_img[:, :, 3] = cv2.bitwise_and(sub_img[:, :, 3], poly_mask)

        actual_bbox = (x1, y1, crop_w, crop_h)
        return sub_img, actual_bbox

    def save_component_sprite(
        self,
        sprite_rgba: np.ndarray,
        component_type: str,
        asset_id: int,
        custom_name: str = "",
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Save extracted component sprite as a lossless PNG file.
        Uses clean standardized snake_case naming.
        """
        dest_dir = output_dir or self.output_components_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        prefix = custom_name.strip() if custom_name.strip() else f"excavator_{component_type}"
        clean_prefix = "".join(c if c.isalnum() or c == "_" else "_" for c in prefix.lower())

        filename = f"{clean_prefix}_asset_{asset_id}.png"
        target_path = dest_dir / filename

        # Avoid collision
        idx = 1
        while target_path.exists():
            target_path = dest_dir / f"{clean_prefix}_asset_{asset_id}_{idx:02d}.png"
            idx += 1

        pil_img = Image.fromarray(sprite_rgba)
        pil_img.save(target_path, format="PNG", optimize=True)
        return target_path

    @staticmethod
    def calculate_pivot_coordinates(
        crop_w: int,
        crop_h: int,
        norm_x: float,
        norm_y: float
    ) -> Tuple[int, int]:
        """Convert normalized (0.0-1.0) pivot coordinates to exact integer pixel coordinates."""
        px = int(round(norm_x * crop_w))
        py = int(round(norm_y * crop_h))
        return min(crop_w, max(0, px)), min(crop_h, max(0, py))

    @staticmethod
    def normalize_pivot_coordinates(
        crop_w: int,
        crop_h: int,
        pixel_x: int,
        pixel_y: int
    ) -> Tuple[float, float]:
        """Convert pixel coordinates to normalized (0.0-1.0) coordinates."""
        if crop_w <= 0 or crop_h <= 0:
            return 0.5, 0.5
        norm_x = min(1.0, max(0.0, pixel_x / crop_w))
        norm_y = min(1.0, max(0.0, pixel_y / crop_h))
        return round(norm_x, 4), round(norm_y, 4)

    def generate_component_metadata(
        self,
        asset_id: int,
        component_type: str,
        component_name: str,
        source_path: Path | str,
        orig_w: int,
        orig_h: int,
        export_w: int,
        export_h: int,
        bbox: Tuple[int, int, int, int],
        pivot_norm: Tuple[float, float],
        pivot_pixel: Tuple[int, int],
        pivot_status: str,
        transparency_status: str,
        processing_method: str,
        manual_review_status: str,
        approval_status: str,
        export_path: Path | str = ""
    ) -> Dict[str, Any]:
        """
        Generate structured JSON metadata adhering to prompt specifications:
        - Asset ID
        - Component type
        - Source image path & hash
        - Original & export dimensions
        - Bounding box
        - Pivot coordinates (normalized & pixel)
        - Transparency status
        - Processing method
        - Review & approval status
        - Export path
        """
        src_p = Path(source_path)
        src_hash = compute_sha256(src_p) if src_p.is_file() else ""

        meta = {
            "asset_id": asset_id,
            "component_type": component_type,
            "component_name": component_name,
            "source_image_path": str(src_p),
            "source_image_hash": src_hash,
            "original_dimensions": {"width": orig_w, "height": orig_h},
            "export_dimensions": {"width": export_w, "height": export_h},
            "bounding_box": {
                "x": bbox[0],
                "y": bbox[1],
                "width": bbox[2],
                "height": bbox[3],
            },
            "pivot_coordinates": {
                "normalized_x": pivot_norm[0],
                "normalized_y": pivot_norm[1],
                "pixel_x": pivot_pixel[0],
                "pixel_y": pivot_pixel[1],
                "pivot_status": pivot_status,
            },
            "transparency_status": transparency_status,
            "processing_method": processing_method,
            "manual_review_status": manual_review_status,
            "approval_status": approval_status,
            "export_path": str(export_path) if export_path else "",
            "flame_component_spec": {
                "anchor": f"Anchor({pivot_norm[0]:.3f}, {pivot_norm[1]:.3f})",
                "sprite_size": [export_w, export_h],
            }
        }
        return meta

    def save_metadata_file(self, metadata: Dict[str, Any], output_path: Path) -> Path:
        """Save component metadata as human-readable JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        return output_path
