"""
Text & Label Detection Engine for Construction Asset Processor
Identifies unwanted text, letters, numbers, vehicle labels, fake brand names,
captions, titles, UI text, and watermark candidates in game assets.

Strictly non-destructive: Never modifies original images, never deletes text from source files.
Supports local OpenCV computer-vision detection and optional neural EasyOCR adapter.
"""

import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from core.database import db

logger = logging.getLogger(__name__)

# Standard detection categories
CATEGORIES = [
    "Alphabetic text",
    "Numbers",
    "Vehicle labels",
    "Fake brand names",
    "Watermark-like text",
    "Image captions",
    "Embedded titles",
    "UI text",
    "Unknown writing",
]

# Color mapping for bounding box rendering
CATEGORY_COLORS = {
    "Alphabetic text": "#3B82F6",       # Blue
    "Numbers": "#10B981",               # Emerald Green
    "Vehicle labels": "#F59E0B",        # Amber
    "Fake brand names": "#EC4899",      # Pink
    "Watermark-like text": "#EF4444",   # Red (Critical alert)
    "Image captions": "#8B5CF6",        # Violet
    "Embedded titles": "#6366F1",       # Indigo
    "UI text": "#06B6D4",               # Cyan
    "Unknown writing": "#9CA3AF",       # Cool Gray
}

# Review status options
REVIEW_STATUSES = [
    "pending",
    "unwanted",
    "intentional",
    "rejected",
]


class EasyOCRAdapter:
    """
    Adapter for EasyOCR neural text recognition.
    Per requirements:
    - Never claim OCR is available until model is installed.
    - Explain model download size (~95MB) and cache models locally.
    - Gracefully fallback to OpenCV detector when uninstalled.
    """

    def __init__(self):
        self._reader = None
        self._is_importable = False
        self._import_checked = False
        self._init_error = None

    def check_availability(self) -> Tuple[bool, str]:
        """Check if easyocr library is installed and importable."""
        if self._import_checked:
            if self._is_importable:
                return True, "EasyOCR library is installed and ready."
            return False, self._init_error or "EasyOCR is not installed in the current environment."

        self._import_checked = True
        try:
            import easyocr  # noqa: F401
            self._is_importable = True
            return True, "EasyOCR library is installed and ready."
        except ImportError:
            self._is_importable = False
            self._init_error = (
                "EasyOCR is not installed in this environment.\n"
                "To enable deep neural OCR recognition (~95 MB model download):\n"
                "pip install easyocr\n"
                "Defaulting to local OpenCV Computer Vision detector."
            )
            return False, self._init_error
        except Exception as e:
            self._is_importable = False
            self._init_error = f"Error importing EasyOCR: {str(e)}"
            return False, self._init_error

    def get_reader(self):
        """Lazy initialization of EasyOCR reader with local model caching."""
        if not self._is_importable:
            available, _ = self.check_availability()
            if not available:
                return None

        if self._reader is not None:
            return self._reader

        try:
            import easyocr
            # Model storage in local project data directory if possible
            model_storage_dir = Path(__file__).resolve().parent.parent / "data" / "models" / "easyocr"
            model_storage_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Initializing EasyOCR reader with English recognition model...")
            self._reader = easyocr.Reader(
                ["en"],
                gpu=False,
                model_storage_directory=str(model_storage_dir),
                download_enabled=True,
                verbose=False,
            )
            return self._reader
        except Exception as e:
            logger.warning("Failed to initialize EasyOCR reader: %s", e)
            self._init_error = str(e)
            return None

    def detect(self, img_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Run EasyOCR detection & recognition on a BGR image."""
        reader = self.get_reader()
        if reader is None:
            return []

        try:
            # Convert BGR to RGB for EasyOCR
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            results = reader.readtext(img_rgb)
            # results is a list of [bbox, text, prob]
            h, w = img_bgr.shape[:2]
            regions = []

            for bbox, text, prob in results:
                # bbox is [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                xs = [pt[0] for pt in bbox]
                ys = [pt[1] for pt in bbox]
                bx = max(0, int(min(xs)))
                by = max(0, int(min(ys)))
                bw = min(w - bx, int(max(xs) - min(xs)))
                bh = min(h - by, int(max(ys) - min(ys)))

                if bw < 4 or bh < 4:
                    continue

                category, is_wm = classify_text_region(bx, by, bw, bh, w, h, text)

                regions.append({
                    "box_x": bx,
                    "box_y": by,
                    "box_w": bw,
                    "box_h": bh,
                    "recognized_text": text.strip(),
                    "confidence": round(float(prob), 3),
                    "category": category,
                    "is_watermark_candidate": 1 if is_wm else 0,
                    "model_name": "EasyOCR",
                })

            return regions
        except Exception as e:
            logger.error("EasyOCR inference error: %s", e)
            return []


class OpenCVTextDetector:
    """
    Local multi-feature computer vision text detector using OpenCV.
    Requires no neural downloads, runs locally at high speed.
    Uses Morphological Gradient, MSER Extremal Regions, and geometric clustering.
    """

    def __init__(self):
        # Initialize MSER detector for character regions
        try:
            self._mser = cv2.MSER_create(
                delta=5,
                min_area=30,
                max_area=18000,
                max_variation=0.25,
            )
        except Exception:
            self._mser = None

    def detect(self, img_bgr: np.ndarray, asset_meta: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Detect candidate text regions in the image using computer vision.
        Returns a list of region dictionaries.
        """
        if img_bgr is None or img_bgr.size == 0:
            return []

        h, w = img_bgr.shape[:2]
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # 1. Morphological Gradient / Sobel for text stroke energy
        # Text regions exhibit dense horizontal gradients (high frequency stroke transitions)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        gradient = cv2.convertScaleAbs(cv2.addWeighted(cv2.absdiff(grad_x, 0), 0.7, cv2.absdiff(grad_y, 0), 0.3, 0))

        # Blur and threshold the gradient map
        blurred = cv2.GaussianBlur(gradient, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Connect individual letters horizontally into words using a rectangular structuring element
        # Typical text has greater horizontal width than vertical gap
        kernel_w = max(9, int(w * 0.015))
        kernel_h = max(3, int(h * 0.005))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, kernel_h))
        connected = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        # Find contours from morphological analysis
        contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidate_boxes = []

        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            # Filter non-text geometry
            if bh < 8 or bw < 8:
                continue
            if bh > h * 0.45 or bw > w * 0.95:
                continue
            aspect = bw / float(bh)
            if aspect < 0.12 or aspect > 25.0:
                continue
            area = bw * bh
            if area < 64 or area > (w * h * 0.4):
                continue

            # Verify stroke intensity inside box
            roi_grad = gradient[y : y + bh, x : x + bw]
            if roi_grad.size == 0:
                continue
            mean_grad = np.mean(roi_grad)
            if mean_grad < 18.0:
                # Weak contrast / non-textured region
                continue

            candidate_boxes.append((x, y, bw, bh, mean_grad))

        # 2. MSER Extremal Regions for sharp high-contrast text / logos
        if self._mser is not None:
            try:
                regions_mser, _ = self._mser.detectRegions(gray)
                for p in regions_mser:
                    x, y, bw, bh = cv2.boundingRect(p)
                    if 8 <= bh <= h * 0.35 and 8 <= bw <= w * 0.85:
                        aspect = bw / float(bh)
                        if 0.15 <= aspect <= 15.0:
                            candidate_boxes.append((x, y, bw, bh, 35.0))
            except Exception as mser_err:
                logger.debug("MSER region detection failed: %s", mser_err)

        # 3. Corner Scan specifically for Gemini / AI watermarks
        # Bottom-right corner (within 18% of bottom and right edges)
        wm_x_start = int(w * 0.78)
        wm_y_start = int(h * 0.80)
        corner_roi_grad = gradient[wm_y_start:h, wm_x_start:w]
        if corner_roi_grad.size > 0:
            corner_thresh = cv2.threshold(corner_roi_grad, 40, 255, cv2.THRESH_BINARY)[1]
            c_cnts, _ = cv2.findContours(corner_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cc in c_cnts:
                cx, cy, cbw, cbh = cv2.boundingRect(cc)
                if 8 <= cbw <= (w * 0.22) and 6 <= cbh <= (h * 0.18):
                    abs_x = wm_x_start + cx
                    abs_y = wm_y_start + cy
                    candidate_boxes.append((abs_x, abs_y, cbw, cbh, 45.0))

        # 4. Merge overlapping and nearby bounding boxes
        merged_boxes = self._merge_boxes(candidate_boxes, w, h)

        # 5. Format region records with category and confidence
        detected_regions = []
        for x, y, bw, bh, score in merged_boxes:
            category, is_wm = classify_text_region(x, y, bw, bh, w, h, None, asset_meta)
            # Normalize confidence between 0.45 and 0.95
            conf = min(0.95, max(0.45, round(score / 60.0, 3)))
            if is_wm:
                conf = max(conf, 0.75)

            # Heuristic representation text for CV detector
            synth_text = "[Detected Text]" if not is_wm else "[Watermark / Logo]"

            detected_regions.append({
                "box_x": x,
                "box_y": y,
                "box_w": bw,
                "box_h": bh,
                "recognized_text": synth_text,
                "confidence": conf,
                "category": category,
                "is_watermark_candidate": 1 if is_wm else 0,
                "model_name": "OpenCV-CV",
            })

        return detected_regions

    def _merge_boxes(
        self, boxes: List[Tuple[int, int, int, int, float]], img_w: int, img_h: int
    ) -> List[Tuple[int, int, int, int, float]]:
        """Merge overlapping or nearby bounding boxes."""
        if not boxes:
            return []

        # Convert to [x1, y1, x2, y2, score]
        rects = []
        for x, y, bw, bh, sc in boxes:
            rects.append([x, y, x + bw, y + bh, sc])

        merged = []
        used = [False] * len(rects)

        for i in range(len(rects)):
            if used[i]:
                continue
            r1 = rects[i]
            cur_x1, cur_y1, cur_x2, cur_y2, cur_sc = r1[0], r1[1], r1[2], r1[3], r1[4]
            used[i] = True

            changed = True
            while changed:
                changed = False
                for j in range(len(rects)):
                    if used[j]:
                        continue
                    r2 = rects[j]
                    # Check if r2 overlaps or is within proximity horizontally and vertically
                    prox_x = max(10, int(img_w * 0.02))
                    prox_y = max(6, int(img_h * 0.01))

                    x_overlap = not (r2[2] < (cur_x1 - prox_x) or r2[0] > (cur_x2 + prox_x))
                    y_overlap = not (r2[3] < (cur_y1 - prox_y) or r2[1] > (cur_y2 + prox_y))

                    if x_overlap and y_overlap:
                        cur_x1 = min(cur_x1, r2[0])
                        cur_y1 = min(cur_y1, r2[1])
                        cur_x2 = max(cur_x2, r2[2])
                        cur_y2 = max(cur_y2, r2[3])
                        cur_sc = max(cur_sc, r2[4])
                        used[j] = True
                        changed = True

            bw = cur_x2 - cur_x1
            bh = cur_y2 - cur_y1
            # Final sanity check on merged box
            if 8 <= bw <= img_w * 0.96 and 6 <= bh <= img_h * 0.5:
                merged.append((cur_x1, cur_y1, bw, bh, cur_sc))

        return merged


def classify_text_region(
    bx: int,
    by: int,
    bw: int,
    bh: int,
    img_w: int,
    img_h: int,
    recognized_text: Optional[str] = None,
    asset_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[str, bool]:
    """
    Intelligently classify a bounding box into one of the 9 categories.
    Determines if it is a watermark candidate for Stage 7 review.
    """
    text = (recognized_text or "").strip().lower()

    # Position checks
    rel_x = bx / float(img_w)
    rel_y = by / float(img_h)
    rel_right = (bx + bw) / float(img_w)
    rel_bottom = (by + bh) / float(img_h)
    rel_w = bw / float(img_w)
    rel_h = bh / float(img_h)

    # 1. Watermark Detection Check (Critical for Gemini watermarks)
    # Gemini watermark is typically in bottom-right corner, roughly within last 18% of image
    is_bottom_right = rel_right >= 0.82 and rel_bottom >= 0.82
    is_bottom_left = rel_x <= 0.18 and rel_bottom >= 0.85
    is_small_badge = rel_w <= 0.28 and rel_h <= 0.16

    watermark_keywords = [
        "gemini", "google", "made by", "ai generated", "generated with",
        "created with", "shutterstock", "getty", "istock", "watermark",
        "adobe", "stock", "preview", "sample",
    ]
    has_wm_word = any(kw in text for kw in watermark_keywords)

    if has_wm_word or (is_bottom_right and is_small_badge):
        return "Watermark-like text", True

    if is_bottom_left and is_small_badge and rel_w < 0.20:
        return "Watermark-like text", True

    # 2. Recognized text inspection if OCR available
    if text:
        # Check for numbers
        clean_nums = "".join(c for c in text if c.isdigit() or c in ".,-/#")
        if len(clean_nums) >= 2 and len(clean_nums) >= len(text) * 0.65:
            return "Numbers", False

        # Brand / Vehicle Model name keywords
        brand_keywords = [
            "cat", "caterpillar", "komatsu", "volvo", "hitachi", "hyundai",
            "jcb", "liebherr", "sany", "doosan", "bobcat", "case", "kubota",
            "turbo", "diesel", "heavy", "power", "v8", "v12", "eco", "4x4",
        ]
        if any(kw in text for kw in brand_keywords):
            return "Vehicle labels", False

        # UI elements
        ui_keywords = ["start", "play", "stop", "menu", "score", "level", "fps", "coins", "health", "pause", "exit"]
        if any(kw in text for kw in ui_keywords):
            return "UI text", False

    # 3. Geometric / Positional checks
    # Embedded titles: Centered horizontally at top or bottom, relatively wide
    is_centered_h = abs((rel_x + rel_w / 2.0) - 0.5) < 0.20
    if rel_y <= 0.15 and rel_w >= 0.28:
        return "Embedded titles", False

    # Image captions: Bottom centered or full width band
    if rel_bottom >= 0.85 and rel_w >= 0.35 and is_centered_h:
        return "Image captions", False

    # Vehicle labels: If asset is an excavator or vehicle, and box is located on the body (central area)
    is_central = 0.20 <= rel_x <= 0.80 and 0.20 <= rel_y <= 0.80
    if is_central and rel_w <= 0.35 and rel_h <= 0.20:
        # Likely vehicle label or brand mark on equipment
        return "Vehicle labels", False

    # UI text check if image is small icon or badge
    if img_w <= 128 and img_h <= 128:
        return "UI text", False

    # Default category
    if text and text.isalpha():
        return "Alphabetic text", False

    return "Unknown writing", False


class TextDetectionEngine:
    """
    Master Text Detection and Label Analysis Engine.
    Coordinates local OpenCV analysis and neural EasyOCR adapter.
    Ensures non-destructive operation, transaction management, and database synchronization.
    """

    def __init__(self):
        self.opencv_detector = OpenCVTextDetector()
        self.easyocr_adapter = EasyOCRAdapter()

    def get_engine_status(self) -> Dict[str, Any]:
        """Query availability and status of underlying detection backends."""
        ocr_available, ocr_msg = self.easyocr_adapter.check_availability()
        return {
            "opencv_available": True,
            "opencv_version": cv2.__version__,
            "easyocr_available": ocr_available,
            "easyocr_status": ocr_msg,
            "active_mode": "EasyOCR (Neural)" if ocr_available else "OpenCV (Computer Vision)",
        }

    def detect_text(
        self, asset: Dict[str, Any], method: str = "auto"
    ) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Analyze an image asset and identify all visible text regions.
        Does NOT modify the source file.
        Returns:
            Tuple of (regions_list, model_name, model_version)
        """
        file_path = asset.get("original_path")
        if not file_path or not os.path.exists(file_path):
            logger.warning("Asset file does not exist: %s", file_path)
            return [], "None", "0.0.0"

        # Load image safely using OpenCV
        try:
            # Handle unicode paths on Windows via numpy fromfile
            img_array = np.fromfile(file_path, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("cv2.imdecode returned None")
        except Exception as read_err:
            logger.error("Failed to read image for text detection '%s': %s", file_path, read_err)
            return [], "Error", "1.0.0"

        # Determine method
        use_ocr = False
        if method == "easyocr":
            use_ocr = True
        elif method == "auto":
            avail, _ = self.easyocr_adapter.check_availability()
            use_ocr = avail

        regions = []
        model_name = "OpenCV-CV"
        model_ver = cv2.__version__

        if use_ocr:
            try:
                regions = self.easyocr_adapter.detect(img)
                model_name = "EasyOCR"
                model_ver = "1.7.0"
            except Exception as ocr_err:
                logger.warning("EasyOCR run failed, falling back to OpenCV: %s", ocr_err)
                regions = self.opencv_detector.detect(img, asset_meta=asset)
                model_name = "OpenCV-CV"
                model_ver = cv2.__version__
        else:
            regions = self.opencv_detector.detect(img, asset_meta=asset)

        return regions, model_name, model_ver

    def process_and_save_asset(
        self, asset: Dict[str, Any], method: str = "auto"
    ) -> Tuple[bool, int, List[Dict[str, Any]]]:
        """
        Execute detection on single asset and persist results into SQLite.
        Records history entry and updates asset text counters.
        Returns: (success, detected_count, regions)
        """
        asset_id = asset["id"]
        try:
            regions, model_name, model_ver = self.detect_text(asset, method=method)
            detected_count = len(regions)

            # Persist via DatabaseManager
            db.save_text_detection_result(
                asset_id=asset_id,
                regions=regions,
                model_name=model_name,
                model_version=model_ver,
                status="success",
            )
            return True, detected_count, regions
        except Exception as e:
            logger.error("Failed text detection processing for asset #%s: %s", asset_id, e)
            # Record failed history
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO text_detection_history
                        (asset_id, detected_count, model_name, model_version, status, error_message)
                    VALUES (?, 0, ?, 'error', 'failed', ?)
                """, (asset_id, method, str(e)))
                cursor.execute("""
                    UPDATE assets SET
                        text_detection_status = 'failed',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (asset_id,))
            return False, 0, []


# Global singleton engine instance
text_engine = TextDetectionEngine()
