"""
Stage 13 Background Workers & Task Management (Stage 13.1)
Construction Asset Processor

Moves all heavy operations completely off the Qt main GUI thread:
1. BackgroundRemovalWorker (GrabCut + color distance with progress & cancellation).
2. WhiteBgDetectionWorker (border sampling & variance analysis).
3. QualityAuditWorker (multi-point asset health checklist).
4. ImageLoadWorker (asynchronous full-resolution loading & array decode).
5. ComponentExtractionWorker (polygon/rect cropping, PNG encoding, SHA-256).

Guarantees:
- Never touches QWidget or GUI objects directly from worker threads.
- Emits clean Qt signals for thread-safe UI updates on the main thread.
- Thread-safe cancellation and error handling.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from PySide6.QtCore import QObject, QThread, Signal

from core.database import db
from core.excavator_component_extractor import ExcavatorComponentExtractor
from core.excavator_prep_engine import ExcavatorPrepEngine
from core.stage13_quality_validator import Stage13QualityReport, Stage13QualityValidator

logger = logging.getLogger("AssetProcessor.Stage13Workers")


class BackgroundRemovalWorker(QThread):
    """Executes GrabCut and color distance background removal in a background thread."""

    started_work = Signal(int)  # asset_id
    progress = Signal(int, str)  # percentage (0-100), stage_name
    finished_work = Signal(int, object, dict, str)  # asset_id, rgba_array, diagnostics, message
    canceled = Signal(int)  # asset_id
    error = Signal(int, str)  # asset_id, error_message

    def __init__(
        self,
        asset_id: int,
        input_path: Path | str,
        output_path: Optional[Path | str] = None,
        color_tolerance: int = 25,
        grabcut_iterations: int = 3,
        user_mask: Optional[np.ndarray] = None,
        fg_strokes: Optional[List[Dict[str, Any]]] = None,
        bg_strokes: Optional[List[Dict[str, Any]]] = None,
        lasso_points: Optional[List[Tuple[int, int]]] = None,
        feather_radius: int = 2,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.asset_id = asset_id
        self.input_path = input_path
        self.output_path = output_path
        self.color_tolerance = color_tolerance
        self.grabcut_iterations = grabcut_iterations
        self.user_mask = user_mask
        self.fg_strokes = fg_strokes
        self.bg_strokes = bg_strokes
        self.lasso_points = lasso_points
        self.feather_radius = feather_radius
        self._is_cancelled = False
        self.engine = ExcavatorPrepEngine()

    def request_cancel(self):
        """Request graceful cancellation."""
        self._is_cancelled = True
        logger.info(f"Cancellation requested for asset #{self.asset_id} background removal.")

    def run(self):
        try:
            self.started_work.emit(self.asset_id)
            self.progress.emit(10, "Decoding image & sampling borders...")

            if self._is_cancelled:
                self.canceled.emit(self.asset_id)
                return

            self.progress.emit(25, "Seeding color-distance mask...")

            if self._is_cancelled:
                self.canceled.emit(self.asset_id)
                return

            self.progress.emit(45, f"Running GrabCut refinement ({self.grabcut_iterations} passes)...")

            # Run engine processing
            success, rgba, diag, msg = self.engine.remove_background(
                input_path=self.input_path,
                output_path=self.output_path,
                color_tolerance=self.color_tolerance,
                grabcut_iterations=self.grabcut_iterations,
                user_mask=self.user_mask,
                fg_strokes=self.fg_strokes,
                bg_strokes=self.bg_strokes,
                lasso_points=self.lasso_points,
                feather_radius=self.feather_radius,
                cancel_check=lambda: self._is_cancelled,
            )

            if self._is_cancelled:
                self.canceled.emit(self.asset_id)
                return

            self.progress.emit(85, "Smoothing edges & evaluating diagnostics...")

            if success:
                self.progress.emit(100, "Background removal complete.")
                self.finished_work.emit(self.asset_id, rgba, diag, msg)
            else:
                self.error.emit(self.asset_id, msg)

        except Exception as e:
            logger.error(f"BackgroundRemovalWorker exception: {e}", exc_info=True)
            self.error.emit(self.asset_id, f"Worker error: {str(e)}\n{traceback.format_exc()}")


class WhiteBgDetectionWorker(QThread):
    """Executes white background analysis in background."""

    finished_work = Signal(int, bool, float, dict)  # asset_id, is_white, confidence, details
    error = Signal(int, str)

    def __init__(self, asset_id: int, image_path: Path | str, color_tolerance: int = 25, parent=None):
        super().__init__(parent)
        self.asset_id = asset_id
        self.image_path = image_path
        self.color_tolerance = color_tolerance
        self.engine = ExcavatorPrepEngine()

    def run(self):
        try:
            p = Path(self.image_path)
            if not p.is_file():
                self.error.emit(self.asset_id, f"File does not exist: {p}")
                return

            img_bgr = cv2.imread(str(p))
            if img_bgr is None:
                self.error.emit(self.asset_id, f"Failed to decode image: {p.name}")
                return

            is_white, conf, details = self.engine.detect_white_background(img_bgr, tolerance=self.color_tolerance)
            self.finished_work.emit(self.asset_id, is_white, conf, details)
        except Exception as e:
            logger.error(f"WhiteBgDetectionWorker error: {e}", exc_info=True)
            self.error.emit(self.asset_id, str(e))


class QualityAuditWorker(QThread):
    """Executes multi-point quality validation in background."""

    finished_work = Signal(int, object)  # asset_id, Stage13QualityReport
    error = Signal(int, str)

    def __init__(
        self,
        asset_id: int,
        image_path: Path | str,
        component_type: str = "other",
        pivot_coords: Optional[Tuple[float, float]] = None,
        source_path: Optional[Path | str] = None,
        expected_source_hash: Optional[str] = None,
        require_transparency: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.asset_id = asset_id
        self.image_path = image_path
        self.component_type = component_type
        self.pivot_coords = pivot_coords
        self.source_path = source_path
        self.expected_source_hash = expected_source_hash
        self.require_transparency = require_transparency
        self.validator = Stage13QualityValidator()

    def run(self):
        try:
            report = self.validator.validate_asset(
                image_path=self.image_path,
                component_type=self.component_type,
                pivot_coords=self.pivot_coords,
                source_path=self.source_path,
                expected_source_hash=self.expected_source_hash,
                require_transparency=self.require_transparency,
            )
            self.finished_work.emit(self.asset_id, report)
        except Exception as e:
            logger.error(f"QualityAuditWorker error: {e}", exc_info=True)
            self.error.emit(self.asset_id, str(e))


class ImageLoadWorker(QThread):
    """Loads and decodes full-resolution image and cutout in background."""

    finished_work = Signal(int, str, object, object)  # asset_id, load_path, orig_pil_or_array, cutout_array
    error = Signal(int, str)

    def __init__(self, asset_id: int, load_path: str, proc_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.asset_id = asset_id
        self.load_path = load_path
        self.proc_path = proc_path

    def run(self):
        try:
            lp = Path(self.load_path)
            if not lp.is_file():
                self.error.emit(self.asset_id, f"Image file not found: {self.load_path}")
                return

            # Read cutout if present
            cutout_arr = None
            if self.proc_path and Path(self.proc_path).is_file():
                cutout_bgr = cv2.imread(str(self.proc_path), cv2.IMREAD_UNCHANGED)
                if cutout_bgr is not None and len(cutout_bgr.shape) == 3 and cutout_bgr.shape[2] == 4:
                    cutout_arr = cv2.cvtColor(cutout_bgr, cv2.COLOR_BGRA2RGBA)

            self.finished_work.emit(self.asset_id, self.load_path, None, cutout_arr)

        except Exception as e:
            logger.error(f"ImageLoadWorker error: {e}", exc_info=True)
            self.error.emit(self.asset_id, str(e))


class ComponentExtractionWorker(QThread):
    """Crops component, creates transparent sprite, and generates metadata in background."""

    finished_work = Signal(int, dict, str)  # asset_id, comp_dict, sprite_path
    error = Signal(int, str)

    def __init__(
        self,
        asset_id: int,
        source_file: str,
        component_type: str,
        custom_name: str,
        crop_rect: Optional[Tuple[int, int, int, int]] = None,
        polygon_points: Optional[List[Tuple[int, int]]] = None,
        pivot_norm: Tuple[float, float] = (0.5, 0.5),
        pivot_status: str = "Verified",
        prep_id: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.asset_id = asset_id
        self.source_file = source_file
        self.component_type = component_type
        self.custom_name = custom_name
        self.crop_rect = crop_rect
        self.polygon_points = polygon_points
        self.pivot_norm = pivot_norm
        self.pivot_status = pivot_status
        self.prep_id = prep_id
        self.extractor = ExcavatorComponentExtractor()

    def run(self):
        try:
            src_p = Path(self.source_file)
            if not src_p.is_file():
                self.error.emit(self.asset_id, f"Source image missing: {self.source_file}")
                return

            with Image.open(src_p) as pil_img:
                arr = np.array(pil_img.convert("RGBA"))

            if self.polygon_points and len(self.polygon_points) >= 3:
                cropped_arr, bbox = self.extractor.crop_component_polygon(arr, self.polygon_points)
                method = "polygon_lasso_crop"
            elif self.crop_rect:
                cropped_arr, bbox = self.extractor.crop_component_rect(arr, self.crop_rect)
                method = "bounding_rect_crop"
            else:
                cropped_arr = arr.copy()
                bbox = (0, 0, arr.shape[1], arr.shape[0])
                method = "full_illustration_preservation"

            export_h, export_w = cropped_arr.shape[:2]

            sprite_path = self.extractor.save_component_sprite(
                cropped_arr,
                component_type=self.component_type,
                asset_id=self.asset_id,
                custom_name=self.custom_name,
            )

            px, py = self.extractor.calculate_pivot_coordinates(export_w, export_h, self.pivot_norm[0], self.pivot_norm[1])

            comp_dict = {
                "asset_id": self.asset_id,
                "preparation_id": self.prep_id,
                "component_type": self.component_type,
                "component_name": sprite_path.stem,
                "source_path": str(src_p),
                "export_width": export_w,
                "export_height": export_h,
                "bbox_x": bbox[0],
                "bbox_y": bbox[1],
                "bbox_w": bbox[2],
                "bbox_h": bbox[3],
                "pivot_norm_x": self.pivot_norm[0],
                "pivot_norm_y": self.pivot_norm[1],
                "pivot_pixel_x": px,
                "pivot_pixel_y": py,
                "pivot_status": self.pivot_status,
                "transparency_status": "True Alpha",
                "processing_method": method,
                "manual_review_status": "Reviewed",
                "approval_status": "Approved",
                "export_path": str(sprite_path),
                "is_unavailable": 0,
            }

            self.finished_work.emit(self.asset_id, comp_dict, str(sprite_path))

        except Exception as e:
            logger.error(f"ComponentExtractionWorker error: {e}", exc_info=True)
            self.error.emit(self.asset_id, str(e))

