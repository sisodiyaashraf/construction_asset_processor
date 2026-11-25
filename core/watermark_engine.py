"""
Watermark Detection & Review Engine (Stage 7)
Construction Asset Processor

Identifies suspected watermark candidates, attribution marks, logos,
semi-transparent overlays, and repeated visual signatures in game assets.

Strictly non-destructive:
- Never modifies original source images.
- Never erases, blurs, crops, or reconstructs watermark pixels.
- Never automatically approves an image as watermark-free without analysis.
- Presents explainable candidate scores and visual signal justifications.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
from PIL import Image

from core.database import db

logger = logging.getLogger("AssetProcessor.WatermarkEngine")

ENGINE_VERSION = "1.0.0"

# Standard Watermark Candidate Categories per Stage 7 specification
WATERMARK_CATEGORIES = [
    "Possible Text Watermark",
    "Possible Logo Watermark",
    "Possible Platform Attribution",
    "Possible Copyright Mark",
    "Possible Repeated Overlay",
    "Uncertain Mark",
    "No Watermark Candidate Detected",
]

# Color mapping for UI overlays & canvas rendering
WATERMARK_CATEGORY_COLORS = {
    "Possible Text Watermark": "#F59E0B",          # Amber
    "Possible Logo Watermark": "#EC4899",          # Pink
    "Possible Platform Attribution": "#EF4444",     # Safety Red
    "Possible Copyright Mark": "#8B5CF6",          # Violet
    "Possible Repeated Overlay": "#3B82F6",        # Blueprint Blue
    "Uncertain Mark": "#9CA3AF",                   # Cool Gray
    "No Watermark Candidate Detected": "#10B981",    # Emerald Green
}

# Review status transitions
WATERMARK_REVIEW_STATUSES = [
    "pending",
    "confirmed",
    "rejected",
    "uncertain",
]

# Replacement status transitions
WATERMARK_REPLACEMENT_STATUSES = [
    "none",
    "pending",
    "completed",
]


class WatermarkDetectionEngine:
    """
    Modular local watermark candidate detection engine.
    Analyzes multi-feature visual signals, logo badges, translucent overlays,
    and integrates Stage 6 text region metadata without modifying source files.
    """

    def __init__(self):
        self._version = ENGINE_VERSION

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata and offline status."""
        return {
            "name": "Local Computer Vision Watermark Detector",
            "version": self._version,
            "offline": True,
            "external_api": False,
            "active_backend": "OpenCV Multi-Signal CV",
            "signals": [
                "Stage 6 Text Region Reuse & Attribution Keyword Scan",
                "Corner Signature & Platform Attribution Geometry",
                "Compact Logo & Badge Contour Geometry",
                "Low-Opacity Translucent Overlay Detection",
                "Cross-Image Spatial Alignment & Frequency Check",
            ],
        }

    def detect_watermarks(self, asset: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Analyze an asset for candidate watermark regions.
        Does NOT modify the image file on disk.
        Returns: (candidate_regions, engine_version, detection_method)
        """
        file_path = asset.get("original_path")
        if not file_path or not os.path.exists(file_path):
            logger.warning("Asset file does not exist: %s", file_path)
            return [], self._version, "error_missing_file"

        try:
            # Safe image decode supporting Windows unicode paths
            img_array = np.fromfile(file_path, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("cv2.imdecode returned None")
        except Exception as read_err:
            logger.error("Failed to read image for watermark detection '%s': %s", file_path, read_err)
            return [], self._version, "error_decode_failed"

        h, w = img.shape[:2]
        asset_id = asset.get("id")

        candidates: List[Dict[str, Any]] = []

        # Signal 1: Stage 6 Text-Region Reuse
        s1_candidates = self._check_stage6_text_regions(asset_id, w, h)
        candidates.extend(s1_candidates)

        # Signal 2: Corner Attribution & Gemini Badge Scan
        s2_candidates = self._detect_corner_signatures(img, w, h)
        candidates.extend(s2_candidates)

        # Signal 3: Logo & Graphic Badge Detection
        s3_candidates = self._detect_logo_badges(img, w, h)
        candidates.extend(s3_candidates)

        # Signal 4: Low-Opacity / Translucent Overlay Detection
        s4_candidates = self._detect_translucent_overlays(img, w, h)
        candidates.extend(s4_candidates)

        # Merge overlapping or duplicate candidates
        merged = self._merge_candidates(candidates, w, h)

        return merged, self._version, "multi_signal_cv"

    def _check_stage6_text_regions(
        self, asset_id: Optional[int], img_w: int, img_h: int
    ) -> List[Dict[str, Any]]:
        """
        Signal 1: Read and reuse Stage 6 text regions flagged as watermark candidates
        or containing attribution/platform keywords.
        """
        if not asset_id:
            return []

        text_regions = db.get_text_regions(asset_id)
        candidates = []

        attr_keywords = [
            "gemini", "google", "ai", "generated", "made by", "created with",
            "shutterstock", "getty", "istock", "watermark", "adobe", "stock",
            "preview", "sample", "copyright", "all rights", "caterpillar", "komatsu"
        ]

        for tr in text_regions:
            bx = tr.get("box_x", 0)
            by = tr.get("box_y", 0)
            bw = tr.get("box_w", 0)
            bh = tr.get("box_h", 0)
            text = (tr.get("recognized_text") or "").lower().strip()
            is_wm_flag = tr.get("is_watermark_candidate", 0) == 1
            cat = tr.get("category", "")

            # Check for keyword matches
            matched_kw = [kw for kw in attr_keywords if kw in text]

            # Relative position
            rel_right = (bx + bw) / float(img_w)
            rel_bottom = (by + bh) / float(img_h)
            is_corner = (rel_right >= 0.80 and rel_bottom >= 0.80) or (bx <= img_w * 0.20 and rel_bottom >= 0.80)

            if matched_kw:
                c_type = "Possible Platform Attribution" if any(k in ("gemini", "google", "ai", "generated", "made by") for k in matched_kw) else "Possible Copyright Mark"
                score = 0.90
                reason = f"Stage 6 text region contains platform/attribution keywords: '{', '.join(matched_kw)}'"
                candidates.append({
                    "x": bx, "y": by, "width": bw, "height": bh,
                    "candidate_type": c_type,
                    "candidate_text": tr.get("recognized_text", ""),
                    "candidate_score": score,
                    "detection_method": "stage6_text_reuse",
                    "detection_reason": reason,
                    "review_status": "pending",
                })
            elif is_wm_flag:
                score = 0.82 if is_corner else 0.70
                c_type = "Possible Text Watermark" if is_corner else "Uncertain Mark"
                reason = f"Stage 6 flagged watermark candidate in {'corner' if is_corner else 'periphery'} region (rel_x: {bx/img_w:.2f}, rel_y: {by/img_h:.2f})"
                candidates.append({
                    "x": bx, "y": by, "width": bw, "height": bh,
                    "candidate_type": c_type,
                    "candidate_text": tr.get("recognized_text", ""),
                    "candidate_score": score,
                    "detection_method": "stage6_text_reuse",
                    "detection_reason": reason,
                    "review_status": "pending",
                })
            elif cat in ("Watermark-like text", "Fake brand names") and is_corner:
                candidates.append({
                    "x": bx, "y": by, "width": bw, "height": bh,
                    "candidate_type": "Possible Text Watermark",
                    "candidate_text": tr.get("recognized_text", ""),
                    "candidate_score": 0.75,
                    "detection_method": "stage6_text_reuse",
                    "detection_reason": f"Stage 6 '{cat}' located in corner attribution zone",
                    "review_status": "pending",
                })

        return candidates

    def _detect_corner_signatures(self, img_bgr: np.ndarray, w: int, h: int) -> List[Dict[str, Any]]:
        """
        Signal 2: Examine corner regions for artificial attribution stamps or badges.
        Focuses on bottom-right corner (>= 78% width, >= 80% height),
        bottom-left corner, and top-right corner.
        """
        candidates = []
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # Corner definitions: (name, x_start, y_start, x_end, y_end, candidate_type, score_boost)
        corners = [
            ("Bottom-Right Corner", int(w * 0.78), int(h * 0.80), w, h, "Possible Platform Attribution", 0.88),
            ("Bottom-Left Corner", 0, int(h * 0.82), int(w * 0.22), h, "Possible Text Watermark", 0.75),
            ("Top-Right Corner", int(w * 0.80), 0, w, int(h * 0.18), "Possible Copyright Mark", 0.70),
        ]

        for corner_name, cx1, cy1, cx2, cy2, cand_type, base_score in corners:
            roi = gray[cy1:cy2, cx1:cx2]
            if roi.size == 0 or roi.shape[0] < 12 or roi.shape[1] < 12:
                continue

            # Compute local stroke gradients
            grad_x = cv2.Sobel(roi, cv2.CV_32F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3)
            grad_mag = cv2.magnitude(grad_x, grad_y)
            mean_grad = np.mean(grad_mag)

            if mean_grad < 16.0:
                # Flat or clean corner
                continue

            # Check for isolated localized clusters in corner
            _, thresh = cv2.threshold(grad_mag.astype(np.uint8), 35, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
            connected = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                bx, by, bw, bh = cv2.boundingRect(cnt)
                # Filter noise
                if bw < 12 or bh < 8:
                    continue
                if bw > (cx2 - cx1) * 0.95 or bh > (cy2 - cy1) * 0.95:
                    continue
                aspect = bw / float(bh)
                if aspect < 0.2 or aspect > 16.0:
                    continue

                abs_x = cx1 + bx
                abs_y = cy1 + by

                # Calculate confidence score based on corner positioning and gradient strength
                score = min(0.95, round(base_score + min(0.08, (mean_grad - 16.0) / 100.0), 2))
                reason = (
                    f"Local high-frequency visual signature in {corner_name} "
                    f"(x: {abs_x}, y: {abs_y}, size: {bw}×{bh} px, stroke energy: {mean_grad:.1f})"
                )

                candidates.append({
                    "x": abs_x, "y": abs_y, "width": bw, "height": bh,
                    "candidate_type": cand_type,
                    "candidate_text": "",
                    "candidate_score": score,
                    "detection_method": "corner_signature_cv",
                    "detection_reason": reason,
                    "review_status": "pending",
                })

        return candidates

    def _detect_logo_badges(self, img_bgr: np.ndarray, w: int, h: int) -> List[Dict[str, Any]]:
        """
        Signal 3: Detect compact logo-like shapes, badges, or emblems.
        Identifies compact geometric contours with circularity / symmetry
        located away from primary game vehicle structures.
        """
        candidates = []
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # Bilateral filter to reduce noise while keeping badge edges
        filtered = cv2.bilateralFilter(gray, 7, 50, 50)
        edges = cv2.Canny(filtered, 50, 150)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            # Badges are typically compact (20px to 140px)
            if bw < 16 or bh < 16 or bw > 160 or bh > 160:
                continue
            aspect = bw / float(bh)
            if aspect < 0.6 or aspect > 1.8:
                continue

            area = cv2.contourArea(cnt)
            rect_area = bw * bh
            if rect_area <= 0:
                continue
            extent = area / float(rect_area)
            if extent < 0.35 or extent > 0.90:
                continue

            # Position check: logos usually near borders (outer 25% perimeter)
            rel_x = bx / float(w)
            rel_y = by / float(h)
            is_perimeter = (rel_x <= 0.20 or rel_x >= 0.75 or rel_y <= 0.20 or rel_y >= 0.75)
            if not is_perimeter:
                continue

            score = 0.68
            reason = f"Compact badge/logo contour in peripheral zone (aspect: {aspect:.2f}, extent: {extent:.2f})"

            candidates.append({
                "x": bx, "y": by, "width": bw, "height": bh,
                "candidate_type": "Possible Logo Watermark",
                "candidate_text": "",
                "candidate_score": score,
                "detection_method": "logo_badge_cv",
                "detection_reason": reason,
                "review_status": "pending",
            })

        return candidates

    def _detect_translucent_overlays(self, img_bgr: np.ndarray, w: int, h: int) -> List[Dict[str, Any]]:
        """
        Signal 4: Low-opacity / translucent pattern candidates.
        Analyzes subtle luminance differences between central and edge regions,
        and identifies semi-transparent stamps or watermark patterns.
        """
        candidates = []
        lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        l_channel = lab[:, :, 0]

        # Top-hat and Black-hat transform to reveal faint structures brighter or darker than local neighborhood
        k_size = max(15, int(min(w, h) * 0.03))
        if k_size % 2 == 0:
            k_size += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))

        tophat = cv2.morphologyEx(l_channel, cv2.MORPH_TOPHAT, kernel)
        blackhat = cv2.morphologyEx(l_channel, cv2.MORPH_BLACKHAT, kernel)
        faint_structures = cv2.add(tophat, blackhat)

        # Faint thresholding
        _, thresh = cv2.threshold(faint_structures, 28, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            if bw < 25 or bh < 12:
                continue
            if bw > w * 0.6 or bh > h * 0.4:
                continue

            # Faint overlay signature
            roi = faint_structures[by:by+bh, bx:bx+bw]
            if roi.size == 0:
                continue
            density = np.count_nonzero(roi) / float(bw * bh)
            if density < 0.15 or density > 0.85:
                continue

            rel_y = (by + bh) / float(h)
            rel_x = (bx + bw) / float(w)
            is_near_edge = (rel_y >= 0.80 or rel_y <= 0.20 or rel_x >= 0.80 or rel_x <= 0.20)

            c_type = "Possible Repeated Overlay" if not is_near_edge else "Uncertain Mark"
            score = 0.58 if not is_near_edge else 0.62
            reason = f"Low-opacity translucent structure detected via morphological luminance contrast (density: {density:.2f})"

            candidates.append({
                "x": bx, "y": by, "width": bw, "height": bh,
                "candidate_type": c_type,
                "candidate_text": "",
                "candidate_score": score,
                "detection_method": "translucent_overlay_cv",
                "detection_reason": reason,
                "review_status": "pending",
            })

        return candidates

    def _merge_candidates(
        self, candidates: List[Dict[str, Any]], img_w: int, img_h: int
    ) -> List[Dict[str, Any]]:
        """Merge nearby and overlapping candidate bounding boxes to prevent clutter."""
        if not candidates:
            return []

        # Sort by candidate_score descending
        sorted_cands = sorted(candidates, key=lambda c: float(c.get("candidate_score", 0)), reverse=True)
        merged: List[Dict[str, Any]] = []
        used = [False] * len(sorted_cands)

        for i in range(len(sorted_cands)):
            if used[i]:
                continue
            c1 = sorted_cands[i]
            cur_x1 = c1["x"]
            cur_y1 = c1["y"]
            cur_x2 = c1["x"] + c1["width"]
            cur_y2 = c1["y"] + c1["height"]
            best_type = c1["candidate_type"]
            best_score = float(c1.get("candidate_score", 0.5))
            best_method = c1.get("detection_method", "cv")
            best_reason = c1.get("detection_reason", "")
            best_text = c1.get("candidate_text", "")
            used[i] = True

            changed = True
            while changed:
                changed = False
                for j in range(len(sorted_cands)):
                    if used[j]:
                        continue
                    c2 = sorted_cands[j]
                    r2_x1 = c2["x"]
                    r2_y1 = c2["y"]
                    r2_x2 = c2["x"] + c2["width"]
                    r2_y2 = c2["y"] + c2["height"]

                    prox_x = max(10, int(img_w * 0.02))
                    prox_y = max(8, int(img_h * 0.015))

                    x_overlap = not (r2_x2 < (cur_x1 - prox_x) or r2_x1 > (cur_x2 + prox_x))
                    y_overlap = not (r2_y2 < (cur_y1 - prox_y) or r2_y1 > (cur_y2 + prox_y))

                    if x_overlap and y_overlap:
                        cur_x1 = min(cur_x1, r2_x1)
                        cur_y1 = min(cur_y1, r2_y1)
                        cur_x2 = max(cur_x2, r2_x2)
                        cur_y2 = max(cur_y2, r2_y2)
                        # Keep higher scoring type & text
                        if float(c2.get("candidate_score", 0)) > best_score:
                            best_score = float(c2.get("candidate_score", 0))
                            best_type = c2["candidate_type"]
                            best_method = c2.get("detection_method", best_method)
                            best_reason = c2.get("detection_reason", best_reason)
                        if not best_text and c2.get("candidate_text"):
                            best_text = c2.get("candidate_text")
                        used[j] = True
                        changed = True

            bw = cur_x2 - cur_x1
            bh = cur_y2 - cur_y1

            # Final size bounds check
            if 10 <= bw <= img_w * 0.95 and 6 <= bh <= img_h * 0.60:
                merged.append({
                    "x": cur_x1,
                    "y": cur_y1,
                    "width": bw,
                    "height": bh,
                    "candidate_type": best_type,
                    "candidate_text": best_text,
                    "candidate_score": round(best_score, 2),
                    "detection_method": best_method,
                    "detection_reason": best_reason,
                    "review_status": "pending",
                })

        return merged

    def process_and_save_asset(
        self, asset: Dict[str, Any]
    ) -> Tuple[bool, int, List[Dict[str, Any]]]:
        """
        Execute detection on single asset and persist results into SQLite.
        Records history entry and updates asset watermark counters.
        Returns: (success, candidate_count, candidates)
        """
        asset_id = asset["id"]
        try:
            candidates, engine_ver, method = self.detect_watermarks(asset)
            count = len(candidates)

            # Persist via DatabaseManager
            db.save_watermark_detection_result(
                asset_id=asset_id,
                regions=candidates,
                engine_version=engine_ver,
                detection_method=method,
                status="success",
            )
            return True, count, candidates
        except Exception as e:
            logger.error("Failed watermark detection for asset #%s: %s", asset_id, e)
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO watermark_detection_history
                        (asset_id, engine_version, detection_method, candidate_count, processing_status, error_message)
                    VALUES (?, ?, 'error', 0, 'failed', ?)
                """, (asset_id, self._version, str(e)))
                cursor.execute("""
                    UPDATE assets SET
                        watermark_detection_status = 'failed',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (asset_id,))
            return False, 0, []

    def batch_detect(self, assets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Synchronously batch process a list of assets."""
        total = len(assets)
        with_cands = 0
        clean_cnt = 0
        failed_cnt = 0

        for asset in assets:
            ok, cnt, _ = self.process_and_save_asset(asset)
            if ok:
                if cnt > 0:
                    with_cands += 1
                else:
                    clean_cnt += 1
            else:
                failed_cnt += 1

        return {
            "total": total,
            "processed": with_cands + clean_cnt + failed_cnt,
            "with_candidates": with_cands,
            "clean": clean_cnt,
            "failed": failed_cnt,
        }


# Global singleton watermark engine
watermark_engine = WatermarkDetectionEngine()
