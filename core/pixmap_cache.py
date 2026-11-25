"""
In-Memory Thread-Safe LRU Pixmap & Thumbnail Cache (Stage 13.1)
Construction Asset Processor

Provides:
1. Fast in-memory LRU caching of scaled QPixmaps for gallery cards, list thumbnails, and viewports.
2. Strict memory budgeting (default 128 MB maximum texture cache) to prevent RAM bloat.
3. Cache invalidation on file modification time changes.
4. Safe fallback: loads cached disk thumbnail first before touching full-resolution source.
5. Thread-safe operations using threading locks.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

logger = logging.getLogger("AssetProcessor.PixmapCache")


class PixmapCache:
    """Thread-safe, memory-bounded LRU cache for QPixmaps."""

    def __init__(
        self,
        max_memory_bytes: int = 128 * 1024 * 1024,
        max_items: int = 300,
        max_bytes: Optional[int] = None
    ):
        self.max_memory_bytes = max_bytes if max_bytes is not None else max_memory_bytes
        self.max_items = max_items
        self._lock = threading.Lock()
        # Key: (path_str, target_w, target_h, mtime) -> (pixmap, byte_size)
        self._cache: OrderedDict[Tuple[str, int, int, float], Tuple[QPixmap, int]] = OrderedDict()
        self._current_memory_bytes: int = 0

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._current_memory_bytes

    def get_pixmap(
        self,
        file_path: str | Path,
        target_size: Optional[Tuple[int, int] | int] = None,
        thumbnail_fallback_path: Optional[str | Path | int] = None,
        height: Optional[int] = None
    ) -> Optional[QPixmap]:
        """
        Retrieve cached QPixmap or load and scale it safely into memory.
        
        Args:
            file_path: Path to the image file.
            target_size: Desired (width, height) to scale to, or None for original size.
            thumbnail_fallback_path: Preferred pre-generated thumbnail disk path.
        """
        if isinstance(target_size, int):
            if isinstance(thumbnail_fallback_path, int):
                target_size = (target_size, thumbnail_fallback_path)
                thumbnail_fallback_path = None
            elif height is not None:
                target_size = (target_size, height)
            else:
                target_size = (target_size, target_size)

        path_str = str(file_path)
        if not path_str:
            return None

        p = Path(path_str)
        if not p.is_file():
            # If main file is missing, try thumbnail fallback
            if thumbnail_fallback_path and Path(thumbnail_fallback_path).is_file():
                p = Path(thumbnail_fallback_path)
                path_str = str(p)
            else:
                return None

        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0

        tw = target_size[0] if target_size else 0
        th = target_size[1] if target_size else 0
        cache_key = (path_str, tw, th, mtime)

        with self._lock:
            if cache_key in self._cache:
                pix, byte_size = self._cache.pop(cache_key)
                self._cache[cache_key] = (pix, byte_size)  # Move to end (most recently used)
                return pix

        # Cache miss - load pixmap safely
        loaded_pix = self._load_and_scale(p, target_size, thumbnail_fallback_path)
        if loaded_pix is None or loaded_pix.isNull():
            return None

        # Calculate memory footprint (32-bit RGBA = 4 bytes per pixel)
        byte_size = loaded_pix.width() * loaded_pix.height() * 4

        with self._lock:
            # Evict if exceeding memory or item count limit
            while (
                (self._current_memory_bytes + byte_size > self.max_memory_bytes or len(self._cache) >= self.max_items)
                and self._cache
            ):
                _, (_, evicted_bytes) = self._cache.popitem(last=False)  # Evict least recently used
                self._current_memory_bytes -= evicted_bytes

            self._cache[cache_key] = (loaded_pix, byte_size)
            self._current_memory_bytes += byte_size

        return loaded_pix

    def _load_and_scale(
        self,
        p: Path,
        target_size: Optional[Tuple[int, int]],
        thumbnail_fallback_path: Optional[str | Path]
    ) -> Optional[QPixmap]:
        """Load image with QImageReader to avoid decoding huge images when thumbnail exists."""
        load_source = p

        # If a pre-generated disk thumbnail is provided and exists, prefer it for fast thumbnailing
        if target_size and target_size[0] <= 256 and target_size[1] <= 256:
            if thumbnail_fallback_path and Path(thumbnail_fallback_path).is_file():
                load_source = Path(thumbnail_fallback_path)

        reader = QImageReader(str(load_source))
        reader.setAutoTransform(True)

        orig_size = reader.size()
        if not orig_size.isValid():
            # Fallback to direct QPixmap load
            pix = QPixmap(str(load_source))
            if pix.isNull():
                return None
            if target_size and target_size[0] > 0 and target_size[1] > 0:
                return pix.scaled(target_size[0], target_size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return pix

        # Scale down during read if target_size is specified to avoid huge RAM allocations
        if target_size and target_size[0] > 0 and target_size[1] > 0:
            scaled_target = orig_size.scaled(target_size[0], target_size[1], Qt.KeepAspectRatio)
            reader.setScaledSize(scaled_target)

        qimg = reader.read()
        if qimg.isNull():
            # Fallback to standard QPixmap
            pix = QPixmap(str(load_source))
            if not pix.isNull() and target_size:
                return pix.scaled(target_size[0], target_size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return pix if not pix.isNull() else None

        return QPixmap.fromImage(qimg)

    def invalidate(self, file_path: Optional[str | Path] = None):
        """Invalidate cache for a specific file or clear entire cache."""
        with self._lock:
            if file_path is None:
                self._cache.clear()
                self._current_memory_bytes = 0
            else:
                path_str = str(file_path)
                keys_to_remove = [k for k in self._cache.keys() if k[0] == path_str]
                for k in keys_to_remove:
                    _, byte_size = self._cache.pop(k)
                    self._current_memory_bytes -= byte_size

    def get_stats(self) -> dict:
        """Return cache telemetry."""
        with self._lock:
            return {
                "item_count": len(self._cache),
                "memory_mb": round(self._current_memory_bytes / (1024 * 1024), 2),
                "max_memory_mb": round(self.max_memory_bytes / (1024 * 1024), 2),
            }

    # Alias for convenience
    get = get_pixmap


# Global singleton instance
pixmap_cache = PixmapCache()

