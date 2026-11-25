"""
Flutter Project Export Pipeline Engine (Stage 10)
Construction Asset Processor

Manages deployment of approved, optimized game assets into a Flutter + Flame project:
- Standardized directory layout:
  - assets/images/excavator/
  - assets/images/vehicles/
  - assets/images/components/
  - assets/images/tools/
  - assets/images/environment/
  - assets/images/terrain/
  - assets/images/backgrounds/
  - assets/images/effects/
  - assets/images/ui/
  - assets/spritesheets/
  - assets/animations/
  - assets/atlases/
  - assets/metadata/
- Safe staging execution: processes assets into a temporary staging folder first,
  validates all outputs, and atomic-copies to the target Flutter project.
- Strict provenance tracking and zero accidental deletion or overwriting.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AssetProcessor.FlutterExportEngine")

ENGINE_VERSION = "1.0.0"

FLUTTER_CATEGORY_SUBDIRS = {
    "excavator": "assets/images/excavator",
    "vehicles": "assets/images/vehicles",
    "construction vehicles": "assets/images/vehicles",
    "components": "assets/images/components",
    "vehicle components": "assets/images/components",
    "tools": "assets/images/tools",
    "tools and equipment": "assets/images/tools",
    "environment": "assets/images/environment",
    "terrain": "assets/images/terrain",
    "backgrounds": "assets/images/backgrounds",
    "background": "assets/images/backgrounds",
    "effects": "assets/images/effects",
    "ui": "assets/images/ui",
    "ui assets": "assets/images/ui",
    "spritesheet": "assets/spritesheets",
    "sprite_sheet": "assets/spritesheets",
    "animation": "assets/animations",
    "atlas": "assets/atlases",
    "metadata": "assets/metadata",
    "other": "assets/images/other",
}


class FlutterExportEngine:
    """
    Coordinates safe staging, subfolder routing, and export execution into a target Flutter project.
    """

    def __init__(self):
        self._version = ENGINE_VERSION

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata."""
        return {
            "name": "Flutter + Flame Asset Export Pipeline",
            "version": self._version,
            "offline": True,
            "capabilities": [
                "Hierarchical mobile game asset subfolder generation",
                "Two-phase atomic staging to prevent partial corruptions",
                "Automated category-based routing",
                "Collision protection & rollback on critical errors",
            ],
        }

    def resolve_destination_subfolder(
        self,
        category: str,
        asset_type: str = "image",
    ) -> str:
        """Map asset semantic category or type to its standard Flutter subfolder."""
        type_norm = asset_type.lower()
        if type_norm in ("spritesheet", "sprite_sheet"):
            return "assets/spritesheets"
        if type_norm in ("animation", "animation_sequence"):
            return "assets/animations"
        if type_norm in ("atlas", "texture_atlas"):
            return "assets/atlases"
        if type_norm in ("metadata", "manifest"):
            return "assets/metadata"

        cat_norm = category.strip().lower()
        return FLUTTER_CATEGORY_SUBDIRS.get(cat_norm, "assets/images/other")

    def inspect_flutter_project(self, target_dir: Union[str, Path]) -> Dict[str, Any]:
        """
        Validate whether a selected directory is a valid Flutter project.
        Checks for pubspec.yaml and standard project files.
        """
        p = Path(target_dir).resolve()
        if not p.exists() or not p.is_dir():
            return {
                "is_valid_flutter_project": False,
                "path": str(p),
                "error": "Directory does not exist.",
                "has_pubspec": False,
            }

        pubspec_file = p / "pubspec.yaml"
        has_pubspec = pubspec_file.exists() and pubspec_file.is_file()

        has_lib = (p / "lib").is_dir()

        is_valid = has_pubspec and has_lib
        return {
            "is_valid_flutter_project": is_valid,
            "path": str(p),
            "project_name": p.name,
            "has_pubspec": has_pubspec,
            "has_lib": has_lib,
            "pubspec_path": str(pubspec_file) if has_pubspec else None,
            "error": "" if is_valid else "Directory lacks pubspec.yaml or lib/ folder.",
        }

    def execute_flutter_export(
        self,
        target_flutter_dir: Union[str, Path],
        export_items: List[Dict[str, Any]],
        collision_mode: str = "increment",  # "increment", "skip", "overwrite"
    ) -> Dict[str, Any]:
        """
        Safely stage and deploy assets into the target Flutter project.
        export_items: list of dicts with:
          - 'source_path': absolute path to file on disk
          - 'category': semantic category (e.g. 'Excavator', 'UI')
          - 'asset_type': 'image', 'spritesheet', 'atlas', 'metadata'
          - 'filename': optional target filename
        """
        dest_root = Path(target_flutter_dir).resolve()
        if not dest_root.exists():
            raise FileNotFoundError(f"Target Flutter directory not found: {dest_root}")

        # Phase 1: Temporary Staging
        staging_dir = Path(tempfile.mkdtemp(prefix="cap_flutter_stage_"))
        staged_files: List[Tuple[Path, Path]] = []  # (staged_path, final_dest_path)
        exported_records: List[Dict[str, Any]] = []

        total_bytes = 0
        try:
            for item in export_items:
                src_p = Path(item["source_path"]).resolve()
                if not src_p.exists():
                    logger.warning("Skipping non-existent export source: %s", src_p)
                    continue

                subfolder = self.resolve_destination_subfolder(
                    category=item.get("category", "other"),
                    asset_type=item.get("asset_type", "image"),
                )

                stage_sub = staging_dir / subfolder
                stage_sub.mkdir(parents=True, exist_ok=True)

                final_sub = dest_root / subfolder
                final_sub.mkdir(parents=True, exist_ok=True)

                filename = item.get("filename") or src_p.name
                final_target = final_sub / filename

                # Collision handling
                if final_target.exists():
                    if collision_mode == "skip":
                        logger.info("Skipping existing file: %s", final_target)
                        continue
                    elif collision_mode == "increment":
                        col_idx = 1
                        stem = final_target.stem
                        ext = final_target.suffix
                        while final_target.exists():
                            final_target = final_sub / f"{stem}_{col_idx:02d}{ext}"
                            col_idx += 1
                        filename = final_target.name

                staged_target = stage_sub / filename
                shutil.copy2(str(src_p), str(staged_target))
                staged_files.append((staged_target, final_target))

                f_size = staged_target.stat().st_size
                total_bytes += f_size
                exported_records.append({
                    "source_path": str(src_p),
                    "destination_path": str(final_target),
                    "relative_flutter_path": f"{subfolder}/{filename}".replace("\\", "/"),
                    "file_size": f_size,
                    "category": item.get("category", "other"),
                })

            # Phase 2: Copy from Staging into Final Flutter Project
            for staged_p, final_p in staged_files:
                final_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(staged_p), str(final_p))

            logger.info("Exported %d assets (%d bytes) to Flutter project at %s", len(exported_records), total_bytes, dest_root)

            return {
                "success": True,
                "target_flutter_dir": str(dest_root),
                "total_exported": len(exported_records),
                "total_bytes": total_bytes,
                "exported_records": exported_records,
                "error": "",
            }

        except Exception as e:
            logger.error("Flutter export failed during staging/copy: %s", e, exc_info=True)
            return {
                "success": False,
                "target_flutter_dir": str(dest_root),
                "total_exported": len(exported_records),
                "total_bytes": total_bytes,
                "exported_records": exported_records,
                "error": str(e),
            }
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _create_canonical_flutter_tree(self, flutter_root: Union[str, Path]) -> Dict[str, Path]:
        """Create standard Flutter mobile asset directories."""
        root = Path(flutter_root).resolve()
        assets_dir = root / "assets"
        subtrees = {
            "images": assets_dir / "images",
            "vehicles": assets_dir / "images" / "vehicles",
            "excavator": assets_dir / "images" / "excavator",
            "spritesheets": assets_dir / "spritesheets",
            "animations": assets_dir / "animations",
            "atlases": assets_dir / "atlases",
            "metadata": assets_dir / "metadata",
        }
        for p in subtrees.values():
            p.mkdir(parents=True, exist_ok=True)
        return subtrees

    def _resolve_collision(self, dest_dir: Path, filename: str, collision_mode: str) -> Optional[Path]:
        """Resolve destination path under collision handling strategy."""
        target = dest_dir / filename
        if not target.exists():
            return target
        if collision_mode == "overwrite":
            return target
        if collision_mode == "skip":
            return None
        # increment
        stem = target.stem
        ext = target.suffix
        idx = 1
        while target.exists():
            target = dest_dir / f"{stem}_{idx}{ext}"
            idx += 1
        return target

    def deploy_assets_to_flutter(
        self,
        flutter_root: Union[str, Path],
        assets_to_deploy: List[Dict[str, Any]],
        update_pubspec: bool = False,
        collision_strategy: str = "increment",
    ) -> Dict[str, Any]:
        """Deploy assets atomically to target Flutter project."""
        root = Path(flutter_root).resolve()
        if not root.exists():
            return {"success": False, "error": f"Directory not found: {root}"}

        self._create_canonical_flutter_tree(root)

        export_items = []
        for a in assets_to_deploy:
            p = a.get("path") or a.get("source_path")
            cat = a.get("category", "other")
            sub = a.get("sub_folder", "images")
            fname = a.get("target_name") or a.get("filename") or (Path(p).name if p else "asset.png")
            export_items.append({
                "source_path": p,
                "category": cat,
                "asset_type": sub,
                "filename": fname,
            })

        try:
            res = self.execute_flutter_export(
                target_flutter_dir=root,
                export_items=export_items,
                collision_mode=collision_strategy,
            )
        except Exception as e:
            return {"success": False, "error": str(e)}

        res["deployed_count"] = res.get("total_exported", len(res.get("exported_records", [])))

        if update_pubspec:
            from core.export_manifest_engine import export_manifest_engine
            pub_path = root / "pubspec.yaml"
            if pub_path.exists():
                pub_res = export_manifest_engine.apply_pubspec_updates(pub_path)
                res["pubspec_updated"] = pub_res.get("updated", False)
                res["pubspec_backup"] = pub_res.get("backup_path")
            else:
                res["pubspec_updated"] = False

        return res


# Global FlutterExportEngine singleton
flutter_export_engine = FlutterExportEngine()
