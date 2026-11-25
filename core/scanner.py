"""
Image Scanner and Metadata Extraction Engine
Construction Asset Processor
Scans folders recursively, extracts image dimensions, color profiles, formats,
hashes, and generates thumbnails. Never modifies original images.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple
from PIL import Image

from app.config import SUPPORTED_EXTENSIONS
from core.database import db
from core.thumbnail import thumbnail_engine

logger = logging.getLogger(__name__)


def compute_file_hash(file_path: Path, block_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file for duplicate detection."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(block_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_collection(path: Path) -> str:
    """Heuristically identify collection category from folder hierarchy."""
    path_str = str(path).lower()
    if "excavat" in path_str:
        return "excavator"
    elif "other" in path_str:
        return "other_images"
    return "other_images"


class AssetScanner:
    """Scans filesystem for image assets and reads non-destructive metadata."""

    def __init__(self, supported_extensions=SUPPORTED_EXTENSIONS):
        self.supported_extensions = {ext.lower() for ext in supported_extensions}

    def discover_image_files(self, folder_path: str, recursive: bool = True) -> List[Path]:
        """Find all matching image files without loading image contents."""
        root = Path(folder_path)
        if not root.exists() or not root.is_dir():
            logger.warning(f"Invalid scan directory: {folder_path}")
            return []

        matched_files: List[Path] = []
        if recursive:
            for dirpath, _, filenames in os.walk(root):
                for fname in filenames:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in self.supported_extensions:
                        matched_files.append(Path(dirpath) / fname)
        else:
            for item in root.iterdir():
                if item.is_file() and item.suffix.lower() in self.supported_extensions:
                    matched_files.append(item)

        return matched_files

    def extract_metadata(self, file_path: Path, target_collection: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Extract image headers and file attributes safely without loading full image pixels into memory.
        """
        try:
            abs_path = file_path.resolve()
            stat = abs_path.stat()
            file_size = stat.st_size

            # Lazy header reading with Pillow
            with Image.open(abs_path) as img:
                width, height = img.size
                img_format = img.format or file_path.suffix.lstrip(".").upper()
                mode = img.mode
                has_transparency = 1 if mode in ("RGBA", "LA") or ("transparency" in img.info) else 0

            aspect_ratio = round(width / height, 3) if height > 0 else 1.0
            file_hash = compute_file_hash(abs_path)
            collection = target_collection or detect_collection(abs_path)

            return {
                "original_path": str(abs_path),
                "filename": abs_path.name,
                "collection": collection,
                "file_size": file_size,
                "file_hash": file_hash,
                "format": img_format,
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
                "color_mode": mode,
                "has_transparency": has_transparency,
                "status": "pending",
                "stage_status": {
                    "imported": True,
                    "classified": False,
                    "renamed": False,
                    "background_removed": False,
                    "text_checked": False,
                    "watermark_checked": False,
                    "optimized": False,
                    "approved": False,
                },
                "metadata": {
                    "extension": abs_path.suffix.lower(),
                    "parent_folder": abs_path.parent.name,
                }
            }
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            return None


# Global scanner instance
scanner = AssetScanner()
