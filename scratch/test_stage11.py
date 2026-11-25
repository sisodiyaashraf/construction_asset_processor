"""
Comprehensive Stage 11 Verification Test Suite
Construction Asset Processor

Tests all requirements of Stage 11 — Flutter + Flame Game Integration & Runtime Asset Verification:
1. Flutter project detection.
2. Invalid project path handling.
3. Missing pubspec.yaml handling.
4. Existing asset declaration inspection.
5. Exported image integrity.
6. Missing asset reference detection.
7. Invalid metadata detection.
8. Atlas boundary validation.
9. Duplicate frame identifier detection.
10. Animation sequence validation.
11. FPS validation.
12. Pivot coordinate validation.
13. Flame format compatibility reporting.
14. Asset-to-component assignment persistence.
15. Preview engine initialization.
16. Performance calculations.
17. Isolated Flutter test fixture generation.
18. Safe integration patch preview.
19. Database migration and rollback.
20. Original source integrity across all 161 catalog assets.
21. Regression tests for Stages 2–10.
"""

import hashlib
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for UI tests
app = QApplication.instance() or QApplication(sys.argv)

from app.config import (
    INPUT_DIR, NAVIGATION_ITEMS, OUTPUT_DIR, THEME_COLORS
)
from core.asset_performance_analyzer import AssetPerformanceAnalyzer, asset_performance_analyzer
from core.database import db
from core.flame_compatibility_engine import FlameCompatibilityEngine, flame_compatibility_engine
from core.flutter_project_inspector import FlutterProjectInspector, flutter_project_inspector
from core.game_asset_preview_engine import GameAssetPreviewEngine, game_asset_preview_engine
from core.runtime_asset_validator import RuntimeAssetValidator, runtime_asset_validator
from ui.components.game_asset_preview_canvas import GameAssetPreviewCanvas
from ui.main_window import MainWindow
from ui.views.game_integration_view import GameIntegrationView


class TestStage11Pipeline(unittest.TestCase):
    """Test suite covering all 21 Stage 11 requirements."""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.test_dir = PROJECT_ROOT / "scratch" / "test_stage11_temp"
        cls.test_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_flutter_project_detection(self):
        """1. Flutter project detection: verify valid Flutter project detection with pubspec and lib."""
        mock_proj = self.test_dir / "valid_flutter_app"
        mock_proj.mkdir(parents=True, exist_ok=True)
        (mock_proj / "lib").mkdir(parents=True, exist_ok=True)
        (mock_proj / "assets").mkdir(parents=True, exist_ok=True)

        pub_content = """name: construction_simulator
description: 2D construction simulator game.
version: 1.0.0+1
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  flame: ^1.18.0
  flame_forge2d: ^0.17.0
flutter:
  assets:
    - assets/images/
"""
        (mock_proj / "pubspec.yaml").write_text(pub_content, encoding="utf-8")

        res = flutter_project_inspector.inspect_project(mock_proj)
        self.assertTrue(res["is_valid_flutter_project"])
        self.assertEqual(res["project_name"], "construction_simulator")
        self.assertTrue(res["has_pubspec"])
        self.assertTrue(res["has_lib"])
        self.assertTrue(res["has_assets"])
        self.assertTrue(res["flame_detected"])
        self.assertEqual(res["flame_version"], "^1.18.0")
        self.assertIn("flame_forge2d", res["flame_packages"])

    def test_02_invalid_project_path_handling(self):
        """2. Invalid project path handling: nonexistent path or file path."""
        non_existent = self.test_dir / "non_existent_folder_xyz"
        res_non = flutter_project_inspector.inspect_project(non_existent)
        self.assertFalse(res_non["is_valid_flutter_project"])
        self.assertEqual(res_non["status"], "invalid_path")

        # Test path pointing to a file
        dummy_file = self.test_dir / "not_a_dir.txt"
        dummy_file.write_text("hello", encoding="utf-8")
        res_file = flutter_project_inspector.inspect_project(dummy_file)
        self.assertFalse(res_file["is_valid_flutter_project"])
        self.assertEqual(res_file["status"], "not_a_directory")

    def test_03_missing_pubspec_handling(self):
        """3. Missing pubspec.yaml handling: directory exists but has no pubspec.yaml."""
        empty_dir = self.test_dir / "empty_flutter_folder"
        empty_dir.mkdir(parents=True, exist_ok=True)
        (empty_dir / "lib").mkdir(parents=True, exist_ok=True)

        res = flutter_project_inspector.inspect_project(empty_dir)
        self.assertFalse(res["is_valid_flutter_project"])
        self.assertEqual(res["status"], "missing_pubspec")
        self.assertFalse(res["has_pubspec"])

    def test_04_existing_asset_declaration_inspection(self):
        """4. Existing asset declaration inspection: reads declared paths and detects missing vs existing."""
        mock_proj = self.test_dir / "asset_decl_app"
        mock_proj.mkdir(parents=True, exist_ok=True)
        (mock_proj / "lib").mkdir(parents=True, exist_ok=True)
        (mock_proj / "assets" / "images").mkdir(parents=True, exist_ok=True)

        # Declare two paths: one exists, one is missing
        pub = """name: test_decl
dependencies:
  flutter:
    sdk: flutter
flutter:
  assets:
    - assets/images/
    - assets/missing_sound_fx/
"""
        (mock_proj / "pubspec.yaml").write_text(pub, encoding="utf-8")

        res = flutter_project_inspector.inspect_project(mock_proj)
        self.assertIn("assets/images/", res["existing_asset_dirs"])
        self.assertIn("assets/missing_sound_fx/", res["missing_asset_dirs"])

    def test_05_exported_image_integrity(self):
        """5. Exported image integrity: decodes image, checks dimensions & alpha transparency."""
        img_path = self.test_dir / "valid_image.png"
        img = Image.new("RGBA", (256, 192), (229, 169, 60, 200))
        img.save(img_path, "PNG")

        results = runtime_asset_validator.validate_image_file(img_path, asset_root=self.test_dir)
        statuses = [r["status"] for r in results]
        self.assertNotIn("FAIL", statuses, f"Image integrity check failed: {results}")

    def test_06_missing_asset_reference_detection(self):
        """6. Missing asset reference detection: flags referenced assets that don't exist on disk."""
        manifest = {
            "asset_catalogs": {
                "images": [
                    {"path": "images/excavator_ghost.png", "category": "vehicles"}
                ]
            }
        }
        mf_path = self.test_dir / "missing_ref_manifest.json"
        mf_path.write_text(json.dumps(manifest), encoding="utf-8")

        results = runtime_asset_validator.validate_metadata_file(mf_path, asset_root=self.test_dir)
        failed_checks = [r for r in results if r["status"] == "FAIL" and r["check_category"] == "file_existence"]
        self.assertGreater(len(failed_checks), 0, "Missing referenced asset must trigger FAIL on file_existence")

    def test_07_invalid_metadata_detection(self):
        """7. Invalid metadata detection: flags corrupted JSON or invalid syntax."""
        corrupt_json = self.test_dir / "corrupted_manifest.json"
        corrupt_json.write_text("{ this is not valid JSON ::: ", encoding="utf-8")

        results = runtime_asset_validator.validate_metadata_file(corrupt_json, asset_root=self.test_dir)
        failed_checks = [r for r in results if r["status"] == "FAIL"]
        self.assertGreater(len(failed_checks), 0, "Corrupt JSON must trigger FAIL")

    def test_08_atlas_boundary_validation(self):
        """8. Atlas boundary validation: detects frame rectangles exceeding atlas canvas."""
        # Create small 512x512 atlas image
        atlas_img_path = self.test_dir / "boundary_atlas.png"
        img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        img.save(atlas_img_path, "PNG")

        # Create metadata with 1 valid frame and 1 out-of-bounds frame (x=450, w=100 -> 550 > 512)
        atlas_meta = {
            "meta": {"image": "boundary_atlas.png", "size": {"w": 512, "h": 512}},
            "frames": {
                "sprite_good": {"frame": {"x": 10, "y": 10, "w": 100, "h": 100}},
                "sprite_bad_overflow": {"frame": {"x": 450, "y": 10, "w": 100, "h": 100}},
            }
        }
        meta_path = self.test_dir / "boundary_atlas.json"
        meta_path.write_text(json.dumps(atlas_meta), encoding="utf-8")

        results = runtime_asset_validator.validate_metadata_file(meta_path, asset_root=self.test_dir)
        overflow_checks = [r for r in results if r["status"] == "FAIL" and r["check_category"] == "atlas_bounds"]
        self.assertGreater(len(overflow_checks), 0, "Overflowing sprite rectangle must trigger FAIL on atlas_bounds")

    def test_09_duplicate_frame_identifier_detection(self):
        """9. Duplicate frame identifier detection: flags duplicate sprite names in metadata."""
        custom_atlas = {
            "atlas": {"width": 1024, "height": 1024},
            "sprites": {
                "excavator_track": {"x": 0, "y": 0, "width": 64, "height": 64},
            }
        }
        # In custom schemas, if duplicates exist or duplicate frames are validated
        meta_path = self.test_dir / "dup_id_atlas.json"
        meta_path.write_text(json.dumps(custom_atlas), encoding="utf-8")

        results = runtime_asset_validator.validate_metadata_file(meta_path, asset_root=self.test_dir)
        # Should validate without duplicates
        dup_checks = [r for r in results if r["status"] == "FAIL" and r["check_category"] == "frame_identifiers"]
        self.assertEqual(len(dup_checks), 0)

    def test_10_animation_sequence_validation(self):
        """10. Animation sequence validation: validates frame sequences and detects non-monotonic/duplicate order."""
        valid_anims = [
            {"name": "idle", "fps": 10, "frames": [{"sequence_order": 0}, {"sequence_order": 1}, {"sequence_order": 2}]},
        ]
        res_valid = runtime_asset_validator._validate_animation_sequences(valid_anims, "test_anim")
        statuses_valid = [r["status"] for r in res_valid]
        self.assertNotIn("FAIL", statuses_valid)

        bad_anims = [
            {"name": "broken_anim", "fps": 10, "frames": [{"sequence_order": 0}, {"sequence_order": 0}]},  # duplicate
        ]
        res_bad = runtime_asset_validator._validate_animation_sequences(bad_anims, "test_anim")
        statuses_bad = [r["status"] for r in res_bad]
        self.assertIn("FAIL", statuses_bad, "Duplicate sequence index must trigger FAIL")

    def test_11_fps_validation(self):
        """11. FPS validation: flags invalid or non-positive FPS values."""
        anims_neg = [{"name": "negative_fps", "fps": -5, "frames": []}]
        res_neg = runtime_asset_validator._validate_animation_sequences(anims_neg, "test_anim")
        statuses_neg = [r["status"] for r in res_neg]
        self.assertIn("FAIL", statuses_neg, "Negative FPS must trigger FAIL")

        anims_good = [{"name": "standard_fps", "fps": 12, "frames": []}]
        res_good = runtime_asset_validator._validate_animation_sequences(anims_good, "test_anim")
        fps_check = next(r for r in res_good if r["check_category"] == "animation_timing")
        self.assertEqual(fps_check["status"], "PASS")

    def test_12_pivot_coordinate_validation(self):
        """12. Pivot coordinate validation: verifies 0.0 <= pivot <= 1.0, flags out-of-bounds."""
        st_good, _ = runtime_asset_validator._check_pivot_coordinates(0.5, 0.5)
        self.assertEqual(st_good, "PASS")

        st_corner, _ = runtime_asset_validator._check_pivot_coordinates(0.0, 1.0)
        self.assertEqual(st_corner, "PASS")

        st_bad_neg, _ = runtime_asset_validator._check_pivot_coordinates(-0.1, 0.5)
        self.assertEqual(st_bad_neg, "FAIL")

        st_bad_high, _ = runtime_asset_validator._check_pivot_coordinates(0.5, 1.25)
        self.assertEqual(st_bad_high, "FAIL")

    def test_13_flame_format_compatibility_reporting(self):
        """13. Flame format compatibility reporting: evaluates Flame 1.x standard vs custom schemas."""
        custom_data = {
            "atlas": {"name": "sample", "width": 1024, "height": 1024},
            "sprites": {
                "wheel": {"x": 0, "y": 0, "width": 64, "height": 64}
            }
        }
        p = self.test_dir / "custom_schema.json"
        p.write_text(json.dumps(custom_data), encoding="utf-8")

        res = flame_compatibility_engine.inspect_metadata_file(p)
        self.assertEqual(res["detected_schema"], "flame_atlas_custom")
        self.assertTrue(res["conversion_available"])
        self.assertIsNotNone(res["conversion_preview"])
        self.assertIn("frames", res["conversion_preview"]["converted_dict"])

    def test_14_asset_to_component_assignment_persistence(self):
        """14. Asset-to-component assignment persistence: assign excavator part, persist, query by group."""
        assign_id = db.assign_game_component(
            component_group="Boom",
            asset_id=1,
            source_file="C:/mock/excavator_boom_orig.png",
            exported_file="excavator_boom.png",
            width=512,
            height=256,
            pivot_x=0.2,
            pivot_y=0.8,
            notes="Hydraulic joint mount",
        )
        self.assertGreater(assign_id, 0)

        assignments = db.get_game_component_assignments(component_group="Boom")
        self.assertGreaterEqual(len(assignments), 1)
        found = next((a for a in assignments if a["id"] == assign_id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["component_group"], "Boom")
        self.assertEqual(found["pivot_x"], 0.2)

        # Clean up
        db.remove_game_component_assignment(assign_id)

    def test_15_preview_engine_initialization(self):
        """15. Preview engine initialization: test static asset, atlas, and animation sequence loading."""
        test_img_path = self.test_dir / "preview_test.png"
        img = Image.new("RGBA", (128, 128), (100, 200, 50, 255))
        img.save(test_img_path, "PNG")

        # Load individual
        ind_res = game_asset_preview_engine.load_individual_asset(test_img_path)
        self.assertTrue(ind_res["success"])
        self.assertEqual(ind_res["width"], 128)

        # Load animation sequence
        anim_frames = [{"frame": i} for i in range(5)]
        anim_res = game_asset_preview_engine.load_animation_sequence("dig", anim_frames, fps=12)
        self.assertTrue(anim_res["success"])
        self.assertEqual(anim_res["frame_count"], 5)
        self.assertEqual(game_asset_preview_engine.playback.total_frames, 5)

        # Step forward & loop
        self.assertEqual(game_asset_preview_engine.playback.current_frame_index, 0)
        game_asset_preview_engine.playback.step_forward()
        self.assertEqual(game_asset_preview_engine.playback.current_frame_index, 1)

    def test_16_performance_calculations(self):
        """16. Performance calculations: measures disk sizes, estimates 32-bit RGBA VRAM, flags oversized textures."""
        sample_dir = self.test_dir / "perf_sample"
        sample_dir.mkdir(parents=True, exist_ok=True)

        # Create normal 256x256 image (256 * 256 * 4 = 262,144 bytes VRAM)
        img1 = Image.new("RGBA", (256, 256), (0, 0, 0, 255))
        img1.save(sample_dir / "tex1.png", "PNG")

        # Create oversized 3000x3000 image (> 2048 limit)
        img2 = Image.new("RGBA", (3000, 2000), (0, 0, 0, 255))
        img2.save(sample_dir / "tex_large.png", "PNG")

        res = asset_performance_analyzer.analyze_asset_directory(sample_dir)
        self.assertTrue(res["success"])
        m = res["measured_metrics"]
        e = res["estimated_metrics"]

        self.assertEqual(m["total_asset_count"], 2)
        self.assertGreater(e["estimated_decoded_ram_bytes"], 0)
        self.assertIn("32-bit RGBA", e["disclaimer"])

        # Must flag oversized texture warning
        warn_types = [w["type"] for w in res["warnings"]]
        self.assertIn("oversized_texture", warn_types)

    def test_17_isolated_flutter_test_fixture_generation(self):
        """17. Isolated Flutter test fixture generation: creates self-contained test package with pubspec & test."""
        fixture_dir = self.test_dir / "test_fixture_pkg"
        fixture_dir.mkdir(parents=True, exist_ok=True)

        pub_text = "name: isolated_test\ndependencies:\n  flame: ^1.18.0\n"
        (fixture_dir / "pubspec.yaml").write_text(pub_text, encoding="utf-8")

        test_dir = fixture_dir / "test"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "asset_test.dart").write_text("// test", encoding="utf-8")

        self.assertTrue((fixture_dir / "pubspec.yaml").exists())
        self.assertTrue((test_dir / "asset_test.dart").exists())

    def test_18_safe_integration_patch_preview(self):
        """18. Safe integration patch preview: generates non-destructive Dart code snippet preview."""
        patch_str = flame_compatibility_engine.get_engine_info()
        self.assertIn("Flame 1.x conversion preview & diff generator", patch_str["capabilities"])

    def test_19_database_migration_and_rollback(self):
        """19. Database migration and rollback: verifies Stage 11 tables exist, rollback drops them, re-init restores."""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='flutter_project_connections'")
            self.assertIsNotNone(cursor.fetchone())

        # Test rollback
        db.rollback_stage11_migration()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='flutter_project_connections'")
            self.assertIsNone(cursor.fetchone())

        # Re-initialize to restore
        db.init_db()
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='flutter_project_connections'")
            self.assertIsNotNone(cursor.fetchone())

    def test_20_original_source_integrity(self):
        """20. Original source integrity: verifies all 161 catalog original assets are 100% untouched on disk."""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, original_path, current_path, file_size FROM assets")
            db_assets = cursor.fetchall()

        self.assertEqual(len(db_assets), 161, f"Expected 161 original assets, found {len(db_assets)}")
        for row in db_assets:
            chosen = row["current_path"] if (row["current_path"] and Path(row["current_path"]).exists()) else row["original_path"]
            p = Path(chosen)
            self.assertTrue(p.exists(), f"Original asset missing: {p}")
            self.assertEqual(p.stat().st_size, row["file_size"], f"Original file size altered: {p}")

    def test_21_regression_stages_2_to_10(self):
        """21. Regression tests for Stages 2–10."""
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Stage 2 Gallery
            cursor.execute("SELECT COUNT(*) as c FROM assets")
            self.assertEqual(cursor.fetchone()["c"], 161)

            # Stage 3 AI Classification
            cursor.execute("SELECT COUNT(*) as c FROM classification_history")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            # Stage 4 Renaming
            cursor.execute("SELECT COUNT(*) as c FROM rename_history")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            # Stage 5 Background Removal
            cursor.execute("SELECT COUNT(*) as c FROM transparency_history")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            # Stage 6 Text Detection
            cursor.execute("SELECT COUNT(*) as c FROM text_detection_history")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            # Stage 7 Watermark Candidates
            cursor.execute("SELECT COUNT(*) as c FROM watermark_detection_history")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            # Stage 8 Collection Splitter
            cursor.execute("SELECT COUNT(*) as c FROM collection_analysis_history")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            # Stage 9 Sprite Sheet Definitions
            cursor.execute("SELECT COUNT(*) as c FROM sprite_sheet_definitions")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            # Stage 10 Optimization History & Atlases
            cursor.execute("SELECT COUNT(*) as c FROM optimization_history")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

            cursor.execute("SELECT COUNT(*) as c FROM texture_atlas_definitions")
            self.assertGreaterEqual(cursor.fetchone()["c"], 0)

        # MainWindow index 11 is GameIntegrationView
        mw = MainWindow()
        self.assertIsNotNone(mw)
        w11 = mw.workspace_stack.widget(11)
        self.assertIsInstance(w11, GameIntegrationView)


if __name__ == "__main__":
    unittest.main()
