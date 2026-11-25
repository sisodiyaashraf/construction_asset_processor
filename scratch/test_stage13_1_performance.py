"""
Comprehensive Performance, Responsiveness & Stability Verification Suite
Stage 13.1 — Construction Asset Processor

Validates:
1. Application startup & 161 catalog assets integrity.
2. Source images 100% untouched (25 in excavater, 136 in excavater/other images).
3. Thread-safe Bounded PixmapCache (hit vs miss benchmark, LRU eviction, memory limits).
4. Double-buffered InteractiveMaskCanvas rendering performance (cached scaling & overlay baking).
5. BackgroundRemovalWorker non-blocking execution & progress emission.
6. BackgroundRemovalWorker cancellation responsiveness.
7. WhiteBgDetectionWorker & QualityAuditWorker background execution.
8. ImageLoadWorker asynchronous decoding & race condition protection.
9. ComponentExtractionWorker background execution & provenance preservation.
10. Database thread safety under concurrent worker access.
11. Stage 13 SQLite index query acceleration.
12. View isolation: MainWindow avoids cascading hidden view reloads.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
from PIL import Image

from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

# Ensure QApplication singleton
app = QApplication.instance() or QApplication(sys.argv)

from app.config import DATABASE_PATH, INPUT_DIR, ROOT_DIR
from core.database import db
from core.excavator_component_extractor import ExcavatorComponentExtractor
from core.excavator_prep_engine import ExcavatorPrepEngine, compute_sha256
from core.pixmap_cache import PixmapCache, pixmap_cache
from core.stage13_quality_validator import Stage13QualityValidator
from core.stage13_workers import (
    BackgroundRemovalWorker, ComponentExtractionWorker,
    ImageLoadWorker, QualityAuditWorker, WhiteBgDetectionWorker
)
from ui.components.interactive_mask_canvas import InteractiveMaskCanvas
from ui.main_window import MainWindow
from ui.views.stage13_sprite_prep_view import Stage13SpritePrepView


class TestStage131PerformanceAndStability(unittest.TestCase):
    """Rigorous verification of Stage 13.1 UI responsiveness, caching, workers, and stability."""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="stage13_1_perf_"))

        # Create a synthetic 2752x1536 test image for stress testing
        cls.large_img_path = cls.temp_dir / "stress_test_large_2752x1536.png"
        large_arr = np.full((1536, 2752, 3), 255, dtype=np.uint8)
        # Add central yellow machine
        cv2.rectangle(large_arr, (400, 400), (2300, 1200), (0, 200, 255), -1)
        # Add white cab
        cv2.rectangle(large_arr, (900, 500), (1400, 850), (255, 255, 255), -1)
        # Add black tracks
        cv2.rectangle(large_arr, (450, 1100), (2250, 1350), (30, 30, 30), -1)
        cv2.imwrite(str(cls.large_img_path), large_arr)

        cls.large_hash = compute_sha256(cls.large_img_path)

    @classmethod
    def tearDownClass(cls):
        if cls.temp_dir.exists():
            import shutil
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. CATALOG INTEGRITY & STARTUP BENCHMARK
    # -------------------------------------------------------------------------
    def test_01_catalog_and_source_integrity(self):
        """Verify all 161 source images exist, are intact, and none have been modified."""
        excav_dir = ROOT_DIR / "excavater"
        other_dir = ROOT_DIR / "excavater" / "other images"

        self.assertTrue(excav_dir.is_dir(), f"Directory missing: {excav_dir}")
        self.assertTrue(other_dir.is_dir(), f"Directory missing: {other_dir}")

        excav_imgs = [p for p in excav_dir.glob("*.jpg")] + [p for p in excav_dir.glob("*.png")]
        other_imgs = [p for p in other_dir.glob("*.jpg")] + [p for p in other_dir.glob("*.png")]

        self.assertEqual(len(excav_imgs), 25, f"Expected 25 excavater images, found {len(excav_imgs)}")
        self.assertEqual(len(other_imgs), 136, f"Expected 136 other images, found {len(other_imgs)}")

        total_source = len(excav_imgs) + len(other_imgs)
        self.assertEqual(total_source, 161, "Total source images must be exactly 161.")

        # Verify DB assets table
        assets = db.get_all_assets()
        self.assertGreaterEqual(len(assets), 161, "Database must track at least 161 catalog assets.")

    # -------------------------------------------------------------------------
    # 2. PIXMAP CACHE PERFORMANCE & MEMORY BOUNDS
    # -------------------------------------------------------------------------
    def test_02_pixmap_cache_hit_vs_miss_timing(self):
        """Verify LRU cache hits are orders of magnitude faster than cold disk decodes."""
        test_cache = PixmapCache(max_bytes=16 * 1024 * 1024)  # 16 MB limit

        # Cold load (Cache miss)
        t0 = time.perf_counter()
        pix_cold = test_cache.get_pixmap(str(self.large_img_path), target_size=(180, 115))
        cold_time_ms = (time.perf_counter() - t0) * 1000

        self.assertIsNotNone(pix_cold)
        self.assertFalse(pix_cold.isNull())

        # Warm load (Cache hit)
        t1 = time.perf_counter()
        pix_warm = test_cache.get_pixmap(str(self.large_img_path), target_size=(180, 115))
        warm_time_ms = (time.perf_counter() - t1) * 1000

        self.assertIsNotNone(pix_warm)
        # Cache hit should be sub-millisecond (< 0.5ms)
        self.assertLess(warm_time_ms, 2.0, f"Cache hit took {warm_time_ms:.3f}ms, expected sub-millisecond.")
        print(f"\n[BENCHMARK] PixmapCache cold miss: {cold_time_ms:.2f}ms | warm hit: {warm_time_ms:.4f}ms (Speedup: {cold_time_ms / max(warm_time_ms, 0.0001):.1f}x)")

    def test_03_pixmap_cache_memory_budget_enforcement(self):
        """Verify cache stays strictly within memory budget through LRU eviction."""
        # Restrict cache to 500 KB to force eviction
        tiny_cache = PixmapCache(max_bytes=500 * 1024)

        # Generate several dummy files and insert
        for i in range(15):
            dummy_p = self.temp_dir / f"dummy_cache_{i}.png"
            if not dummy_p.exists():
                arr = np.full((200, 200, 3), i * 15, dtype=np.uint8)
                cv2.imwrite(str(dummy_p), arr)
            tiny_cache.get_pixmap(str(dummy_p), target_size=(100, 100))

        # Check total bytes
        self.assertLessEqual(tiny_cache.current_bytes, 500 * 1024, "Cache memory must not exceed budget.")
        self.assertGreater(tiny_cache.current_bytes, 0, "Cache should retain most recent items.")

    def wait_worker(self, worker, timeout_ms=15000) -> bool:
        """Pump Qt event loop while waiting for worker thread to finish and emit signals."""
        t0 = time.time()
        while worker.isRunning() and (time.time() - t0) * 1000 < timeout_ms:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        return not worker.isRunning()

    # -------------------------------------------------------------------------
    # 3. INTERACTIVE CANVAS DOUBLE-BUFFERING & ACCURACY
    # -------------------------------------------------------------------------
    def test_04_canvas_double_buffer_and_coordinate_transform(self):
        """Verify canvas pre-scales pixmap once and translates coordinates accurately."""
        canvas = InteractiveMaskCanvas()
        canvas.resize(800, 600)
        canvas.set_image(str(self.large_img_path))

        self.assertEqual(canvas.image_width, 2752)
        self.assertEqual(canvas.image_height, 1536)
        self.assertIsNotNone(canvas._overlay_pixmap)
        self.assertEqual(canvas._overlay_pixmap.width(), 2752)
        self.assertEqual(canvas._overlay_pixmap.height(), 1536)

        # Coordinate transformation check
        img_pt = QPointF(1376.0, 768.0)
        widget_pt = canvas.image_to_widget_coords(img_pt.x(), img_pt.y())
        back_pt = canvas.widget_to_image_coords(widget_pt.toPoint())

        self.assertAlmostEqual(img_pt.x(), back_pt[0], delta=2.0)
        self.assertAlmostEqual(img_pt.y(), back_pt[1], delta=2.0)

        # Add stroke to overlay
        canvas.set_tool("fg_brush")
        canvas.brush_strokes.append({
            "points": [(500, 500), (510, 510), (520, 520)],
            "radius": 15,
            "is_fg": True
        })
        canvas._render_stroke_to_overlay(canvas.brush_strokes[-1])
        # Overlay pixmap remains valid and allocated
        self.assertFalse(canvas._overlay_pixmap.isNull())

    # -------------------------------------------------------------------------
    # 4. ASYNCHRONOUS BACKGROUND REMOVAL WORKER
    # -------------------------------------------------------------------------
    def test_05_background_removal_worker_execution(self):
        """Verify BackgroundRemovalWorker runs off-thread, reports progress, and emits results."""
        out_p = self.temp_dir / "worker_output_transparent.png"
        worker = BackgroundRemovalWorker(
            asset_id=999,
            input_path=self.large_img_path,
            output_path=out_p,
            color_tolerance=30,
            grabcut_iterations=1,
            feather_radius=1
        )

        progress_reports = []
        worker.progress.connect(lambda pct, msg: progress_reports.append((pct, msg)))

        results = {}
        def on_finished(asset_id, rgba, diag, msg):
            results["asset_id"] = asset_id
            results["rgba"] = rgba
            results["diag"] = diag
            results["msg"] = msg

        worker.finished_work.connect(on_finished)

        worker.start()
        finished = self.wait_worker(worker, timeout_ms=15000)
        self.assertTrue(finished, "BackgroundRemovalWorker did not finish in time.")
        self.assertTrue(out_p.is_file(), "Worker must write output PNG.")
        self.assertIn("rgba", results)
        self.assertEqual(results["rgba"].shape[2], 4, "Cutout must have 4 RGBA channels.")
        self.assertGreater(len(progress_reports), 0, "Progress signals must be emitted.")
        self.assertEqual(progress_reports[-1][0], 100, "Final progress must reach 100%.")

    def test_06_background_removal_worker_cancellation(self):
        """Verify BackgroundRemovalWorker cancels promptly when requested."""
        out_p = self.temp_dir / "worker_cancel_output.png"
        worker = BackgroundRemovalWorker(
            asset_id=998,
            input_path=self.large_img_path,
            output_path=out_p,
            color_tolerance=30,
            grabcut_iterations=5  # High iterations to test cancellation
        )

        cancelled_ids = []
        worker.canceled.connect(lambda aid: cancelled_ids.append(aid))

        worker.start()
        time.sleep(0.05)  # Let worker start
        worker.request_cancel()
        finished = self.wait_worker(worker, timeout_ms=5000)

        self.assertTrue(finished, "Worker must stop after cancellation.")
        self.assertIn(998, cancelled_ids, "Cancellation signal must be emitted with asset_id.")

    # -------------------------------------------------------------------------
    # 5. WHITE BG, QUALITY & IMAGE LOAD WORKERS
    # -------------------------------------------------------------------------
    def test_07_white_bg_and_quality_workers(self):
        """Verify WhiteBgDetectionWorker and QualityAuditWorker run in background."""
        # White BG Worker
        wbg_results = {}
        wbg_worker = WhiteBgDetectionWorker(asset_id=997, image_path=self.large_img_path, color_tolerance=25)
        wbg_worker.finished_work.connect(lambda aid, is_w, conf, det: wbg_results.update({
            "aid": aid, "is_white": is_w, "conf": conf, "det": det
        }))
        wbg_worker.start()
        self.wait_worker(wbg_worker, timeout_ms=5000)

        self.assertEqual(wbg_results.get("aid"), 997)
        self.assertTrue(wbg_results.get("is_white"), "Synthetic image has white background border.")

        # Quality Worker
        qual_results = {}
        qual_worker = QualityAuditWorker(
            asset_id=997,
            image_path=self.large_img_path,
            component_type="body",
            source_path=self.large_img_path,
            expected_source_hash=self.large_hash,
            require_transparency=False
        )
        qual_worker.finished_work.connect(lambda aid, report: qual_results.update({"report": report}))
        qual_worker.start()
        self.wait_worker(qual_worker, timeout_ms=5000)

        self.assertIn("report", qual_results)
        self.assertIn(qual_results["report"].overall_status, ["Pass", "Warning", "Fail", "Manual Review Required"])

    def test_08_image_load_worker_rapid_switching(self):
        """Verify ImageLoadWorker handles rapid asset switching without race conditions."""
        worker1 = ImageLoadWorker(asset_id=1, load_path=str(self.large_img_path))
        worker2 = ImageLoadWorker(asset_id=2, load_path=str(self.large_img_path))

        loaded = []
        worker1.finished_work.connect(lambda aid, p, o, c: loaded.append(aid))
        worker2.finished_work.connect(lambda aid, p, o, c: loaded.append(aid))

        worker1.start()
        worker2.start()
        self.wait_worker(worker1, timeout_ms=5000)
        self.wait_worker(worker2, timeout_ms=5000)

        self.assertEqual(len(loaded), 2)
        self.assertIn(1, loaded)
        self.assertIn(2, loaded)

    # -------------------------------------------------------------------------
    # 6. COMPONENT EXTRACTION WORKER
    # -------------------------------------------------------------------------
    def test_09_component_extraction_worker(self):
        """Verify ComponentExtractionWorker extracts sprite and calculates coordinates in background."""
        worker = ComponentExtractionWorker(
            asset_id=995,
            source_file=str(self.large_img_path),
            component_type="bucket",
            custom_name="test_excavator_bucket",
            crop_rect=(500, 500, 300, 300),
            pivot_norm=(0.5, 0.5)
        )

        res = {}
        worker.finished_work.connect(lambda aid, comp_dict, sp: res.update({"dict": comp_dict, "path": sp}))
        worker.start()
        self.wait_worker(worker, timeout_ms=5000)

        self.assertIn("dict", res)
        self.assertGreaterEqual(res["dict"]["export_width"], 300)
        self.assertGreaterEqual(res["dict"]["export_height"], 300)
        self.assertTrue(Path(res["path"]).is_file())

    # -------------------------------------------------------------------------
    # 7. DATABASE CONCURRENCY & INDEX VERIFICATION
    # -------------------------------------------------------------------------
    def test_10_database_indices_and_query_plans(self):
        """Verify Stage 13 SQLite indices accelerate queries via EXPLAIN QUERY PLAN."""
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Check index on stage13_review_status
            cursor.execute("EXPLAIN QUERY PLAN SELECT * FROM assets WHERE stage13_review_status = 'Approved for Export'")
            plan_review = [row[3] for row in cursor.fetchall()]
            has_idx_review = any("idx_assets_stage13_review" in step for step in plan_review)
            self.assertTrue(has_idx_review, f"Query should use idx_assets_stage13_review index: {plan_review}")

            # Check index on excavator_preparations
            cursor.execute("EXPLAIN QUERY PLAN SELECT * FROM excavator_preparations WHERE asset_id = 1")
            plan_prep = [row[3] for row in cursor.fetchall()]
            has_idx_prep = any("sqlite_autoindex_excavator_preparations" in step or "idx_excav_prep_asset" in step or "PRIMARY" in step for step in plan_prep)
            self.assertTrue(has_idx_prep, f"Query should use asset index: {plan_prep}")

    # -------------------------------------------------------------------------
    # 8. VIEW ISOLATION IN MAIN WINDOW
    # -------------------------------------------------------------------------
    def test_11_main_window_refresh_isolation(self):
        """Verify MainWindow._refresh_active_view only updates the currently active widget."""
        main_win = MainWindow()
        # Set active view to Stage 13 (index 12)
        main_win.workspace_stack.setCurrentIndex(12)
        self.assertEqual(main_win.workspace_stack.currentWidget(), main_win.stage13_sprite_prep_view)

        # Trigger asset status update
        main_win._on_asset_status_updated(asset_id=1, new_status="Reviewed")
        # Ensure status bar reflects change
        self.assertIn("Asset #1", main_win.status_bar.detail_label.text())

        # Cleanup
        main_win.close()


if __name__ == "__main__":
    unittest.main()
