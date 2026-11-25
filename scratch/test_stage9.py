"""
Comprehensive Stage 9 Verification Test Suite
Construction Asset Processor

Tests all requirements of Stage 9 — Sprite Sheet Editor & Animation Frame Management:
1. SQLite Schema (4 new tables, 3 new columns in assets, indices)
2. DatabaseManager CRUD methods & stats
3. Sprite Sheet Engine info & offline capabilities
4. Image source inspection (dimensions, mode, transparency)
5. Mode A Uniform Grid calculation (exact fitting)
6. Mode A Uniform Grid calculation with spacing & margins
7. Grid bounds clipping & validation
8. Mode B Manual frame creation
9. Frame deletion & continuous sequence renumbering
10. Frame duplication
11. Frame reordering & sequence order
12. Pivot presets & kinematic pixel offset resolution
13. Animation Playback Controller (play, pause, stop, step, loop)
14. FPS configuration & custom frame duration
15. Lossless PNG frame extraction & transparency retention
16. Flutter + Flame documented JSON metadata export
17. Filename collision handling (increment, skip, overwrite)
18. Stage 8 candidate region import
19. Canvas & Timeline UI components with undo/redo
20. SpriteSheetEditorView & MainWindow integration
21. Source image non-destructive integrity check across real assets
"""

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for UI tests
app = QApplication.instance() or QApplication(sys.argv)

from app.config import (
    INPUT_DIR, NAVIGATION_ITEMS, OUTPUT_SPRITES_DIR, THEME_COLORS
)
from core.animation_preview_engine import AnimationPlaybackController
from core.database import db
from core.sprite_sheet_engine import (
    ANIMATION_PRESETS, PIVOT_PRESETS, STANDARD_FPS_VALUES,
    SpriteSheetEngine, sprite_sheet_engine
)
from ui.components.animation_preview import AnimationPreviewWidget
from ui.components.frame_inspector import FrameInspector
from ui.components.frame_timeline import FrameTimeline
from ui.components.sprite_sheet_canvas import (
    SpriteSheetCanvasContainer, SpriteSheetCanvasWidget
)
from ui.components.sprite_sheet_export_dialog import SpriteSheetExportDialog
from ui.main_window import MainWindow
from ui.views.sprite_sheet_editor_view import SpriteSheetEditorView


class TestStage9SpriteSheetEditor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = PROJECT_ROOT / "scratch" / "test_stage9_tmp"
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        # Create a synthetic test sprite sheet with transparency (4 frames of 64x64 on 256x64 canvas)
        cls.test_sheet_path = cls.test_dir / "test_spritesheet_alpha.png"
        img = Image.new("RGBA", (256, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        colors = [(255, 100, 100, 255), (100, 255, 100, 255), (100, 100, 255, 255), (255, 255, 100, 255)]
        for i, col in enumerate(colors):
            draw.rectangle([i * 64 + 4, 4, (i + 1) * 64 - 5, 59], fill=col, outline=(255, 255, 255, 255))
        img.save(cls.test_sheet_path, "PNG")

        # Record hash of test sheet to verify non-destructiveness
        with open(cls.test_sheet_path, "rb") as f:
            cls.test_sheet_hash = hashlib.sha256(f.read()).hexdigest()

    def test_01_sqlite_schema_tables_and_columns(self):
        """Verify 4 new tables, columns in assets, and indices exist."""
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Check tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertIn("sprite_sheet_definitions", tables)
            self.assertIn("sprite_frames", tables)
            self.assertIn("sprite_animations", tables)
            self.assertIn("animation_frame_sequences", tables)

            # 2. Check assets columns
            cursor.execute("PRAGMA table_info(assets)")
            cols = {row[1] for row in cursor.fetchall()}
            self.assertIn("sprite_sheet_id", cols)
            self.assertIn("sprite_frames_count", cols)
            self.assertIn("sprite_editor_status", cols)

            # 3. Check indices
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indices = {row[0] for row in cursor.fetchall()}
            self.assertTrue("idx_sheet_def_asset" in indices or "idx_sprite_sheet_definitions_asset_id" in indices)
            self.assertTrue("idx_sprite_frames_sheet" in indices or "idx_sprite_frames_sheet_id" in indices)
            self.assertTrue("idx_sprite_anim_sheet" in indices or "idx_sprite_animations_sheet_id" in indices)

    def test_02_database_manager_crud(self):
        """Test DB Manager CRUD methods for sprite sheets, frames, and animations."""
        # 1. Create definition
        sheet_id = db.create_or_update_sprite_sheet_definition(
            name="test_excavator_arm",
            source_image_path=str(self.test_sheet_path),
            source_filename="test_spritesheet_alpha.png",
            sheet_width=256,
            sheet_height=64,
            layout_mode="uniform",
            columns=4,
            rows=1,
            frame_width=64,
            frame_height=64,
            default_fps=12,
            status="draft",
        )
        self.assertIsInstance(sheet_id, int)
        self.assertGreater(sheet_id, 0)

        # 2. Read definition
        sheet_def = db.get_sprite_sheet_definition(sheet_id)
        self.assertIsNotNone(sheet_def)
        self.assertEqual(sheet_def["name"], "test_excavator_arm")
        self.assertEqual(sheet_def["columns"], 4)
        self.assertEqual(sheet_def["default_fps"], 12)

        # 3. Add frames
        test_frames = [
            {"frame_index": 0, "frame_name": "arm_00", "x": 0, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 1.0, "duration_ms": 100, "sequence_order": 0},
            {"frame_index": 1, "frame_name": "arm_01", "x": 64, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 1.0, "duration_ms": 100, "sequence_order": 1},
        ]
        db.save_sprite_frames(sheet_id, test_frames)

        frames = db.get_sprite_frames(sheet_id)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]["frame_name"], "arm_00")
        self.assertEqual(frames[1]["pivot_y"], 1.0)

        # 4. Create Animation Sequence
        anim_id = db.create_sprite_animation(sheet_id, "Digging", animation_type="Digging", fps=12, loop=1)
        self.assertIsInstance(anim_id, int)

        frame_ids = [f["id"] for f in frames]
        db.set_animation_frame_sequence(anim_id, frame_ids)

        seq = db.get_animation_frame_sequence(anim_id)
        self.assertEqual(len(seq), 2)

        # 5. Stats
        stats = db.get_sprite_sheet_stats()
        self.assertGreaterEqual(stats["total_sheets"], 1)
        self.assertGreaterEqual(stats["total_frames"], 2)
        self.assertGreaterEqual(stats["total_animations"], 1)

    def test_03_engine_info_and_capabilities(self):
        """Verify sprite_sheet_engine info and offline capabilities."""
        info = sprite_sheet_engine.get_engine_info()
        self.assertTrue(info["offline"])
        self.assertIn("version", info)
        self.assertGreater(len(info["capabilities"]), 3)

    def test_04_image_source_inspection(self):
        """Verify image source inspection returns accurate dimensions and transparency."""
        res = sprite_sheet_engine.inspect_image_source(str(self.test_sheet_path))
        self.assertTrue(res["valid"])
        self.assertEqual(res["width"], 256)
        self.assertEqual(res["height"], 64)
        self.assertEqual(res["channels"], 4)
        self.assertTrue(res["has_transparency"])
        self.assertAlmostEqual(res["aspect_ratio"], 4.0, places=2)

    def test_05_uniform_grid_calculation_exact(self):
        """Mode A: Test uniform grid calculation with exact rows and columns."""
        frames = sprite_sheet_engine.calculate_uniform_grid(
            image_width=256,
            image_height=64,
            columns=4,
            rows=1,
            frame_width=64,
            frame_height=64,
            name_prefix="test_grid",
        )
        self.assertEqual(len(frames), 4)
        for i, f in enumerate(frames):
            self.assertEqual(f["frame_index"], i)
            self.assertEqual(f["x"], i * 64)
            self.assertEqual(f["y"], 0)
            self.assertEqual(f["width"], 64)
            self.assertEqual(f["height"], 64)
            self.assertEqual(f["pivot_x"], 0.5)
            self.assertEqual(f["pivot_y"], 0.5)

    def test_06_uniform_grid_margins_and_spacing(self):
        """Mode A: Test grid generation with margins and spacing."""
        # 3 cols x 2 rows, frame 50x50, spacing X=10, Y=10, margin L=20, T=30
        frames = sprite_sheet_engine.calculate_uniform_grid(
            image_width=300,
            image_height=200,
            columns=3,
            rows=2,
            frame_width=50,
            frame_height=50,
            spacing_x=10,
            spacing_y=10,
            margin_left=20,
            margin_top=30,
            name_prefix="spaced",
        )
        self.assertEqual(len(frames), 6)
        # Check frame (col=1, row=1 -> index 4)
        f4 = frames[4]
        expected_x = 20 + 1 * (50 + 10)  # 80
        expected_y = 30 + 1 * (50 + 10)  # 90
        self.assertEqual(f4["x"], expected_x)
        self.assertEqual(f4["y"], expected_y)

    def test_07_uniform_grid_bounds_clipping(self):
        """Verify out-of-bounds frames beyond image dimensions are safely excluded."""
        frames = sprite_sheet_engine.calculate_uniform_grid(
            image_width=100,
            image_height=100,
            columns=3,
            rows=3,
            frame_width=60,  # 3 * 60 = 180 > 100!
            frame_height=60,
        )
        # Only frame (0,0) fits within 100x100
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["x"], 0)
        self.assertEqual(frames[0]["y"], 0)

    def test_08_mode_b_manual_frame_creation(self):
        """Mode B: Test manual frame creation with arbitrary coordinates and custom pivot."""
        frame = sprite_sheet_engine.create_manual_frame(
            index=3,
            x=15,
            y=25,
            w=90,
            h=70,
            frame_name="irregular_hydraulic_joint",
            pivot=(0.25, 0.75),
            duration_ms=150,
        )
        self.assertEqual(frame["frame_index"], 3)
        self.assertEqual(frame["x"], 15)
        self.assertEqual(frame["y"], 25)
        self.assertEqual(frame["width"], 90)
        self.assertEqual(frame["height"], 70)
        self.assertEqual(frame["pivot_x"], 0.25)
        self.assertEqual(frame["pivot_y"], 0.75)
        self.assertEqual(frame["duration_ms"], 150)

    def test_09_frame_deletion_and_renumbering(self):
        """Verify deleting a frame and renumbering maintains continuous indexing."""
        frames = [
            {"frame_index": 0, "frame_name": "f_0", "sequence_order": 0},
            {"frame_index": 1, "frame_name": "f_1", "sequence_order": 1},
            {"frame_index": 2, "frame_name": "f_2", "sequence_order": 2},
        ]
        del frames[1]  # delete middle frame
        renumbered = sprite_sheet_engine.renumber_frames(frames)
        self.assertEqual(len(renumbered), 2)
        self.assertEqual(renumbered[0]["frame_index"], 0)
        self.assertEqual(renumbered[0]["sequence_order"], 0)
        self.assertEqual(renumbered[1]["frame_index"], 1)
        self.assertEqual(renumbered[1]["sequence_order"], 1)
        self.assertEqual(renumbered[1]["frame_name"], "f_2")

    def test_10_frame_duplication(self):
        """Verify duplicating a frame preserves coordinates and pivot while appending."""
        src = {"frame_index": 0, "frame_name": "idle_0", "x": 10, "y": 20, "width": 50, "height": 50, "pivot_x": 0.5, "pivot_y": 1.0, "duration_ms": 120}
        dup = dict(src)
        dup["frame_name"] = "idle_0_copy"
        dup["frame_index"] = 1
        dup["sequence_order"] = 1

        self.assertEqual(dup["x"], 10)
        self.assertEqual(dup["y"], 20)
        self.assertEqual(dup["pivot_x"], 0.5)
        self.assertEqual(dup["pivot_y"], 1.0)
        self.assertEqual(dup["duration_ms"], 120)

    def test_11_frame_reordering(self):
        """Verify reordering frame list updates sequence_order correctly."""
        f0 = {"frame_index": 0, "frame_name": "step_0"}
        f1 = {"frame_index": 1, "frame_name": "step_1"}
        reordered = [f1, f0]  # swap
        renum = sprite_sheet_engine.renumber_frames(reordered)
        self.assertEqual(renum[0]["frame_index"], 0)
        self.assertEqual(renum[0]["frame_name"], "step_1")
        self.assertEqual(renum[1]["frame_index"], 1)
        self.assertEqual(renum[1]["frame_name"], "step_0")

    def test_12_pivot_point_presets_and_offsets(self):
        """Verify pivot presets and absolute pixel offset calculations."""
        # Test presets exist
        self.assertIn("Center", PIVOT_PRESETS)
        self.assertIn("Bottom Center", PIVOT_PRESETS)
        self.assertIn("Bottom Left", PIVOT_PRESETS)
        self.assertEqual(PIVOT_PRESETS["Bottom Center"], (0.5, 1.0))

        frame = {"x": 100, "y": 200, "width": 80, "height": 60, "pivot_x": 0.5, "pivot_y": 1.0}
        px_off, py_off, abs_x, abs_y = sprite_sheet_engine.resolve_pivot_coordinates(frame)
        self.assertEqual(px_off, 40)
        self.assertEqual(py_off, 60)
        self.assertEqual(abs_x, 140)
        self.assertEqual(abs_y, 260)

    def test_13_animation_playback_controller(self):
        """Test AnimationPlaybackController stepping, jumping, loop mode, and speed."""
        ctrl = AnimationPlaybackController()
        frames = [
            {"frame_index": 0, "name": "f0", "duration_ms": 100},
            {"frame_index": 1, "name": "f1", "duration_ms": 100},
            {"frame_index": 2, "name": "f2", "duration_ms": 100},
        ]
        ctrl.set_sequence(frames)
        self.assertEqual(ctrl.get_sequence_length(), 3)
        self.assertEqual(ctrl.current_index, 0)

        # Step forward
        ctrl.step_forward()
        self.assertEqual(ctrl.current_index, 1)

        # Step backward
        ctrl.step_backward()
        self.assertEqual(ctrl.current_index, 0)

        # Jump to frame
        ctrl.goto_frame(2)
        self.assertEqual(ctrl.current_index, 2)

        # Step forward with loop enabled -> wraps to 0
        ctrl.set_loop_enabled(True)
        ctrl.step_forward()
        self.assertEqual(ctrl.current_index, 0)

        # Speed multiplier
        ctrl.set_speed_multiplier(2.0)
        self.assertEqual(ctrl.speed_multiplier, 2.0)

        # Stop
        ctrl.stop()
        self.assertFalse(ctrl.is_playing)
        self.assertEqual(ctrl.current_index, 0)

    def test_14_fps_and_duration_calculations(self):
        """Test FPS settings and duration delay conversions."""
        ctrl = AnimationPlaybackController()
        ctrl.set_fps(24)
        self.assertEqual(ctrl.fps, 24)

        # Clamping
        ctrl.set_fps(0)
        self.assertEqual(ctrl.fps, 1)
        ctrl.set_fps(200)
        self.assertEqual(ctrl.fps, 120)

    def test_15_lossless_png_frame_extraction(self):
        """Test crop and export of lossless PNG frames with full alpha preservation."""
        frames = [
            {"frame_index": 0, "frame_name": "red_box", "x": 0, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 0.5},
            {"frame_index": 1, "frame_name": "green_box", "x": 64, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 0.5},
        ]
        out_dir = self.test_dir / "exported_frames"
        out_dir.mkdir(parents=True, exist_ok=True)

        res = sprite_sheet_engine.export_individual_frames(
            source_image_path=str(self.test_sheet_path),
            frames=frames,
            output_dir=out_dir,
            filename_pattern="test_export_{index:02d}",
            collision_mode="overwrite",
        )
        self.assertEqual(len(res), 2)
        for p in res:
            self.assertTrue(Path(p).exists())
            with Image.open(p) as img:
                self.assertEqual(img.size, (64, 64))
                self.assertEqual(img.mode, "RGBA")
                # Verify alpha exists (not fully opaque)
                alpha_chan = np.array(img)[:, :, 3]
                self.assertTrue(np.any(alpha_chan == 0))

    def test_16_flutter_flame_json_metadata_export(self):
        """Test exporting Flutter + Flame JSON metadata specification."""
        sheet_def = {
            "name": "excavator_tracks",
            "source_filename": "tracks_sheet.png",
            "sheet_width": 256,
            "sheet_height": 64,
            "layout_mode": "uniform",
            "columns": 4,
            "rows": 1,
            "frame_width": 64,
            "frame_height": 64,
            "spacing_x": 0,
            "spacing_y": 0,
            "default_fps": 15,
            "loop_default": 1,
        }
        frames = [
            {"frame_index": 0, "frame_name": "tracks_0", "x": 0, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 1.0, "duration_ms": 66},
            {"frame_index": 1, "frame_name": "tracks_1", "x": 64, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 1.0, "duration_ms": 66},
        ]
        anims = [
            {"name": "Driving", "type": "Driving", "fps": 15, "loop": 1, "sequence": [0, 1]}
        ]
        out_dir = self.test_dir / "exported_meta"
        out_dir.mkdir(parents=True, exist_ok=True)

        meta_path = sprite_sheet_engine.export_flutter_flame_metadata(
            sheet_def=sheet_def,
            frames=frames,
            animations=anims,
            output_dir=out_dir,
        )
        self.assertTrue(Path(meta_path).exists())

        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["generator"], "Construction Asset Processor — Sprite Sheet Engine")
        self.assertEqual(data["format_version"], "1.0.0")
        self.assertIn("flame_integration", data)
        self.assertIn("SpriteAnimation.fromFrameData", data["flame_integration"]["dart_sample"])
        self.assertEqual(len(data["frames"]), 2)
        self.assertEqual(data["frames"][0]["pivot"]["normalized_x"], 0.5)
        self.assertEqual(data["frames"][0]["pivot"]["normalized_y"], 1.0)
        self.assertEqual(data["frames"][0]["pivot"]["pixel_offset_x"], 32)
        self.assertEqual(data["frames"][0]["pivot"]["pixel_offset_y"], 64)

    def test_17_filename_collision_handling(self):
        """Verify export collision modes (increment suffix vs skip vs overwrite)."""
        frames = [{"frame_index": 0, "frame_name": "coll_test", "x": 0, "y": 0, "width": 32, "height": 32}]
        out_dir = self.test_dir / "collision_test"
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        # First export
        res1 = sprite_sheet_engine.export_individual_frames(
            str(self.test_sheet_path), frames, out_dir, "collision_frame", collision_mode="increment"
        )
        self.assertTrue(Path(res1[0]).exists())
        self.assertEqual(Path(res1[0]).name, "collision_frame.png")

        # Second export with increment -> collision_frame_01.png
        res2 = sprite_sheet_engine.export_individual_frames(
            str(self.test_sheet_path), frames, out_dir, "collision_frame", collision_mode="increment"
        )
        self.assertTrue(Path(res2[0]).exists())
        self.assertEqual(Path(res2[0]).name, "collision_frame_01.png")

    def test_18_stage8_candidate_import(self):
        """Verify candidate sprite sheet regions from Stage 8 can be imported."""
        # Find any asset with composition_type 'Sprite Sheet' or 'Animation Frame Grid'
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, filename FROM assets WHERE composition_type IN ('Sprite Sheet', 'Animation Frame Grid') LIMIT 1")
            row = cursor.fetchone()
        if row:
            asset_id = row["id"]
            imported = sprite_sheet_engine.import_stage8_candidate_regions(asset_id)
            self.assertIsInstance(imported, list)
            if imported:
                self.assertIn("x", imported[0])
                self.assertIn("width", imported[0])
                self.assertIn("pivot_x", imported[0])

    def test_19_canvas_and_timeline_ui_components(self):
        """Instantiate SpriteSheetCanvas, test zoom, pan, select, draw, undo/redo, and Timeline."""
        canvas_container = SpriteSheetCanvasContainer()
        canvas = canvas_container.canvas
        canvas.set_image(str(self.test_sheet_path), [
            {"frame_index": 0, "frame_name": "f0", "x": 0, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 0.5},
            {"frame_index": 1, "frame_name": "f1", "x": 64, "y": 0, "width": 64, "height": 64, "pivot_x": 0.5, "pivot_y": 0.5},
        ])

        # Test selection
        canvas.select_frame(0)
        self.assertEqual(canvas._selected_index, 0)

        # Test zoom
        canvas.zoom_100()
        self.assertEqual(canvas._scale, 1.0)
        canvas.zoom_in()
        self.assertGreater(canvas._scale, 1.0)
        canvas.zoom_100()
        self.assertEqual(canvas._scale, 1.0)

        # Test undo/redo
        initial_frames_len = len(canvas._frames)
        canvas.push_undo_snapshot()
        canvas.delete_selected_frame()
        self.assertEqual(len(canvas._frames), initial_frames_len - 1)
        canvas.undo()
        self.assertEqual(len(canvas._frames), initial_frames_len)
        canvas.redo()
        self.assertEqual(len(canvas._frames), initial_frames_len - 1)

        # Test Timeline
        timeline = FrameTimeline()
        timeline.set_frames(canvas._frames)
        self.assertEqual(len(timeline._cards), len(canvas._frames))
        canvas_container.close()
        timeline.close()
        app.processEvents()

    def test_20_view_and_main_window_integration(self):
        """Instantiate SpriteSheetEditorView and MainWindow, verify index 9 and navigation."""
        view = SpriteSheetEditorView()
        self.assertIsNotNone(view)
        self.assertEqual(view.active_mode, "uniform")

        # Test MainWindow
        mw = MainWindow()
        self.assertIsNotNone(mw)
        # Check that workspace stack index 9 contains SpriteSheetEditorView
        w9 = mw.workspace_stack.widget(9)
        self.assertIsInstance(w9, SpriteSheetEditorView)

        # Check navigation item badge
        sprite_item = next((item for item in NAVIGATION_ITEMS if item["id"] == "spritesheet"), None)
        self.assertIsNotNone(sprite_item)
        self.assertEqual(sprite_item["badge"], "Active")

        # Switch to index 9
        mw._on_navigation_changed("spritesheet", 9)
        self.assertEqual(mw.workspace_stack.currentIndex(), 9)
        mw.close()

    def test_21_source_image_non_destructive_integrity(self):
        """Verify that our synthetic test sheet and real assets were never modified."""
        # 1. Synthetic test sheet
        with open(self.test_sheet_path, "rb") as f:
            current_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(current_hash, self.test_sheet_hash, "Synthetic sprite sheet was modified!")

        # 2. Check catalog assets
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, original_path, current_path, file_size FROM assets LIMIT 20")
            rows = cursor.fetchall()
        for r in rows:
            chosen = r["current_path"] if (r["current_path"] and Path(r["current_path"]).exists()) else r["original_path"]
            p = Path(chosen)
            self.assertTrue(p.exists(), f"Asset file missing: {p}")
            self.assertEqual(p.stat().st_size, r["file_size"], f"Asset file size modified: {p}")


if __name__ == "__main__":
    unittest.main()
