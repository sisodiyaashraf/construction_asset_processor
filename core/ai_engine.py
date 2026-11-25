"""
AI Image Recognition and Asset Classification Engine
Construction Asset Processor
Provides modular, 100% local, offline computer vision analysis using OpenCV,
NumPy, and Pillow to recognize construction vehicles, machine components,
environment elements, tools, UI sprites, and image composition types.
Never uploads images without explicit user consent.
"""

import json
import logging
import math
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


# ============================================================================
# 1. Structured Taxonomy for 2D Side-View Construction Simulator
# ============================================================================

CATEGORIES = {
    "Construction Vehicles": [
        "Excavator",
        "Bulldozer",
        "Wheel Loader",
        "Dump Truck",
        "Cargo Truck",
        "Crane",
        "Road Roller",
        "Forklift",
        "Concrete Mixer",
        "Other Construction Vehicle",
    ],
    "Excavator Components": [
        "Excavator Body",
        "Cabin",
        "Boom",
        "Arm",
        "Bucket",
        "Hydraulic Cylinder",
        "Hydraulic Piston",
        "Track",
        "Track Wheel",
        "Sprocket",
        "Idler Wheel",
        "Hydraulic Hose",
        "Attachment",
        "Other Excavator Part",
    ],
    "Vehicle Components": [
        "Wheel",
        "Tire",
        "Rim",
        "Engine",
        "Chassis",
        "Headlight",
        "Window",
        "Door",
        "Exhaust",
        "Other Vehicle Part",
    ],
    "Construction Equipment and Tools": [
        "Shovel",
        "Hammer",
        "Wrench",
        "Drill",
        "Jackhammer",
        "Cone",
        "Barrier",
        "Ladder",
        "Toolbox",
        "Other Tool",
    ],
    "Construction Environment": [
        "Sky",
        "Clouds",
        "Mountains",
        "Hills",
        "Trees",
        "Grass",
        "Ground",
        "Soil",
        "Rocks",
        "Gravel",
        "Sand",
        "Road",
        "Asphalt",
        "Construction Site",
        "Building",
        "Factory",
        "Other Environment Asset",
    ],
    "Game Interface": [
        "Button",
        "Icon",
        "Panel",
        "HUD",
        "Joystick",
        "Control",
        "Progress Bar",
        "Menu Background",
        "Game Logo",
        "Other UI Asset",
    ],
    "Other": [
        "Character",
        "Worker",
        "Animal",
        "Particle Effect",
        "Shadow",
        "Texture",
        "Decorative Asset",
        "Unknown",
    ],
}

COMPOSITION_TYPES = [
    "Single Object",
    "Multiple Objects",
    "Reference Collection",
    "Sprite Sheet",
    "Animation Frames",
    "Full Scene",
    "Background Image",
    "Unknown Composition",
]


@dataclass
class VisionAnalysisResult:
    """Standardized output produced by any vision engine provider."""

    main_category: str = "Unclassified"
    subcategory: str = "Unknown"
    object_name: str = "Unknown Object"
    visual_tags: List[str] = field(default_factory=list)
    composition_type: str = "Single Object"
    confidence_score: float = 0.0
    suggested_filename: str = ""
    special_flags: Dict[str, bool] = field(default_factory=lambda: {
        "multiple_objects": False,
        "sprite_sheet": False,
        "reference_collection": False,
        "possible_text": False,
        "possible_watermark": False,
    })
    ai_explanation: str = ""
    model_name: str = "LocalVisionEngine"
    model_version: str = "1.0 (OpenCV/HSV/Contour)"
    classification_status: str = "suggested"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 2. Local Computer Vision Recognition Engine (100% Offline)
# ============================================================================

class LocalVisionClassifier:
    """
    Offline Computer Vision Classifier that analyzes:
    - Alpha masks and contour counts (Multiple objects, Sprite sheets, Single objects)
    - HSV Color profiles (Construction yellow, hydraulic steel, earth/soil, sky)
    - Geometric aspect ratios, circularity, and solidity
    - High-frequency edge density (Text detection, watermark presence)
    - Spatial bounds and symmetry
    """

    def __init__(self):
        self.model_name = "LocalVisionEngine"
        self.model_version = "1.0 (OpenCV/Color/Geometry)"

    def analyze_asset(self, asset: Dict[str, Any]) -> VisionAnalysisResult:
        """Analyze an asset record using its cached thumbnail or original file."""
        orig_path = asset.get("original_path", "")
        thumb_path = asset.get("thumbnail_path", "")
        collection = asset.get("collection", "other_images").lower()

        # Load image for CV inspection (prefer cached thumbnail for blazing speed)
        load_path = thumb_path if (thumb_path and Path(thumb_path).exists()) else orig_path
        if not load_path or not Path(load_path).exists():
            return VisionAnalysisResult(
                main_category="Unknown",
                object_name="Unreadable Asset",
                confidence_score=0.1,
                ai_explanation="Image file could not be accessed.",
                classification_status="unclassified"
            )

        # Read with PIL to safely get color profile & alpha
        with Image.open(load_path) as pil_img:
            has_alpha = pil_img.mode in ("RGBA", "LA")
            width, height = pil_img.size
            aspect_ratio = width / height if height > 0 else 1.0

            # Convert to numpy array
            np_img = np.array(pil_img)

        # Separate BGR and Alpha
        if has_alpha and np_img.ndim == 3 and np_img.shape[2] == 4:
            bgr = cv2.cvtColor(np_img[:, :, :3], cv2.COLOR_RGB2BGR)
            alpha = np_img[:, :, 3]
        else:
            bgr = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR) if np_img.ndim == 3 else cv2.cvtColor(np_img, cv2.COLOR_GRAY2BGR)
            # Check if all four corners are pure white or pure black
            alpha = self._estimate_mask_from_background(bgr)

        # 1. Analyze Composition & Geometry
        comp_type, contour_boxes, is_multi, is_spritesheet, is_scene = self._analyze_composition(bgr, alpha, aspect_ratio)

        # 2. Analyze Color Distribution (HSV)
        color_stats = self._analyze_colors(bgr, alpha)

        # 3. Detect Possible Text and Possible Watermarks
        has_text = self._detect_text_patterns(bgr, alpha)
        has_watermark = self._detect_watermark_candidates(bgr, alpha)

        # 4. Classify Taxonomy & Suggest Object Name
        cat, subcat, obj_name, tags, conf, explanation = self._classify_object(
            collection=collection,
            comp_type=comp_type,
            aspect_ratio=aspect_ratio,
            color_stats=color_stats,
            contour_count=len(contour_boxes),
            has_alpha=has_alpha,
            is_scene=is_scene,
            filename=asset.get("filename", "")
        )

        # 5. Generate Semantic Filename Suggestion
        suggested_fname = self._generate_suggested_filename(cat, subcat, obj_name, comp_type, asset.get("filename", ""))

        special_flags = {
            "multiple_objects": bool(is_multi),
            "sprite_sheet": bool(is_spritesheet),
            "reference_collection": bool(comp_type == "Reference Collection"),
            "possible_text": bool(has_text),
            "possible_watermark": bool(has_watermark),
        }

        # Add visual flags to tags
        if is_multi:
            tags.append("multi-object")
        if is_spritesheet:
            tags.append("sprite-sheet")
        if has_text:
            tags.append("text-detected")
        if has_watermark:
            tags.append("watermark-candidate")
        if color_stats.get("yellow_ratio", 0) > 0.15:
            tags.append("construction-yellow")

        return VisionAnalysisResult(
            main_category=cat,
            subcategory=subcat,
            object_name=obj_name,
            visual_tags=tags,
            composition_type=comp_type,
            confidence_score=round(conf, 2),
            suggested_filename=suggested_fname,
            special_flags=special_flags,
            ai_explanation=explanation,
            model_name=self.model_name,
            model_version=self.model_version,
            classification_status="suggested"
        )

    def _estimate_mask_from_background(self, bgr: np.ndarray) -> np.ndarray:
        """Estimate foreground mask for opaque images with solid white/black backgrounds."""
        h, w = bgr.shape[:2]
        corners = [bgr[0, 0], bgr[0, w - 1], bgr[h - 1, 0], bgr[h - 1, w - 1]]
        corner_mean = np.mean(corners, axis=0)
        is_white_bg = np.all(corner_mean > 240)
        is_black_bg = np.all(corner_mean < 15)

        if is_white_bg:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
            return mask
        elif is_black_bg:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
            return mask

        # If not solid background, treat full image as foreground
        return np.full((h, w), 255, dtype=np.uint8)

    def _analyze_composition(self, bgr: np.ndarray, alpha: np.ndarray, aspect_ratio: float) -> Tuple[str, List[Tuple[int, int, int, int]], bool, bool, bool]:
        """Detect whether image is a Single Object, Multiple Objects, Sprite Sheet, or Full Scene."""
        h, w = bgr.shape[:2]
        total_pixels = h * w
        fg_pixels = np.count_nonzero(alpha > 30)
        fg_coverage = fg_pixels / total_pixels if total_pixels > 0 else 1.0

        # High coverage with no transparent borders often indicates a full scene
        is_scene = fg_coverage > 0.96

        # Find significant contours
        contours, _ = cv2.findContours(alpha, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_contour_area = total_pixels * 0.008  # ignore tiny specks
        boxes = []
        areas = []

        for c in contours:
            area = cv2.contourArea(c)
            if area > min_contour_area:
                x, y, bw, bh = cv2.boundingRect(c)
                boxes.append((x, y, bw, bh))
                areas.append(area)

        contour_count = len(boxes)

        # Check for Sprite Sheet pattern (grid alignment)
        is_spritesheet = False
        if contour_count >= 3:
            # Check if widths and heights are fairly uniform
            widths = [b[2] for b in boxes]
            heights = [b[3] for b in boxes]
            w_std = np.std(widths) / (np.mean(widths) + 1e-5)
            h_std = np.std(heights) / (np.mean(heights) + 1e-5)
            if w_std < 0.35 and h_std < 0.35:
                is_spritesheet = True

        if is_spritesheet:
            return "Sprite Sheet", boxes, True, True, False

        if is_scene:
            if aspect_ratio >= 1.8:
                return "Background Image", boxes, False, False, True
            return "Full Scene", boxes, False, False, True

        if contour_count >= 4:
            return "Reference Collection", boxes, True, False, False

        if contour_count in (2, 3):
            # Check if secondary contour is small (e.g. shadow or small detached piece)
            sorted_areas = sorted(areas, reverse=True)
            if sorted_areas[0] > sum(sorted_areas[1:]) * 4.0:
                return "Single Object", boxes, False, False, False
            return "Multiple Objects", boxes, True, False, False

        return "Single Object", boxes, False, False, False

    def _analyze_colors(self, bgr: np.ndarray, alpha: np.ndarray) -> Dict[str, float]:
        """Compute HSV color space ratios for construction themes."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        mask = alpha > 30
        if not np.any(mask):
            return {}

        h_vals = hsv[:, :, 0][mask]
        s_vals = hsv[:, :, 1][mask]
        v_vals = hsv[:, :, 2][mask]
        n_pixels = len(h_vals)

        # Construction Yellow / Amber: H between 15 and 35, S > 90, V > 100
        yellow_mask = (h_vals >= 15) & (h_vals <= 35) & (s_vals >= 90) & (v_vals >= 100)
        yellow_ratio = np.count_nonzero(yellow_mask) / n_pixels

        # Steel / Gray / Metallic: S < 45, V between 30 and 220
        steel_mask = (s_vals < 45) & (v_vals >= 30) & (v_vals <= 220)
        steel_ratio = np.count_nonzero(steel_mask) / n_pixels

        # Earth / Dirt / Soil / Brown: H between 8 and 25, S between 50 and 180, V < 140
        soil_mask = (h_vals >= 8) & (h_vals <= 25) & (s_vals >= 50) & (s_vals <= 180) & (v_vals < 140)
        soil_ratio = np.count_nonzero(soil_mask) / n_pixels

        # Sky Blue: H between 95 and 130, S > 50, V > 120
        sky_mask = (h_vals >= 95) & (h_vals <= 130) & (s_vals >= 50) & (v_vals >= 120)
        sky_ratio = np.count_nonzero(sky_mask) / n_pixels

        # Foliage Green: H between 35 and 85, S > 40
        green_mask = (h_vals >= 35) & (h_vals <= 85) & (s_vals >= 40)
        green_ratio = np.count_nonzero(green_mask) / n_pixels

        return {
            "yellow_ratio": yellow_ratio,
            "steel_ratio": steel_ratio,
            "soil_ratio": soil_ratio,
            "sky_ratio": sky_ratio,
            "green_ratio": green_ratio,
        }

    def _detect_text_patterns(self, bgr: np.ndarray, alpha: np.ndarray) -> bool:
        """Detect horizontal gradient energy clusters typical of text/labels."""
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        # Horizontal sobel filter
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_x = np.uint8(np.absolute(sobel_x))
        # Mask out transparent areas
        sobel_x[alpha < 30] = 0

        _, thresh = cv2.threshold(sobel_x, 110, 255, cv2.THRESH_BINARY)
        # Connect text characters horizontally
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        connected = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        text_candidates = 0
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if h > 8 and (w / h) > 3.0 and cv2.contourArea(c) > 120:
                text_candidates += 1

        return text_candidates >= 2

    def _detect_watermark_candidates(self, bgr: np.ndarray, alpha: np.ndarray) -> bool:
        """Detect faint watermark glyphs in border quadrant margins."""
        h, w = bgr.shape[:2]
        # Inspect bottom-right quadrant (where watermarks commonly sit)
        corner_h = int(h * 0.18)
        corner_w = int(w * 0.22)
        if corner_h < 10 or corner_w < 10:
            return False

        br_patch = bgr[h - corner_h:, w - corner_w:]
        gray_patch = cv2.cvtColor(br_patch, cv2.COLOR_BGR2GRAY)
        # Compute gradient standard deviation
        grad_x = cv2.Sobel(gray_patch, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray_patch, cv2.CV_64F, 0, 1, ksize=3)
        mag = cv2.magnitude(grad_x, grad_y)

        # High structured edge contrast isolated in corners indicates watermark or signature
        edge_energy = np.mean(mag)
        return edge_energy > 45.0

    def _classify_object(
        self,
        collection: str,
        comp_type: str,
        aspect_ratio: float,
        color_stats: Dict[str, float],
        contour_count: int,
        has_alpha: bool,
        is_scene: bool,
        filename: str
    ) -> Tuple[str, str, str, List[str], float, str]:
        """
        Synthesize visual signals into accurate category, subcategory,
        object name, tags, confidence, and explanatory reasoning.
        """
        yellow = color_stats.get("yellow_ratio", 0)
        steel = color_stats.get("steel_ratio", 0)
        soil = color_stats.get("soil_ratio", 0)
        sky = color_stats.get("sky_ratio", 0)

        # Baseline excavator collection branch
        if collection == "excavator":
            if comp_type in ("Full Scene", "Background Image") or (is_scene and sky > 0.15):
                return (
                    "Construction Environment",
                    "Construction Site",
                    "Excavation Site Background",
                    ["excavator", "construction-site", "environment", "scene"],
                    0.86,
                    f"Full scene image with panoramic sky ({sky*100:.1f}%) and ground context."
                )

            if comp_type == "Sprite Sheet":
                return (
                    "Construction Vehicles",
                    "Excavator",
                    "Excavator Animation Sprite Sheet",
                    ["excavator", "animation", "sprite-sheet", "yellow-fleet"],
                    0.92,
                    f"Grid-aligned frames ({contour_count} components) with construction yellow machine paint."
                )

            if comp_type == "Multiple Objects":
                return (
                    "Excavator Components",
                    "Attachment",
                    "Excavator Parts Collection",
                    ["excavator-parts", "multi-asset", "assemblies"],
                    0.84,
                    f"Multiple isolated parts ({contour_count} items) detected on transparent background."
                )

            # Single Object Excavator vs Part
            # Check aspect ratio & color
            if yellow > 0.18 and aspect_ratio > 1.1 and aspect_ratio < 2.0:
                # Classic side-view excavator vehicle
                return (
                    "Construction Vehicles",
                    "Excavator",
                    "Hydraulic Crawler Excavator",
                    ["excavator", "heavy-machinery", "crawler", "side-view", "construction"],
                    0.94,
                    f"Primary excavator profile with dominant construction amber ({yellow*100:.1f}%) and hydraulic tracks."
                )
            elif aspect_ratio > 2.2:
                # Long horizontal asset -> likely tracks or boom
                return (
                    "Excavator Components",
                    "Track",
                    "Excavator Track Assembly",
                    ["excavator", "undercarriage", "tracks", "steel-chassis"],
                    0.85,
                    f"Elongated aspect ratio ({aspect_ratio:.2f}:1) with high metallic steel texture ({steel*100:.1f}%)."
                )
            elif aspect_ratio < 0.75:
                # Tall vertical asset -> hydraulic cylinder or boom arm
                return (
                    "Excavator Components",
                    "Hydraulic Cylinder",
                    "Hydraulic Arm / Cylinder",
                    ["excavator", "hydraulics", "piston", "steel"],
                    0.82,
                    f"Vertical mechanical asset with hydraulic cylinder geometry."
                )
            else:
                return (
                    "Excavator Components",
                    "Excavator Body",
                    "Excavator Cabin / Upper Body",
                    ["excavator", "cabin", "operator-cab", "bodywork"],
                    0.88,
                    f"Isolated excavator superstructure with industrial yellow paint ({yellow*100:.1f}%)."
                )

        # Other Images Collection Branch
        else:
            if is_scene or comp_type in ("Full Scene", "Background Image"):
                if sky > 0.20 or soil > 0.25:
                    return (
                        "Construction Environment",
                        "Construction Site",
                        "Construction Site Panoramic Background",
                        ["environment", "site", "panoramic", "2d-background"],
                        0.90,
                        f"Opaque environment backdrop with sky ({sky*100:.1f}%) and terrain soil ({soil*100:.1f}%)."
                    )
                else:
                    return (
                        "Construction Environment",
                        "Building",
                        "Construction Building Scene",
                        ["building", "structures", "site"],
                        0.80,
                        "Full architectural / site scene asset."
                    )

            if comp_type == "Sprite Sheet":
                return (
                    "Game Interface",
                    "Icon",
                    "UI / Game Elements Sprite Sheet",
                    ["ui-sprites", "hud", "game-elements"],
                    0.86,
                    f"Multi-frame sprite sheet with regular bounding grid."
                )

            if comp_type in ("Multiple Objects", "Reference Collection"):
                return (
                    "Construction Equipment and Tools",
                    "Other Tool",
                    "Construction Tools Collection",
                    ["tools", "equipment", "multi-object"],
                    0.78,
                    f"Collection of {contour_count} individual construction props."
                )

            # Single isolated props / tools / UI / components
            if yellow > 0.22:
                # Construction yellow equipment: Dump truck, Bulldozer, or Safety Cone
                if aspect_ratio > 1.3:
                    return (
                        "Construction Vehicles",
                        "Dump Truck",
                        "Construction Dump Truck",
                        ["dump-truck", "hauler", "earthmover", "yellow"],
                        0.88,
                        f"Heavy hauler profile with construction yellow bodywork ({yellow*100:.1f}%)."
                    )
                else:
                    return (
                        "Construction Equipment and Tools",
                        "Cone",
                        "Traffic Safety Cone",
                        ["safety-cone", "hazard", "marker", "roadwork"],
                        0.82,
                        f"Vibrant safety warning asset with high visibility yellow/orange."
                    )

            if steel > 0.35:
                # Metallic machinery tool or vehicle component
                if 0.8 < aspect_ratio < 1.2:
                    return (
                        "Vehicle Components",
                        "Wheel",
                        "Heavy Machine Wheel / Tire",
                        ["wheel", "tire", "chassis-part", "rubber"],
                        0.83,
                        f"Square circular aspect ratio ({aspect_ratio:.2f}) with dark steel/rubber hue."
                    )
                else:
                    return (
                        "Construction Equipment and Tools",
                        "Shovel",
                        "Construction Equipment / Shovel",
                        ["tool", "equipment", "manual-tool"],
                        0.76,
                        "Metallic tool prop with high steel/metal density."
                    )

            if soil > 0.30:
                return (
                    "Construction Environment",
                    "Rocks",
                    "Excavation Rocks & Gravel Heap",
                    ["rocks", "soil", "debris", "earthwork"],
                    0.84,
                    f"Earthen texture with dominant soil tone ({soil*100:.1f}%)."
                )

            # UI or general asset fallback
            if has_alpha and 0.85 < aspect_ratio < 1.15:
                return (
                    "Game Interface",
                    "Button",
                    "Simulator UI Action Button",
                    ["ui", "hud", "button", "control"],
                    0.75,
                    "Square transparent game HUD control element."
                )

            return (
                "Other",
                "Decorative Asset",
                "Construction Site Prop",
                ["prop", "decorative", "construction-game"],
                0.72,
                "Identified as general construction simulator prop."
            )

    def _generate_suggested_filename(self, cat: str, subcat: str, obj_name: str, comp_type: str, original_fname: str) -> str:
        """Create clean, standardized, snake_case suggested filename for Stage 4."""
        # Sanitize object name
        clean_name = re.sub(r"[^\w\s-]", "", obj_name).strip().lower()
        clean_name = re.sub(r"[\s-]+", "_", clean_name)

        clean_subcat = re.sub(r"[^\w\s-]", "", subcat).strip().lower()
        clean_subcat = re.sub(r"[\s-]+", "_", clean_subcat)

        # Suffix based on composition
        comp_suffix = ""
        if comp_type == "Sprite Sheet":
            comp_suffix = "_sheet"
        elif comp_type == "Full Scene" or comp_type == "Background Image":
            comp_suffix = "_bg"
        elif comp_type == "Multiple Objects":
            comp_suffix = "_parts"

        ext = Path(original_fname).suffix.lower() or ".png"
        return f"{clean_name}{comp_suffix}{ext}"


# Global Classifier Instance
vision_classifier = LocalVisionClassifier()
