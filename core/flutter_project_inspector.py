"""
Flutter Project Inspector (Stage 11)
Construction Asset Processor

Inspects connected Flutter + Flame projects:
- Detects pubspec.yaml, lib/, and assets/ directory trees.
- Parses dependencies for Flame engine modules (flame, flame_audio, flame_forge2d, etc.).
- Evaluates declared asset directories vs on-disk presence.
- Analyzes Dart source files for Flame asset loading conventions (images.load, Sprite.load, SpriteAnimation).
- Detects Flutter CLI availability.
- Strictly non-destructive: never writes or modifies any file during inspection.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger("AssetProcessor.FlutterProjectInspector")

ENGINE_VERSION = "1.0.0"

KNOWN_FLAME_PACKAGES = [
    "flame",
    "flame_audio",
    "flame_forge2d",
    "flame_tiled",
    "flame_rive",
    "flame_svg",
    "flame_isolate",
    "flame_bloc",
    "flame_network_assets",
]


class FlutterProjectInspector:
    """Read-only inspector for external Flutter + Flame mobile projects."""

    def __init__(self):
        self._flutter_bin_cached: Optional[str] = None

    def get_inspector_info(self) -> Dict[str, Any]:
        """Return inspector module capabilities."""
        return {
            "name": "Flutter + Flame Project Inspector",
            "version": ENGINE_VERSION,
            "offline": True,
            "read_only": True,
            "supported_checks": [
                "pubspec.yaml syntax & Flame dependency resolution",
                "Asset declarations vs filesystem existence",
                "Flame game entry points & component detection",
                "Asset loading convention static analysis",
            ],
        }

    def detect_flutter_cli(self) -> Dict[str, Any]:
        """Detect whether flutter CLI is available in PATH or system environments."""
        exe = shutil.which("flutter")
        if not exe:
            return {
                "available": False,
                "executable": "",
                "version": "",
                "message": "Flutter CLI was not found in system PATH.",
            }

        try:
            res = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            version_line = res.stdout.splitlines()[0] if res.stdout else "Flutter (version unknown)"
            return {
                "available": True,
                "executable": exe,
                "version": version_line.strip(),
                "message": f"Detected: {version_line.strip()}",
            }
        except Exception as e:
            return {
                "available": False,
                "executable": exe,
                "version": "",
                "message": f"Error querying Flutter CLI: {e}",
            }

    def inspect_project(self, project_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Perform comprehensive non-destructive inspection of a candidate Flutter project.
        Never alters source files.
        """
        p = Path(project_path).resolve() if project_path else None
        if not p or not p.exists():
            return {
                "is_valid_flutter_project": False,
                "project_path": str(p) if p else "",
                "project_name": "",
                "status": "invalid_path",
                "error": "The specified directory path does not exist on disk.",
                "warnings": ["Directory does not exist."],
                "has_pubspec": False,
                "has_lib": False,
                "has_assets": False,
                "flame_detected": False,
                "flame_version": "Not Detected",
                "flame_packages": {},
                "declared_asset_dirs": [],
                "missing_asset_dirs": [],
                "existing_asset_dirs": [],
                "game_files": [],
                "loading_conventions": [],
            }

        if not p.is_dir():
            return {
                "is_valid_flutter_project": False,
                "project_path": str(p),
                "project_name": p.name,
                "status": "not_a_directory",
                "error": "Target path is a file, not a directory.",
                "warnings": ["Target path is not a directory."],
                "has_pubspec": False,
                "has_lib": False,
                "has_assets": False,
                "flame_detected": False,
                "flame_version": "Not Detected",
                "flame_packages": {},
                "declared_asset_dirs": [],
                "missing_asset_dirs": [],
                "existing_asset_dirs": [],
                "game_files": [],
                "loading_conventions": [],
            }

        # 1. Check for pubspec.yaml
        pubspec_file = p / "pubspec.yaml"
        has_pubspec = pubspec_file.exists() and pubspec_file.is_file()
        if not has_pubspec:
            return {
                "is_valid_flutter_project": False,
                "project_path": str(p),
                "project_name": p.name,
                "status": "missing_pubspec",
                "error": "No pubspec.yaml found in target directory. Not a valid Flutter project.",
                "warnings": ["Missing pubspec.yaml root configuration file."],
                "has_pubspec": False,
                "has_lib": (p / "lib").is_dir(),
                "has_assets": (p / "assets").is_dir(),
                "flame_detected": False,
                "flame_version": "Not Detected",
                "flame_packages": {},
                "declared_asset_dirs": [],
                "missing_asset_dirs": [],
                "existing_asset_dirs": [],
                "game_files": [],
                "loading_conventions": [],
            }

        # 2. Parse pubspec.yaml contents
        parsed_pub = self._parse_pubspec(pubspec_file)

        # 3. Inspect directory structure
        has_lib = (p / "lib").is_dir()
        has_assets = (p / "assets").is_dir()
        has_android = (p / "android").is_dir()
        has_test = (p / "test").is_dir()

        warnings = []
        if not has_lib:
            warnings.append("Project lacks standard 'lib/' Dart directory.")
        if not has_assets:
            warnings.append("Project lacks 'assets/' directory.")

        # 4. Validate declared asset folders
        declared_dirs = parsed_pub.get("declared_assets", [])
        existing_dirs = []
        missing_dirs = []

        for decl in declared_dirs:
            # Handle normalized paths
            norm_rel = decl.strip().replace("\\", "/").rstrip("/")
            disk_p = p / norm_rel
            if disk_p.exists():
                existing_dirs.append(decl)
            else:
                missing_dirs.append(decl)

        if missing_dirs:
            warnings.append(f"{len(missing_dirs)} declared asset paths in pubspec.yaml do not exist on disk.")

        # 5. Detect Flame Game code and asset loading conventions
        game_files, loading_conventions = self._inspect_dart_files(p)

        flame_detected = parsed_pub.get("flame_detected", False) or bool(game_files)
        flame_ver = parsed_pub.get("flame_version", "Not Detected")

        if not flame_detected:
            warnings.append("Flame package is not declared in dependencies. Game integration features will run in generic asset mode.")

        is_valid = has_pubspec and (has_lib or parsed_pub.get("has_flutter_sdk", False))

        return {
            "is_valid_flutter_project": is_valid,
            "project_path": str(p),
            "project_name": parsed_pub.get("name") or p.name,
            "pubspec_path": str(pubspec_file),
            "status": "verified" if is_valid else "incomplete",
            "error": "",
            "warnings": warnings,
            "has_pubspec": True,
            "has_lib": has_lib,
            "has_assets": has_assets,
            "has_android": has_android,
            "has_test": has_test,
            "flutter_sdk_required": parsed_pub.get("sdk_constraint", ""),
            "flame_detected": flame_detected,
            "flame_version": flame_ver,
            "flame_packages": parsed_pub.get("flame_packages", {}),
            "declared_asset_dirs": declared_dirs,
            "existing_asset_dirs": existing_dirs,
            "missing_asset_dirs": missing_dirs,
            "game_files": game_files,
            "loading_conventions": loading_conventions,
        }

    def _parse_pubspec(self, pubspec_path: Path) -> Dict[str, Any]:
        """Parse pubspec.yaml safely extracting project name, dependencies, and assets."""
        res = {
            "name": "",
            "sdk_constraint": "",
            "has_flutter_sdk": False,
            "flame_detected": False,
            "flame_version": "Not Detected",
            "flame_packages": {},
            "declared_assets": [],
        }

        try:
            with open(pubspec_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            logger.warning("Failed to read pubspec.yaml: %s", e)
            return res

        in_deps = False
        in_dev_deps = False
        in_flutter = False
        in_assets = False

        for raw_line in lines:
            line = raw_line.rstrip()

            # Name match
            if re.match(r"^name\s*:\s*(.+)$", line):
                res["name"] = re.match(r"^name\s*:\s*(.+)$", line).group(1).strip().strip("'\"")
                continue

            # Section headers
            if re.match(r"^dependencies\s*:", line):
                in_deps = True
                in_dev_deps = False
                in_flutter = False
                in_assets = False
                continue
            elif re.match(r"^dev_dependencies\s*:", line):
                in_deps = False
                in_dev_deps = True
                in_flutter = False
                in_assets = False
                continue
            elif re.match(r"^flutter\s*:", line):
                in_deps = False
                in_dev_deps = False
                in_flutter = True
                in_assets = False
                continue
            elif re.match(r"^[a-zA-Z0-9_-]+\s*:", line):
                in_deps = False
                in_dev_deps = False
                in_flutter = False
                in_assets = False
                continue

            # Within dependencies
            if in_deps:
                # Check for sdk: flutter
                if "sdk: flutter" in line:
                    res["has_flutter_sdk"] = True

                # Check for Flame packages
                for pkg in KNOWN_FLAME_PACKAGES:
                    pkg_match = re.match(rf"^\s+{re.escape(pkg)}\s*:\s*(.+)$", line)
                    if pkg_match:
                        v_str = pkg_match.group(1).strip().strip("'\"")
                        res["flame_packages"][pkg] = v_str
                        if pkg == "flame":
                            res["flame_detected"] = True
                            res["flame_version"] = v_str

            # Within flutter: assets:
            if in_flutter:
                if re.match(r"^\s+assets\s*:", line):
                    in_assets = True
                    continue
                elif re.match(r"^\s+[a-zA-Z0-9_-]+\s*:", line):
                    in_assets = False
                    continue

                if in_assets:
                    asset_item = re.match(r"^\s+-\s+(.+)$", line)
                    if asset_item:
                        entry = asset_item.group(1).strip().strip("'\"")
                        res["declared_assets"].append(entry)

        return res

    def _inspect_dart_files(self, project_root: Path) -> Tuple[List[str], List[str]]:
        """Scan lib/ directory for Flame classes and asset loading invocations."""
        lib_dir = project_root / "lib"
        if not lib_dir.exists():
            return [], []

        game_files = []
        conventions = set()

        dart_files = list(lib_dir.glob("**/*.dart"))
        # Limit inspection to first 50 files for speed
        for df in dart_files[:50]:
            try:
                with open(df, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                rel_path = str(df.relative_to(project_root)).replace("\\", "/")

                # Look for Flame game classes
                if any(cls_name in content for cls_name in ["FlameGame", "Game", "PositionComponent", "SpriteComponent", "SpriteAnimationComponent"]):
                    game_files.append(rel_path)

                # Look for asset loading calls
                if "images.load(" in content:
                    conventions.add("images.load (Flame Images Cache)")
                if "Sprite.load(" in content:
                    conventions.add("Sprite.load (Single Sprite Loader)")
                if "SpriteAnimation.fromFrameData(" in content or "SpriteAnimationData.sequenced(" in content:
                    conventions.add("SpriteAnimation.fromFrameData (Sprite Sheet Sequences)")
                if "FlameAudio.play(" in content or "FlameAudio.bgm" in content:
                    conventions.add("FlameAudio (Audio Engine)")
                if "rootBundle.loadString(" in content:
                    conventions.add("rootBundle.loadString (Flutter Asset Bundle)")

            except Exception as e:
                logger.debug("Failed reading dart file %s: %s", df, e)

        return game_files, sorted(list(conventions))


# Global FlutterProjectInspector singleton
flutter_project_inspector = FlutterProjectInspector()
