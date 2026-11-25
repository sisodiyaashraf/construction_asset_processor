"""
Excavator Preparation Engine (Stage 13)
Construction Asset Processor

Provides:
1. Source image SHA-256 integrity verification (ensures source files remain untouched).
2. White background detection with adjustable color tolerance.
3. High-precision background removal using OpenCV GrabCut + color-distance segmentation.
4. Interactive brush masking (FG/BG strokes) & polygon lasso support with Undo/Redo stack.
5. Edge refinement and diagnostic quality warnings (halos, holes, missing mechanical edges).
"""

from __future__ import annotations

import copy
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.config import OUTPUT_DIR, ROOT_DIR

logger = logging.getLogger("AssetProcessor.ExcavatorPrepEngine")


def compute_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 hex digest of a file to verify integrity."""
    p = Path(file_path)
    if not p.is_file():
        return ""
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class MaskHistoryManager:
    """Maintains an undo/redo stack for GrabCut / user mask arrays."""

    def __init__(self, max_depth: int = 25):
        self.max_depth = max_depth
        self.undo_stack: List[np.ndarray] = []
        self.redo_stack: List[np.ndarray] = []

    def push(self, mask: np.ndarray) -> None:
        """Push a copy of the mask onto the undo stack and clear redo."""
        self.undo_stack.append(mask.copy())
        if len(self.undo_stack) > self.max_depth:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self, current_mask: np.ndarray) -> Optional[np.ndarray]:
        """Revert to previous mask state."""
        if not self.undo_stack:
            return None
        self.redo_stack.append(current_mask.copy())
        return self.undo_stack.pop()

    def redo(self, current_mask: np.ndarray) -> Optional[np.ndarray]:
        """Re-apply undone mask state."""
        if not self.redo_stack:
            return None
        self.undo_stack.append(current_mask.copy())
        return self.redo_stack.pop()

    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()


class ExcavatorPrepEngine:
    """Core computer-vision engine for Stage 13 asset preparation."""

    def __init__(self):
        self.output_dir = OUTPUT_DIR / "prepared_sprites"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def verify_source_integrity(source_path: Path | str, expected_hash: str) -> bool:
        """
        Verify that original source file has not been altered.
        Returns True if current SHA-256 matches expected_hash.
        """
        p = Path(source_path)
        if not p.is_file() or not expected_hash:
            return False
        current_hash = compute_sha256(p)
        return current_hash.lower() == expected_hash.lower()

    @staticmethod
    def detect_white_background(
        img_bgr: np.ndarray,
        tolerance: int = 25
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Detect whether an image has an opaque white or near-white background.
        
        Args:
            img_bgr: OpenCV BGR image array.
            tolerance: Color distance threshold from pure white (255, 255, 255).
                       Values >= (255 - tolerance) are considered white.
        
        Returns:
            Tuple of (is_white_bg, confidence_score_0_to_1, details_dict).
        """
        h, w = img_bgr.shape[:2]
        border_size = max(2, min(15, h // 25, w // 25))

        top = img_bgr[:border_size, :]
        bottom = img_bgr[h - border_size:, :]
        left = img_bgr[:, :border_size]
        right = img_bgr[:, w - border_size:]

        border_pixels = np.vstack([
            top.reshape(-1, 3),
            bottom.reshape(-1, 3),
            left.reshape(-1, 3),
            right.reshape(-1, 3)
        ])

        # Convert to RGB for intuitive thresholding
        border_rgb = border_pixels[:, ::-1]
        mean_rgb = np.mean(border_rgb, axis=0)
        std_rgb = np.std(border_rgb, axis=0)

        # White threshold: each channel >= 255 - tolerance
        min_threshold = max(200, 255 - tolerance)
        white_mask = (border_rgb[:, 0] >= min_threshold) & \
                     (border_rgb[:, 1] >= min_threshold) & \
                     (border_rgb[:, 2] >= min_threshold)
        white_pixel_ratio = float(np.mean(white_mask))

        # Check corner pixels specifically (often solid background)
        corner_box = min(20, h // 10, w // 10)
        c_tl = img_bgr[:corner_box, :corner_box]
        c_tr = img_bgr[:corner_box, w - corner_box:]
        c_bl = img_bgr[h - corner_box:, :corner_box]
        c_br = img_bgr[h - corner_box:, w - corner_box:]

        corners = np.vstack([
            c_tl.reshape(-1, 3),
            c_tr.reshape(-1, 3),
            c_bl.reshape(-1, 3),
            c_br.reshape(-1, 3)
        ])[:, ::-1]
        corner_white_ratio = float(np.mean(
            (corners[:, 0] >= min_threshold) &
            (corners[:, 1] >= min_threshold) &
            (corners[:, 2] >= min_threshold)
        ))

        is_white_bg = white_pixel_ratio > 0.65 or corner_white_ratio > 0.85
        confidence = round((white_pixel_ratio * 0.6 + corner_white_ratio * 0.4), 3)

        details = {
            "white_pixel_ratio": round(white_pixel_ratio, 3),
            "corner_white_ratio": round(corner_white_ratio, 3),
            "mean_border_rgb": [round(float(c), 1) for c in mean_rgb],
            "std_border_rgb": [round(float(c), 1) for c in std_rgb],
            "min_threshold": min_threshold,
            "border_size": border_size,
        }
        return is_white_bg, confidence, details

    def remove_background(
        self,
        input_path: Path | str,
        output_path: Optional[Path | str] = None,
        color_tolerance: int = 25,
        grabcut_iterations: int = 3,
        user_mask: Optional[np.ndarray] = None,
        fg_strokes: Optional[List[Dict[str, Any]]] = None,
        bg_strokes: Optional[List[Dict[str, Any]]] = None,
        lasso_points: Optional[List[Tuple[int, int]]] = None,
        lasso_mode: str = "foreground",  # "foreground" or "background"
        feather_radius: int = 2,
        cancel_check: Optional[Any] = None,
    ) -> Tuple[bool, Optional[np.ndarray], Dict[str, Any], str]:
        """
        Non-destructive background removal using GrabCut + Color-Distance Segmentation.
        
        Args:
            input_path: Source image path.
            output_path: Optional destination path to write RGBA PNG working copy.
            color_tolerance: White/near-white color tolerance threshold (10-60).
            grabcut_iterations: Number of GrabCut refinement iterations.
            user_mask: Optional pre-existing OpenCV GrabCut mask array (values GC_BGD, GC_FGD, etc.).
            fg_strokes: List of foreground brush strokes [{'points': [(x,y)], 'radius': r}].
            bg_strokes: List of background brush strokes [{'points': [(x,y)], 'radius': r}].
            lasso_points: List of (x, y) vertices defining a closed polygon region.
            lasso_mode: Whether lasso marks "foreground" or "background".
            feather_radius: Radius for edge anti-aliasing / smoothing (1-5).
            
        Returns:
            Tuple of (success, final_rgba_array, quality_diagnostics, message).
        """
        try:
            in_p = Path(input_path).resolve()
            if not in_p.is_file():
                return False, None, {}, f"Source file does not exist: {in_p}"

            img_bgr = cv2.imread(str(in_p))
            if img_bgr is None:
                return False, None, {}, f"Failed to decode image: {in_p.name}"

            h, w = img_bgr.shape[:2]

            # 1. Initialize or clone GrabCut mask
            if user_mask is not None and user_mask.shape == (h, w):
                mask = user_mask.copy()
            else:
                mask = np.zeros((h, w), dtype=np.uint8)
                # Outer perimeter is definite background
                border = max(2, min(10, h // 30, w // 30))
                mask[:] = cv2.GC_PR_FGD
                mask[:border, :] = cv2.GC_BGD
                mask[h - border:, :] = cv2.GC_BGD
                mask[:, :border] = cv2.GC_BGD
                mask[:, w - border:] = cv2.GC_BGD

            # 2. Color-distance seeding from white / light border
            min_threshold = max(200, 255 - color_tolerance)
            rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            white_pixels = (
                (rgb[:, :, 0] >= min_threshold) &
                (rgb[:, :, 1] >= min_threshold) &
                (rgb[:, :, 2] >= min_threshold)
            )

            # Mark perimeter white pixels as definite background
            # But do NOT mark interior white pixels immediately as definite background,
            # because excavator surfaces, reflections, or cabin glass might be white!
            border_margin = max(4, min(20, h // 20, w // 20))
            perimeter_mask = np.zeros((h, w), dtype=bool)
            perimeter_mask[:border_margin, :] = True
            perimeter_mask[h - border_margin:, :] = True
            perimeter_mask[:, :border_margin] = True
            perimeter_mask[:, w - border_margin:] = True

            # Connected components of white connected to perimeter are definite background
            white_uint8 = white_pixels.astype(np.uint8) * 255
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(white_uint8, connectivity=8)
            for i in range(1, num_labels):
                component_mask = (labels == i)
                if np.any(component_mask & perimeter_mask):
                    mask[component_mask] = cv2.GC_BGD
                else:
                    # Interior white regions get PR_BGD (probable background) rather than definite background
                    # so GrabCut can keep them if color/contrast matches machinery!
                    mask[component_mask & (mask != cv2.GC_FGD)] = cv2.GC_PR_BGD

            # 3. Apply User Brush Strokes
            if fg_strokes:
                for stroke in fg_strokes:
                    radius = stroke.get("radius", 15)
                    pts = stroke.get("points", [])
                    for pt in pts:
                        cv2.circle(mask, (int(pt[0]), int(pt[1])), int(radius), cv2.GC_FGD, -1)
                    if len(pts) > 1:
                        for p1, p2 in zip(pts[:-1], pts[1:]):
                            cv2.line(mask, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), cv2.GC_FGD, int(radius * 2))

            if bg_strokes:
                for stroke in bg_strokes:
                    radius = stroke.get("radius", 15)
                    pts = stroke.get("points", [])
                    for pt in pts:
                        cv2.circle(mask, (int(pt[0]), int(pt[1])), int(radius), cv2.GC_BGD, -1)
                    if len(pts) > 1:
                        for p1, p2 in zip(pts[:-1], pts[1:]):
                            cv2.line(mask, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), cv2.GC_BGD, int(radius * 2))

            # 4. Apply Polygon Lasso Mask
            if lasso_points and len(lasso_points) >= 3:
                poly_arr = np.array(lasso_points, dtype=np.int32).reshape((-1, 1, 2))
                fill_val = cv2.GC_FGD if lasso_mode == "foreground" else cv2.GC_BGD
                cv2.fillPoly(mask, [poly_arr], fill_val)

            # 5. Run GrabCut refinement if there is both foreground and background
            has_fg = np.any((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD))
            has_bg = np.any((mask == cv2.GC_BGD) | (mask == cv2.GC_PR_BGD))

            if has_fg and has_bg and grabcut_iterations > 0:
                bgd_model = np.zeros((1, 65), np.float64)
                fgd_model = np.zeros((1, 65), np.float64)
                mode = cv2.GC_INIT_WITH_MASK
                for it in range(grabcut_iterations):
                    if cancel_check and cancel_check():
                        return False, None, {}, "Operation cancelled by user."
                    try:
                        cv2.grabCut(img_bgr, mask, None, bgd_model, fgd_model, 1, mode)
                        mode = cv2.GC_EVAL
                    except Exception as e:
                        logger.warning("GrabCut refinement iteration %d failed: %s", it, e)
                        break

                if cancel_check and cancel_check():
                    return False, None, {}, "Operation cancelled by user."

            # 6. Extract Alpha Channel (FG = 1 or 3)
            alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

            # 7. Edge Smoothing and Anti-Aliasing
            if feather_radius > 0:
                k_size = feather_radius * 2 + 1
                alpha_feathered = cv2.GaussianBlur(alpha, (k_size, k_size), 0)
                # Keep definite foreground unfeathered internally
                alpha = np.where(mask == cv2.GC_FGD, 255, alpha_feathered)

            # 8. Assemble 4-channel RGBA array
            rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGBA)
            rgba[:, :, 3] = alpha

            # 9. Diagnostic Quality Analysis
            quality_diag = self._evaluate_cutout_quality(img_bgr, alpha, h, w)

            # 10. Write output file if path provided
            if output_path:
                out_p = Path(output_path).resolve()
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_pil = Image.fromarray(rgba)
                out_pil.save(out_p, format="PNG", optimize=True)

            return True, rgba, quality_diag, "Background removed successfully."

        except Exception as e:
            logger.error("Background removal error: %s", e, exc_info=True)
            return False, None, {}, f"Background removal failed: {str(e)}"

    @staticmethod
    def _evaluate_cutout_quality(
        orig_bgr: np.ndarray,
        alpha: np.ndarray,
        h: int,
        w: int
    ) -> Dict[str, Any]:
        """
        Evaluate edge quality, white halos, holes, and mechanical edge continuity.
        Returns detailed diagnostic dictionary and warning flags.
        """
        total_pixels = h * w
        fg_pixels = int(np.sum(alpha > 20))
        fg_ratio = fg_pixels / total_pixels if total_pixels > 0 else 0.0

        warnings = []

        # 1. Excessive Foreground Removal Warning
        excessive_removal = fg_ratio < 0.03
        if excessive_removal:
            warnings.append("Excessive foreground removal: foreground is less than 3% of canvas area.")

        # 2. Barely Removed Background Warning
        barely_removed = fg_ratio > 0.97
        if barely_removed:
            warnings.append("Barely any background removed: foreground exceeds 97% of canvas area.")

        # 3. White Halo Detection
        # Check transition edge pixels (10 < alpha < 245) for high brightness
        edge_mask = (alpha > 15) & (alpha < 240)
        halo_count = 0
        halo_ratio = 0.0
        if np.any(edge_mask):
            rgb = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2RGB)
            edge_rgb = rgb[edge_mask]
            bright_edges = np.all(edge_rgb >= 235, axis=1)
            halo_count = int(np.sum(bright_edges))
            halo_ratio = halo_count / len(edge_rgb) if len(edge_rgb) > 0 else 0.0

        white_halo_detected = halo_ratio > 0.25 and halo_count > 100
        if white_halo_detected:
            warnings.append(f"Possible white halo detected along edges ({halo_ratio * 100:.1f}% bright transition pixels).")

        # 4. Unwanted Transparent Holes Detection
        # Dilate alpha and check for small closed 0-alpha regions inside solid foreground
        closed_fg = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        diff_holes = (closed_fg > 200) & (alpha == 0)
        hole_pixels = int(np.sum(diff_holes))
        has_holes = hole_pixels > 300
        if has_holes:
            warnings.append(f"Unwanted transparent holes detected ({hole_pixels} enclosed missing pixels).")

        # 5. Missing Mechanical Edges (Thin lines continuity)
        # Apply Canny to original and check if prominent edges were wiped out
        canny = cv2.Canny(orig_bgr, 50, 150)
        edge_lost = np.sum((canny > 0) & (alpha == 0)) / np.sum(canny > 0) if np.sum(canny > 0) > 0 else 0.0
        missing_edges = edge_lost > 0.40 and not excessive_removal
        if missing_edges:
            warnings.append("Potential loss of fine mechanical edges (rods, bucket teeth, cables).")

        # Overall Status
        if warnings:
            quality_status = "Warning" if len(warnings) <= 2 else "Fail"
        else:
            quality_status = "Pass"

        return {
            "quality_status": str(quality_status),
            "foreground_ratio": float(round(fg_ratio, 3)),
            "foreground_pixels": int(fg_pixels),
            "total_pixels": int(total_pixels),
            "white_halo_detected": bool(white_halo_detected),
            "halo_pixel_ratio": float(round(halo_ratio, 3)),
            "unwanted_holes_detected": bool(has_holes),
            "hole_pixels": int(hole_pixels),
            "missing_edges_detected": bool(missing_edges),
            "warnings": [str(w) for w in warnings],
        }
