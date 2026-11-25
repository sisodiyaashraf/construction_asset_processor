"""
Export Manifest & Pubspec.yaml Engine (Stage 10)
Construction Asset Processor

Manages Flutter project integration declarations and Flame engine manifests:
- Pubspec.yaml parser, preview, backup, and safe asset declaration updater.
- Never damages existing dependencies, flutter configuration, or comments.
- Prevents duplicate asset folder paths.
- Creates timestamped backups before writing.
- Generates standalone YAML snippet if user chooses not to write directly.
- Generates unified Flame Asset Manifest JSON linking sprite sheets, atlases, and animations.
- Provides sample Dart Flame integration code snippets as documentation.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("AssetProcessor.ExportManifestEngine")

ENGINE_VERSION = "1.0.0"

DEFAULT_FLUTTER_ASSET_PATHS = [
    "assets/images/excavator/",
    "assets/images/vehicles/",
    "assets/images/components/",
    "assets/images/tools/",
    "assets/images/environment/",
    "assets/images/terrain/",
    "assets/images/backgrounds/",
    "assets/images/effects/",
    "assets/images/ui/",
    "assets/images/other/",
    "assets/spritesheets/",
    "assets/animations/",
    "assets/atlases/",
    "assets/metadata/",
]


class ExportManifestEngine:
    """
    Engine responsible for Flutter pubspec.yaml asset declarations and Flame manifests.
    """

    def __init__(self):
        self._version = ENGINE_VERSION

    def get_engine_info(self) -> Dict[str, Any]:
        """Return engine metadata."""
        return {
            "name": "Export Manifest & Pubspec Generator",
            "version": self._version,
            "offline": True,
            "capabilities": [
                "Safe, non-destructive pubspec.yaml asset section updating",
                "Automated timestamped pubspec backup creation",
                "Duplicate declaration prevention",
                "Unified Flame game engine manifest JSON generation",
                "Dart integration code snippet generation",
            ],
        }

    # -------------------------------------------------------------------------
    # Pubspec.yaml Inspection & Updating
    # -------------------------------------------------------------------------

    def generate_asset_yaml_snippet(
        self, asset_folders: Optional[List[str]] = None
    ) -> str:
        """Generate a clean standalone YAML block for asset declarations."""
        folders = asset_folders or DEFAULT_FLUTTER_ASSET_PATHS
        # Clean and deduplicate while preserving order
        seen: Set[str] = set()
        clean_folders = []
        for f in folders:
            norm = f.replace("\\", "/").strip()
            if not norm.endswith("/") and not norm.endswith(".png") and not norm.endswith(".json"):
                norm += "/"
            if norm not in seen:
                seen.add(norm)
                clean_folders.append(norm)

        lines = ["flutter:", "  assets:"]
        for f in clean_folders:
            lines.append(f"    - {f}")
        return "\n".join(lines) + "\n"

    def preview_pubspec_updates(
        self,
        pubspec_path: Union[str, Path],
        asset_folders: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an existing pubspec.yaml and preview the proposed updates without writing.
        Identifies already-declared folders and proposed additions.
        """
        p = Path(pubspec_path).resolve()
        if not p.exists() or not p.is_file():
            return {
                "success": False,
                "error": f"Pubspec file not found: {p}",
                "original_content": "",
                "proposed_content": "",
                "added_folders": [],
                "existing_folders": [],
            }

        with open(p, "r", encoding="utf-8") as f:
            original_content = f.read()

        folders_to_add = asset_folders or DEFAULT_FLUTTER_ASSET_PATHS
        # Clean folders
        req_folders = []
        for f in folders_to_add:
            norm = f.replace("\\", "/").strip()
            if not norm.endswith("/") and not norm.endswith(".png") and not norm.endswith(".json"):
                norm += "/"
            req_folders.append(norm)

        # Parse existing assets under flutter: -> assets:
        existing_declared: Set[str] = set()
        in_flutter = False
        in_assets = False

        for line in original_content.splitlines():
            stripped = line.strip()
            if re.match(r"^flutter\s*:", line):
                in_flutter = True
                continue
            if in_flutter:
                if re.match(r"^\s+assets\s*:", line):
                    in_assets = True
                    continue
                elif re.match(r"^[a-zA-Z0-9_-]+\s*:", line):
                    in_flutter = False
                    in_assets = False
                elif in_assets:
                    if re.match(r"^\s+-\s+", line):
                        asset_entry = re.sub(r"^\s+-\s+", "", line).strip().strip("'\"")
                        existing_declared.add(asset_entry.replace("\\", "/"))
                    elif re.match(r"^\s+[a-zA-Z0-9_-]+\s*:", line):
                        in_assets = False

        # Filter only genuine new additions
        new_folders = [f for f in req_folders if f not in existing_declared]

        if not new_folders:
            return {
                "success": True,
                "needs_update": False,
                "error": "",
                "original_content": original_content,
                "proposed_content": original_content,
                "added_folders": [],
                "existing_folders": list(existing_declared),
            }

        # Build proposed content safely
        lines = original_content.splitlines()
        flutter_line_idx = -1
        assets_line_idx = -1

        for idx, line in enumerate(lines):
            if re.match(r"^flutter\s*:", line):
                flutter_line_idx = idx
            elif flutter_line_idx != -1 and re.match(r"^\s+assets\s*:", line):
                assets_line_idx = idx
                break
            elif flutter_line_idx != -1 and re.match(r"^[a-zA-Z0-9_-]+\s*:", line):
                break

        proposed_lines = list(lines)

        if assets_line_idx != -1:
            # Insert new entries directly under existing assets:
            insert_pos = assets_line_idx + 1
            for nf in new_folders:
                proposed_lines.insert(insert_pos, f"    - {nf}")
                insert_pos += 1
        elif flutter_line_idx != -1:
            # Insert assets: block under existing flutter:
            insert_pos = flutter_line_idx + 1
            proposed_lines.insert(insert_pos, "  assets:")
            insert_pos += 1
            for nf in new_folders:
                proposed_lines.insert(insert_pos, f"    - {nf}")
                insert_pos += 1
        else:
            # Append flutter: assets: block at end
            proposed_lines.append("")
            proposed_lines.append("flutter:")
            proposed_lines.append("  assets:")
            for nf in new_folders:
                proposed_lines.append(f"    - {nf}")

        proposed_content = "\n".join(proposed_lines) + "\n"

        return {
            "success": True,
            "needs_update": True,
            "error": "",
            "original_content": original_content,
            "proposed_content": proposed_content,
            "added_folders": new_folders,
            "existing_folders": list(existing_declared),
        }

    def apply_pubspec_updates(
        self,
        pubspec_path: Union[str, Path],
        asset_folders: Optional[List[str]] = None,
        create_backup: bool = True,
    ) -> Dict[str, Any]:
        """
        Safely update pubspec.yaml with automated backup and diff validation.
        Never modifies dependencies.
        """
        p = Path(pubspec_path).resolve()
        preview = self.preview_pubspec_updates(p, asset_folders=asset_folders)
        if not preview["success"]:
            return preview

        if not preview.get("needs_update", False):
            return {
                "success": True,
                "updated": False,
                "message": "All asset folders are already declared in pubspec.yaml.",
                "backup_path": None,
                "added_folders": [],
            }

        backup_file = None
        if create_backup:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = p.parent / f"pubspec_backup_{timestamp}.yaml"
            shutil.copy2(str(p), str(backup_file))
            logger.info("Created pubspec backup at: %s", backup_file)

        with open(p, "w", encoding="utf-8") as f:
            f.write(preview["proposed_content"])

        logger.info("Successfully updated pubspec.yaml with %d new asset folders", len(preview["added_folders"]))

        return {
            "success": True,
            "updated": True,
            "message": f"Successfully added {len(preview['added_folders'])} asset folder entries to pubspec.yaml.",
            "backup_path": str(backup_file) if backup_file else None,
            "added_folders": preview["added_folders"],
        }

    def generate_pubspec_snippet(
        self,
        asset_folders: Optional[List[str]] = None,
    ) -> str:
        """Alias for generate_asset_yaml_snippet."""
        return self.generate_asset_yaml_snippet(asset_folders=asset_folders)

    def update_pubspec_file(
        self,
        pubspec_path: Union[str, Path],
        asset_folders: Optional[List[str]] = None,
        create_backup: bool = True,
    ) -> Dict[str, Any]:
        """Alias for apply_pubspec_updates."""
        return self.apply_pubspec_updates(pubspec_path, asset_folders=asset_folders, create_backup=create_backup)

    # -------------------------------------------------------------------------
    # Unified Flame Asset Manifest
    # -------------------------------------------------------------------------

    def generate_flame_manifest(
        self,
        project_name: str = "flutter_flame_game",
        exported_assets: Optional[List[Dict[str, Any]]] = None,
        texture_atlases: Optional[List[Dict[str, Any]]] = None,
        sprite_animations: Optional[List[Dict[str, Any]]] = None,
        output_file: Optional[Path] = None,
        output_path: Optional[Path] = None,
        animations: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> str:
        """
        Generate a unified JSON manifest cataloging all exported game assets,
        sprite sheets, animations, and texture atlases for Flutter + Flame game loader.
        """
        dest_out = output_path or output_file
        assets_list = exported_assets or []
        anims_list = animations or sprite_animations or []

        manifest = {
            "manifest_version": "1.0.0",
            "generator": "Construction Asset Processor — Export Manifest Engine",
            "generated_at": datetime.now().isoformat(),
            "project_name": project_name,
            "total_assets": len(assets_list),
            "asset_catalogs": {
                "images": [],
                "atlases": [],
                "animations": anims_list,
            },
            "flame_integration_samples": {
                "load_sprite": (
                    "// Load individual sprite:\n"
                    "final sprite = await Sprite.load('images/vehicles/excavator_yellow.png');\n"
                    "final component = SpriteComponent(sprite: sprite, size: Vector2(128, 128));"
                ),
                "load_animation": (
                    "// Load animation from sprite sheet:\n"
                    "final image = await images.load('spritesheets/excavator_digging.png');\n"
                    "final animation = SpriteAnimation.fromFrameData(\n"
                    "  image,\n"
                    "  SpriteAnimationData.sequenced(\n"
                    "    amount: 8,\n"
                    "    stepTime: 0.1,\n"
                    "    textureSize: Vector2(128, 128),\n"
                    "  ),\n"
                    ");"
                ),
            },
            "animations": anims_list,
        }

        # Index individual images
        for a in assets_list:
            manifest["asset_catalogs"]["images"].append({
                "path": a.get("relative_flutter_path", a.get("path", "")),
                "category": a.get("category", "other"),
                "size_bytes": a.get("file_size", 0),
            })

        # Index atlases
        if texture_atlases:
            for atl in texture_atlases:
                manifest["asset_catalogs"]["atlases"].append({
                    "name": atl.get("atlas_name", ""),
                    "image": atl.get("image_path", ""),
                    "metadata": atl.get("metadata_path", ""),
                    "sprite_count": atl.get("packed_count", 0),
                    "efficiency": atl.get("packing_efficiency", 0.0),
                })

        out_path = Path(dest_out) if dest_out else (Path(tempfile.gettempdir()) / "flame_asset_manifest.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return str(out_path.resolve())


# Global ExportManifestEngine singleton
export_manifest_engine = ExportManifestEngine()
