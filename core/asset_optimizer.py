"""
Asset Optimizer Engine (Stage 10)
Construction Asset Processor

Local optimization pipeline using Pillow:
- Lossless PNG optimization with compression level configuration & RGBA alpha retention.
- Lossless & Lossy WebP optimization with quality controls.
- JPEG optimization with progressive encoding.
- Dimension scaling (100%, 75%, 50%, 25%, custom) with aspect ratio lock.
- Transparent margin inspection and non-destructive trimming with pivot recalculation.
- Traceable before-and-after telemetry: dimensions, file sizes, format, and storage reduction.

Strictly non-destructive:
- Never modifies original source images.
- All optimizations operate strictly on copies or exported outputs.
- Never sacrifices visible quality silently.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from PIL import Image

from app.config import OUTPUT_OPTIMIZED_DIR

logger = logging.getLogger("AssetProcessor.AssetOptimizer")

ENGINE_VERSION = "1.0.0"

SUPPORTED_OPTIMIZE_FORMATS = {"PNG", "WEBP", "JPEG", "JPG"}
STANDARD_SCALES = [1.0, 0.75, 0.5, 0.25]


class AssetOptimizer:
    """
    Production image optimizer transforming approved game assets into
    clean, memory-efficient copies for mobile game integration.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_OPTIMIZED_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_optimizer_info(self) -> Dict[str, Any]:
        """Return engine metadata and local processing capabilities."""
        return {
            "name": "Asset Optimization Engine",
            "version": ENGINE_VERSION,
            "offline": True,
            "formats": ["PNG (Lossless)", "WebP (Lossless & Lossy)", "JPEG (Progressive)"],
            "capabilities": [
                "Lossless PNG compression with full alpha preservation",
                "WebP lossy/lossless conversions with configurable quality",
                "High-fidelity Lanczos downscaling with aspect-ratio locking",
                "Transparent margin analysis & trimming with pivot adjustment",
                "Before/after size and dimension telemetry",
            ],
        }

    # -------------------------------------------------------------------------
    # Transparent Margin Analysis & Trimming
    # -------------------------------------------------------------------------

    def analyze_transparent_margins(
        self,
        image_input: Union[str, Path, Image.Image],
        alpha_threshold: int = 5,
    ) -> Dict[str, Any]:
        """
        Inspect empty transparent padding around non-transparent pixel content.
        Returns content bounding box, margins on 4 sides, and crop recommendation.
        Never alters source pixels.
        """
        if isinstance(image_input, (str, Path)):
            img = Image.open(str(image_input))
            should_close = True
        else:
            img = image_input
            should_close = False

        try:
            w, h = img.size
            if img.mode not in ("RGBA", "LA") and not (img.mode == "P" and "transparency" in img.info):
                # Image has no alpha channel — entire image is content
                return {
                    "has_alpha": False,
                    "has_empty_margins": False,
                    "image_width": w,
                    "image_height": h,
                    "content_bounds": (0, 0, w, h),
                    "content_width": w,
                    "content_height": h,
                    "margin_left": 0,
                    "margin_top": 0,
                    "margin_right": 0,
                    "margin_bottom": 0,
                    "wasted_pixel_pct": 0.0,
                }

            # Convert to RGBA numpy array to inspect alpha plane
            img_rgba = img.convert("RGBA") if img.mode != "RGBA" else img
            alpha_arr = np.array(img_rgba)[:, :, 3]

            # Find pixels with opacity above threshold
            non_empty_indices = np.where(alpha_arr > alpha_threshold)
            if len(non_empty_indices[0]) == 0 or len(non_empty_indices[1]) == 0:
                # Fully transparent image
                return {
                    "has_alpha": True,
                    "has_empty_margins": True,
                    "image_width": w,
                    "image_height": h,
                    "content_bounds": (0, 0, 0, 0),
                    "content_width": 0,
                    "content_height": 0,
                    "margin_left": w,
                    "margin_top": h,
                    "margin_right": 0,
                    "margin_bottom": 0,
                    "wasted_pixel_pct": 100.0,
                }

            min_y = int(np.min(non_empty_indices[0]))
            max_y = int(np.max(non_empty_indices[0])) + 1
            min_x = int(np.min(non_empty_indices[1]))
            max_x = int(np.max(non_empty_indices[1])) + 1

            margin_left = min_x
            margin_top = min_y
            margin_right = w - max_x
            margin_bottom = h - max_y

            content_w = max_x - min_x
            content_h = max_y - min_y

            total_pixels = w * h
            content_pixels = content_w * content_h
            wasted_pixel_pct = round(max(0.0, (1.0 - (content_pixels / max(1, total_pixels)))) * 100.0, 1)

            has_margins = (margin_left > 0 or margin_top > 0 or margin_right > 0 or margin_bottom > 0)

            return {
                "has_alpha": True,
                "has_empty_margins": has_margins,
                "image_width": w,
                "image_height": h,
                "content_bounds": (min_x, min_y, max_x, max_y),
                "content_width": content_w,
                "content_height": content_h,
                "margin_left": margin_left,
                "margin_top": margin_top,
                "margin_right": margin_right,
                "margin_bottom": margin_bottom,
                "wasted_pixel_pct": wasted_pixel_pct,
            }
        finally:
            if should_close:
                img.close()

    def trim_transparent_margins(
        self,
        image_input: Union[str, Path, Image.Image],
        padding: int = 0,
        pivot: Tuple[float, float] = (0.5, 0.5),
        alpha_threshold: int = 5,
    ) -> Tuple[Image.Image, Tuple[float, float], Dict[str, Any]]:
        """
        Crop transparent margins from an image copy and recalculate pivot point.
        Returns: (cropped_img, (new_pivot_x, new_pivot_y), analysis_meta)
        Never touches the original image file.
        """
        if isinstance(image_input, (str, Path)):
            src_img = Image.open(str(image_input))
        else:
            src_img = image_input.copy()

        analysis = self.analyze_transparent_margins(src_img, alpha_threshold=alpha_threshold)
        if not analysis["has_empty_margins"] or analysis["content_width"] <= 0:
            return src_img, pivot, analysis

        min_x, min_y, max_x, max_y = analysis["content_bounds"]
        orig_w, orig_h = src_img.size

        # Apply user padding
        pad = max(0, padding)
        crop_x1 = max(0, min_x - pad)
        crop_y1 = max(0, min_y - pad)
        crop_x2 = min(orig_w, max_x + pad)
        crop_y2 = min(orig_h, max_y + pad)

        cropped = src_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        new_w, new_h = cropped.size

        # Recalculate normalized pivot point relative to cropped boundaries
        orig_px_abs = pivot[0] * orig_w
        orig_py_abs = pivot[1] * orig_h

        new_px_rel = orig_px_abs - crop_x1
        new_py_rel = orig_py_abs - crop_y1

        new_pivot_x = round(max(0.0, min(1.0, new_px_rel / max(1, new_w))), 4)
        new_pivot_y = round(max(0.0, min(1.0, new_py_rel / max(1, new_h))), 4)

        analysis["crop_applied"] = (crop_x1, crop_y1, crop_x2, crop_y2)
        analysis["new_width"] = new_w
        analysis["new_height"] = new_h
        analysis["new_pivot"] = (new_pivot_x, new_pivot_y)

        return cropped, (new_pivot_x, new_pivot_y), analysis

    # -------------------------------------------------------------------------
    # Scaling & Resizing
    # -------------------------------------------------------------------------

    def scale_image(
        self,
        img: Image.Image,
        scale: float = 1.0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        lock_aspect_ratio: bool = True,
        allow_upscale: bool = False,
    ) -> Image.Image:
        """
        Scale image using high-quality Lanczos resampling.
        Default: aspect ratio locked, no automatic upscaling.
        """
        orig_w, orig_h = img.size
        if orig_w <= 0 or orig_h <= 0:
            return img

        if target_width is not None or target_height is not None:
            tw = target_width or orig_w
            th = target_height or orig_h

            if lock_aspect_ratio:
                aspect = orig_w / float(orig_h)
                if target_width is not None and target_height is None:
                    tw = target_width
                    th = int(round(tw / aspect))
                elif target_height is not None and target_width is None:
                    th = target_height
                    tw = int(round(th * aspect))
                else:
                    scale_fit = min(tw / orig_w, th / orig_h)
                    tw = int(round(orig_w * scale_fit))
                    th = int(round(orig_h * scale_fit))

            if not allow_upscale:
                tw = min(tw, orig_w)
                th = min(th, orig_h)

            dest_w, dest_h = max(1, tw), max(1, th)
        else:
            scale = max(0.05, min(scale, 4.0 if allow_upscale else 1.0))
            if abs(scale - 1.0) < 1e-4:
                return img
            dest_w = max(1, int(round(orig_w * scale)))
            dest_h = max(1, int(round(orig_h * scale)))

        if (dest_w, dest_h) == (orig_w, orig_h):
            return img

        return img.resize((dest_w, dest_h), Image.Resampling.LANCZOS)

    # -------------------------------------------------------------------------
    # Core Optimization Execution
    # -------------------------------------------------------------------------

    def optimize_image(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        format_target: str = "PNG",
        quality: int = 90,
        lossless: bool = True,
        scale: float = 1.0,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        lock_aspect_ratio: bool = True,
        trim_margins: bool = False,
        margin_padding: int = 0,
        pivot: Tuple[float, float] = (0.5, 0.5),
        allow_upscale: bool = False,
        png_compression_level: int = 9,
    ) -> Dict[str, Any]:
        """
        Execute optimization pipeline on an image copy.
        Returns comprehensive performance and provenance telemetry.
        Never modifies the source image file.
        """
        src_path = Path(input_path).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Source asset not found: {input_path}")

        orig_file_size = src_path.stat().st_size
        format_norm = format_target.upper().replace("JPG", "JPEG")
        if format_norm not in SUPPORTED_OPTIMIZE_FORMATS:
            format_norm = "PNG"

        # Determine target file extension and path
        ext_map = {"PNG": ".png", "WEBP": ".webp", "JPEG": ".jpg"}
        ext = ext_map.get(format_norm, ".png")

        if output_path:
            out_file = Path(output_path).resolve()
        else:
            base_name = f"{src_path.stem}_opt{ext}"
            out_file = (self.output_dir / base_name).resolve()

        out_file.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(str(src_path)) as im:
            orig_w, orig_h = im.size
            orig_mode = im.mode

            # Detect alpha presence
            has_alpha = orig_mode in ("RGBA", "LA") or (orig_mode == "P" and "transparency" in im.info)
            if has_alpha and orig_mode != "RGBA":
                work_img = im.convert("RGBA")
            else:
                work_img = im.copy()

            # Optional Transparent Margin Trimming
            new_pivot = pivot
            trim_meta = {}
            if trim_margins and has_alpha:
                work_img, new_pivot, trim_meta = self.trim_transparent_margins(
                    work_img, padding=margin_padding, pivot=pivot
                )

            # Optional Dimension Scaling
            if scale != 1.0 or target_width is not None or target_height is not None:
                work_img = self.scale_image(
                    work_img,
                    scale=scale,
                    target_width=target_width,
                    target_height=target_height,
                    lock_aspect_ratio=lock_aspect_ratio,
                    allow_upscale=allow_upscale,
                )

            final_w, final_h = work_img.size

            # Save according to target format specifications
            save_kwargs = {}
            actual_lossless = False

            if format_norm == "PNG":
                actual_lossless = True
                save_kwargs = {
                    "format": "PNG",
                    "optimize": True,
                    "compress_level": max(1, min(9, png_compression_level)),
                }
                work_img.save(str(out_file), **save_kwargs)

            elif format_norm == "WEBP":
                actual_lossless = lossless
                save_kwargs = {
                    "format": "WEBP",
                    "lossless": lossless,
                    "quality": max(1, min(100, quality)),
                    "method": 6 if lossless else 4,
                }
                work_img.save(str(out_file), **save_kwargs)

            elif format_norm == "JPEG":
                actual_lossless = False
                # JPEG does not support transparency — composite over solid neutral background
                if work_img.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", work_img.size, (255, 255, 255))
                    bg.paste(work_img, mask=work_img.split()[-1])
                    jpeg_img = bg
                elif work_img.mode != "RGB":
                    jpeg_img = work_img.convert("RGB")
                else:
                    jpeg_img = work_img

                save_kwargs = {
                    "format": "JPEG",
                    "quality": max(1, min(95, quality)),
                    "optimize": True,
                    "progressive": True,
                }
                jpeg_img.save(str(out_file), **save_kwargs)

        opt_file_size = out_file.stat().st_size
        size_diff = orig_file_size - opt_file_size
        reduction_pct = round(max(0.0, (size_diff / max(1, orig_file_size))) * 100.0, 1) if size_diff > 0 else 0.0

        transparency_status = "transparent" if has_alpha and format_norm != "JPEG" else "opaque"

        telemetry = {
            "source_path": str(src_path),
            "output_path": str(out_file),
            "input_size": orig_file_size,
            "output_size": opt_file_size,
            "size_difference": size_diff,
            "reduction_percentage": reduction_pct,
            "input_dimensions": (orig_w, orig_h),
            "output_dimensions": (final_w, final_h),
            "input_format": src_path.suffix.upper().replace(".", ""),
            "output_format": format_norm,
            "is_lossless": actual_lossless,
            "transparency_status": transparency_status,
            "pivot": new_pivot,
            "trim_applied": bool(trim_meta.get("crop_applied")),
            "compression_settings": save_kwargs,
            "success": True,
            "savings_bytes": size_diff,
            "savings_percent": reduction_pct,
        }

        logger.info(
            "Optimized %s (%d bytes) -> %s (%d bytes, %0.1f%% reduction)",
            src_path.name, orig_file_size, out_file.name, opt_file_size, reduction_pct
        )

        return telemetry

    def optimize_asset(
        self,
        src_path: Union[str, Path],
        dest_path: Optional[Union[str, Path]] = None,
        target_format: str = "PNG",
        quality: int = 90,
        lossless: bool = True,
        scale: float = 1.0,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        trim_transparent_margin: bool = False,
        margin_padding: int = 0,
        **kwargs
    ) -> Dict[str, Any]:
        """Convenience wrapper for optimize_image accepting alternative keyword naming."""
        try:
            return self.optimize_image(
                input_path=src_path,
                output_path=dest_path,
                format_target=target_format,
                quality=quality,
                lossless=lossless,
                scale=scale,
                target_width=max_width,
                target_height=max_height,
                trim_margins=trim_transparent_margin,
                margin_padding=margin_padding,
                **kwargs
            )
        except Exception as e:
            logger.error("Error optimizing asset %s: %s", src_path, e)
            return {"success": False, "error": str(e)}

    def detect_transparent_margins(
        self,
        image_input: Union[str, Path, Image.Image],
        alpha_threshold: int = 5,
    ) -> Dict[str, Any]:
        """Convenience alias for analyze_transparent_margins with has_transparency key."""
        info = self.analyze_transparent_margins(image_input, alpha_threshold=alpha_threshold)
        info["has_transparency"] = info.get("has_alpha", False)
        return info


# Global AssetOptimizer singleton
asset_optimizer = AssetOptimizer()
