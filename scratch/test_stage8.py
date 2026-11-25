"""
Comprehensive Stage 8 Verification Test Suite
Tests all 19 requirements of Stage 8 — Collection Splitter & Asset Extraction System:
1. SQLite Schema (3 new tables, 7 new columns in assets, indices)
2. DatabaseManager CRUD methods & stats
3. Collection Splitter Engine (composition classification, alpha & opaque segmentation, scene protection)
4. Sprite Sheet grid generator
5. Region extraction with padding & lossless preservation
6. Non-destructive safety & collision avoidance
7. Background worker thread controls (pause, resume, cancel)
8. Collection Canvas interactive controls & undo/redo
9. Collection Card & Extraction Inspector
10. Extraction Preview Dialog & export execution
11. CollectionSplitterView & MainWindow integration
12. End-to-end analysis & extraction across real project assets
"""

import hashlib
import os
import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for UI tests
app = QApplication.instance() or QApplication(sys.argv)

from app.config import THEME_COLORS, NAVIGATION_ITEMS
from core.database import db
from core.collection_splitter_engine import (
    CollectionSplitterEngine, collection_splitter_engine,
    COMPOSITION_TYPES, COMPOSITION_COLORS
)
from core.workers import CollectionAnalysisWorker
from ui.components.collection_canvas import CollectionCanvasWidget, CollectionCanvasContainer
from ui.components.collection_card import CollectionCard
from ui.components.extraction_inspector import ExtractionInspector
from ui.components.extraction_preview import ExtractionPreviewDialog, ExtractedAssetPreviewCard
from ui.views.collection_splitter_view import CollectionSplitterView
from ui.main_window import MainWindow


class TestStage8CollectionSplitter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = PROJECT_ROOT / "scratch" / "test_stage8_tmp"
        cls.test_dir.mkdir(parents=True, exist_ok=True)

    def test_01_sqlite_schema_tables_and_columns(self):
        """Verify 3 new tables, columns in assets, and indices exist."""
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Check tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertIn("collection_analysis_history", tables)
            self.assertIn("collection_regions", tables)
            self.assertIn("extracted_assets", tables)

            # 2. Check assets columns
            cursor.execute("PRAGMA table_info(assets)")
            cols = {row[1] for row in cursor.fetchall()}
            expected_cols = [
                "splitter_composition_type",
                "splitter_candidate_count",
                "splitter_analysis_status",
                "splitter_review_status",
                "splitter_extraction_status",
                "extracted_assets_count",
                "splitter_analysis_timestamp",
            ]
            for c in expected_cols:
                self.assertIn(c, cols, f"Missing column {c} in assets table")

            # 3. Check indices
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indices = {row[0] for row in cursor.fetchall()}
            self.assertIn("idx_assets_splitter_comp", indices)
            self.assertIn("idx_assets_splitter_status", indices)
            self.assertIn("idx_coll_regions_asset", indices)
            self.assertIn("idx_extracted_source_asset", indices)

    def test_02_database_manager_methods(self):
        """Verify DatabaseManager CRUD operations for Stage 8."""
        assets = db.get_assets(limit=1)
        self.assertTrue(len(assets) > 0)
        asset_id = assets[0]["id"]

        # History
        hist_id = db.add_collection_analysis_history(
            asset_id=asset_id,
            composition_type="Multiple Object Collection",
            candidate_count=3,
            detection_method="unit_test",
            explanation="Testing database manager methods",
            analysis_status="completed"
        )
        self.assertIsInstance(hist_id, int)
        history = db.get_collection_analysis_history(asset_id)
        self.assertTrue(len(history) > 0)
        self.assertEqual(history[0]["composition_type"], "Multiple Object Collection")

        # Regions
        reg_id = db.add_collection_region(
            asset_id=asset_id,
            x=10, y=20, width=50, height=60,
            region_type="isolated_asset",
            confidence_score=0.92,
            source_method="unit_test",
            review_status="pending"
        )
        self.assertIsInstance(reg_id, int)

        reg = db.get_collection_region(reg_id)
        self.assertIsNotNone(reg)
        self.assertEqual(reg["x"], 10)
        self.assertEqual(reg["width"], 50)

        # Update region
        db.update_collection_region(reg_id, {"width": 80, "review_status": "confirmed"})
        updated_reg = db.get_collection_region(reg_id)
        self.assertEqual(updated_reg["width"], 80)
        self.assertEqual(updated_reg["review_status"], "confirmed")

        # Stats
        stats = db.get_collection_splitter_stats()
        self.assertIn("total_images", stats)
        self.assertIn("analyzed_images", stats)
        self.assertIn("collection_candidates", stats)
        self.assertIn("sprite_sheets", stats)
        self.assertIn("ready_to_split", stats)
        self.assertIn("extracted_assets", stats)

        # Cleanup test region
        db.delete_collection_region(reg_id)
        self.assertIsNone(db.get_collection_region(reg_id))

    def test_03_alpha_connected_components_segmentation(self):
        """Verify engine segments multi-object transparent PNGs with alpha channel."""
        # Create transparent RGBA image with 3 separate circles
        img = Image.new("RGBA", (300, 150), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Object 1
        draw.ellipse([20, 30, 70, 80], fill=(255, 165, 0, 255))
        # Object 2
        draw.ellipse([120, 40, 170, 90], fill=(0, 200, 100, 255))
        # Object 3
        draw.ellipse([220, 20, 280, 80], fill=(0, 100, 255, 255))

        test_path = self.test_dir / "test_transparent_3obj.png"
        img.save(test_path)

        comp_type, regions, expl = collection_splitter_engine.analyze_image_file(str(test_path))
        self.assertIn(comp_type, ("Multiple Object Collection", "Sprite Sheet"))
        self.assertEqual(len(regions), 3)
        for r in regions:
            self.assertIn(r["region_type"], ("isolated_asset", "sprite_frame", "object"))
            self.assertGreater(r["width"], 20)
            self.assertGreater(r["height"], 20)

    def test_04_opaque_background_contour_segmentation(self):
        """Verify engine segments multiple objects on opaque studio backdrop."""
        # Create solid gray backdrop with 2 distinct dark rectangles
        img = Image.new("RGB", (300, 150), (240, 240, 240))
        draw = ImageDraw.Draw(img)
        # Box 1
        draw.rectangle([30, 30, 90, 90], fill=(20, 30, 40))
        # Box 2
        draw.rectangle([180, 40, 250, 110], fill=(180, 40, 30))

        test_path = self.test_dir / "test_opaque_2obj.png"
        img.save(test_path)

        comp_type, regions, expl = collection_splitter_engine.analyze_image_file(str(test_path))
        self.assertEqual(comp_type, "Multiple Object Collection")
        self.assertEqual(len(regions), 2)

    def test_05_scene_preservation_guard(self):
        """Verify background scenes are protected and NOT split into objects."""
        # Create rich landscape with noise / full border coverage
        np_scene = np.zeros((200, 300, 3), dtype=np.uint8)
        # Sky
        np_scene[:100, :] = [180, 120, 70]
        # Ground
        np_scene[100:, :] = [40, 100, 50]
        # High texture everywhere
        noise = np.random.randint(0, 40, (200, 300, 3), dtype=np.uint8)
        np_scene = np.clip(np_scene + noise, 0, 255).astype(np.uint8)

        test_path = self.test_dir / "test_scene.png"
        Image.fromarray(np_scene).save(test_path)

        comp_type, regions, expl = collection_splitter_engine.analyze_image_file(str(test_path))
        self.assertEqual(comp_type, "Background Scene")
        self.assertEqual(len(regions), 0)

    def test_06_sprite_sheet_uniform_grid_generation(self):
        """Verify uniform sprite sheet grid calculation."""
        grid = collection_splitter_engine.generate_sprite_grid(
            image_width=400,
            image_height=300,
            cols=4,
            rows=3,
            margin_x=10,
            margin_y=15,
            spacing_x=6,
            spacing_y=6,
        )
        self.assertEqual(len(grid), 12)
        # Check frame indices
        for idx, box in enumerate(grid):
            self.assertEqual(box["frame_index"], idx)
            self.assertEqual(box["width"], 90)
            self.assertEqual(box["height"], 86)
            self.assertGreaterEqual(box["x"], 10)
            self.assertGreaterEqual(box["y"], 15)

    def test_07_region_extraction_with_padding_and_lossless_mode(self):
        """Verify non-destructive extraction preserving RGBA transparency and applying padding."""
        orig_img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(orig_img)
        draw.rectangle([50, 50, 100, 100], fill=(229, 169, 60, 255))

        # Extract with 8px padding
        crop = collection_splitter_engine.extract_region(orig_img, 50, 50, 50, 50, padding=8)
        self.assertEqual(crop.size, (66, 66))
        self.assertEqual(crop.mode, "RGBA")

        # Interior pixel should be exact color
        interior_px = crop.getpixel((8 + 10, 8 + 10))
        self.assertEqual(interior_px, (229, 169, 60, 255))

        # Border pixel should be transparent padded pixel
        border_px = crop.getpixel((0, 0))
        self.assertEqual(border_px, (0, 0, 0, 0))

    def test_08_safe_asset_export_and_provenance(self):
        """Verify safe asset export avoiding collisions and recording provenance."""
        assets = db.get_assets(limit=1)
        self.assertTrue(len(assets) > 0)
        source_asset = assets[0]

        crop = Image.new("RGBA", (64, 64), (16, 185, 129, 255))
        out_folder = self.test_dir / "separated_test"
        if out_folder.exists():
            for f in out_folder.glob("*.*"):
                f.unlink()
        out_folder.mkdir(parents=True, exist_ok=True)

        # Export 1
        success1, path1, err1 = collection_splitter_engine.export_extracted_asset(
            cropped_img=crop,
            source_asset_id=source_asset["id"],
            source_region_id=None,
            proposed_filename="excavator_gear.png",
            output_folder=str(out_folder),
            frame_index=0,
            padding=8,
        )
        self.assertTrue(success1)
        self.assertTrue(Path(path1).exists())
        self.assertEqual(Path(path1).name, "excavator_gear.png")

        # Export 2 with same name -> collision resolution "_01"
        success2, path2, err2 = collection_splitter_engine.export_extracted_asset(
            cropped_img=crop,
            source_asset_id=source_asset["id"],
            source_region_id=None,
            proposed_filename="excavator_gear.png",
            output_folder=str(out_folder),
            frame_index=1,
            padding=8,
        )
        self.assertTrue(success2)
        self.assertTrue(Path(path2).exists())
        self.assertEqual(Path(path2).name, "excavator_gear_01.png")

        # Check provenance in SQLite
        extracted_records = db.get_extracted_assets_for_source(source_asset["id"])
        self.assertGreaterEqual(len(extracted_records), 2)
        exported_fnames = [r["output_filename"] for r in extracted_records]
        self.assertIn("excavator_gear.png", exported_fnames)
        self.assertIn("excavator_gear_01.png", exported_fnames)

    def test_09_source_image_integrity(self):
        """Verify that source images are NEVER modified."""
        assets = db.get_assets(limit=5)
        for a in assets:
            orig_p = Path(a["original_path"])
            if orig_p.exists():
                h1 = hashlib.md5(orig_p.read_bytes()).hexdigest()
                # Run engine analysis
                collection_splitter_engine.process_and_save_asset(a)
                # Verify hash unchanged
                h2 = hashlib.md5(orig_p.read_bytes()).hexdigest()
                self.assertEqual(h1, h2, f"Source image was modified: {orig_p}")

    def test_10_worker_lifecycle_controls(self):
        """Verify CollectionAnalysisWorker thread methods: cancel, pause, resume."""
        worker = CollectionAnalysisWorker(mode="all", parent=None)
        self.assertFalse(worker._is_cancelled)
        self.assertFalse(worker._is_paused)

        worker.pause()
        self.assertTrue(worker._is_paused)

        worker.resume()
        self.assertFalse(worker._is_paused)

        worker.cancel()
        self.assertTrue(worker._is_cancelled)

    def test_11_collection_canvas_widget_and_undo_redo(self):
        """Verify interactive collection canvas, coordinate mapping, and undo/redo history."""
        canvas = CollectionCanvasWidget()
        test_path = self.test_dir / "test_transparent_3obj.png"
        canvas.load_image(str(test_path), [
            {"id": 1, "x": 10, "y": 10, "width": 50, "height": 50, "region_type": "isolated_asset"}
        ])

        self.assertEqual(len(canvas.get_regions()), 1)

        # Coordinate mapping
        canvas._scale = 2.0
        canvas._offset = QPoint(100, 50)
        c_pt = canvas.img_to_canvas(20, 30)
        self.assertEqual(c_pt.x(), 100 + 20 * 2.0)
        self.assertEqual(c_pt.y(), 50 + 30 * 2.0)

        img_pt = canvas.canvas_to_img(c_pt.x(), c_pt.y())
        self.assertEqual(img_pt.x(), 20)
        self.assertEqual(img_pt.y(), 30)

        # Test Undo / Redo
        canvas.set_regions([
            {"id": 1, "x": 10, "y": 10, "width": 50, "height": 50, "region_type": "isolated_asset"},
            {"id": 2, "x": 80, "y": 80, "width": 40, "height": 40, "region_type": "isolated_asset"},
        ])
        self.assertEqual(len(canvas.get_regions()), 2)

        canvas.undo()
        self.assertEqual(len(canvas.get_regions()), 1)

        canvas.redo()
        self.assertEqual(len(canvas.get_regions()), 2)

    def test_12_collection_card_and_inspector_ui(self):
        """Verify CollectionCard and ExtractionInspector initialization and data loading."""
        assets = db.get_assets(limit=1)
        self.assertTrue(len(assets) > 0)
        asset = assets[0]

        card = CollectionCard(asset)
        self.assertEqual(card.asset_id, asset["id"])
        card.set_selected(True)
        self.assertTrue(card.is_selected)

        inspector = ExtractionInspector()
        inspector.load_asset(asset)
        self.assertEqual(inspector.lbl_filename.text(), asset["filename"])

    def test_13_extraction_preview_dialog(self):
        """Verify ExtractionPreviewDialog generates previews and respects approved selections."""
        assets = db.get_assets(limit=1)
        self.assertTrue(len(assets) > 0)
        asset = assets[0]

        regions = [
            {"id": 1, "x": 10, "y": 10, "width": 40, "height": 40, "region_type": "isolated_asset"},
            {"id": 2, "x": 60, "y": 60, "width": 50, "height": 50, "region_type": "isolated_asset"},
        ]

        dlg = ExtractionPreviewDialog(
            source_asset=asset,
            regions=regions,
            default_padding=4,
        )
        self.assertEqual(len(dlg.cards), 2)
        self.assertEqual(dlg.padding, 4)
        self.assertTrue(dlg.cards[0].is_approved)
        self.assertTrue(dlg.cards[1].is_approved)

        # Deselect first
        dlg.cards[0].chk_approve.setChecked(False)
        self.assertFalse(dlg.cards[0].is_approved)
        self.assertEqual(sum(1 for c in dlg.cards if c.is_approved), 1)

    def test_14_collection_splitter_view_and_mainwindow(self):
        """Verify CollectionSplitterView UI and stack integration in MainWindow."""
        win = MainWindow()
        self.assertGreaterEqual(win.workspace_stack.count(), 13)

        # Switch to Splitter View (Index 8)
        win.sidebar.select_id("splitter")
        self.assertEqual(win.workspace_stack.currentIndex(), 8)
        self.assertIsInstance(win.workspace_stack.currentWidget(), CollectionSplitterView)

        splitter_view = win.collection_splitter_view
        self.assertIsNotNone(splitter_view)
        # Verify 6 stat cards exist
        self.assertIsNotNone(splitter_view.card_total)
        self.assertIsNotNone(splitter_view.card_analyzed)
        self.assertIsNotNone(splitter_view.card_collections)
        self.assertIsNotNone(splitter_view.card_sprites)
        self.assertIsNotNone(splitter_view.card_ready)
        self.assertIsNotNone(splitter_view.card_extracted)

    def test_15_batch_analysis_across_all_real_assets(self):
        """Run collection splitter analysis across all 161 imported catalog assets."""
        all_assets = db.get_assets(limit=10000)
        self.assertEqual(len(all_assets), 161, f"Expected 161 catalog assets, found {len(all_assets)}")

        collection_count = 0
        sprite_sheet_count = 0
        single_count = 0
        scene_count = 0

        for a in all_assets:
            success, comp_type, cand_cnt, msg = collection_splitter_engine.process_and_save_asset(a)
            self.assertTrue(success)
            self.assertIn(comp_type, COMPOSITION_TYPES)
            if comp_type in ("Multiple Object Collection", "Overlapping Object Collection"):
                collection_count += 1
            elif comp_type in ("Sprite Sheet", "Animation Frame Grid"):
                sprite_sheet_count += 1
            elif comp_type == "Background Scene":
                scene_count += 1
            else:
                single_count += 1

        stats = db.get_collection_splitter_stats()
        self.assertEqual(stats["total_images"], 161)
        self.assertEqual(stats["analyzed_images"], 161)
        self.assertGreater(stats["collection_candidates"] + stats["sprite_sheets"], 0)
        print(f"\n[Stage 8 Real Assets Analysis Result]:")
        print(f"  • Total Images: {stats['total_images']}")
        print(f"  • Collection Candidates: {stats['collection_candidates']}")
        print(f"  • Sprite Sheets: {stats['sprite_sheets']}")
        print(f"  • Single Objects: {single_count}")
        print(f"  • Background Scenes: {scene_count}")
        print(f"  • Ready to Split: {stats['ready_to_split']}")


if __name__ == "__main__":
    unittest.main()
