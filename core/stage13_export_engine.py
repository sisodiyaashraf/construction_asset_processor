"""
Stage 13 Approved Export Engine
Construction Asset Processor

Transfers approved excavator components to the Flutter + Flame game project:
Target Directory: C:\\Users\\sk\\Desktop\\ashrafprojects\\construction_simulator\\assets\\images
Subfolders:
- excavator/
- components/
- environment/
- terrain/
- metadata/

Safety & Project Separation Guarantees:
- Never modifies original source images.
- Only exports user-approved components (approval_status == 'Approved').
- Strictly preserves Flutter Dart code, architecture, and pubspec.yaml (ZERO modifications).
- Generates structured export manifest: stage13_export_manifest.json.
- Verifies every exported file by re-opening and validating PNG integrity.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from app.config import ROOT_DIR
from core.database import db
from core.excavator_prep_engine import compute_sha256

logger = logging.getLogger("AssetProcessor.Stage13ExportEngine")

DEFAULT_FLUTTER_ASSETS_DIR = Path(r"C:\Users\sk\Desktop\ashrafprojects\construction_simulator\assets\images")

# Subfolder category mapping
COMPONENT_SUBFOLDER_MAP: Dict[str, str] = {
    "complete_excavator": "excavator",
    "undercarriage": "excavator",
    "chassis": "excavator",
    "cabin": "excavator",
    "boom": "components",
    "stick": "components",
    "bucket": "components",
    "hydraulic_cylinder": "components",
    "hydraulic_rod": "components",
    "background": "environment",
    "terrain": "terrain",
    "other": "components",
}


class Stage13ExportEngine:
    """Safely deploys approved assets into the Flutter + Flame game project directory."""

    def __init__(self, target_base_dir: Optional[Path | str] = None):
        self.target_base_dir = Path(target_base_dir) if target_base_dir else DEFAULT_FLUTTER_ASSETS_DIR

    def prepare_export_plan(
        self,
        approved_components: List[Dict[str, Any]],
        destination_override: Optional[Path | str] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate preview plan of proposed exports without touching disk.
        """
        target_dir = Path(destination_override) if destination_override else self.target_base_dir
        plan = []

        for comp in approved_components:
            comp_type = comp.get("component_type", "other")
            subfolder = COMPONENT_SUBFOLDER_MAP.get(comp_type, "components")
            dest_folder = target_dir / subfolder

            source_file = comp.get("export_path") or comp.get("source_path")
            src_p = Path(source_file) if source_file else Path("unknown.png")

            target_filename = src_p.name if src_p.name else f"excavator_{comp_type}_{comp.get('id')}.png"
            dest_path = dest_folder / target_filename

            plan.append({
                "component_id": comp.get("id"),
                "component_name": comp.get("component_name", target_filename),
                "component_type": comp_type,
                "subfolder": subfolder,
                "source_file": str(src_p),
                "dest_path": str(dest_path),
                "pivot_norm": (comp.get("pivot_norm_x", 0.5), comp.get("pivot_norm_y", 0.5)),
                "dimensions": (comp.get("export_width", 0), comp.get("export_height", 0)),
                "approval_status": comp.get("approval_status", "Pending"),
                "already_exists": dest_path.exists(),
            })

        return plan

    def execute_export(
        self,
        approved_components: List[Dict[str, Any]],
        destination_override: Optional[Path | str] = None
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Execute export of approved components:
        1. Validate approval status (reject unapproved).
        2. Create canonical mobile folders.
        3. Copy image files.
        4. Validate every copied file.
        5. Write stage13_export_manifest.json to metadata/ subfolder.
        6. Record export job in SQLite database.
        """
        target_dir = Path(destination_override) if destination_override else self.target_base_dir

        # Filter strictly for approved components
        valid_items = [c for c in approved_components if c.get("approval_status") == "Approved"]
        if not valid_items:
            return False, {}, "No approved components to export. Only approved components may be exported."

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            for sub in ("excavator", "components", "environment", "terrain", "metadata"):
                (target_dir / sub).mkdir(parents=True, exist_ok=True)

            exported_records: List[Dict[str, Any]] = []
            errors: List[str] = []

            for comp in valid_items:
                comp_type = comp.get("component_type", "other")
                subfolder = COMPONENT_SUBFOLDER_MAP.get(comp_type, "components")
                dest_folder = target_dir / subfolder

                src_str = comp.get("export_path") or comp.get("source_path")
                if not src_str or not Path(src_str).is_file():
                    errors.append(f"Component {comp.get('id')} source file missing: {src_str}")
                    continue

                src_p = Path(src_str)
                dest_filename = src_p.name
                dest_p = dest_folder / dest_filename

                # Avoid destructive overwrites by appending suffix if not identical
                if dest_p.exists() and dest_p.resolve() != src_p.resolve():
                    dest_hash = compute_sha256(dest_p)
                    src_hash = compute_sha256(src_p)
                    if dest_hash != src_hash:
                        stem = src_p.stem
                        suffix = src_p.suffix
                        idx = 1
                        while (dest_folder / f"{stem}_{idx:02d}{suffix}").exists():
                            idx += 1
                        dest_p = dest_folder / f"{stem}_{idx:02d}{suffix}"

                # Copy file if source and dest are different paths
                if dest_p.resolve() != src_p.resolve():
                    shutil.copy2(src_p, dest_p)

                # Validate copied file opens successfully
                try:
                    with Image.open(dest_p) as pil_test:
                        w, h = pil_test.size
                        pil_test.verify()
                except Exception as e:
                    errors.append(f"Export validation failed on {dest_p.name}: {str(e)}")
                    continue

                # Relative asset path for Flame loader
                rel_path = f"images/{subfolder}/{dest_p.name}"

                exported_records.append({
                    "component_id": comp.get("id"),
                    "component_name": comp.get("component_name", dest_p.stem),
                    "component_type": comp_type,
                    "subfolder": subfolder,
                    "filename": dest_p.name,
                    "relative_asset_path": rel_path,
                    "export_path": str(dest_p),
                    "source_path": comp.get("source_path", ""),
                    "source_hash": comp.get("source_hash", ""),
                    "file_hash": compute_sha256(dest_p),
                    "dimensions": {"width": w, "height": h},
                    "pivot": {
                        "normalized_x": comp.get("pivot_norm_x", 0.5),
                        "normalized_y": comp.get("pivot_norm_y", 0.5),
                        "pixel_x": comp.get("pivot_pixel_x", 0),
                        "pixel_y": comp.get("pivot_pixel_y", 0),
                        "status": comp.get("pivot_status", "Verified"),
                    },
                    "flame_loading_code": f"final sprite = await Sprite.load('{rel_path}');",
                })

            # Generate export manifest
            manifest = {
                "manifest_version": "1.0.0",
                "export_stage": "Stage 13 Excavator Asset Preparation",
                "export_timestamp": datetime.now().isoformat(),
                "destination_dir": str(target_dir),
                "total_components_exported": len(exported_records),
                "components": exported_records,
                "subfolder_summary": {
                    "excavator": sum(1 for r in exported_records if r["subfolder"] == "excavator"),
                    "components": sum(1 for r in exported_records if r["subfolder"] == "components"),
                    "environment": sum(1 for r in exported_records if r["subfolder"] == "environment"),
                    "terrain": sum(1 for r in exported_records if r["subfolder"] == "terrain"),
                }
            }

            manifest_path = target_dir / "metadata" / "stage13_export_manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

            # Record job in database
            job_id = db.record_stage13_export_job({
                "destination_path": str(target_dir),
                "components_count": len(exported_records),
                "manifest_path": str(manifest_path),
                "status": "completed" if not errors else "completed_with_warnings",
                "details_json": json.dumps({
                    "exported_count": len(exported_records),
                    "error_count": len(errors),
                    "errors": errors,
                })
            })

            summary = {
                "job_id": job_id,
                "exported_count": len(exported_records),
                "manifest_path": str(manifest_path),
                "target_directory": str(target_dir),
                "errors": errors,
            }

            msg = f"Export completed: {len(exported_records)} approved components deployed to {target_dir}."
            if errors:
                msg += f" ({len(errors)} warnings encountered)."

            return True, summary, msg

        except Exception as e:
            logger.error("Stage 13 Export execution error: %s", e, exc_info=True)
            return False, {}, f"Export execution failed: {str(e)}"
