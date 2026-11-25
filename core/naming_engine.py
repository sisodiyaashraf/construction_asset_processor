"""
Construction Asset Processor - Smart Asset Renaming Engine (Stage 4)
Generates standardized, semantic, lowercase snake_case filenames for 2D construction simulator assets.
Detects naming collisions, resolves duplicates, and coordinates with SQLite and filesystem.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.database import db

logger = logging.getLogger("AssetProcessor.NamingEngine")

# Known colors and view angles for semantic tagging
KNOWN_COLORS = {
    "yellow", "red", "orange", "blue", "green", "black", "white", "gray", "grey"
}

KNOWN_VIEWS = {
    "side_view", "side", "front_view", "front", "top_view", "top", "isometric", "perspective", "profile"
}

# Object category normalization mappings
EXCAVATOR_PARTS = {
    "cabin", "boom", "arm", "bucket", "track", "track_wheel", "sprocket",
    "hydraulic_cylinder", "hydraulic_piston", "hydraulic_hose", "attachment",
    "excavator_body", "chassis", "undercarriage", "counterweight"
}

CONSTRUCTION_VEHICLES = {
    "excavator", "bulldozer", "wheel_loader", "dump_truck", "cargo_truck",
    "crane", "road_roller", "forklift", "concrete_mixer"
}

TOOLS = {
    "shovel", "hammer", "wrench", "drill", "jackhammer", "cone", "barrier",
    "ladder", "toolbox"
}

ENVIRONMENT = {
    "sky", "cloud", "clouds", "mountain", "mountains", "hill", "hills",
    "tree", "trees", "grass", "ground", "soil", "rock", "rocks", "gravel",
    "sand", "road", "asphalt", "construction_site", "building", "factory"
}

UI_ELEMENTS = {
    "button", "icon", "panel", "hud", "joystick", "control", "progress_bar",
    "menu_background", "game_logo"
}


def sanitize_token(token: str) -> str:
    """Normalize a single token to lowercase alphanumeric characters."""
    token = str(token).lower().strip()
    token = re.sub(r"[^a-z0-9_]", "_", token)
    token = re.sub(r"_+", "_", token)
    return token.strip("_")


def clean_filename(base_name: str, extension: str) -> str:
    """
    Ensure base name adheres strictly to naming rules:
    - Lowercase snake_case
    - Only [a-z0-9_]
    - No consecutive underscores
    - Preserves file extension (with dot)
    """
    clean_base = sanitize_token(base_name)
    if not clean_base:
        clean_base = "construction_asset"

    ext = extension.lower().strip()
    if not ext.startswith("."):
        ext = f".{ext}" if ext else ".png"

    # Enforce safe characters in extension
    ext = "." + re.sub(r"[^a-z0-9]", "", ext.lstrip("."))
    if ext == ".":
        ext = ".png"

    return f"{clean_base}{ext}"


class NamingEngine:
    """
    Standardized filename generator and collision detector for 2D simulator assets.
    """

    def __init__(self, database=None):
        self.db = database or db

    def generate_name_for_asset(self, asset: Dict[str, Any]) -> str:
        """
        Generate a standardized semantic filename for an asset dictionary.
        Follows the structure:
        [prefix]_[main_object]_[subtype/part]_[color]_[view/purpose]_[composition].[ext]
        """
        orig_name = asset.get("filename", "")
        ext = Path(orig_name).suffix or ".png"

        main_cat = sanitize_token(asset.get("main_category") or "")
        subcat = sanitize_token(asset.get("subcategory") or "")
        obj_name = sanitize_token(asset.get("object_name") or "")
        collection = sanitize_token(asset.get("collection") or "")
        comp_type = asset.get("composition_type") or "Single Object"

        # Parse visual tags
        raw_tags = asset.get("visual_tags", [])
        if isinstance(raw_tags, str):
            try:
                tags_list = json.loads(raw_tags)
            except Exception:
                tags_list = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, (list, tuple, set)):
            tags_list = list(raw_tags)
        else:
            tags_list = []

        clean_tags = [sanitize_token(t) for t in tags_list if t]

        # 1. Identify Color if visually supported
        found_color = ""
        for tag in clean_tags:
            for color in KNOWN_COLORS:
                if color in tag:
                    found_color = "gray" if color == "grey" else color
                    break
            if found_color:
                break

        # 2. Identify View Angle
        found_view = ""
        for tag in clean_tags:
            for view in KNOWN_VIEWS:
                if view in tag:
                    found_view = "side_view" if view in ("side", "profile") else view
                    break
            if found_view:
                break

        # Default view to side_view ONLY for vehicles/excavator parts if side-view simulator
        # Do not default to side_view for backgrounds, textures, or general environment
        is_env_or_bg = (
            "environment" in main_cat or
            "background" in obj_name or
            "scene" in obj_name or
            comp_type in ("Background Image", "Full Scene") or
            any(e in obj_name for e in ("sky", "ground", "soil", "rock", "road", "site"))
        )
        if not found_view and not is_env_or_bg:
            if "excavator" in collection or "vehicle" in main_cat or "excavator" in obj_name:
                found_view = "side_view"

        # 3. Assemble tokens based on category and object
        tokens: List[str] = []

        # Excavator collection or parts
        if "excavator" in collection or "excavator" in main_cat or "excavator" in obj_name:
            tokens.append("excavator")
            part_name = ""
            if obj_name and obj_name != "excavator":
                part_name = obj_name.replace("excavator_", "")
            elif subcat and subcat != "excavator":
                part_name = subcat.replace("excavator_", "")

            if part_name:
                tokens.append(part_name)

            if found_color and found_color not in part_name:
                tokens.append(found_color)
            if found_view and found_view not in tokens and not is_env_or_bg:
                tokens.append(found_view)

        # Construction Vehicles
        elif any(v in obj_name or v in subcat for v in CONSTRUCTION_VEHICLES):
            tokens.append("construction")
            v_name = obj_name or subcat
            tokens.append(v_name.replace("construction_", ""))
            if found_color:
                tokens.append(found_color)
            if found_view and found_view not in tokens:
                tokens.append(found_view)

        # Tools & Equipment
        elif "tool" in main_cat or any(t in obj_name or t in subcat for t in TOOLS):
            tokens.append("construction")
            tool_name = obj_name or subcat or "tool"
            tokens.append(tool_name.replace("construction_", ""))
            if "tool" not in tokens:
                tokens.append("tool")

        # Environment
        elif "environment" in main_cat or any(e in obj_name or e in subcat for e in ENVIRONMENT):
            tokens.append("construction")
            env_name = obj_name or subcat or "environment"
            tokens.append(env_name.replace("construction_", ""))
            if "texture" in clean_tags or "texture" in orig_name.lower():
                tokens.append("texture")
            elif "background" in clean_tags or comp_type in ("Background Image", "Full Scene"):
                if "background" not in str(tokens):
                    tokens.append("background")

        # Game UI
        elif "ui" in main_cat or "interface" in main_cat or any(u in obj_name for u in UI_ELEMENTS):
            tokens.append("game")
            ui_name = obj_name or subcat or "ui"
            tokens.append(ui_name.replace("game_", ""))
            if "button" in clean_tags or "button" in ui_name:
                if "button" not in tokens:
                    tokens.append("button")
            elif "icon" in clean_tags or "icon" in ui_name:
                if "icon" not in tokens:
                    tokens.append("icon")

        # General / Fallback
        else:
            prefix = "excavator" if "excavator" in collection else "construction"
            tokens.append(prefix)
            if obj_name and obj_name != "unknown":
                tokens.append(obj_name)
            elif subcat and subcat != "unknown":
                tokens.append(subcat)
            else:
                tokens.append("asset")

            if found_color:
                tokens.append(found_color)

        # 4. Handle Composition Suffix (avoid duplication if already in tokens)
        joined_current = "_".join(tokens)
        if comp_type == "Sprite Sheet" or "sheet" in clean_tags:
            if "sheet" not in joined_current:
                tokens.append("sheet")
        elif comp_type == "Reference Collection" or comp_type == "Multiple Objects":
            if "collection" not in joined_current and "parts" not in joined_current:
                tokens.append("parts")
        elif comp_type == "Animation Frames":
            if "anim" not in joined_current and "frames" not in joined_current:
                tokens.append("anim")
        elif comp_type in ("Background Image", "Full Scene"):
            if "background" not in joined_current and "bg" not in joined_current:
                tokens.append("background")

        # 5. Clean up duplicates in tokens while preserving order
        dedup_tokens: List[str] = []
        for t in tokens:
            t_clean = sanitize_token(t)
            if t_clean and t_clean not in dedup_tokens:
                dedup_tokens.append(t_clean)

        raw_base = "_".join(dedup_tokens)
        return clean_filename(raw_base, ext)

    def process_all_assets(self, assets: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Generate smart filenames for all provided assets (or all assets in DB),
        detect collisions, and resolve them with numbered suffixes while flagging conflicts.
        Returns list of result dicts:
        {
            'asset_id': int,
            'original_filename': str,
            'original_path': str,
            'suggested_filename': str,
            'base_suggestion': str,
            'naming_conflict': int (0 or 1),
            'conflict_reason': str,
            'naming_status': str,
        }
        """
        if assets is None:
            assets = self.db.get_assets(limit=10000, sort_by="id", ascending=True)

        if not assets:
            return []

        # 1. First pass: Generate base smart names
        base_proposals: List[Dict[str, Any]] = []
        for asset in assets:
            base_name = self.generate_name_for_asset(asset)
            base_proposals.append({
                "asset_id": asset["id"],
                "asset": asset,
                "original_filename": asset["filename"],
                "original_path": asset.get("current_path") or asset.get("original_path", ""),
                "base_suggestion": base_name,
                "suggested_filename": base_name,
                "naming_conflict": 0,
                "conflict_reason": "",
                "naming_status": asset.get("naming_status") or "pending",
            })

        # 2. Collision Detection: Group by proposed filename per destination folder
        # Files are in input/excavator/original or input/other_images/original
        folder_groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in base_proposals:
            orig_p = Path(item["original_path"])
            folder_key = str(orig_p.parent)
            folder_groups.setdefault(folder_key, []).append(item)

        results: List[Dict[str, Any]] = []

        for folder_path, items in folder_groups.items():
            folder = Path(folder_path)
            # Track existing files on disk in this directory (excluding files that are being renamed)
            existing_disk_files = {f.name.lower() for f in folder.iterdir() if f.is_file()} if folder.exists() else set()
            orig_names_in_folder = {it["original_filename"].lower() for it in items}

            # Frequency map of base suggestions in this folder
            name_counts: Dict[str, int] = {}
            for it in items:
                name_counts[it["base_suggestion"]] = name_counts.get(it["base_suggestion"], 0) + 1

            # Sequence counters for collision resolution
            seq_tracker: Dict[str, int] = {}

            for it in items:
                base_name = it["base_suggestion"]
                stem = Path(base_name).stem
                suffix = Path(base_name).suffix

                is_duplicate = name_counts[base_name] > 1

                if is_duplicate:
                    it["naming_conflict"] = 1
                    it["conflict_reason"] = f"Collision: {name_counts[base_name]} assets proposed '{base_name}'"
                    # Resolve with sequential numbering _01, _02, etc.
                    cur_idx = seq_tracker.get(base_name, 0) + 1
                    seq_tracker[base_name] = cur_idx
                    resolved_name = f"{stem}_{cur_idx:02d}{suffix}"

                    # Ensure resolved name doesn't collide with non-batch disk file
                    while resolved_name.lower() in (existing_disk_files - orig_names_in_folder):
                        cur_idx += 1
                        resolved_name = f"{stem}_{cur_idx:02d}{suffix}"

                    it["suggested_filename"] = resolved_name
                else:
                    # Single proposal, but check if it already exists on disk and is NOT this asset
                    if (base_name.lower() in existing_disk_files and
                            base_name.lower() != it["original_filename"].lower()):
                        it["naming_conflict"] = 1
                        it["conflict_reason"] = f"Collision: File '{base_name}' already exists on disk"
                        # Generate non-colliding alternative
                        cur_idx = 2
                        resolved_name = f"{stem}_{cur_idx:02d}{suffix}"
                        while resolved_name.lower() in existing_disk_files:
                            cur_idx += 1
                            resolved_name = f"{stem}_{cur_idx:02d}{suffix}"
                        it["suggested_filename"] = resolved_name
                    else:
                        it["naming_conflict"] = 0
                        it["suggested_filename"] = base_name

                results.append(it)

        return results

    def apply_batch_suggestions(self, proposals: List[Dict[str, Any]]) -> int:
        """Save generated suggestions into SQLite database."""
        count = 0
        for p in proposals:
            asset_id = p["asset_id"]
            sug_name = p["suggested_filename"]
            conflict = p["naming_conflict"]
            # If asset already had an approved name or manual edit, don't overwrite blindly
            existing = p.get("asset") or self.db.get_asset(asset_id)
            current_status = existing.get("naming_status", "pending") if existing else "pending"

            status_to_set = "conflict" if conflict else current_status
            if status_to_set not in ("approved", "manual", "conflict"):
                status_to_set = "pending"

            success = self.db.update_naming(
                asset_id=asset_id,
                suggested_filename=sug_name,
                naming_status=status_to_set,
                naming_conflict=conflict
            )
            if success:
                count += 1

        self.db.log_event(
            action="Batch Names Generated",
            stage="renaming",
            message=f"Generated and updated smart filenames for {count} assets.",
            status="success"
        )
        return count


# Global instance
naming_engine = NamingEngine()
