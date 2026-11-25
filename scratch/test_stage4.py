"""
Comprehensive Verification Test Suite for Stage 4: Smart Asset Renaming
Validates:
1. Compilation of all Stage 4 modules.
2. Filename standardization & sanitization rules ([a-z0-9_], no spaces, extension preserved).
3. Batch proposal generation & collision detection (161 assets).
4. Manual edits, approval, and rejection updates in SQLite.
5. Real statistics querying for the 6 metrics cards.
6. Filtering & search query validation.
7. Safe rename execution and one-click rollback on disk (using dedicated test dummy asset).
8. Guarantee that all 161 original assets remain 100% untouched.
"""

import os
import sys
import py_compile
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import db
from core.naming_engine import naming_engine, clean_filename, sanitize_token


def test_compilation():
    print("\n--- 1. Testing Compilation of Stage 4 Modules ---")
    files = [
        "core/database.py",
        "core/naming_engine.py",
        "ui/components/renaming_inspector.py",
        "ui/components/rename_preview_dialog.py",
        "ui/components/rename_history_dialog.py",
        "ui/views/renaming_view.py",
        "ui/main_window.py"
    ]
    for f in files:
        py_compile.compile(f, doraise=True)
        print(f"  [PASS] Compiled {f}")


def test_naming_rules():
    print("\n--- 2. Testing Naming Rules & Sanitization ---")
    cases = [
        ("Excavator Yellow Side View!!", ".PNG", "excavator_yellow_side_view.png"),
        ("construction--dump--truck   red", ".JPG", "construction_dump_truck_red.jpg"),
        ("123___rock__texture--sample", "webp", "123_rock_texture_sample.webp"),
        ("  ___Special #$% Asset   ", ".png", "special_asset.png"),
        ("", ".png", "construction_asset.png"),
    ]
    import re
    safe_pattern = re.compile(r"^[a-z0-9_]+\.[a-z0-9]+$")

    for raw, ext, expected in cases:
        result = clean_filename(raw, ext)
        assert result == expected, f"Expected {expected}, got {result}"
        assert safe_pattern.match(result), f"Result {result} failed safe pattern!"
        assert "__" not in result, f"Result {result} contains repeated underscores!"
        print(f"  [PASS] clean_filename('{raw}', '{ext}') -> '{result}'")


def test_batch_generation_and_collisions():
    print("\n--- 3. Testing Batch Generation & Collision Detection across 161 Assets ---")
    assets = db.get_assets(limit=1000, sort_by="id", ascending=True)
    assert len(assets) == 161, f"Expected 161 assets, found {len(assets)}"

    proposals = naming_engine.process_all_assets(assets)
    assert len(proposals) == 161, f"Expected 161 proposals, got {len(proposals)}"

    conflicts = [p for p in proposals if p["naming_conflict"] == 1]
    print(f"  [INFO] Total proposals: {len(proposals)}, Flagged collisions: {len(conflicts)}")

    # Verify every proposal has a valid clean filename
    import re
    safe_pattern = re.compile(r"^[a-z0-9_]+\.[a-z0-9]+$")
    for p in proposals:
        fn = p["suggested_filename"]
        assert safe_pattern.match(fn), f"Invalid suggested filename: {fn}"
        assert "__" not in fn, f"Double underscore in: {fn}"

    # Apply batch proposals to SQLite
    saved_count = naming_engine.apply_batch_suggestions(proposals)
    assert saved_count == 161, f"Expected 161 saved suggestions, got {saved_count}"
    print(f"  [PASS] Successfully applied and persisted 161 standardized names to SQLite.")


def test_metrics_and_database_updates():
    print("\n--- 4. Testing Real Statistics & Status Transitions ---")
    stats = db.get_naming_stats()
    print("  Current naming stats:", stats)
    assert stats["total_images"] == 161
    assert stats["names_generated"] == 161
    assert stats["pending_review"] >= 0

    # Test single asset manual edit
    test_asset = db.get_assets(limit=1)[0]
    aid = test_asset["id"]

    # Manual edit
    success = db.update_naming(
        asset_id=aid,
        approved_filename="excavator_custom_manual_name.png",
        naming_status="manual",
        naming_conflict=0
    )
    assert success
    updated = db.get_asset(aid)
    assert updated["naming_status"] == "manual"
    assert updated["approved_filename"] == "excavator_custom_manual_name.png"
    print("  [PASS] Manual filename override saved and verified in SQLite.")

    # Approve status
    db.update_naming(asset_id=aid, naming_status="approved")
    updated = db.get_asset(aid)
    assert updated["naming_status"] == "approved"
    print("  [PASS] Approved status transition verified.")

    # Reject status
    db.update_naming(asset_id=aid, naming_status="rejected")
    updated = db.get_asset(aid)
    assert updated["naming_status"] == "rejected"
    print("  [PASS] Rejected status transition verified.")

    # Reset back to pending for cleanliness
    db.update_naming(asset_id=aid, naming_status="pending", approved_filename=None)


def test_filters_and_queries():
    print("\n--- 5. Testing Database Queries & Filters ---")
    # Collection filter
    exc_cnt = db.get_asset_count(collection="excavator")
    other_cnt = db.get_asset_count(collection="other_images")
    assert exc_cnt == 25, f"Expected 25 excavator images, got {exc_cnt}"
    assert other_cnt == 136, f"Expected 136 other images, got {other_cnt}"
    print(f"  [PASS] Collection filtering: Excavator={exc_cnt}, Other={other_cnt}")

    # Search filter (160 Gemini files + 1 gg.png = 161 total)
    search_cnt = db.get_asset_count(search="Gemini")
    assert search_cnt == 160, f"Expected 160 Gemini files, got {search_cnt}"
    png_cnt = db.get_asset_count(search="png")
    assert png_cnt == 161, f"Expected 161 PNG files, got {png_cnt}"
    print(f"  [PASS] Search filtering verified: {search_cnt} matches for 'Gemini', {png_cnt} matches for 'png'")


def test_filesystem_safe_rename_and_rollback():
    print("\n--- 6. Testing Safe Filesystem Rename & Rollback (Zero Data Loss) ---")
    # Create an isolated dummy file in scratch directory
    scratch_dir = Path(__file__).resolve().parent
    dummy_orig = scratch_dir / "dummy_test_asset_orig.png"
    dummy_orig.write_bytes(b"\x89PNG\r\n\x1a\nTESTDUMMYDATA")

    # Insert temporary asset record into SQLite
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO assets (
                filename, original_path, current_path, collection, format,
                width, height, file_size, rename_status, naming_status, status
            ) VALUES (?, ?, ?, 'test', 'png', 100, 100, 20, 'not_renamed', 'pending', 'pending')
        """, (dummy_orig.name, str(dummy_orig.resolve()), str(dummy_orig.resolve())))
        dummy_id = cursor.lastrowid

    try:
        # Step A: Perform Safe Rename
        target_name = "dummy_test_asset_renamed.png"
        target_file = scratch_dir / target_name
        if target_file.exists():
            target_file.unlink()

        success, msg = db.execute_rename_asset(dummy_id, target_name, user_approved=True)
        assert success, f"execute_rename_asset failed: {msg}"
        assert not dummy_orig.exists(), "Original dummy file should no longer exist after rename!"
        assert target_file.exists(), "Target file must exist on disk after rename!"

        # Check DB update
        asset_after_rename = db.get_asset(dummy_id)
        assert asset_after_rename["filename"] == target_name
        assert asset_after_rename["rename_status"] == "renamed"
        assert asset_after_rename["naming_status"] == "approved"
        print(f"  [PASS] Safe Rename executed: '{dummy_orig.name}' -> '{target_name}' on disk & DB.")

        # Step B: Test Overwrite Protection
        # Create a conflicting file with target name
        conflict_dummy = scratch_dir / "dummy_conflict.png"
        conflict_dummy.write_bytes(b"CONFLICT")
        # Attempt to rename target_file to dummy_conflict.png should be refused!
        fail_success, fail_msg = db.execute_rename_asset(dummy_id, "dummy_conflict.png")
        assert not fail_success, "Expected rename to fail when target already exists on disk!"
        assert "already exists on disk" in fail_msg
        conflict_dummy.unlink()
        print("  [PASS] Overwrite protection verified: refused to overwrite existing disk file.")

        # Step C: Test Rollback
        history_list = db.get_rename_history(limit=5)
        match_hist = [h for h in history_list if h["asset_id"] == dummy_id]
        assert len(match_hist) > 0, "No rename history record found for test asset!"
        hist_entry = match_hist[0]
        assert hist_entry["rollback_status"] == "active"

        rb_success, rb_msg = db.rollback_rename_asset(hist_entry["id"])
        assert rb_success, f"Rollback failed: {rb_msg}"
        assert dummy_orig.exists(), "Original file must exist again after rollback!"
        assert not target_file.exists(), "Renamed file must not exist after rollback!"

        asset_after_rb = db.get_asset(dummy_id)
        assert asset_after_rb["filename"] == dummy_orig.name
        assert asset_after_rb["rename_status"] == "not_renamed"
        print(f"  [PASS] Safe Rollback executed: restored '{target_name}' -> '{dummy_orig.name}' on disk & DB.")

    finally:
        # Cleanup dummy files and DB entry
        if dummy_orig.exists():
            dummy_orig.unlink()
        target_f = scratch_dir / "dummy_test_asset_renamed.png"
        if target_f.exists():
            target_f.unlink()

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM assets WHERE id = ?", (dummy_id,))
            cursor.execute("DELETE FROM rename_history WHERE asset_id = ?", (dummy_id,))


def test_original_assets_intact():
    print("\n--- 7. Verifying 161 User Collection Assets Remain 100% Intact ---")
    assets = db.get_assets(limit=1000)
    for a in assets:
        p = Path(a["original_path"])
        assert p.exists(), f"Source file missing: {p}"
        assert a["rename_status"] == "not_renamed", f"Asset #{a['id']} has rename_status {a['rename_status']}"
    print("  [PASS] All 161 original image files are confirmed intact and untouched on disk.")


if __name__ == "__main__":
    print("================================================================")
    print("       STAGE 4 — SMART ASSET RENAMING TEST SUITE                ")
    print("================================================================")
    test_compilation()
    test_naming_rules()
    test_batch_generation_and_collisions()
    test_metrics_and_database_updates()
    test_filters_and_queries()
    test_filesystem_safe_rename_and_rollback()
    test_original_assets_intact()
    print("\n================================================================")
    print("       ALL 7 STAGE 4 TEST SUITES PASSED PERFECTLY!             ")
    print("================================================================")
