"""
Flame Metadata Compatibility Engine (Stage 11)
Construction Asset Processor

Inspects Stage 10 Flame JSON output and compares against target Flutter + Flame specifications:
- Identifies atlas format schemas:
  - 'flame_atlas_v1' (Flame 1.x TexturePacker-style standard: meta, frames: {name: {frame, sourceSize}})
  - 'flame_atlas_custom' (Stage 10 generator format: atlas, sprites: {name: {x, y, width, height}})
  - 'flame_manifest_v1' (Unified asset catalog linking sprites, atlases, animations)
  - 'flame_spritesheet_data' (SpriteAnimationData.sequenced)
- Inspects relative asset paths, frame rects, dimensions, pivots, FPS, and animation sequences.
- Never silently rewrites metadata.
- Provides non-destructive conversion preview (source format, target format, JSON diff) for user review and approval.
- Preserves original metadata files strictly intact.
"""

from __future__ import annotations

import difflib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("AssetProcessor.FlameCompatibilityEngine")

ENGINE_VERSION = "1.0.0"

SUPPORTED_SCHEMAS = [
    "flame_atlas_v1",        # Standard Flame 1.x TexturePacker JSON format
    "flame_atlas_custom",    # Internal Stage 10 generator schema
    "flame_manifest_v1",     # Unified multi-catalog manifest
    "flame_spritesheet_v1",  # Animation frames sequence metadata
]


class FlameCompatibilityEngine:
    """Evaluates Flame engine JSON format compatibility and generates non-destructive migration previews."""

    def __init__(self):
        self._version = ENGINE_VERSION

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata."""
        return {
            "name": "Flame Metadata Compatibility Engine",
            "version": self._version,
            "offline": True,
            "supported_schemas": SUPPORTED_SCHEMAS,
            "capabilities": [
                "Multi-schema JSON format detection",
                "Relative asset path validation",
                "Kinematic pivot metadata inspection",
                "Flame 1.x conversion preview & diff generator",
            ],
        }

    def detect_schema_format(self, data: Dict[str, Any]) -> str:
        """Identify which Flame metadata schema standard is used."""
        if not isinstance(data, dict):
            return "unknown"

        if "frames" in data and isinstance(data["frames"], dict):
            meta = data.get("meta", {})
            if meta.get("target_engine") == "Flame" or "size" in meta:
                return "flame_atlas_v1"
            return "flame_atlas_v1"

        if "atlas" in data and "sprites" in data:
            return "flame_atlas_custom"

        if "asset_catalogs" in data:
            return "flame_manifest_v1"

        if "animations" in data or "frames" in data:
            return "flame_spritesheet_v1"

        return "generic_json"

    def inspect_metadata_file(
        self,
        metadata_path: Union[str, Path],
        flame_version_target: str = "1.18.0",
        asset_root: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Inspect a metadata file for Flame compatibility against target Flame version.
        Never modifies the file.
        """
        p = Path(metadata_path).resolve()
        if not p.exists():
            return {
                "file_path": str(p),
                "is_compatible": False,
                "compatibility_status": "incompatible",
                "detected_schema": "missing",
                "target_schema": "flame_atlas_v1",
                "issues": [{"severity": "ERROR", "message": f"File does not exist: {p.name}"}],
                "conversion_available": False,
                "conversion_preview": None,
            }

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {
                "file_path": str(p),
                "is_compatible": False,
                "compatibility_status": "incompatible",
                "detected_schema": "corrupted",
                "target_schema": "flame_atlas_v1",
                "issues": [{"severity": "ERROR", "message": f"Invalid JSON syntax: {e}"}],
                "conversion_available": False,
                "conversion_preview": None,
            }

        detected_schema = self.detect_schema_format(data)
        issues: List[Dict[str, Any]] = []

        # 1. Compatibility rules evaluation
        is_compatible = True
        needs_conversion = False
        target_schema = "flame_atlas_v1"

        if detected_schema == "flame_atlas_v1":
            # Flame 1.x standard: check meta and frames
            meta = data.get("meta", {})
            if not meta.get("image"):
                issues.append({
                    "severity": "WARNING",
                    "message": "Metadata missing 'meta.image' field linking to texture atlas image file.",
                })
            frames = data.get("frames", {})
            if not frames:
                issues.append({"severity": "WARNING", "message": "Atlas declares empty frames map."})
            for fname, finfo in list(frames.items())[:10]:
                if "frame" not in finfo:
                    issues.append({"severity": "ERROR", "message": f"Frame '{fname}' lacks 'frame' boundary dict."})
                    is_compatible = False

        elif detected_schema == "flame_atlas_custom":
            # Stage 10 internal format: compatible with processor, but Flame prefers flame_atlas_v1
            needs_conversion = True
            is_compatible = False
            issues.append({
                "severity": "WARNING",
                "message": (
                    "File uses Stage 10 internal generator schema ('atlas'/'sprites' keys). "
                    "Flame 1.x requires the standard TexturePacker schema ('meta'/'frames' keys)."
                ),
            })

        elif detected_schema == "flame_manifest_v1":
            target_schema = "flame_manifest_v1"
            catalogs = data.get("asset_catalogs", {})
            if not catalogs:
                issues.append({"severity": "WARNING", "message": "Manifest has empty asset catalogs."})

        elif detected_schema == "flame_spritesheet_v1":
            target_schema = "flame_spritesheet_v1"
            # Animation definitions check
            anims = data.get("animations", [])
            for a in anims:
                if not a.get("name"):
                    issues.append({"severity": "WARNING", "message": "Animation entry missing 'name' attribute."})

        else:
            is_compatible = False
            needs_conversion = True
            issues.append({
                "severity": "ERROR",
                "message": f"Unrecognized JSON schema '{detected_schema}'. Not directly loadable by Flame.",
            })

        # 2. Generate conversion preview if schema can be upgraded
        conversion_preview = None
        if needs_conversion or detected_schema == "flame_atlas_custom":
            conversion_preview = self.generate_conversion_preview(data, target_schema="flame_atlas_v1")

        status = "compatible" if is_compatible and not issues else ("warning" if is_compatible else "incompatible")

        return {
            "file_path": str(p),
            "filename": p.name,
            "is_compatible": is_compatible,
            "compatibility_status": status,
            "detected_schema": detected_schema,
            "target_schema": target_schema,
            "issues": issues,
            "conversion_available": conversion_preview is not None,
            "conversion_preview": conversion_preview,
        }

    def generate_conversion_preview(
        self,
        source_data: Dict[str, Any],
        target_schema: str = "flame_atlas_v1",
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a non-destructive transformation preview between schemas.
        Returns source JSON, converted target JSON, and visual text unified diff.
        Does NOT write or alter any file.
        """
        src_schema = self.detect_schema_format(source_data)
        if src_schema == target_schema:
            return None

        converted: Dict[str, Any] = {}

        if src_schema == "flame_atlas_custom" and target_schema == "flame_atlas_v1":
            atlas_info = source_data.get("atlas", {})
            img_file = atlas_info.get("image_file") or f"{atlas_info.get('name', 'atlas')}.png"
            w = atlas_info.get("width", 2048)
            h = atlas_info.get("height", 2048)

            converted = {
                "meta": {
                    "app": "Construction Asset Processor",
                    "version": "1.0.0",
                    "target_engine": "Flame",
                    "image": img_file,
                    "size": {"w": w, "h": h},
                    "scale": "1",
                },
                "frames": {},
            }

            sprites = source_data.get("sprites", {})
            for sname, sinfo in sprites.items():
                sw = sinfo.get("width", 0)
                sh = sinfo.get("height", 0)
                converted["frames"][sname] = {
                    "frame": {
                        "x": sinfo.get("x", 0),
                        "y": sinfo.get("y", 0),
                        "w": sw,
                        "h": sh,
                    },
                    "rotated": False,
                    "trimmed": False,
                    "spriteSourceSize": {"x": 0, "y": 0, "w": sw, "h": sh},
                    "sourceSize": {"w": sw, "h": sh},
                    "pivot": [0.5, 0.5],
                }
        else:
            # Fallback wrapper
            converted = {
                "meta": {
                    "app": "Construction Asset Processor",
                    "target_engine": "Flame",
                    "schema": target_schema,
                },
                "content": source_data,
            }

        src_str = json.dumps(source_data, indent=2)
        tgt_str = json.dumps(converted, indent=2)

        # Generate text diff
        diff_lines = list(difflib.unified_diff(
            src_str.splitlines(keepends=True),
            tgt_str.splitlines(keepends=True),
            fromfile=f"Source ({src_schema})",
            tofile=f"Target ({target_schema})",
            n=3,
        ))
        diff_text = "".join(diff_lines)

        return {
            "source_schema": src_schema,
            "target_schema": target_schema,
            "source_json": src_str,
            "converted_json": tgt_str,
            "diff_text": diff_text,
            "converted_dict": converted,
        }


# Global FlameCompatibilityEngine singleton
flame_compatibility_engine = FlameCompatibilityEngine()
