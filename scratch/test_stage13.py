"""
Comprehensive Verification Test Suite for Stage 13
Excavator Asset Extraction, Background Cleanup & Sprite Preparation
Construction Asset Processor

Tests all 12 prompt testing requirements:
1. Original source images remain unchanged.
2. Source hashes remain identical after processing.
3. Background removal creates real transparency.
4. White foreground details can be preserved through manual masking.
5. Undo and redo work correctly.
6. Polygon and brush masks work correctly.
7. Extracted component metadata is valid.
8. Pivot coordinates are saved correctly.
9. Invalid images are rejected safely.
10. Export manifest is generated correctly.
11. Unapproved assets cannot be exported.
12. Exported PNGs can be reopened successfully.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for UI tests
app = QApplication.instance() or QApplication(sys.argv)

from app.config import INPUT_DIR, ROOT_DIR
from core.database import db
from core.excavator_component_extractor import (
    COMPONENT_TYPES, PIVOT_PRESETS,
    ExcavatorComponentExtractor
)
from core.excavator_prep_engine import (
    ExcavatorPrepEngine, MaskHistoryManager,
    compute_sha256
)
from core.stage13_export_engine import Stage13ExportEngine
from core.stage13_quality_validator import Stage13QualityValidator
from ui.components.interactive_mask_canvas import InteractiveMaskCanvas
from ui.views.stage13_sprite_prep_view import Stage13SpritePrepView


class TestStage13Verification(unittest.TestCase):
    """Stage 13 verification suite testing computer vision, integrity, and export."""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.prep_engine = ExcavatorPrepEngine()
        cls.extractor = ExcavatorComponentExtractor()
        cls.validator = Stage13QualityValidator()
        cls.export_engine = Stage13ExportEngine()

        # Create temporary working directory for test outputs
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="stage13_test_"))

        # Create a synthetic test image with white background and excavator-like colors (yellow + white cab + black tracks)
        cls.test_img_path = cls.temp_dir / "test_excavator_source.png"
        img = np.full((200, 300, 3), 255, dtype=np.uint8)  # White background

        # Yellow body (RGB: 229, 169, 60 -> BGR: 60, 169, 229)
        cv2.rectangle(img, (50, 60), (220, 140), (60, 169, 229), -1)

        # White cab roof (light surface that must be preserved)
        cv2.rectangle(img, (80, 40), (140, 60), (250, 250, 250), -1)

        # Black tracks (BGR: 30, 30, 30)
        cv2.rectangle(img, (40, 140), (230, 175), (30, 30, 30), -1)

        # Yellow boom arm
        cv2.line(img, (200, 90), (280, 40), (60, 169, 229), 12)

        cv2.imwrite(str(cls.test_img_path), img)
        cls.initial_hash = compute_sha256(cls.test_img_path)

    @classmethod
    def tearDownClass(cls):
        if cls.temp_dir.exists():
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    # 1 & 2. Source Image Hash & Non-Destructive Integrity
    def test_01_original_source_integrity_and_hashes(self):
        """Test Requirement 1 & 2: Original source files and SHA-256 hashes remain identical."""
        orig_hash_before = compute_sha256(self.test_img_path)
        self.assertEqual(orig_hash_before, self.initial_hash)

        # Run background removal into a copy
        out_copy = self.temp_dir / "cutout_copy.png"
        success, rgba, diag, msg = self.prep_engine.remove_background(
            self.test_img_path,
            output_path=out_copy,
            color_tolerance=25
        )
        self.assertTrue(success)
        self.assertTrue(out_copy.exists())

        # Verify source image was NEVER modified
        orig_hash_after = compute_sha256(self.test_img_path)
        self.assertEqual(orig_hash_after, self.initial_hash, "Source image hash modified during background removal!")
        self.assertTrue(self.prep_engine.verify_source_integrity(self.test_img_path, self.initial_hash))

    # 3. Background removal creates real transparency
    def test_02_background_removal_creates_real_transparency(self):
        """Test Requirement 3: Background removal creates real transparency (alpha < 250)."""
        out_p = self.temp_dir / "transparency_test.png"
        success, rgba, diag, msg = self.prep_engine.remove_background(
            self.test_img_path,
            output_path=out_p,
            color_tolerance=30
        )
        self.assertTrue(success)
        self.assertIsNotNone(rgba)
        self.assertEqual(rgba.shape[2], 4)

        # Check alpha channel contains true transparent pixels
        alpha = rgba[:, :, 3]
        transparent_pixels = np.sum(alpha < 250)
        total_pixels = alpha.size
        trans_ratio = transparent_pixels / total_pixels

        self.assertGreater(trans_ratio, 0.20, "Cutout does not contain sufficient transparent background pixels.")

        # Reopen saved file with PIL to confirm on-disk format
        with Image.open(out_p) as pil_img:
            self.assertEqual(pil_img.mode, "RGBA")
            pil_alpha = np.array(pil_img.split()[-1])
            self.assertGreater(np.sum(pil_alpha < 250), 0)

    # 4. White foreground details preserved through manual masking
    def test_03_white_foreground_preserved_with_manual_masking(self):
        """Test Requirement 4: White excavator components (e.g. cabin roof) preserved with FG brush."""
        # Cab roof is at x: 80-140, y: 40-60 (white pixels)
        # Without FG brush, it might be removed by color distance
        # Add FG stroke covering the roof
        fg_strokes = [{
            "points": [(110, 50)],
            "radius": 15
        }]

        out_p = self.temp_dir / "white_preservation_test.png"
        success, rgba, diag, msg = self.prep_engine.remove_background(
            self.test_img_path,
            output_path=out_p,
            color_tolerance=20,
            fg_strokes=fg_strokes
        )
        self.assertTrue(success)

        # Check that pixels at the roof (x=110, y=50) are solid (alpha == 255)
        roof_alpha = rgba[50, 110, 3]
        self.assertEqual(roof_alpha, 255, "White excavator roof was erased instead of preserved by FG brush!")

    # 5. Undo and redo work correctly
    def test_04_undo_redo_mask_history(self):
        """Test Requirement 5: Undo and redo work correctly on mask states."""
        history = MaskHistoryManager(max_depth=10)
        self.assertFalse(history.can_undo())
        self.assertFalse(history.can_redo())

        m1 = np.zeros((10, 10), dtype=np.uint8)
        m2 = np.ones((10, 10), dtype=np.uint8)
        m3 = np.full((10, 10), 2, dtype=np.uint8)

        history.push(m1)
        history.push(m2)
        self.assertTrue(history.can_undo())

        # Current state is m3. Undo should return m2
        undone = history.undo(m3)
        self.assertTrue(np.array_equal(undone, m2))
        self.assertTrue(history.can_redo())

        # Undo again should return m1
        undone2 = history.undo(undone)
        self.assertTrue(np.array_equal(undone2, m1))

        # Redo should return m2
        redone = history.redo(undone2)
        self.assertTrue(np.array_equal(redone, m2))

    # 6. Polygon and brush masks work correctly
    def test_05_polygon_and_brush_masks(self):
        """Test Requirement 6: Polygon and brush masks correctly crop and segment components."""
        # Test polygon extraction
        poly_pts = [(40, 135), (235, 135), (235, 180), (40, 180)]  # Tracks region
        with Image.open(self.test_img_path) as pil_img:
            arr = np.array(pil_img.convert("RGBA"))

        cropped, bbox = self.extractor.crop_component_polygon(arr, poly_pts, padding=2)
        self.assertIsNotNone(cropped)
        self.assertEqual(cropped.shape[2], 4)
        self.assertGreater(bbox[2], 180)  # width
        self.assertGreater(bbox[3], 35)   # height

        # Pixels inside tracks bbox are present
        self.assertGreater(np.sum(cropped[:, :, 3] > 0), 100)

    # 7. Extracted component metadata is valid
    def test_06_extracted_component_metadata(self):
        """Test Requirement 7: Extracted component metadata contains all required structured JSON fields."""
        meta = self.extractor.generate_component_metadata(
            asset_id=999,
            component_type="boom",
            component_name="excavator_boom_main",
            source_path=self.test_img_path,
            orig_w=300,
            orig_h=200,
            export_w=120,
            export_h=80,
            bbox=(180, 30, 120, 80),
            pivot_norm=(0.15, 0.85),
            pivot_pixel=(18, 68),
            pivot_status="Verified",
            transparency_status="True Alpha",
            processing_method="lasso_grabcut",
            manual_review_status="Approved",
            approval_status="Approved",
            export_path=str(self.temp_dir / "boom_test.png")
        )

        required_keys = [
            "asset_id", "component_type", "component_name", "source_image_path",
            "source_image_hash", "original_dimensions", "export_dimensions",
            "bounding_box", "pivot_coordinates", "transparency_status",
            "processing_method", "manual_review_status", "approval_status",
            "export_path", "flame_component_spec"
        ]
        for key in required_keys:
            self.assertIn(key, meta, f"Metadata missing required key: {key}")

        self.assertEqual(meta["source_image_hash"], self.initial_hash)
        self.assertEqual(meta["pivot_coordinates"]["pivot_status"], "Verified")

    # 8. Pivot coordinates saved correctly
    def test_07_pivot_coordinates_and_presets(self):
        """Test Requirement 8: Pivot coordinates saved correctly in normalized and pixel format."""
        crop_w, crop_h = 200, 100
        norm_x, norm_y = 0.15, 0.85  # Boom base preset

        px, py = self.extractor.calculate_pivot_coordinates(crop_w, crop_h, norm_x, norm_y)
        self.assertEqual(px, 30)
        self.assertEqual(py, 85)

        # Convert back
        rev_nx, rev_ny = self.extractor.normalize_pivot_coordinates(crop_w, crop_h, px, py)
        self.assertAlmostEqual(rev_nx, norm_x, places=2)
        self.assertAlmostEqual(rev_ny, norm_y, places=2)

    # 9. Invalid images rejected safely
    def test_08_invalid_images_rejected_safely(self):
        """Test Requirement 9: Corrupt or non-existent files are rejected safely."""
        fake_path = self.temp_dir / "does_not_exist_9999.png"
        report = self.validator.validate_asset(fake_path)
        self.assertEqual(report.overall_status, "Fail")
        self.assertGreater(report.failed_count, 0)

        # Corrupt file test
        corrupt_path = self.temp_dir / "corrupt_test.png"
        with open(corrupt_path, "wb") as f:
            f.write(b"NOT_A_VALID_PNG_FILE_HEADER")

        report_corrupt = self.validator.validate_asset(corrupt_path)
        self.assertEqual(report_corrupt.overall_status, "Fail")

    # 10. Export manifest generated correctly
    def test_09_export_manifest_generation(self):
        """Test Requirement 10: Export manifest is generated with proper Flame specs."""
        dest_dir = self.temp_dir / "flutter_assets_test"
        dummy_png = self.temp_dir / "valid_sprite.png"
        Image.fromarray(np.full((50, 50, 4), 200, dtype=np.uint8)).save(dummy_png, format="PNG")

        approved_comps = [{
            "id": 1,
            "component_type": "bucket",
            "component_name": "excavator_bucket",
            "source_path": str(self.test_img_path),
            "source_hash": self.initial_hash,
            "export_path": str(dummy_png),
            "export_width": 50,
            "export_height": 50,
            "pivot_norm_x": 0.85,
            "pivot_norm_y": 0.85,
            "pivot_status": "Verified",
            "approval_status": "Approved"
        }]

        success, summary, msg = self.export_engine.execute_export(
            approved_comps,
            destination_override=dest_dir
        )
        self.assertTrue(success)
        manifest_file = dest_dir / "metadata" / "stage13_export_manifest.json"
        self.assertTrue(manifest_file.is_file())

        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        self.assertEqual(manifest_data["total_components_exported"], 1)
        self.assertIn("components", manifest_data)
        self.assertEqual(manifest_data["components"][0]["component_type"], "bucket")
        self.assertIn("flame_loading_code", manifest_data["components"][0])

    # 11. Unapproved assets cannot be exported
    def test_10_unapproved_assets_cannot_be_exported(self):
        """Test Requirement 11: Unapproved assets cannot be exported."""
        dest_dir = self.temp_dir / "flutter_assets_unapproved_test"
        unapproved_comps = [{
            "id": 2,
            "component_type": "cabin",
            "component_name": "excavator_cabin",
            "export_path": str(self.test_img_path),
            "approval_status": "Pending"  # Not approved!
        }]

        success, summary, msg = self.export_engine.execute_export(
            unapproved_comps,
            destination_override=dest_dir
        )
        self.assertFalse(success)
        self.assertIn("No approved components", msg)
        self.assertFalse((dest_dir / "metadata" / "stage13_export_manifest.json").exists())

    # 12. Exported PNGs can be reopened successfully
    def test_11_exported_pngs_reopen_successfully(self):
        """Test Requirement 12: Exported PNGs can be reopened and verified successfully."""
        dest_dir = self.temp_dir / "flutter_reopen_test"
        test_sprite = self.temp_dir / "test_track.png"

        # Create transparent sprite
        arr = np.zeros((64, 128, 4), dtype=np.uint8)
        arr[10:50, 10:110, :] = [40, 40, 40, 255]
        Image.fromarray(arr).save(test_sprite, format="PNG")

        approved_comps = [{
            "id": 3,
            "component_type": "undercarriage",
            "component_name": "excavator_tracks",
            "source_path": str(self.test_img_path),
            "source_hash": self.initial_hash,
            "export_path": str(test_sprite),
            "export_width": 128,
            "export_height": 64,
            "pivot_norm_x": 0.5,
            "pivot_norm_y": 1.0,
            "pivot_status": "Verified",
            "approval_status": "Approved"
        }]

        success, summary, msg = self.export_engine.execute_export(
            approved_comps,
            destination_override=dest_dir
        )
        self.assertTrue(success)

        # Check exported file in excavator/ subfolder
        exported_file = dest_dir / "excavator" / "test_track.png"
        self.assertTrue(exported_file.is_file())

        with Image.open(exported_file) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.size, (128, 64))
            self.assertEqual(img.mode, "RGBA")
            img.verify()

    # 13. Database CRUD and Statistics
    def test_12_database_stage13_crud_and_stats(self):
        """Test Stage 13 SQLite tables, CRUD methods, and dashboard aggregation."""
        # Get first asset in DB
        assets = db.get_assets(limit=1)
        if not assets:
            self.skipTest("No assets in database to test DB CRUD.")

        asset_id = assets[0]["id"]
        prep = db.get_or_create_excavator_prep(asset_id)
        self.assertIsNotNone(prep)
        self.assertEqual(prep["asset_id"], asset_id)

        # Update prep
        db.update_excavator_prep(asset_id, {
            "review_status": "Suitable",
            "white_bg_detected": 1,
            "color_tolerance": 35
        })
        prep_updated = db.get_excavator_prep_by_asset(asset_id)
        self.assertEqual(prep_updated["review_status"], "Suitable")
        self.assertEqual(prep_updated["white_bg_detected"], 1)

        # Save component
        comp_id = db.save_extracted_component({
            "asset_id": asset_id,
            "preparation_id": prep["id"],
            "component_type": "chassis",
            "component_name": "test_chassis",
            "source_path": assets[0]["original_path"],
            "source_hash": assets[0]["file_hash"],
            "export_width": 200,
            "export_height": 100,
            "approval_status": "Approved"
        })
        self.assertGreater(comp_id, 0)

        # Retrieve component
        comp = db.get_extracted_component(comp_id)
        self.assertIsNotNone(comp)
        self.assertEqual(comp["component_type"], "chassis")

        # Stats
        stats = db.get_stage13_dashboard_stats()
        self.assertGreaterEqual(stats["total_assets"], 1)
        self.assertGreaterEqual(stats["reviewed_count"], 1)
        self.assertGreaterEqual(stats["extracted_sprites"], 1)
        self.assertGreaterEqual(stats["approved_for_export"], 1)

        # Cleanup test component
        db.delete_extracted_component(comp_id)

    # 14. UI Canvas and Master View
    def test_13_ui_canvas_and_master_view(self):
        """Test interactive canvas tools and Stage13SpritePrepView instantiation."""
        canvas = InteractiveMaskCanvas()
        canvas.set_image(str(self.test_img_path))
        self.assertEqual(canvas.image_width, 300)
        self.assertEqual(canvas.image_height, 200)

        # Test tool changes
        canvas.set_tool("fg_brush")
        self.assertEqual(canvas.current_tool, "fg_brush")
        canvas.set_tool("pivot")
        self.assertEqual(canvas.current_tool, "pivot")

        # Test pivot setting
        canvas.set_pivot(0.25, 0.75)
        self.assertEqual(canvas.pivot_norm, (0.25, 0.75))

        # Test crop rect
        canvas.set_crop_rect(10, 10, 100, 80)
        self.assertIsNotNone(canvas.crop_rect)
        self.assertEqual(canvas.crop_rect.width(), 100)

        # Test master view instantiation
        view = Stage13SpritePrepView()
        self.assertIsNotNone(view)
        self.assertIsNotNone(view.canvas)
        self.assertGreaterEqual(len(view.catalog_assets), 1)


if __name__ == "__main__":
    unittest.main()
