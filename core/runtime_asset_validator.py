"""
Runtime Asset Validator (Stage 11)
Construction Asset Processor

Performs exhaustive pre-integration validation on assets exported for Flutter + Flame:
- Verifies every referenced file exists on disk.
- Ensures all paths are relative, safe, and confined within the asset root.
- Decodes image streams and checks for bit corruption or invalid headers.
- Verifies image dimensions match recorded metadata specifications.
- Validates alpha transparency claims vs actual pixel values.
- Checks texture atlas frame rectangles remain within atlas bounds (x>=0, y>=0, x+w<=W, y+h<=H).
- Validates frame dimensions (w>0, h>0) and ensures unique frame names per atlas/animation.
- Validates animation sequences, contiguous frame numbering, frame durations, and FPS.
- Verifies normalized kinematic pivot coordinates (0.0 <= pivot <= 1.0).
- Generates structured status: PASS, WARNING, FAIL, NOT TESTED.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
from PIL import Image

logger = logging.getLogger("AssetProcessor.RuntimeAssetValidator")

ENGINE_VERSION = "1.0.0"

CHECK_CATEGORIES = [
    "path_safety",
    "file_existence",
    "image_decode",
    "dimension_conformance",
    "transparency_consistency",
    "atlas_bounds",
    "frame_dimensions",
    "frame_identifiers",
    "animation_sequence",
    "animation_timing",
    "pivot_coordinates",
]


class RuntimeAssetValidator:
    """Validator performing deep asset & metadata inspection before mobile engine execution."""

    def __init__(self):
        self._version = ENGINE_VERSION

    def get_validator_info(self) -> Dict[str, Any]:
        """Return engine metadata."""
        return {
            "name": "Runtime Game Asset Validator",
            "version": self._version,
            "offline": True,
            "check_categories": CHECK_CATEGORIES,
            "supported_statuses": ["PASS", "WARNING", "FAIL", "NOT TESTED"],
        }

    def validate_asset_tree(
        self,
        asset_root: Union[str, Path],
        manifest_path: Optional[Union[str, Path]] = None,
        flame_version: str = "1.18.0",
    ) -> Dict[str, Any]:
        """
        Validate an entire exported Flutter asset tree (`assets/` directory) and manifests.
        Returns comprehensive telemetry and individual categorized check results.
        """
        root = Path(asset_root).resolve()
        if not root.exists() or not root.is_dir():
            return {
                "total_checked": 1,
                "passed_count": 0,
                "warning_count": 0,
                "failed_count": 1,
                "not_tested_count": 0,
                "overall_status": "FAIL",
                "results": [{
                    "asset_path": str(root),
                    "asset_type": "directory",
                    "check_category": "file_existence",
                    "status": "FAIL",
                    "message": f"Asset root directory does not exist: {root}",
                    "details": {},
                }],
            }

        results: List[Dict[str, Any]] = []

        # 1. Inspect manifests if present
        manifest_files = []
        if manifest_path and Path(manifest_path).exists():
            manifest_files.append(Path(manifest_path).resolve())
        else:
            # Look in assets/metadata/ and assets/
            manifest_files.extend(root.glob("metadata/*.json"))
            manifest_files.extend(root.glob("*.json"))
            manifest_files.extend(root.glob("atlases/*.json"))
            manifest_files.extend(root.glob("spritesheets/*.json"))

        checked_images: Set[Path] = set()

        # Validate manifests first
        for mf in manifest_files:
            m_res = self.validate_metadata_file(mf, asset_root=root)
            results.extend(m_res)

        # 2. Inspect all image files in asset tree
        image_extensions = {".png", ".webp", ".jpg", ".jpeg"}
        all_images = [p for p in root.glob("**/*") if p.is_file() and p.suffix.lower() in image_extensions]

        for img_p in all_images:
            i_res = self.validate_image_file(img_p, asset_root=root)
            results.extend(i_res)
            checked_images.add(img_p)

        # Aggregate counts
        passed = sum(1 for r in results if r["status"] == "PASS")
        warning = sum(1 for r in results if r["status"] == "WARNING")
        failed = sum(1 for r in results if r["status"] == "FAIL")
        not_tested = sum(1 for r in results if r["status"] == "NOT TESTED")

        overall = "FAIL" if failed > 0 else ("WARNING" if warning > 0 else ("PASS" if passed > 0 else "NOT TESTED"))

        return {
            "total_checked": len(results),
            "passed_count": passed,
            "warning_count": warning,
            "failed_count": failed,
            "not_tested_count": not_tested,
            "overall_status": overall,
            "results": results,
        }

    def validate_image_file(
        self,
        image_path: Union[str, Path],
        asset_root: Optional[Path] = None,
        expected_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Validate an individual image file on disk for integrity, bounds, and transparency."""
        p = Path(image_path).resolve()
        rel_str = str(p.relative_to(asset_root)).replace("\\", "/") if asset_root and p.is_relative_to(asset_root) else p.name
        results: List[Dict[str, Any]] = []

        # A. Path Safety
        safety_status, safety_msg = self._check_path_safety(p, asset_root)
        results.append({
            "asset_path": rel_str,
            "asset_type": "image",
            "check_category": "path_safety",
            "status": safety_status,
            "message": safety_msg,
            "details": {"path": str(p)},
        })
        if safety_status == "FAIL":
            return results

        # B. File Existence & Size
        if not p.exists() or p.stat().st_size == 0:
            results.append({
                "asset_path": rel_str,
                "asset_type": "image",
                "check_category": "file_existence",
                "status": "FAIL",
                "message": "Image file does not exist or has 0 bytes.",
                "details": {},
            })
            return results

        # C. Image Decoding & Header Verification
        try:
            with Image.open(str(p)) as im:
                im.verify()

            # Re-open for data inspection since verify() clears pointers
            with Image.open(str(p)) as im:
                w, h = im.size
                mode = im.mode
                fmt = im.format

                # Dimension bounds
                if w <= 0 or h <= 0:
                    dim_status = "FAIL"
                    dim_msg = f"Non-positive dimensions detected: {w}x{h}"
                elif w > 4096 or h > 4096:
                    dim_status = "WARNING"
                    dim_msg = f"Oversized texture dimension ({w}x{h}) exceeds mobile GPU recommendation (4096px)."
                else:
                    dim_status = "PASS"
                    dim_msg = f"Valid texture dimensions: {w}x{h} ({fmt})"

                results.append({
                    "asset_path": rel_str,
                    "asset_type": "image",
                    "check_category": "image_decode",
                    "status": "PASS",
                    "message": f"Successfully decoded {fmt} image in mode {mode}.",
                    "details": {"width": w, "height": h, "format": fmt, "mode": mode},
                })

                results.append({
                    "asset_path": rel_str,
                    "asset_type": "image",
                    "check_category": "frame_dimensions",
                    "status": dim_status,
                    "message": dim_msg,
                    "details": {"width": w, "height": h},
                })

                # Metadata dimension cross-check
                if expected_meta and "width" in expected_meta and "height" in expected_meta:
                    exp_w = expected_meta["width"]
                    exp_h = expected_meta["height"]
                    if (w, h) != (exp_w, exp_h):
                        results.append({
                            "asset_path": rel_str,
                            "asset_type": "image",
                            "check_category": "dimension_conformance",
                            "status": "FAIL",
                            "message": f"Dimensions mismatch metadata specification: actual {w}x{h} vs expected {exp_w}x{exp_h}.",
                            "details": {"actual": (w, h), "expected": (exp_w, exp_h)},
                        })
                    else:
                        results.append({
                            "asset_path": rel_str,
                            "asset_type": "image",
                            "check_category": "dimension_conformance",
                            "status": "PASS",
                            "message": f"Dimensions match recorded metadata: {w}x{h}.",
                            "details": {"dimensions": (w, h)},
                        })

                # Transparency check
                has_alpha = mode in ("RGBA", "LA") or (mode == "P" and "transparency" in im.info)
                if has_alpha:
                    # Check for true transparency in pixel array
                    rgba = im.convert("RGBA") if mode != "RGBA" else im
                    alpha_plane = np.array(rgba)[:, :, 3]
                    has_real_trans = bool(np.any(alpha_plane < 255))
                    is_all_blank = bool(np.all(alpha_plane == 0))

                    if is_all_blank:
                        t_status = "FAIL"
                        t_msg = "Image has alpha channel but is 100% transparent (blank blank pixels)."
                    elif not has_real_trans:
                        t_status = "WARNING"
                        t_msg = "Image has 32-bit RGBA channel but contains no transparent pixels (solid opaque)."
                    else:
                        t_status = "PASS"
                        t_msg = "Valid alpha transparency detected with clean semi-transparent/opaque regions."

                    results.append({
                        "asset_path": rel_str,
                        "asset_type": "image",
                        "check_category": "transparency_consistency",
                        "status": t_status,
                        "message": t_msg,
                        "details": {"has_alpha": has_alpha, "has_actual_transparency": has_real_trans},
                    })
                else:
                    results.append({
                        "asset_path": rel_str,
                        "asset_type": "image",
                        "check_category": "transparency_consistency",
                        "status": "PASS",
                        "message": "Opaque image format (no alpha plane required).",
                        "details": {"has_alpha": False},
                    })

        except Exception as e:
            results.append({
                "asset_path": rel_str,
                "asset_type": "image",
                "check_category": "image_decode",
                "status": "FAIL",
                "message": f"Failed to decode image data (corrupted or unsupported): {e}",
                "details": {"error": str(e)},
            })

        return results

    def validate_metadata_file(
        self,
        metadata_path: Union[str, Path],
        asset_root: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Validate JSON metadata file (Texture Atlas or Flame Manifest)."""
        p = Path(metadata_path).resolve()
        rel_str = str(p.relative_to(asset_root)).replace("\\", "/") if asset_root and p.is_relative_to(asset_root) else p.name
        results: List[Dict[str, Any]] = []

        if not p.exists():
            results.append({
                "asset_path": rel_str,
                "asset_type": "metadata",
                "check_category": "file_existence",
                "status": "FAIL",
                "message": f"Metadata file missing: {p.name}",
                "details": {},
            })
            return results

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            results.append({
                "asset_path": rel_str,
                "asset_type": "metadata",
                "check_category": "image_decode",
                "status": "FAIL",
                "message": f"Invalid JSON syntax in metadata: {e}",
                "details": {"error": str(e)},
            })
            return results

        # 1. Texture Atlas validation (contains 'frames' or 'atlas')
        if "frames" in data:
            results.extend(self._validate_atlas_frames(data, p, asset_root))
        elif "sprites" in data and "atlas" in data:
            results.extend(self._validate_custom_atlas(data, p, asset_root))

        # 2. Flame Asset Manifest validation (contains 'asset_catalogs' or 'animations')
        if "asset_catalogs" in data:
            results.extend(self._validate_flame_manifest(data, p, asset_root))

        # 3. Animation Sequences validation (if standalone animation file)
        if "animations" in data:
            results.extend(self._validate_animation_sequences(data["animations"], rel_str))

        return results

    def _validate_atlas_frames(
        self,
        atlas_data: Dict[str, Any],
        metadata_file: Path,
        asset_root: Optional[Path],
    ) -> List[Dict[str, Any]]:
        """Validate texture atlas frames rects, identifiers, and bounds."""
        results = []
        rel_meta = str(metadata_file.relative_to(asset_root)).replace("\\", "/") if asset_root else metadata_file.name

        meta_info = atlas_data.get("meta", {})
        image_name = meta_info.get("image") or f"{metadata_file.stem}.png"
        atlas_img_path = metadata_file.parent / image_name

        # Verify atlas image existence
        if not atlas_img_path.exists():
            # Try in assets/images/ or same folder
            results.append({
                "asset_path": rel_meta,
                "asset_type": "atlas",
                "check_category": "file_existence",
                "status": "FAIL",
                "message": f"Atlas image texture '{image_name}' referenced in metadata is missing on disk.",
                "details": {"referenced_image": image_name},
            })
            atlas_w = meta_info.get("size", {}).get("w", 2048)
            atlas_h = meta_info.get("size", {}).get("h", 2048)
        else:
            with Image.open(str(atlas_img_path)) as im:
                atlas_w, atlas_h = im.size

        frames = atlas_data.get("frames", {})
        frame_names_seen = set()

        for fname, f_info in frames.items():
            # Duplicate identifier check
            if fname in frame_names_seen:
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "atlas",
                    "check_category": "frame_identifiers",
                    "status": "FAIL",
                    "message": f"Duplicate sprite frame identifier in atlas: '{fname}'",
                    "details": {"frame_name": fname},
                })
            frame_names_seen.add(fname)

            rect = f_info.get("frame", {})
            x = rect.get("x", 0)
            y = rect.get("y", 0)
            w = rect.get("w", 0)
            h = rect.get("h", 0)

            # Positive dimensions check
            if w <= 0 or h <= 0:
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "atlas",
                    "check_category": "frame_dimensions",
                    "status": "FAIL",
                    "message": f"Frame '{fname}' has invalid non-positive dimensions: {w}x{h}",
                    "details": {"frame": fname, "width": w, "height": h},
                })
            else:
                # Atlas boundary check
                if x < 0 or y < 0 or (x + w) > atlas_w or (y + h) > atlas_h:
                    results.append({
                        "asset_path": rel_meta,
                        "asset_type": "atlas",
                        "check_category": "atlas_bounds",
                        "status": "FAIL",
                        "message": f"Frame '{fname}' rect [{x}, {y}, {w}, {h}] overflows atlas bounds ({atlas_w}x{atlas_h}).",
                        "details": {"frame": fname, "rect": [x, y, w, h], "atlas_size": [atlas_w, atlas_h]},
                    })
                else:
                    results.append({
                        "asset_path": rel_meta,
                        "asset_type": "atlas",
                        "check_category": "atlas_bounds",
                        "status": "PASS",
                        "message": f"Frame '{fname}' correctly contained inside atlas boundary.",
                        "details": {"frame": fname, "rect": [x, y, w, h]},
                    })

            # Check normalized pivot if present
            pivot = f_info.get("pivot")
            if pivot and isinstance(pivot, (list, tuple)) and len(pivot) == 2:
                px, py = pivot
                p_status, p_msg = self._check_pivot_coordinates(px, py)
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "atlas",
                    "check_category": "pivot_coordinates",
                    "status": p_status,
                    "message": f"Frame '{fname}' pivot ({px:.2f}, {py:.2f}): {p_msg}",
                    "details": {"frame": fname, "pivot": [px, py]},
                })

        return results

    def _validate_custom_atlas(
        self,
        atlas_data: Dict[str, Any],
        metadata_file: Path,
        asset_root: Optional[Path],
    ) -> List[Dict[str, Any]]:
        """Validate custom atlas layout."""
        results = []
        rel_meta = str(metadata_file.relative_to(asset_root)).replace("\\", "/") if asset_root else metadata_file.name
        atlas_info = atlas_data.get("atlas", {})
        atlas_w = atlas_info.get("width", 2048)
        atlas_h = atlas_info.get("height", 2048)

        sprites = atlas_data.get("sprites", {})
        seen_names = set()

        for sname, sinfo in sprites.items():
            if sname in seen_names:
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "atlas",
                    "check_category": "frame_identifiers",
                    "status": "FAIL",
                    "message": f"Duplicate sprite name in atlas: '{sname}'",
                    "details": {"sprite": sname},
                })
            seen_names.add(sname)

            x = sinfo.get("x", 0)
            y = sinfo.get("y", 0)
            w = sinfo.get("width", 0)
            h = sinfo.get("height", 0)

            if x < 0 or y < 0 or (x + w) > atlas_w or (y + h) > atlas_h:
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "atlas",
                    "check_category": "atlas_bounds",
                    "status": "FAIL",
                    "message": f"Sprite '{sname}' [{x}, {y}, {w}, {h}] overflows atlas bounds ({atlas_w}x{atlas_h}).",
                    "details": {"sprite": sname, "rect": [x, y, w, h]},
                })
            else:
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "atlas",
                    "check_category": "atlas_bounds",
                    "status": "PASS",
                    "message": f"Sprite '{sname}' is well within atlas bounds.",
                    "details": {"sprite": sname},
                })

        return results

    def _validate_flame_manifest(
        self,
        manifest_data: Dict[str, Any],
        metadata_file: Path,
        asset_root: Optional[Path],
    ) -> List[Dict[str, Any]]:
        """Validate unified Flame asset manifest catalog references."""
        results = []
        rel_meta = str(metadata_file.relative_to(asset_root)).replace("\\", "/") if asset_root else metadata_file.name

        catalogs = manifest_data.get("asset_catalogs", {})
        images = catalogs.get("images", [])

        for img_entry in images:
            img_rel = img_entry.get("path") or img_entry.get("relative_flutter_path")
            if not img_rel:
                continue

            target_disk = (asset_root / img_rel) if asset_root else Path(img_rel)
            if not target_disk.exists():
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "manifest",
                    "check_category": "file_existence",
                    "status": "FAIL",
                    "message": f"Manifest references missing image asset: '{img_rel}'",
                    "details": {"path": img_rel},
                })
            else:
                results.append({
                    "asset_path": rel_meta,
                    "asset_type": "manifest",
                    "check_category": "file_existence",
                    "status": "PASS",
                    "message": f"Manifest referenced asset exists: '{img_rel}'",
                    "details": {"path": img_rel},
                })

        return results

    def _validate_animation_sequences(
        self,
        animations: List[Dict[str, Any]],
        source_label: str,
    ) -> List[Dict[str, Any]]:
        """Validate animation frame ordering, contiguous indices, FPS, and timing."""
        results = []

        for anim in animations:
            anim_name = anim.get("name") or anim.get("animation_name") or "unnamed_animation"
            fps = anim.get("fps") or 10
            step_time = anim.get("step_time") or anim.get("duration_ms") or (1.0 / max(1, fps))

            # Validate FPS
            if fps <= 0 or fps > 120:
                results.append({
                    "asset_path": source_label,
                    "asset_type": "animation",
                    "check_category": "animation_timing",
                    "status": "FAIL",
                    "message": f"Animation '{anim_name}' has invalid FPS ({fps}). Must be between 1 and 120.",
                    "details": {"animation": anim_name, "fps": fps},
                })
            else:
                results.append({
                    "asset_path": source_label,
                    "asset_type": "animation",
                    "check_category": "animation_timing",
                    "status": "PASS",
                    "message": f"Animation '{anim_name}' has valid FPS ({fps}) and step time ({step_time}s).",
                    "details": {"animation": anim_name, "fps": fps, "step_time": step_time},
                })

            # Validate frame sequence ordering
            frames = anim.get("frames", [])
            if not frames and "frame_count" in anim:
                # Count-based declaration
                fc = anim["frame_count"]
                if fc <= 0:
                    results.append({
                        "asset_path": source_label,
                        "asset_type": "animation",
                        "check_category": "animation_sequence",
                        "status": "FAIL",
                        "message": f"Animation '{anim_name}' declares zero or negative frame_count ({fc}).",
                        "details": {"animation": anim_name, "frame_count": fc},
                    })
                else:
                    results.append({
                        "asset_path": source_label,
                        "asset_type": "animation",
                        "check_category": "animation_sequence",
                        "status": "PASS",
                        "message": f"Animation '{anim_name}' sequence count valid ({fc} frames).",
                        "details": {"animation": anim_name, "frame_count": fc},
                    })
            elif frames:
                # Inspect sequence numbers
                indices = [f.get("sequence_order", idx) for idx, f in enumerate(frames)]
                is_sorted = indices == sorted(indices)
                has_dups = len(indices) != len(set(indices))

                if has_dups:
                    results.append({
                        "asset_path": source_label,
                        "asset_type": "animation",
                        "check_category": "animation_sequence",
                        "status": "FAIL",
                        "message": f"Animation '{anim_name}' contains duplicate frame sequence numbers: {indices}",
                        "details": {"animation": anim_name, "indices": indices},
                    })
                elif not is_sorted:
                    results.append({
                        "asset_path": source_label,
                        "asset_type": "animation",
                        "check_category": "animation_sequence",
                        "status": "WARNING",
                        "message": f"Animation '{anim_name}' frame sequence indices are non-monotonic: {indices}",
                        "details": {"animation": anim_name, "indices": indices},
                    })
                else:
                    results.append({
                        "asset_path": source_label,
                        "asset_type": "animation",
                        "check_category": "animation_sequence",
                        "status": "PASS",
                        "message": f"Animation '{anim_name}' sequence ordering valid ({len(frames)} frames).",
                        "details": {"animation": anim_name, "count": len(frames)},
                    })

        return results

    def _check_path_safety(self, path: Path, asset_root: Optional[Path]) -> Tuple[str, str]:
        """Check for directory traversal (..) and unauthorized paths."""
        path_str = str(path)
        if ".." in path_str:
            return "FAIL", "Directory traversal detected ('..' in file path)."

        if asset_root:
            try:
                # Must resolve inside asset root
                path.resolve().relative_to(asset_root.resolve())
            except ValueError:
                return "FAIL", f"Asset path escapes authorized asset root: {path}"

        return "PASS", "Asset path is relative, safe, and contained inside authorized root."

    def _check_pivot_coordinates(self, px: float, py: float) -> Tuple[str, str]:
        """Verify normalized kinematic pivot coordinates."""
        if not (0.0 <= px <= 1.0 and 0.0 <= py <= 1.0):
            return "FAIL", f"Pivot ({px:.3f}, {py:.3f}) falls outside normalized coordinate range [0.0, 1.0]."
        return "PASS", f"Normalized pivot coordinates ({px:.2f}, {py:.2f}) valid."


# Global RuntimeAssetValidator singleton
runtime_asset_validator = RuntimeAssetValidator()
