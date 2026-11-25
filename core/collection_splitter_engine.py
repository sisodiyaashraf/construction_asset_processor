"""
Collection Splitter & Asset Extraction Engine (Stage 8)
Construction Asset Processor

Identifies images containing multiple separate game assets, sprite sheets,
or isolated objects, allows precise region selection/editing, and exports
isolated components as clean image files linked to their source provenance.

Strictly non-destructive:
- Never modifies original source images.
- Never overwrites original files or existing extracted assets.
- Preserves full resolution and alpha transparency.
- Never automatically splits an image without user approval.
"""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.config import OUTPUT_SEPARATED_DIR
from core.database import db

logger = logging.getLogger("AssetProcessor.CollectionSplitter")

ENGINE_VERSION = "1.0.0"

# Standard composition classifications per Stage 8 specification
COMPOSITION_TYPES = [
    "Single Object",
    "Multiple Object Collection",
    "Overlapping Object Collection",
    "Sprite Sheet",
    "Animation Frame Grid",
    "Background Scene",
    "Unknown Composition",
]

# UI theme colors for composition badges
COMPOSITION_COLORS = {
    "Single Object": "#10B981",                   # Emerald Green
    "Multiple Object Collection": "#F59E0B",      # Amber
    "Overlapping Object Collection": "#EC4899",   # Pink
    "Sprite Sheet": "#3B82F6",                    # Blueprint Blue
    "Animation Frame Grid": "#8B5CF6",            # Violet
    "Background Scene": "#06B6D4",                # Cyan
    "Unknown Composition": "#9CA3AF",             # Cool Gray
}

# Standard padding options
PADDING_OPTIONS = [0, 4, 8, 16, 32]


class CollectionSplitterEngine:
    """
    Local Computer Vision composition analyzer and region extractor.
    Combines alpha transparency segmentation, border background sampling,
    connected-component analysis, and grid alignment detection.
    """

    def __init__(self):
        self._version = ENGINE_VERSION

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata and local status."""
        return {
            "name": "Local Computer Vision Collection Splitter",
            "version": self._version,
            "offline": True,
            "active_backend": "OpenCV Multi-Feature CV",
            "capabilities": [
                "Alpha-Channel Connected Components Segmentation",
                "Solid Background & Studio Backdrop Detection",
                "Grid Alignment & Uniform Frame Detection for Sprite Sheets",
                "Non-Destructive Crop with Custom Padding",
                "Source Image Provenance & Overwrite Collision Safety",
            ],
        }

    def analyze_composition(
        self, asset: Dict[str, Any]
    ) -> Tuple[str, List[Dict[str, Any]], str, str]:
        """
        Analyze image composition and propose candidate object regions.
        Does NOT alter source files on disk.
        Returns: (composition_type, candidate_regions, explanation, detection_method)
        """
        file_path = asset.get("original_path")
        if not file_path or not os.path.exists(file_path):
            return "Unknown Composition", [], "Source file not found on disk", "error_missing"

        try:
            # Safe image decode supporting Windows unicode paths
            img_array = np.fromfile(file_path, dtype=np.uint8)
            img_bgr = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)
            if img_bgr is None:
                raise ValueError("cv2.imdecode returned None")
        except Exception as read_err:
            logger.error("Failed to read image for collection analysis '%s': %s", file_path, read_err)
            return "Unknown Composition", [], f"Read error: {str(read_err)}", "error_read"

        h, w = img_bgr.shape[:2]
        # True alpha check: only consider transparent if there are actual non-opaque pixels
        has_actual_alpha = (
            img_bgr.ndim == 3 and img_bgr.shape[2] == 4 and
            np.count_nonzero(img_bgr[:, :, 3] < 240) > (w * h * 0.005)
        )

        # 1. Check if image is a full panoramic background scene
        # Full construction environment backgrounds cover almost 100% of the canvas with complex texture
        is_scene, scene_reason = self._is_full_scene_background(img_bgr, w, h, has_actual_alpha)
        if is_scene:
            return "Background Scene", [], scene_reason, "scene_detector_cv"

        # 2. Extract candidate foreground object regions
        if has_actual_alpha:
            regions, method_desc = self._segment_transparent_image(img_bgr, w, h)
        else:
            regions, method_desc = self._segment_opaque_image(img_bgr[:, :, :3], w, h)

        # 3. Classify composition based on detected regions and spatial arrangement
        comp_type, explanation = self._classify_regions(regions, w, h, has_actual_alpha, method_desc)

        return comp_type, regions, explanation, method_desc

    def analyze_image_file(
        self, file_path: str
    ) -> Tuple[str, List[Dict[str, Any]], str]:
        """Convenience method to analyze an image path directly."""
        asset = {"id": 0, "original_path": file_path, "filename": Path(file_path).name}
        comp_type, regions, explanation, _ = self.analyze_composition(asset)
        return comp_type, regions, explanation

    def _is_full_scene_background(
        self, img: np.ndarray, w: int, h: int, has_alpha: bool
    ) -> Tuple[bool, str]:
        """
        Check if the image is an intended full environmental scene / panoramic background.
        Scenes have high edge density and color variance across all 4 quadrants and borders.
        """
        if has_alpha:
            alpha = img[:, :, 3]
            non_zero_ratio = np.count_nonzero(alpha > 15) / float(w * h)
            if non_zero_ratio < 0.92:
                # Has significant transparent space, not a full opaque scene
                return False, ""

        gray = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)

        # Sample border pixels to see if edges have diverse landscape colors vs solid background
        border_pixels = np.concatenate([
            gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]
        ])
        border_std = np.std(border_pixels)

        # If border has very low std dev (< 10), it's likely a studio backdrop, not a full landscape scene
        if border_std < 12.0:
            return False, ""

        # Measure edge density across 4 quadrants
        edges = cv2.Canny(gray, 60, 150)
        mid_x = w // 2
        mid_y = h // 2
        q1 = np.count_nonzero(edges[:mid_y, :mid_x]) / float(mid_x * mid_y)
        q2 = np.count_nonzero(edges[:mid_y, mid_x:]) / float(mid_x * mid_y)
        q3 = np.count_nonzero(edges[mid_y:, :mid_x]) / float(mid_x * mid_y)
        q4 = np.count_nonzero(edges[mid_y:, mid_x:]) / float(mid_x * mid_y)

        # In a landscape scene, edges are distributed across top (sky/horizon) and bottom (ground)
        min_q = min(q1, q2, q3, q4)
        mean_q = (q1 + q2 + q3 + q4) / 4.0

        if min_q > 0.02 and mean_q > 0.05 and border_std > 22.0:
            return True, "Full panoramic construction scene / landscape with edge distribution across all quadrants"

        return False, ""

    def _segment_transparent_image(
        self, img_bgra: np.ndarray, w: int, h: int
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Segment transparent PNGs using true alpha channel connected components.
        """
        alpha = img_bgra[:, :, 3]
        _, binary = cv2.threshold(alpha, 25, 255, cv2.THRESH_BINARY)

        # Morphological close to bridge tiny internal gaps within an object
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # Connected component analysis
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(closed, connectivity=8)

        candidate_regions = []
        min_area = max(400, int((w * h) * 0.0008))
        max_area = int((w * h) * 0.98)

        for i in range(1, num_labels):  # Skip background label 0
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]
            area = stats[i, cv2.CC_STAT_AREA]

            # Filter tiny dust or full image bounding box
            if area < min_area or area > max_area:
                continue
            if bw < 20 or bh < 20:
                continue

            # Confidence score based on solidity and size
            solidity = area / float(bw * bh)
            conf = min(0.95, max(0.50, round(0.60 + 0.35 * solidity, 2)))

            candidate_regions.append({
                "x": int(x),
                "y": int(y),
                "width": int(bw),
                "height": int(bh),
                "region_type": "object",
                "confidence_score": conf,
                "source_method": "alpha_connected_components",
                "review_status": "pending",
            })

        # Merge boxes that heavily overlap
        merged = self._merge_overlapping_regions(candidate_regions, w, h)
        return merged, "alpha_connected_components"

    def _segment_opaque_image(
        self, img_bgr: np.ndarray, w: int, h: int
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Segment opaque images using border background sampling and contour analysis.
        """
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # Sample border pixels to detect solid background color
        top_border = gray[0:max(3, int(h * 0.02)), :]
        bottom_border = gray[-max(3, int(h * 0.02)):, :]
        left_border = gray[:, 0:max(3, int(w * 0.02))]
        right_border = gray[:, -max(3, int(w * 0.02)):]

        all_borders = np.concatenate([
            top_border.flatten(), bottom_border.flatten(),
            left_border.flatten(), right_border.flatten()
        ])
        bg_mean = float(np.median(all_borders))
        bg_std = float(np.std(all_borders))

        # Check if background is uniform
        is_uniform_bg = (bg_std < 18.0)

        if is_uniform_bg:
            # Difference from background color
            diff = cv2.absdiff(gray, int(bg_mean))
            thresh_val = max(18, int(bg_std * 2.5))
            _, binary = cv2.threshold(diff, thresh_val, 255, cv2.THRESH_BINARY)
            method = "opaque_uniform_backdrop_diff"
        else:
            # Adaptive thresholding and morphological gradient for non-uniform backdrops
            grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
            _, binary = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            method = "opaque_gradient_contours"

        # Morphological closing to solidify objects
        k_w = max(7, int(w * 0.01))
        k_h = max(7, int(h * 0.01))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, k_h))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidate_regions = []
        min_area = max(500, int((w * h) * 0.001))
        max_area = int((w * h) * 0.95)

        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh
            if area < min_area or area > max_area:
                continue
            if bw < 25 or bh < 25:
                continue

            conf = 0.70 if is_uniform_bg else 0.55
            candidate_regions.append({
                "x": int(x),
                "y": int(y),
                "width": int(bw),
                "height": int(bh),
                "region_type": "object",
                "confidence_score": conf,
                "source_method": method,
                "review_status": "pending",
            })

        merged = self._merge_overlapping_regions(candidate_regions, w, h)
        return merged, method

    def _merge_overlapping_regions(
        self, regions: List[Dict[str, Any]], img_w: int, img_h: int
    ) -> List[Dict[str, Any]]:
        """Merge bounding boxes that overlap by more than 40% area or are tightly enclosed."""
        if not regions:
            return []

        # Sort by area descending
        sorted_regs = sorted(regions, key=lambda r: r["width"] * r["height"], reverse=True)
        merged: List[Dict[str, Any]] = []
        used = [False] * len(sorted_regs)

        for i in range(len(sorted_regs)):
            if used[i]:
                continue
            r1 = sorted_regs[i]
            cur_x1 = r1["x"]
            cur_y1 = r1["y"]
            cur_x2 = r1["x"] + r1["width"]
            cur_y2 = r1["y"] + r1["height"]
            score = r1.get("confidence_score", 0.6)
            method = r1.get("source_method", "cv")
            used[i] = True

            changed = True
            while changed:
                changed = False
                for j in range(len(sorted_regs)):
                    if used[j]:
                        continue
                    r2 = sorted_regs[j]
                    r2_x1 = r2["x"]
                    r2_y1 = r2["y"]
                    r2_x2 = r2["x"] + r2["width"]
                    r2_y2 = r2["y"] + r2["height"]

                    # Intersection rectangle
                    ix1 = max(cur_x1, r2_x1)
                    iy1 = max(cur_y1, r2_y1)
                    ix2 = min(cur_x2, r2_x2)
                    iy2 = min(cur_y2, r2_y2)

                    if ix2 > ix1 and iy2 > iy1:
                        inter_area = (ix2 - ix1) * (iy2 - iy1)
                        r2_area = (r2_x2 - r2_x1) * (r2_y2 - r2_y1)
                        if inter_area >= 0.35 * r2_area:
                            cur_x1 = min(cur_x1, r2_x1)
                            cur_y1 = min(cur_y1, r2_y1)
                            cur_x2 = max(cur_x2, r2_x2)
                            cur_y2 = max(cur_y2, r2_y2)
                            used[j] = True
                            changed = True

            bw = cur_x2 - cur_x1
            bh = cur_y2 - cur_y1
            if bw >= 20 and bh >= 20:
                merged.append({
                    "x": cur_x1,
                    "y": cur_y1,
                    "width": bw,
                    "height": bh,
                    "region_type": "object",
                    "confidence_score": score,
                    "source_method": method,
                    "review_status": "pending",
                })

        # Sort top-to-bottom, left-to-right
        merged.sort(key=lambda r: (r["y"] // 40, r["x"]))
        return merged

    def _classify_regions(
        self, regions: List[Dict[str, Any]], w: int, h: int, has_alpha: bool, method: str
    ) -> Tuple[str, str]:
        """
        Evaluate region count, size consistency, and grid alignment
        to determine the high-level composition type.
        """
        count = len(regions)

        if count == 0:
            return "Background Scene", "Zero isolated object boundaries found; full unified canvas"

        if count == 1:
            r = regions[0]
            rel_area = (r["width"] * r["height"]) / float(w * h)
            if rel_area >= 0.88:
                return "Background Scene", "Single large region encompassing nearly 100% of canvas"
            return "Single Object", "Single isolated foreground object identified"

        # Check for Sprite Sheet or Animation Frame Grid
        # Hallmarks: >= 3 regions, uniform widths and heights, and grid row/col alignment
        if count >= 3:
            widths = [r["width"] for r in regions]
            heights = [r["height"] for r in regions]
            mean_w = np.mean(widths)
            mean_h = np.mean(heights)
            std_w = np.std(widths)
            std_h = np.std(heights)

            is_uniform_size = (std_w / max(1.0, mean_w) < 0.22) and (std_h / max(1.0, mean_h) < 0.22)

            if is_uniform_size:
                # Check grid alignment (do boxes share similar Y coordinates in rows?)
                y_coords = sorted(set(r["y"] // 25 for r in regions))
                x_coords = sorted(set(r["x"] // 25 for r in regions))
                if len(y_coords) >= 2 or len(x_coords) >= 3:
                    # Update region_type to sprite_frame
                    for idx, reg in enumerate(regions):
                        reg["region_type"] = "sprite_frame"
                    return "Sprite Sheet", f"Detected {count} uniform frames aligned in grid layout"

        # Check for Overlapping vs Multiple Object Collection
        # Check if bounding boxes are separated by clean distance
        has_touching = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                r1, r2 = regions[i], regions[j]
                # Distance between rects
                dx = max(0, max(r1["x"], r2["x"]) - min(r1["x"] + r1["width"], r2["x"] + r2["width"]))
                dy = max(0, max(r1["y"], r2["y"]) - min(r1["y"] + r1["height"], r2["y"] + r2["height"]))
                if dx == 0 and dy == 0:
                    has_touching = True
                    break
            if has_touching:
                break

        if has_touching:
            return "Overlapping Object Collection", f"Found {count} candidate objects with partial boundary contact"

        return "Multiple Object Collection", f"Found {count} distinct isolated game objects separated by background"

    def generate_sprite_grid(
        self,
        img_w: int = 0,
        img_h: int = 0,
        cols: int = 1,
        rows: int = 1,
        frame_w: int = 0,
        frame_h: int = 0,
        h_spacing: int = 0,
        v_spacing: int = 0,
        margin_x: int = 0,
        margin_y: int = 0,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Generate strict grid of animation frames for Sprite Sheet mode.
        Preserves frame order (0, 1, 2...) in row-major order.
        """
        if img_w <= 0 and "image_width" in kwargs:
            img_w = kwargs["image_width"]
        if img_h <= 0 and "image_height" in kwargs:
            img_h = kwargs["image_height"]
        if h_spacing <= 0 and "spacing_x" in kwargs:
            h_spacing = kwargs["spacing_x"]
        if v_spacing <= 0 and "spacing_y" in kwargs:
            v_spacing = kwargs["spacing_y"]

        cols = max(1, cols)
        rows = max(1, rows)

        if frame_w <= 0:
            avail_w = img_w - (2 * margin_x) - ((cols - 1) * h_spacing)
            frame_w = max(10, avail_w // cols)

        if frame_h <= 0:
            avail_h = img_h - (2 * margin_y) - ((rows - 1) * v_spacing)
            frame_h = max(10, avail_h // rows)

        frames = []
        frame_idx = 0

        for r in range(rows):
            for c in range(cols):
                fx = margin_x + c * (frame_w + h_spacing)
                fy = margin_y + r * (frame_h + v_spacing)

                # Clamp to image boundaries
                if fx + frame_w > img_w or fy + frame_h > img_h:
                    continue

                frames.append({
                    "x": int(fx),
                    "y": int(fy),
                    "width": int(frame_w),
                    "height": int(frame_h),
                    "region_type": "sprite_frame",
                    "frame_index": frame_idx,
                    "confidence_score": 1.0,
                    "source_method": "sprite_grid_generator",
                    "review_status": "approved",
                })
                frame_idx += 1

        return frames

    def extract_region(
        self,
        img_pil: Image.Image,
        x: int,
        y: int,
        w: int,
        h: int,
        padding: int = 0,
    ) -> Image.Image:
        """
        Crop an individual region from an image with optional padding.
        Clamps to image boundaries. Preserves exact pixel data and alpha channel.
        Does NOT alter colors, upscale, or remove background.
        """
        img_w, img_h = img_pil.size

        # Apply padding and clamp
        crop_x1 = max(0, x - padding)
        crop_y1 = max(0, y - padding)
        crop_x2 = min(img_w, x + w + padding)
        crop_y2 = min(img_h, y + h + padding)

        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            raise ValueError(f"Invalid crop coordinates: ({crop_x1}, {crop_y1}, {crop_x2}, {crop_y2})")

        return img_pil.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    def export_extracted_asset(
        self,
        source_asset: Optional[Dict[str, Any]] = None,
        region: Optional[Dict[str, Any]] = None,
        custom_filename: Optional[str] = None,
        padding: int = 0,
        frame_index: int = 0,
        **kwargs,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Extract an individual region and safely export to `output/separated/`.
        Guarantees zero-overwrite collision avoidance and records provenance in SQLite.
        Supports both source_asset dict or direct kwargs (cropped_img, source_asset_id, etc.).
        """
        cropped_img = kwargs.get("cropped_img")
        source_asset_id = kwargs.get("source_asset_id")
        source_region_id = kwargs.get("source_region_id")
        output_folder = kwargs.get("output_folder")
        proposed_filename = kwargs.get("proposed_filename") or custom_filename

        if source_asset is None and source_asset_id is not None:
            source_asset = db.get_asset(source_asset_id) or {
                "id": source_asset_id, "filename": "asset.png", "collection": "other_images"
            }
        elif source_asset is None:
            return False, "", {"error": "source_asset or source_asset_id required"}

        if region is None:
            region = {"id": source_region_id, "region_type": "isolated_asset"}

        try:
            # Determine output directory
            if output_folder:
                dest_dir = Path(output_folder)
            else:
                coll_name = source_asset.get("collection", "other_images")
                subfolder = "excavator" if "excavat" in coll_name.lower() else "other_images"
                if region.get("region_type") == "sprite_frame":
                    subfolder = "sprite_frames"
                dest_dir = OUTPUT_SEPARATED_DIR / subfolder

            dest_dir.mkdir(parents=True, exist_ok=True)

            # Determine standardized filename
            if proposed_filename and proposed_filename.strip():
                base_name = proposed_filename.strip()
            else:
                src_stem = Path(source_asset.get("filename", "asset.png")).stem
                if region.get("region_type") == "sprite_frame":
                    base_name = f"{src_stem}_frame_{frame_index:03d}.png"
                else:
                    base_name = f"{src_stem}_part_{frame_index + 1:02d}.png"

            # Enforce clean filename sanitization
            if not base_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                base_name += ".png"

            # Zero-overwrite collision resolution
            dest_file = dest_dir / base_name
            collision_idx = 1
            while dest_file.exists():
                stem = Path(base_name).stem
                ext = Path(base_name).suffix
                stem_clean = re.sub(r'_\d+$', '', stem)
                dest_file = dest_dir / f"{stem_clean}_{collision_idx:02d}{ext}"
                collision_idx += 1

            if cropped_img is not None:
                cropped = cropped_img
            else:
                src_path = source_asset.get("original_path")
                if not src_path or not os.path.exists(src_path):
                    return False, "", {"error": "Source file missing"}

                with Image.open(src_path) as src_img:
                    cropped = self.extract_region(
                        src_img,
                        x=region.get("x", 0),
                        y=region.get("y", 0),
                        w=region.get("width", src_img.width),
                        h=region.get("height", src_img.height),
                        padding=padding,
                    )

            # Save extracted image preserving transparency if present
            if cropped.mode in ("RGBA", "LA") or (cropped.mode == "P" and "transparency" in cropped.info):
                cropped.save(dest_file, format="PNG", optimize=True)
            elif dest_file.suffix.lower() == ".png":
                cropped.save(dest_file, format="PNG", optimize=True)
            elif dest_file.suffix.lower() == ".webp":
                cropped.save(dest_file, format="WEBP", lossless=True)
            else:
                cropped.save(dest_file, quality=95, optimize=True)

            out_w, out_h = cropped.size

            # Record provenance in SQLite
            ext_id = db.record_extracted_asset(
                source_asset_id=source_asset["id"],
                source_region_id=region.get("id"),
                output_path=str(dest_file.resolve()),
                output_filename=dest_file.name,
                width=out_w,
                height=out_h,
                frame_index=frame_index,
                padding=padding,
                export_status="exported",
            )

            meta = {
                "id": ext_id,
                "source_asset_id": source_asset["id"],
                "output_path": str(dest_file),
                "filename": dest_file.name,
                "width": out_w,
                "height": out_h,
                "frame_index": frame_index,
                "padding": padding,
            }
            return True, str(dest_file), meta

        except Exception as e:
            logger.error("Failed to export extracted asset from #%s: %s", source_asset.get("id"), e)
            return False, "", {"error": str(e)}

    def process_and_save_asset(
        self, asset: Dict[str, Any]
    ) -> Tuple[bool, str, int, List[Dict[str, Any]]]:
        """
        Execute automated composition analysis on single asset and persist results into SQLite.
        Returns: (success, composition_type, candidate_count, regions)
        """
        aid = asset["id"]
        try:
            comp_type, regions, explanation, method = self.analyze_composition(asset)
            db.save_collection_analysis_result(
                asset_id=aid,
                composition_type=comp_type,
                regions=regions,
                detection_method=method,
                explanation=explanation,
                status="success",
            )
            return True, comp_type, len(regions), regions
        except Exception as e:
            logger.error("Failed collection analysis for asset #%s: %s", aid, e)
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO collection_analysis_history
                        (asset_id, composition_type, candidate_count, detection_method, explanation, analysis_status)
                    VALUES (?, 'Unknown Composition', 0, 'error', ?, 'failed')
                """, (aid, str(e)))
                cursor.execute("""
                    UPDATE assets SET
                        splitter_analysis_status = 'failed',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (aid,))
            return False, "Unknown Composition", 0, []

    def batch_analyze(self, assets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Synchronously batch analyze a list of assets."""
        total = len(assets)
        collections = 0
        sprite_sheets = 0
        single_objs = 0
        scenes = 0
        failed = 0

        for a in assets:
            ok, comp, cnt, _ = self.process_and_save_asset(a)
            if ok:
                if comp in ("Multiple Object Collection", "Overlapping Object Collection"):
                    collections += 1
                elif comp in ("Sprite Sheet", "Animation Frame Grid"):
                    sprite_sheets += 1
                elif comp == "Single Object":
                    single_objs += 1
                elif comp == "Background Scene":
                    scenes += 1
            else:
                failed += 1

        return {
            "total": total,
            "processed": total - failed,
            "collections": collections,
            "sprite_sheets": sprite_sheets,
            "single_objects": single_objs,
            "scenes": scenes,
            "failed": failed,
        }


# Global singleton splitter engine
collection_splitter_engine = CollectionSplitterEngine()
