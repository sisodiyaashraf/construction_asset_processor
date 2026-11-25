"""
Thumbnail Generation Engine
High-performance thumbnail creation and caching for Construction Asset Processor.
Preserves transparency for RGBA PNGs and creates optimized previews.
Original files are strictly read-only and never modified.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image

from app.config import THUMBNAILS_DIR

logger = logging.getLogger(__name__)


class ThumbnailEngine:
    """Manages high-performance thumbnail creation, caching, and retrieval."""

    def __init__(self, cache_dir: Path = THUMBNAILS_DIR, default_size: Tuple[int, int] = (256, 256)):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_size = default_size

    def get_thumbnail_filename(self, file_path: str, size: Tuple[int, int]) -> str:
        """Generate a deterministic, unique cache filename based on file path and dimensions."""
        key = f"{file_path}_{size[0]}x{size[1]}".encode("utf-8")
        digest = hashlib.sha256(key).hexdigest()[:16]
        ext = Path(file_path).suffix.lower()
        # Default to png thumbnail to preserve transparency
        return f"thumb_{digest}.png"

    def get_thumbnail_path(self, original_path: str, size: Optional[Tuple[int, int]] = None) -> Path:
        """Get the expected path where thumbnail should reside."""
        thumb_size = size or self.default_size
        filename = self.get_thumbnail_filename(original_path, thumb_size)
        return self.cache_dir / filename

    def create_thumbnail(
        self,
        original_path: str,
        size: Optional[Tuple[int, int]] = None,
        force_recreate: bool = False
    ) -> Optional[str]:
        """
        Create a thumbnail for the image at original_path.
        Returns the absolute string path to the cached thumbnail, or None if failed.
        Never modifies the source image.
        """
        thumb_size = size or self.default_size
        target_path = self.get_thumbnail_path(original_path, thumb_size)

        if not force_recreate and target_path.exists() and target_path.stat().st_size > 0:
            return str(target_path)

        try:
            src_path = Path(original_path)
            if not src_path.exists():
                logger.error(f"Source image file does not exist: {original_path}")
                return None

            # Open original in read-only mode
            with Image.open(src_path) as img:
                # Handle color modes
                if img.mode in ("RGBA", "LA") or ("transparency" in img.info):
                    # Preserve alpha channel
                    thumb = img.convert("RGBA")
                elif img.mode == "P":
                    thumb = img.convert("RGBA")
                else:
                    thumb = img.convert("RGB")

                # Generate thumbnail using high-quality Lanczos resampling
                thumb.thumbnail(thumb_size, Image.Resampling.LANCZOS)

                # Save as PNG to avoid loss and keep transparency
                thumb.save(str(target_path), format="PNG", optimize=True)

            return str(target_path)

        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {original_path}: {e}")
            return None


# Global thumbnail engine instance
thumbnail_engine = ThumbnailEngine()
