"""
Database Layer for Construction Asset Processor
SQLite database manager with thread-safe access, schema migration,
metadata tracking, and dashboard metric calculations.
"""

import json
import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import DATABASE_PATH

logger = logging.getLogger(__name__)


def format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if num_bytes <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


# Register custom timestamp converters to prevent Python 3.12+ DeprecationWarning
def _convert_timestamp(val: bytes) -> str:
    return val.decode("utf-8")


sqlite3.register_converter("timestamp", _convert_timestamp)
sqlite3.register_converter("TIMESTAMP", _convert_timestamp)


class DatabaseManager:
    """Manages SQLite database connections and operations."""

    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Context manager providing thread-safe sqlite3 connection with Row factory."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=20.0,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency and foreign keys
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error during transaction: {e}")
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create database tables and indices if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Assets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    collection TEXT NOT NULL DEFAULT 'other_images',
                    file_size INTEGER NOT NULL DEFAULT 0,
                    file_hash TEXT,
                    format TEXT,
                    width INTEGER DEFAULT 0,
                    height INTEGER DEFAULT 0,
                    aspect_ratio REAL DEFAULT 0.0,
                    color_mode TEXT,
                    has_transparency INTEGER DEFAULT 0,
                    thumbnail_path TEXT,
                    status TEXT DEFAULT 'pending',
                    stage_status TEXT DEFAULT '{}',
                    metadata_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Indices for rapid querying
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_collection ON assets (collection);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_status ON assets (status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_hash ON assets (file_hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_filename ON assets (filename);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_format ON assets (format);")

            # Scan history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_path TEXT NOT NULL,
                    scanned_count INTEGER DEFAULT 0,
                    new_imported_count INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Processing logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processing_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER,
                    action TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'import',
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'info',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL
                );
            """)

            # App key-value settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Classification history table (Stage 3)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS classification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    main_category TEXT,
                    subcategory TEXT,
                    object_name TEXT,
                    visual_tags TEXT,
                    composition_type TEXT,
                    confidence_score REAL DEFAULT 0.0,
                    model_name TEXT,
                    suggested_filename TEXT,
                    action TEXT NOT NULL,
                    ai_explanation TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_class_hist_asset ON classification_history(asset_id);")

            # Rename history table (Stage 4)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rename_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    original_path TEXT NOT NULL,
                    new_path TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    new_filename TEXT NOT NULL,
                    operation_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    operation_status TEXT DEFAULT 'success',
                    user_approval INTEGER DEFAULT 1,
                    rollback_status TEXT DEFAULT 'active',
                    error_message TEXT DEFAULT '',
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rename_hist_asset ON rename_history(asset_id);")

            # Transparency history table (Stage 5)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transparency_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    method TEXT DEFAULT 'local_cv',
                    processed_path TEXT NOT NULL,
                    quality_status TEXT DEFAULT 'pending',
                    manual_approval TEXT DEFAULT 'unreviewed',
                    error_message TEXT DEFAULT '',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trans_hist_asset ON transparency_history(asset_id);")

            # Text Detection Regions table (Stage 6)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS text_regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    box_x INTEGER NOT NULL,
                    box_y INTEGER NOT NULL,
                    box_w INTEGER NOT NULL,
                    box_h INTEGER NOT NULL,
                    recognized_text TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    category TEXT DEFAULT 'Unknown writing',
                    review_status TEXT DEFAULT 'unreviewed',
                    is_watermark_candidate INTEGER DEFAULT 0,
                    manual_correction TEXT DEFAULT '',
                    model_name TEXT DEFAULT 'OpenCV_MSER',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_text_regions_asset ON text_regions(asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_text_regions_review ON text_regions(review_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_text_regions_watermark ON text_regions(is_watermark_candidate);")

            # Text Detection History table (Stage 6)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS text_detection_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    detected_count INTEGER DEFAULT 0,
                    model_name TEXT DEFAULT 'OpenCV_MSER',
                    model_version TEXT DEFAULT '1.0',
                    status TEXT DEFAULT 'success',
                    error_message TEXT DEFAULT '',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_text_hist_asset ON text_detection_history(asset_id);")

            # Watermark Regions table (Stage 7)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watermark_regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    candidate_type TEXT NOT NULL,
                    candidate_text TEXT DEFAULT '',
                    candidate_score REAL NOT NULL,
                    detection_method TEXT NOT NULL,
                    detection_reason TEXT NOT NULL,
                    review_status TEXT DEFAULT 'pending',
                    reviewer_notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watermark_regions_asset ON watermark_regions(asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watermark_regions_review ON watermark_regions(review_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watermark_regions_type ON watermark_regions(candidate_type);")

            # Watermark Detection History table (Stage 7)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watermark_detection_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    engine_version TEXT DEFAULT '1.0',
                    detection_method TEXT DEFAULT 'multi_signal_cv',
                    candidate_count INTEGER DEFAULT 0,
                    processing_status TEXT DEFAULT 'success',
                    error_message TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watermark_hist_asset ON watermark_detection_history(asset_id);")

            # Collection Analysis History table (Stage 8)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS collection_analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    composition_type TEXT NOT NULL,
                    candidate_count INTEGER DEFAULT 0,
                    detection_method TEXT DEFAULT 'multi_feature_cv',
                    explanation TEXT DEFAULT '',
                    analysis_status TEXT DEFAULT 'success',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_coll_hist_asset ON collection_analysis_history(asset_id);")

            # Collection Regions table (Stage 8)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS collection_regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    region_type TEXT DEFAULT 'object',
                    confidence_score REAL DEFAULT 0.5,
                    source_method TEXT DEFAULT 'auto_segmentation',
                    review_status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_coll_regions_asset ON collection_regions(asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_coll_regions_review ON collection_regions(review_status);")

            # Extracted Assets table (Stage 8)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS extracted_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_asset_id INTEGER NOT NULL,
                    source_region_id INTEGER,
                    output_path TEXT NOT NULL,
                    output_filename TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    frame_index INTEGER DEFAULT 0,
                    padding INTEGER DEFAULT 0,
                    export_status TEXT DEFAULT 'exported',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_asset_id) REFERENCES assets(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_region_id) REFERENCES collection_regions(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_extracted_source_asset ON extracted_assets(source_asset_id);")

            # Sprite Sheet Definitions table (Stage 9)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sprite_sheet_definitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER,
                    name TEXT NOT NULL,
                    sheet_type TEXT DEFAULT 'uniform_grid',
                    image_path TEXT NOT NULL,
                    image_width INTEGER DEFAULT 0,
                    image_height INTEGER DEFAULT 0,
                    cols INTEGER DEFAULT 1,
                    rows INTEGER DEFAULT 1,
                    frame_width INTEGER DEFAULT 0,
                    frame_height INTEGER DEFAULT 0,
                    h_spacing INTEGER DEFAULT 0,
                    v_spacing INTEGER DEFAULT 0,
                    margin_left INTEGER DEFAULT 0,
                    margin_right INTEGER DEFAULT 0,
                    margin_top INTEGER DEFAULT 0,
                    margin_bottom INTEGER DEFAULT 0,
                    default_fps INTEGER DEFAULT 10,
                    loop_default INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'draft',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sheet_def_asset ON sprite_sheet_definitions(asset_id);")

            # Ensure columns exist in sprite_sheet_definitions
            cursor.execute("PRAGMA table_info(sprite_sheet_definitions)")
            sheet_cols = {row[1] for row in cursor.fetchall()}
            if "default_fps" not in sheet_cols:
                cursor.execute("ALTER TABLE sprite_sheet_definitions ADD COLUMN default_fps INTEGER DEFAULT 10;")
            if "loop_default" not in sheet_cols:
                cursor.execute("ALTER TABLE sprite_sheet_definitions ADD COLUMN loop_default INTEGER DEFAULT 1;")
            if "status" not in sheet_cols:
                cursor.execute("ALTER TABLE sprite_sheet_definitions ADD COLUMN status TEXT DEFAULT 'draft';")

            # Sprite Frames table (Stage 9)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sprite_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sprite_sheet_id INTEGER NOT NULL,
                    frame_index INTEGER NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    pivot_x REAL DEFAULT 0.5,
                    pivot_y REAL DEFAULT 0.5,
                    frame_duration_ms INTEGER DEFAULT 100,
                    frame_name TEXT DEFAULT '',
                    transparency_status TEXT DEFAULT 'opaque',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sprite_sheet_id) REFERENCES sprite_sheet_definitions(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sprite_frames_sheet ON sprite_frames(sprite_sheet_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sprite_frames_order ON sprite_frames(sprite_sheet_id, frame_index);")

            # Sprite Animations table (Stage 9)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sprite_animations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sprite_sheet_id INTEGER NOT NULL,
                    animation_name TEXT NOT NULL,
                    fps INTEGER DEFAULT 10,
                    loop_enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (sprite_sheet_id) REFERENCES sprite_sheet_definitions(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sprite_anim_sheet ON sprite_animations(sprite_sheet_id);")

            # Animation Frame Sequences table (Stage 9)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS animation_frame_sequences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    animation_id INTEGER NOT NULL,
                    frame_id INTEGER NOT NULL,
                    sequence_order INTEGER NOT NULL,
                    duration_override_ms INTEGER DEFAULT 0,
                    FOREIGN KEY (animation_id) REFERENCES sprite_animations(id) ON DELETE CASCADE,
                    FOREIGN KEY (frame_id) REFERENCES sprite_frames(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_anim_seq_anim ON animation_frame_sequences(animation_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_anim_seq_order ON animation_frame_sequences(animation_id, sequence_order);")

            # 1. Optimization History table (Stage 10)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS optimization_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_asset_id INTEGER,
                    input_path TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    input_size INTEGER NOT NULL,
                    output_size INTEGER NOT NULL,
                    input_format TEXT NOT NULL,
                    output_format TEXT NOT NULL,
                    input_width INTEGER NOT NULL,
                    input_height INTEGER NOT NULL,
                    output_width INTEGER NOT NULL,
                    output_height INTEGER NOT NULL,
                    compression_settings TEXT DEFAULT '{}',
                    transparency_status TEXT DEFAULT 'opaque',
                    optimization_status TEXT DEFAULT 'success',
                    error_message TEXT DEFAULT '',
                    export_job_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_asset_id) REFERENCES assets(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_hist_asset ON optimization_history(source_asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_hist_job ON optimization_history(export_job_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_opt_hist_status ON optimization_history(optimization_status);")

            # 2. Flutter Export Jobs table (Stage 10)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS flutter_export_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    target_flutter_dir TEXT NOT NULL,
                    total_assets INTEGER DEFAULT 0,
                    exported_assets INTEGER DEFAULT 0,
                    total_input_bytes INTEGER DEFAULT 0,
                    total_output_bytes INTEGER DEFAULT 0,
                    pubspec_updated INTEGER DEFAULT 0,
                    pubspec_backup_path TEXT DEFAULT '',
                    export_status TEXT DEFAULT 'staged',
                    error_message TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_export_jobs_status ON flutter_export_jobs(export_status);")

            # 3. Texture Atlas Definitions table (Stage 10)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS texture_atlas_definitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    atlas_name TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    output_image_path TEXT NOT NULL,
                    output_metadata_path TEXT NOT NULL,
                    atlas_width INTEGER NOT NULL,
                    atlas_height INTEGER NOT NULL,
                    padding INTEGER DEFAULT 2,
                    spacing INTEGER DEFAULT 2,
                    power_of_two INTEGER DEFAULT 0,
                    allow_rotation INTEGER DEFAULT 0,
                    packing_algorithm TEXT DEFAULT 'maxrects',
                    packing_efficiency REAL DEFAULT 0.0,
                    sprite_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'ready',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_atlas_def_name ON texture_atlas_definitions(atlas_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_atlas_def_category ON texture_atlas_definitions(category);")

            # 4. Texture Atlas Entries table (Stage 10)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS texture_atlas_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    atlas_id INTEGER NOT NULL,
                    source_asset_id INTEGER,
                    source_path TEXT NOT NULL,
                    sprite_name TEXT NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    is_rotated INTEGER DEFAULT 0,
                    original_width INTEGER NOT NULL,
                    original_height INTEGER NOT NULL,
                    trim_offset_x INTEGER DEFAULT 0,
                    trim_offset_y INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (atlas_id) REFERENCES texture_atlas_definitions(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_asset_id) REFERENCES assets(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_atlas_entries_atlas ON texture_atlas_entries(atlas_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_atlas_entries_asset ON texture_atlas_entries(source_asset_id);")

            # 5. Asset Validation Results table (Stage 10)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS asset_validation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_asset_id INTEGER,
                    asset_path TEXT NOT NULL,
                    validation_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT DEFAULT '{}',
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_val_results_asset ON asset_validation_results(source_asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_val_results_status ON asset_validation_results(status);")

            # -----------------------------------------------------------------
            # Stage 11 — Game Integration & Runtime Verification Tables
            # -----------------------------------------------------------------

            # 1. Flutter Project Connections table (Stage 11)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS flutter_project_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL,
                    project_path TEXT NOT NULL UNIQUE,
                    pubspec_path TEXT DEFAULT '',
                    is_valid_flutter INTEGER DEFAULT 0,
                    has_lib INTEGER DEFAULT 0,
                    has_assets INTEGER DEFAULT 0,
                    flutter_version TEXT DEFAULT '',
                    flame_version TEXT DEFAULT '',
                    flame_detected INTEGER DEFAULT 0,
                    declared_asset_dirs TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'connected',
                    last_inspected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_flt_proj_path ON flutter_project_connections(project_path);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_flt_proj_status ON flutter_project_connections(status);")

            # 2. Runtime Validation Sessions table (Stage 11)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runtime_validation_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    session_name TEXT NOT NULL,
                    target_asset_dir TEXT NOT NULL,
                    total_assets INTEGER DEFAULT 0,
                    passed_count INTEGER DEFAULT 0,
                    warning_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    not_tested_count INTEGER DEFAULT 0,
                    overall_status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES flutter_project_connections(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rt_val_sess_proj ON runtime_validation_sessions(project_id);")

            # 3. Runtime Validation Results table (Stage 11)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runtime_validation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    asset_id INTEGER,
                    asset_path TEXT NOT NULL,
                    asset_type TEXT NOT NULL DEFAULT 'image',
                    check_category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES runtime_validation_sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rt_val_res_sess ON runtime_validation_results(session_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rt_val_res_status ON runtime_validation_results(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rt_val_res_cat ON runtime_validation_results(check_category);")

            # 4. Flame Compatibility Results table (Stage 11)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS flame_compatibility_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    metadata_path TEXT NOT NULL,
                    flame_version_detected TEXT DEFAULT '',
                    format_schema TEXT NOT NULL DEFAULT 'flame_atlas_v1',
                    is_compatible INTEGER DEFAULT 0,
                    compatibility_status TEXT NOT NULL DEFAULT 'uninspected',
                    issues_json TEXT DEFAULT '[]',
                    conversion_suggested INTEGER DEFAULT 0,
                    converted_metadata_json TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES flutter_project_connections(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_flame_compat_proj ON flame_compatibility_results(project_id);")

            # 5. Game Component Assignments table (Stage 11 Excavator parts)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_component_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component_group TEXT NOT NULL,
                    asset_id INTEGER NOT NULL,
                    source_file TEXT NOT NULL,
                    exported_file TEXT DEFAULT '',
                    width INTEGER DEFAULT 0,
                    height INTEGER DEFAULT 0,
                    pivot_x REAL DEFAULT 0.5,
                    pivot_y REAL DEFAULT 0.5,
                    transparency_status TEXT DEFAULT 'opaque',
                    validation_status TEXT DEFAULT 'unreviewed',
                    associated_animation TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_comp_group ON game_component_assignments(component_group);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_comp_asset ON game_component_assignments(asset_id);")

            # 6. Integration Test Results table (Stage 11)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS integration_test_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    test_type TEXT NOT NULL DEFAULT 'isolated_fixture',
                    test_package_path TEXT DEFAULT '',
                    flutter_executable TEXT DEFAULT '',
                    flame_compatible INTEGER DEFAULT 0,
                    tests_executed INTEGER DEFAULT 0,
                    tests_passed INTEGER DEFAULT 0,
                    tests_failed INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'not_tested',
                    raw_output TEXT DEFAULT '',
                    patch_preview_content TEXT DEFAULT '',
                    is_patch_approved INTEGER DEFAULT 0,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES flutter_project_connections(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_int_test_proj ON integration_test_results(project_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_int_test_status ON integration_test_results(status);")

            # 7. Asset Performance Reports table (Stage 11)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS asset_performance_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    total_asset_count INTEGER DEFAULT 0,
                    total_disk_bytes INTEGER DEFAULT 0,
                    png_bytes INTEGER DEFAULT 0,
                    webp_bytes INTEGER DEFAULT 0,
                    atlas_count INTEGER DEFAULT 0,
                    sprite_count INTEGER DEFAULT 0,
                    atlas_avg_efficiency REAL DEFAULT 0.0,
                    max_texture_width INTEGER DEFAULT 0,
                    max_texture_height INTEGER DEFAULT 0,
                    duplicate_count INTEGER DEFAULT 0,
                    missing_ref_count INTEGER DEFAULT 0,
                    estimated_decoded_ram_bytes INTEGER DEFAULT 0,
                    animation_ram_breakdown_json TEXT DEFAULT '{}',
                    warnings_json TEXT DEFAULT '[]',
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES flutter_project_connections(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_rep_proj ON asset_performance_reports(project_id);")

            # -----------------------------------------------------------------
            # Stage 13 — Excavator Asset Extraction, Background Cleanup & Sprite Preparation
            # -----------------------------------------------------------------

            # 1. Excavator Preparations table (Stage 13)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS excavator_preparations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL UNIQUE,
                    source_path TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    review_status TEXT DEFAULT 'Not Reviewed',
                    white_bg_detected INTEGER DEFAULT 0,
                    has_watermark_warning INTEGER DEFAULT 0,
                    has_text_warning INTEGER DEFAULT 0,
                    bg_removal_method TEXT DEFAULT 'grabcut_color_dist',
                    color_tolerance INTEGER DEFAULT 25,
                    processed_image_path TEXT DEFAULT '',
                    mask_path TEXT DEFAULT '',
                    quality_status TEXT DEFAULT 'Manual Review Required',
                    quality_report_json TEXT DEFAULT '{}',
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_excav_prep_asset ON excavator_preparations(asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_excav_prep_review ON excavator_preparations(review_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_excav_prep_qual ON excavator_preparations(quality_status);")

            # 2. Extracted Components table (Stage 13)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS extracted_components (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    preparation_id INTEGER,
                    component_type TEXT NOT NULL,
                    component_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    orig_width INTEGER DEFAULT 0,
                    orig_height INTEGER DEFAULT 0,
                    export_width INTEGER DEFAULT 0,
                    export_height INTEGER DEFAULT 0,
                    bbox_x INTEGER DEFAULT 0,
                    bbox_y INTEGER DEFAULT 0,
                    bbox_w INTEGER DEFAULT 0,
                    bbox_h INTEGER DEFAULT 0,
                    pivot_norm_x REAL DEFAULT 0.5,
                    pivot_norm_y REAL DEFAULT 0.5,
                    pivot_pixel_x INTEGER DEFAULT 0,
                    pivot_pixel_y INTEGER DEFAULT 0,
                    pivot_status TEXT DEFAULT 'Not Defined',
                    transparency_status TEXT DEFAULT 'True Alpha',
                    processing_method TEXT DEFAULT 'lasso_grabcut',
                    manual_review_status TEXT DEFAULT 'Reviewed',
                    approval_status TEXT DEFAULT 'Pending',
                    export_path TEXT DEFAULT '',
                    is_unavailable INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
                    FOREIGN KEY (preparation_id) REFERENCES excavator_preparations(id) ON DELETE SET NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ext_comp_asset ON extracted_components(asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ext_comp_type ON extracted_components(component_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ext_comp_appr ON extracted_components(approval_status);")

            # 3. Stage 13 Export Jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stage13_export_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    destination_path TEXT NOT NULL,
                    components_count INTEGER DEFAULT 0,
                    manifest_path TEXT DEFAULT '',
                    status TEXT DEFAULT 'completed',
                    details_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_stg13_exp_status ON stage13_export_jobs(status);")

            # -----------------------------------------------------------------
            # Stage 13.2 — Global Sequential Asset Pipeline & Processing Queue
            # -----------------------------------------------------------------
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflow_stages (
                    stage_id INTEGER PRIMARY KEY,
                    stage_key TEXT UNIQUE NOT NULL,
                    stage_name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'locked',
                    is_unlocked INTEGER DEFAULT 0,
                    total_eligible INTEGER DEFAULT 0,
                    completed_count INTEGER DEFAULT 0,
                    needs_review_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    last_run_timestamp TIMESTAMP,
                    notes TEXT DEFAULT ''
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflow_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    stage_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    output_path TEXT DEFAULT '',
                    approval_status TEXT DEFAULT 'unreviewed',
                    error_message TEXT DEFAULT '',
                    retry_count INTEGER DEFAULT 0,
                    source_hash TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
                    FOREIGN KEY (stage_id) REFERENCES workflow_stages(stage_id) ON DELETE CASCADE,
                    UNIQUE(asset_id, stage_id)
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wf_q_asset ON workflow_queue(asset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wf_q_stage ON workflow_queue(stage_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wf_q_status ON workflow_queue(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wf_q_appr ON workflow_queue(approval_status);")

            # Schema migration for Stage 3, Stage 4, Stage 5 & Stage 6 fields on assets table
            cursor.execute("PRAGMA table_info(assets);")
            existing_cols = {row["name"] for row in cursor.fetchall()}

            new_columns = [
                ("main_category", "TEXT DEFAULT 'Unclassified'"),
                ("subcategory", "TEXT DEFAULT ''"),
                ("object_name", "TEXT DEFAULT ''"),
                ("visual_tags", "TEXT DEFAULT '[]'"),
                ("composition_type", "TEXT DEFAULT 'Single Object'"),
                ("confidence_score", "REAL DEFAULT 0.0"),
                ("classification_status", "TEXT DEFAULT 'unclassified'"),
                ("model_name", "TEXT DEFAULT ''"),
                ("model_version", "TEXT DEFAULT ''"),
                ("analysis_timestamp", "TIMESTAMP"),
                ("ai_explanation", "TEXT DEFAULT ''"),
                ("manual_override", "INTEGER DEFAULT 0"),
                ("suggested_filename", "TEXT DEFAULT ''"),
                ("special_flags", "TEXT DEFAULT '{}'"),
                # Stage 4 Smart Renaming fields
                ("approved_filename", "TEXT DEFAULT ''"),
                ("naming_status", "TEXT DEFAULT 'pending'"),
                ("naming_conflict", "INTEGER DEFAULT 0"),
                ("rename_status", "TEXT DEFAULT 'not_renamed'"),
                ("current_path", "TEXT DEFAULT ''"),
                ("last_rename_timestamp", "TIMESTAMP"),
                # Stage 5 Background Removal & Transparency fields
                ("background_eligibility", "TEXT DEFAULT 'Unknown — Manual Review'"),
                ("background_method", "TEXT DEFAULT 'local_cv'"),
                ("bg_processing_status", "TEXT DEFAULT 'not_processed'"),
                ("processed_path", "TEXT DEFAULT ''"),
                ("processed_width", "INTEGER DEFAULT 0"),
                ("processed_height", "INTEGER DEFAULT 0"),
                ("processed_file_size", "INTEGER DEFAULT 0"),
                ("alpha_detected", "INTEGER DEFAULT 0"),
                ("bg_processing_timestamp", "TIMESTAMP"),
                ("bg_quality_status", "TEXT DEFAULT 'pending'"),
                ("bg_manual_approval", "TEXT DEFAULT 'unreviewed'"),
                ("bg_processing_error", "TEXT DEFAULT ''"),
                # Stage 6 Text & Label Detection fields
                ("text_detected_count", "INTEGER DEFAULT 0"),
                ("text_detection_status", "TEXT DEFAULT 'uninspected'"),
                ("text_review_status", "TEXT DEFAULT 'pending'"),
                ("has_watermark_text", "INTEGER DEFAULT 0"),
                ("text_detection_timestamp", "TIMESTAMP"),
                # Stage 7 Watermark Detection & Review fields
                ("watermark_detection_status", "TEXT DEFAULT 'uninspected'"),
                ("watermark_candidate_count", "INTEGER DEFAULT 0"),
                ("watermark_review_status", "TEXT DEFAULT 'unreviewed'"),
                ("watermark_replacement_status", "TEXT DEFAULT 'none'"),
                ("watermark_detection_timestamp", "TIMESTAMP"),
                # Stage 8 Collection Splitter & Asset Extraction fields
                ("splitter_composition_type", "TEXT DEFAULT 'Unknown'"),
                ("splitter_candidate_count", "INTEGER DEFAULT 0"),
                ("splitter_analysis_status", "TEXT DEFAULT 'uninspected'"),
                ("splitter_review_status", "TEXT DEFAULT 'pending'"),
                ("splitter_extraction_status", "TEXT DEFAULT 'not_extracted'"),
                ("extracted_assets_count", "INTEGER DEFAULT 0"),
                ("splitter_analysis_timestamp", "TIMESTAMP"),
                # Stage 9 Sprite Sheet & Animation Frame Management fields
                ("sprite_sheet_id", "INTEGER"),
                ("sprite_frames_count", "INTEGER DEFAULT 0"),
                ("sprite_editor_status", "TEXT DEFAULT 'unconfigured'"),
                # Stage 10 Asset Optimization, Validation & Flutter Export fields
                ("optimization_status", "TEXT DEFAULT 'pending'"),
                ("optimized_size", "INTEGER DEFAULT 0"),
                ("validation_status", "TEXT DEFAULT 'unvalidated'"),
                ("is_approved_for_export", "INTEGER DEFAULT 0"),
                # Stage 11 Game Integration fields
                ("game_component_group", "TEXT DEFAULT ''"),
                ("game_component_status", "TEXT DEFAULT 'unassigned'"),
                ("runtime_validation_status", "TEXT DEFAULT 'untested'"),
                # Stage 13 Excavator Asset Extraction & Sprite Preparation fields
                ("stage13_review_status", "TEXT DEFAULT 'Not Reviewed'"),
                ("stage13_prep_status", "TEXT DEFAULT 'unprocessed'"),
                ("stage13_components_count", "INTEGER DEFAULT 0"),
                # Stage 13.2 Global Sequential Workflow fields
                ("workflow_current_stage", "INTEGER DEFAULT 1"),
                ("workflow_overall_status", "TEXT DEFAULT 'pending'"),
            ]

            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE assets ADD COLUMN {col_name} {col_type};")

            # Initialize current_path = original_path where empty
            cursor.execute("UPDATE assets SET current_path = original_path WHERE current_path IS NULL OR current_path = '';")

            # Create indices for classification and renaming query acceleration
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_main_category ON assets(main_category);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_class_status ON assets(classification_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_confidence ON assets(confidence_score);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_naming_status ON assets(naming_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_rename_status ON assets(rename_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_naming_conflict ON assets(naming_conflict);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_bg_eligibility ON assets(background_eligibility);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_bg_status ON assets(bg_processing_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_bg_approval ON assets(bg_manual_approval);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_text_status ON assets(text_detection_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_text_review ON assets(text_review_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_has_watermark ON assets(has_watermark_text);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_wm_status ON assets(watermark_detection_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_wm_candidate_cnt ON assets(watermark_candidate_count);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_wm_review ON assets(watermark_review_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_wm_replacement ON assets(watermark_replacement_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_splitter_comp ON assets(splitter_composition_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_splitter_status ON assets(splitter_analysis_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_splitter_review ON assets(splitter_review_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_splitter_ext ON assets(splitter_extraction_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_sprite_sheet ON assets(sprite_sheet_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_sprite_status ON assets(sprite_editor_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_opt_status ON assets(optimization_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_val_status ON assets(validation_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_approved_export ON assets(is_approved_for_export);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_stage13_review ON assets(stage13_review_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_stage13_prep ON assets(stage13_prep_status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_stage13_comp_count ON assets(stage13_components_count);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_wf_stage ON assets(workflow_current_stage);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_wf_status ON assets(workflow_overall_status);")

            # Seed / sync initial Stage 13.2 workflow pipeline data
            self._migrate_stage13_2_workflow(cursor)

            logger.info("Database schema initialized and migrated successfully at %s", self.db_path)

    def upsert_asset(self, asset: Dict[str, Any]) -> Tuple[int, bool]:
        """
        Insert or update an asset record.
        Returns (asset_id, is_new).
        """
        stage_status_json = json.dumps(asset.get("stage_status", {}))
        metadata_json = json.dumps(asset.get("metadata", {}))

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM assets WHERE original_path = ?", (asset["original_path"],))
            row = cursor.fetchone()

            if row:
                asset_id = row["id"]
                cursor.execute("""
                    UPDATE assets SET
                        filename = ?,
                        collection = ?,
                        file_size = ?,
                        file_hash = ?,
                        format = ?,
                        width = ?,
                        height = ?,
                        aspect_ratio = ?,
                        color_mode = ?,
                        has_transparency = ?,
                        thumbnail_path = COALESCE(?, thumbnail_path),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    asset["filename"],
                    asset.get("collection", "other_images"),
                    asset.get("file_size", 0),
                    asset.get("file_hash", ""),
                    asset.get("format", ""),
                    asset.get("width", 0),
                    asset.get("height", 0),
                    asset.get("aspect_ratio", 0.0),
                    asset.get("color_mode", ""),
                    asset.get("has_transparency", 0),
                    asset.get("thumbnail_path"),
                    asset_id
                ))
                return asset_id, False
            else:
                cursor.execute("""
                    INSERT INTO assets (
                        original_path, filename, collection, file_size, file_hash,
                        format, width, height, aspect_ratio, color_mode,
                        has_transparency, thumbnail_path, status, stage_status,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset["original_path"],
                    asset["filename"],
                    asset.get("collection", "other_images"),
                    asset.get("file_size", 0),
                    asset.get("file_hash", ""),
                    asset.get("format", ""),
                    asset.get("width", 0),
                    asset.get("height", 0),
                    asset.get("aspect_ratio", 0.0),
                    asset.get("color_mode", ""),
                    asset.get("has_transparency", 0),
                    asset.get("thumbnail_path"),
                    asset.get("status", "pending"),
                    stage_status_json,
                    metadata_json
                ))
                return cursor.lastrowid, True

    def get_asset(self, asset_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single asset by id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assets WHERE id = ?", (asset_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_asset_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """Retrieve single asset by original_path."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM assets WHERE original_path = ?", (path,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_asset_status(self, asset_id: int, status: str) -> bool:
        """Update the review status of an asset."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE assets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, asset_id)
            )
            return cursor.rowcount > 0

    def update_asset_thumbnail(self, asset_id: int, thumbnail_path: str) -> bool:
        """Update thumbnail path for an asset."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE assets SET thumbnail_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (thumbnail_path, asset_id)
            )
            return cursor.rowcount > 0

    def _build_filter_conditions(
        self,
        collection: Optional[Any] = None,
        status: Optional[Any] = None,
        formats: Optional[Any] = None,
        has_transparency: Optional[int] = None,
        dim_category: Optional[str] = None,
        min_width: Optional[int] = None,
        max_width: Optional[int] = None,
        min_height: Optional[int] = None,
        max_height: Optional[int] = None,
        search: Optional[str] = None,
        **kwargs
    ) -> Tuple[List[str], List[Any]]:
        """Helper to build consistent WHERE clauses and parameters."""
        conditions = []
        params: List[Any] = []

        # Collection filter (string or list)
        if collection and collection != "all":
            if isinstance(collection, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(collection))
                conditions.append(f"collection IN ({placeholders})")
                params.extend(list(collection))
            else:
                conditions.append("collection = ?")
                params.append(collection)

        # Status filter (string or list)
        if status and status != "all":
            if isinstance(status, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(status))
                conditions.append(f"status IN ({placeholders})")
                params.extend(list(status))
            elif status == "unreviewed":
                conditions.append("status = 'pending'")
            else:
                conditions.append("status = ?")
                params.append(status)

        # Formats filter (e.g. ['PNG', 'JPG', 'WEBP'])
        if formats and formats != "all":
            if isinstance(formats, (list, set, tuple)):
                upper_fmts = [f.upper() for f in formats]
                placeholders = ",".join(["?"] * len(upper_fmts))
                conditions.append(f"UPPER(format) IN ({placeholders})")
                params.extend(upper_fmts)
            else:
                conditions.append("UPPER(format) = ?")
                params.append(formats.upper())

        # Transparency filter (0 = opaque, 1 = transparent)
        if has_transparency is not None:
            conditions.append("has_transparency = ?")
            params.append(1 if has_transparency else 0)

        # Dimension category preset
        if dim_category:
            if dim_category == "small":
                conditions.append("MAX(width, height) <= 512")
            elif dim_category == "medium":
                conditions.append("MAX(width, height) > 512 AND MAX(width, height) <= 1920")
            elif dim_category == "large":
                conditions.append("MAX(width, height) > 1920")

        # Custom dimension bounds
        if min_width is not None and min_width > 0:
            conditions.append("width >= ?")
            params.append(min_width)
        if max_width is not None and max_width > 0:
            conditions.append("width <= ?")
            params.append(max_width)
        if min_height is not None and min_height > 0:
            conditions.append("height >= ?")
            params.append(min_height)
        if max_height is not None and max_height > 0:
            conditions.append("height <= ?")
            params.append(max_height)

        # Search term
        if search and search.strip():
            term = search.strip()
            conditions.append(
                "(filename LIKE ? OR original_path LIKE ? OR object_name LIKE ? OR "
                "main_category LIKE ? OR suggested_filename LIKE ? OR approved_filename LIKE ?)"
            )
            params.extend([f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%"])

        # Stage 3 Classification Filters
        classification_status = kwargs.get("classification_status")
        if classification_status and classification_status != "all":
            if isinstance(classification_status, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(classification_status))
                conditions.append(f"classification_status IN ({placeholders})")
                params.extend(list(classification_status))
            else:
                conditions.append("classification_status = ?")
                params.append(classification_status)

        category = kwargs.get("category")
        if category and category != "all":
            if isinstance(category, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(category))
                conditions.append(f"main_category IN ({placeholders})")
                params.extend(list(category))
            else:
                conditions.append("main_category = ?")
                params.append(category)

        composition_type = kwargs.get("composition_type")
        if composition_type and composition_type != "all":
            conditions.append("composition_type = ?")
            params.append(composition_type)

        confidence_min = kwargs.get("confidence_min")
        if confidence_min is not None:
            conditions.append("confidence_score >= ?")
            params.append(float(confidence_min))

        confidence_max = kwargs.get("confidence_max")
        if confidence_max is not None:
            conditions.append("confidence_score <= ?")
            params.append(float(confidence_max))

        # Stage 4 Smart Renaming Filters
        naming_status = kwargs.get("naming_status")
        if naming_status and naming_status != "all":
            if isinstance(naming_status, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(naming_status))
                conditions.append(f"naming_status IN ({placeholders})")
                params.extend(list(naming_status))
            else:
                conditions.append("naming_status = ?")
                params.append(naming_status)

        rename_status = kwargs.get("rename_status")
        if rename_status and rename_status != "all":
            conditions.append("rename_status = ?")
            params.append(rename_status)

        has_conflict = kwargs.get("has_conflict")
        if has_conflict is None:
            has_conflict = kwargs.get("naming_conflict")
        if has_conflict is not None:
            conditions.append("naming_conflict = ?")
            params.append(1 if has_conflict else 0)

        # Stage 5 Background Removal Filters
        bg_eligibility = kwargs.get("bg_eligibility")
        if bg_eligibility and bg_eligibility != "all":
            if isinstance(bg_eligibility, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(bg_eligibility))
                conditions.append(f"background_eligibility IN ({placeholders})")
                params.extend(list(bg_eligibility))
            else:
                conditions.append("background_eligibility = ?")
                params.append(bg_eligibility)

        bg_processing_status = kwargs.get("bg_processing_status")
        if bg_processing_status and bg_processing_status != "all":
            if isinstance(bg_processing_status, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(bg_processing_status))
                conditions.append(f"bg_processing_status IN ({placeholders})")
                params.extend(list(bg_processing_status))
            else:
                conditions.append("bg_processing_status = ?")
                params.append(bg_processing_status)

        bg_manual_approval = kwargs.get("bg_manual_approval")
        if bg_manual_approval and bg_manual_approval != "all":
            conditions.append("bg_manual_approval = ?")
            params.append(bg_manual_approval)

        # Stage 6 Text & Label Detection Filters
        text_status = kwargs.get("text_status") or kwargs.get("text_detection_status")
        if text_status and text_status != "all":
            if text_status == "has_text":
                conditions.append("text_detected_count > 0")
            elif text_status == "no_text":
                conditions.append("text_detection_status != 'uninspected' AND text_detected_count == 0")
            elif isinstance(text_status, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(text_status))
                conditions.append(f"text_detection_status IN ({placeholders})")
                params.extend(list(text_status))
            else:
                conditions.append("text_detection_status = ?")
                params.append(text_status)

        text_review_status = kwargs.get("text_review_status")
        if text_review_status and text_review_status != "all":
            conditions.append("text_review_status = ?")
            params.append(text_review_status)

        has_watermark_text = kwargs.get("has_watermark_text")
        if has_watermark_text is not None:
            conditions.append("has_watermark_text = ?")
            params.append(1 if has_watermark_text else 0)

        # Stage 7 Watermark Detection & Review Filters
        wm_status = kwargs.get("watermark_status") or kwargs.get("watermark_detection_status")
        if wm_status and wm_status != "all":
            if wm_status == "has_candidates":
                conditions.append("watermark_candidate_count > 0")
            elif wm_status in ("no_candidates", "no_candidate"):
                conditions.append("watermark_detection_status != 'uninspected' AND watermark_candidate_count == 0")
            elif isinstance(wm_status, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(wm_status))
                conditions.append(f"watermark_detection_status IN ({placeholders})")
                params.extend(list(wm_status))
            else:
                conditions.append("watermark_detection_status = ?")
                params.append(wm_status)

        wm_review = kwargs.get("watermark_review_status")
        if wm_review and wm_review != "all":
            if isinstance(wm_review, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(wm_review))
                conditions.append(f"watermark_review_status IN ({placeholders})")
                params.extend(list(wm_review))
            else:
                conditions.append("watermark_review_status = ?")
                params.append(wm_review)

        wm_type = kwargs.get("watermark_type") or kwargs.get("candidate_type")
        if wm_type and wm_type != "all":
            conditions.append("id IN (SELECT DISTINCT asset_id FROM watermark_regions WHERE candidate_type = ?)")
            params.append(wm_type)

        wm_repl = kwargs.get("watermark_replacement_status")
        if wm_repl and wm_repl != "all":
            conditions.append("watermark_replacement_status = ?")
            params.append(wm_repl)

        # Stage 8 Collection Splitter & Asset Extraction Filters
        splitter_comp = kwargs.get("splitter_composition") or kwargs.get("splitter_composition_type")
        if splitter_comp and splitter_comp != "all":
            if isinstance(splitter_comp, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(splitter_comp))
                conditions.append(f"splitter_composition_type IN ({placeholders})")
                params.extend(list(splitter_comp))
            else:
                conditions.append("splitter_composition_type = ?")
                params.append(splitter_comp)

        splitter_review = kwargs.get("splitter_review") or kwargs.get("splitter_review_status")
        if splitter_review and splitter_review != "all":
            if splitter_review == "ready_to_split":
                conditions.append("(splitter_review_status = 'ready_to_split' OR (splitter_candidate_count > 1 AND splitter_review_status != 'rejected'))")
            elif splitter_review == "needs_review":
                conditions.append("(splitter_candidate_count > 1 AND splitter_review_status IN ('pending', 'unreviewed'))")
            elif splitter_review == "split_completed":
                conditions.append("splitter_extraction_status = 'extracted'")
            elif isinstance(splitter_review, (list, set, tuple)):
                placeholders = ",".join(["?"] * len(splitter_review))
                conditions.append(f"splitter_review_status IN ({placeholders})")
                params.extend(list(splitter_review))
            else:
                conditions.append("splitter_review_status = ?")
                params.append(splitter_review)

        splitter_ext = kwargs.get("splitter_extraction") or kwargs.get("splitter_extraction_status")
        if splitter_ext and splitter_ext != "all":
            conditions.append("splitter_extraction_status = ?")
            params.append(splitter_ext)

        splitter_status = kwargs.get("splitter_status") or kwargs.get("splitter_analysis_status")
        if splitter_status and splitter_status != "all":
            conditions.append("splitter_analysis_status = ?")
            params.append(splitter_status)

        return conditions, params

    def get_assets_count(
        self,
        collection: Optional[Any] = None,
        status: Optional[Any] = None,
        formats: Optional[Any] = None,
        has_transparency: Optional[int] = None,
        dim_category: Optional[str] = None,
        min_width: Optional[int] = None,
        max_width: Optional[int] = None,
        min_height: Optional[int] = None,
        max_height: Optional[int] = None,
        search: Optional[str] = None,
        **kwargs
    ) -> int:
        """Calculate total number of matching assets with given filters."""
        conditions, params = self._build_filter_conditions(
            collection=collection,
            status=status,
            formats=formats,
            has_transparency=has_transparency,
            dim_category=dim_category,
            min_width=min_width,
            max_width=max_width,
            min_height=min_height,
            max_height=max_height,
            search=search,
            **kwargs
        )
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT COUNT(*) as count FROM assets {where_clause}"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return row["count"] if row else 0

    get_asset_count = get_assets_count

    def get_assets(
        self,
        collection: Optional[Any] = None,
        status: Optional[Any] = None,
        formats: Optional[Any] = None,
        has_transparency: Optional[int] = None,
        dim_category: Optional[str] = None,
        min_width: Optional[int] = None,
        max_width: Optional[int] = None,
        min_height: Optional[int] = None,
        max_height: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "id",
        ascending: bool = True,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Query assets with rich filtering, pagination and sorting."""
        sort_map = {
            "id": "id ASC" if ascending else "id DESC",
            "filename_asc": "filename COLLATE NOCASE ASC",
            "filename_desc": "filename COLLATE NOCASE DESC",
            "size_desc": "file_size DESC",
            "size_asc": "file_size ASC",
            "newest": "id DESC",
            "oldest": "id ASC",
            "width_desc": "width DESC",
            "width_asc": "width ASC",
            "height_desc": "height DESC",
            "height_asc": "height ASC",
            "confidence_desc": "confidence_score DESC",
            "confidence_asc": "confidence_score ASC",
        }
        order_clause = sort_map.get(sort_by)
        if not order_clause:
            order_dir = "ASC" if ascending else "DESC"
            order_clause = f"{sort_by} {order_dir}"

        conditions, params = self._build_filter_conditions(
            collection=collection,
            status=status,
            formats=formats,
            has_transparency=has_transparency,
            dim_category=dim_category,
            min_width=min_width,
            max_width=max_width,
            min_height=min_height,
            max_height=max_height,
            search=search,
            **kwargs
        )

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM assets {where_clause} ORDER BY {order_clause} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def bulk_update_status(self, asset_ids: List[int], status: str) -> int:
        """Batch update review status for a list of asset IDs."""
        if not asset_ids:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(asset_ids))
            query = f"UPDATE assets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})"
            cursor.execute(query, [status] + list(asset_ids))
            count = cursor.rowcount

        self.log_event(
            action="Bulk Status Change",
            stage="gallery",
            message=f"Updated {count} assets to '{status}'.",
            status="success"
        )
        return count

    def export_assets_to_csv(self, asset_ids: Optional[List[int]] = None, output_file: Optional[Path] = None) -> Path:
        """Export asset inventory records into a CSV report."""
        import csv
        from app.config import REPORTS_DIR

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = REPORTS_DIR / f"asset_inventory_{timestamp}.csv"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if asset_ids:
                placeholders = ",".join(["?"] * len(asset_ids))
                cursor.execute(f"SELECT * FROM assets WHERE id IN ({placeholders}) ORDER BY id ASC", list(asset_ids))
            else:
                cursor.execute("SELECT * FROM assets ORDER BY id ASC")
            rows = cursor.fetchall()

        fieldnames = [
            "id", "filename", "collection", "format", "width", "height", "aspect_ratio",
            "file_size", "color_mode", "has_transparency", "status", "file_hash",
            "original_path", "thumbnail_path", "created_at"
        ]

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))

        self.log_event(
            action="CSV Export",
            stage="gallery",
            message=f"Exported {len(rows)} records to {output_file.name}.",
            status="info"
        )
        return output_file

    def save_classification(
        self,
        asset_id: int,
        data: Dict[str, Any],
        action: str = "ai_suggestion",
        is_manual: bool = False
    ) -> bool:
        """
        Record AI classification suggestion or manual edit to asset,
        and append to classification_history.
        """
        visual_tags_str = json.dumps(data.get("visual_tags", [])) if isinstance(data.get("visual_tags"), (list, set, tuple)) else str(data.get("visual_tags", "[]"))
        special_flags_str = json.dumps(data.get("special_flags", {})) if isinstance(data.get("special_flags"), dict) else str(data.get("special_flags", "{}"))
        status_val = "manual" if is_manual else data.get("classification_status", "suggested")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE assets SET
                    main_category = ?,
                    subcategory = ?,
                    object_name = ?,
                    visual_tags = ?,
                    composition_type = ?,
                    confidence_score = ?,
                    classification_status = ?,
                    model_name = ?,
                    model_version = ?,
                    analysis_timestamp = CURRENT_TIMESTAMP,
                    ai_explanation = ?,
                    manual_override = ?,
                    suggested_filename = ?,
                    special_flags = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                data.get("main_category", "Unclassified"),
                data.get("subcategory", ""),
                data.get("object_name", ""),
                visual_tags_str,
                data.get("composition_type", "Single Object"),
                float(data.get("confidence_score", 0.0)),
                status_val,
                data.get("model_name", "LocalVisionEngine"),
                data.get("model_version", "1.0"),
                data.get("ai_explanation", ""),
                1 if is_manual else 0,
                data.get("suggested_filename", ""),
                special_flags_str,
                asset_id
            ))

            # Record in history table
            cursor.execute("""
                INSERT INTO classification_history (
                    asset_id, main_category, subcategory, object_name,
                    visual_tags, composition_type, confidence_score,
                    model_name, suggested_filename, action, ai_explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asset_id,
                data.get("main_category", "Unclassified"),
                data.get("subcategory", ""),
                data.get("object_name", ""),
                visual_tags_str,
                data.get("composition_type", "Single Object"),
                float(data.get("confidence_score", 0.0)),
                data.get("model_name", "LocalVisionEngine"),
                data.get("suggested_filename", ""),
                action,
                data.get("ai_explanation", "")
            ))

        self.log_event(
            action="Asset Classified",
            stage="classification",
            message=f"Asset #{asset_id} -> {data.get('object_name', '')} ({data.get('main_category', '')}) [{action}]",
            status="success",
            asset_id=asset_id
        )
        return True

    def update_classification_status(self, asset_id: int, status: str) -> bool:
        """Update review status of classification (approved, rejected, pending, manual)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE assets SET classification_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, asset_id)
            )
            # Record in history
            cursor.execute("""
                INSERT INTO classification_history (
                    asset_id, main_category, subcategory, object_name,
                    composition_type, confidence_score, model_name,
                    suggested_filename, action
                )
                SELECT id, main_category, subcategory, object_name,
                       composition_type, confidence_score, model_name,
                       suggested_filename, ?
                FROM assets WHERE id = ?
            """, (status, asset_id))

        self.log_event(
            action="Classification Review",
            stage="classification",
            message=f"Asset #{asset_id} classification marked as '{status}'.",
            status="info",
            asset_id=asset_id
        )
        return True

    def get_classification_stats(self) -> Dict[str, Any]:
        """Query real database metrics for the AI Classification dashboard cards."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as total FROM assets")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as analyzed FROM assets WHERE classification_status != 'unclassified'")
            analyzed = cursor.fetchone()["analyzed"]

            pending = total - analyzed

            cursor.execute("""
                SELECT COUNT(*) as high_conf
                FROM assets
                WHERE classification_status IN ('approved', 'suggested', 'manual')
                  AND confidence_score >= 0.75
            """)
            successfully_classified = cursor.fetchone()["high_conf"]

            cursor.execute("""
                SELECT COUNT(*) as needs_review
                FROM assets
                WHERE (classification_status = 'suggested' AND confidence_score < 0.75)
                   OR composition_type IN ('Multiple Objects', 'Sprite Sheet', 'Reference Collection')
                   OR special_flags LIKE '%"possible_text": true%'
                   OR special_flags LIKE '%"possible_watermark": true%'
            """)
            needs_review = cursor.fetchone()["needs_review"]

            cursor.execute("""
                SELECT COUNT(*) as unknown_cnt
                FROM assets
                WHERE (main_category = 'Unknown' OR object_name LIKE '%Unknown%')
                  AND classification_status != 'unclassified'
            """)
            unknown_cnt = cursor.fetchone()["unknown_cnt"]

            cursor.execute("""
                SELECT main_category, COUNT(*) as count
                FROM assets
                WHERE main_category IS NOT NULL AND main_category != ''
                GROUP BY main_category
                ORDER BY count DESC
            """)
            categories = {r["main_category"]: r["count"] for r in cursor.fetchall()}

            return {
                "total_images": total,
                "analyzed_images": analyzed,
                "pending_analysis": pending,
                "successfully_classified": successfully_classified,
                "needs_manual_review": needs_review,
                "unknown_images": unknown_cnt,
                "categories": categories,
            }

    def get_classification_history(self, asset_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve audit history entries for asset classification."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM classification_history
                WHERE asset_id = ?
                ORDER BY id DESC LIMIT ?
            """, (asset_id, limit))
            return [dict(row) for row in cursor.fetchall()]



    def get_dashboard_stats(self) -> Dict[str, Any]:
        """
        Calculate and return REAL statistics directly from the database.
        Never returns fabricated numbers.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Overall counts and total bytes
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_count,
                    COALESCE(SUM(file_size), 0) as total_size
                FROM assets
            """)
            row = cursor.fetchone()
            total_images = row["total_count"] if row else 0
            total_size_bytes = row["total_size"] if row else 0

            # Collection breakdown
            cursor.execute("""
                SELECT collection, COUNT(*) as count, COALESCE(SUM(file_size), 0) as size
                FROM assets
                GROUP BY collection
            """)
            collections = {r["collection"]: {"count": r["count"], "size": r["size"]} for r in cursor.fetchall()}

            excavator_info = collections.get("excavator", {"count": 0, "size": 0})
            other_info = collections.get("other_images", {"count": 0, "size": 0})

            # Status breakdown
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM assets
                GROUP BY status
            """)
            statuses = {r["status"]: r["count"] for r in cursor.fetchall()}

            pending_count = statuses.get("pending", 0)
            processed_count = statuses.get("processed", 0)
            approved_count = statuses.get("approved", 0)
            rejected_count = statuses.get("rejected", 0)

            # Format breakdown
            cursor.execute("""
                SELECT format, COUNT(*) as count
                FROM assets
                WHERE format IS NOT NULL AND format != ''
                GROUP BY format
                ORDER BY count DESC
            """)
            format_breakdown = {r["format"].upper(): r["count"] for r in cursor.fetchall()}

            # Overall progress percentage
            # (processed + approved) / total_images
            if total_images > 0:
                completed = processed_count + approved_count
                progress_percent = round((completed / total_images) * 100, 1)
            else:
                progress_percent = 0.0

            return {
                "total_images": total_images,
                "total_storage_size": total_size_bytes,
                "total_storage_formatted": format_bytes(total_size_bytes),
                "excavator_images": excavator_info["count"],
                "excavator_size_formatted": format_bytes(excavator_info["size"]),
                "other_game_images": other_info["count"],
                "other_size_formatted": format_bytes(other_info["size"]),
                "images_processed": processed_count,
                "images_pending_review": pending_count,
                "approved_assets": approved_count,
                "rejected_assets": rejected_count,
                "processing_progress": progress_percent,
                "format_breakdown": format_breakdown,
            }

    def record_scan(self, folder_path: str, scanned_count: int, new_imported_count: int, total_bytes: int) -> int:
        """Record a completed scan in scan_history."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO scan_history (folder_path, scanned_count, new_imported_count, total_bytes)
                VALUES (?, ?, ?, ?)
            """, (folder_path, scanned_count, new_imported_count, total_bytes))
            return cursor.lastrowid

    def get_recent_scans(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve recent folder scan history."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scan_history ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def log_event(self, action: str, message: str, stage: str = "general", status: str = "info", asset_id: Optional[int] = None) -> None:
        """Insert a processing log entry."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO processing_logs (asset_id, action, stage, message, status)
                VALUES (?, ?, ?, ?, ?)
            """, (asset_id, action, stage, message, status))

    def get_recent_logs(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Retrieve latest log entries."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM processing_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_naming(
        self,
        asset_id: int,
        suggested_filename: Optional[str] = None,
        approved_filename: Optional[str] = None,
        naming_status: Optional[str] = None,
        naming_conflict: Optional[int] = None
    ) -> bool:
        """Update smart renaming fields for an asset."""
        updates = []
        params = []
        if suggested_filename is not None:
            updates.append("suggested_filename = ?")
            params.append(suggested_filename)
        if approved_filename is not None:
            updates.append("approved_filename = ?")
            params.append(approved_filename)
        if naming_status is not None:
            updates.append("naming_status = ?")
            params.append(naming_status)
        if naming_conflict is not None:
            updates.append("naming_conflict = ?")
            params.append(int(naming_conflict))

        if not updates:
            return False

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(asset_id)
        query = f"UPDATE assets SET {', '.join(updates)} WHERE id = ?"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.rowcount > 0

    def bulk_update_naming_status(self, asset_ids: List[int], status: str) -> int:
        """Batch update naming status for multiple asset IDs."""
        if not asset_ids:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(asset_ids))
            query = f"UPDATE assets SET naming_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})"
            cursor.execute(query, [status] + list(asset_ids))
            count = cursor.rowcount

        self.log_event(
            action="Bulk Naming Status",
            stage="renaming",
            message=f"Updated {count} assets to naming status '{status}'.",
            status="info"
        )
        return count

    def get_naming_stats(self) -> Dict[str, Any]:
        """Return real SQLite statistics for Smart Renaming metrics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as total FROM assets")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as names_gen FROM assets WHERE suggested_filename IS NOT NULL AND suggested_filename != ''")
            names_gen = cursor.fetchone()["names_gen"]

            cursor.execute("SELECT COUNT(*) as approved FROM assets WHERE naming_status = 'approved'")
            approved = cursor.fetchone()["approved"]

            cursor.execute("SELECT COUNT(*) as pending FROM assets WHERE naming_status != 'approved'")
            pending = cursor.fetchone()["pending"]

            cursor.execute("SELECT COUNT(*) as conflicts FROM assets WHERE naming_conflict = 1 OR naming_status = 'conflict'")
            conflicts = cursor.fetchone()["conflicts"]

            cursor.execute("SELECT COUNT(*) as manual FROM assets WHERE naming_status = 'manual' OR (approved_filename != '' AND approved_filename != suggested_filename)")
            manual = cursor.fetchone()["manual"]

            return {
                "total_images": total,
                "names_generated": names_gen,
                "approved_names": approved,
                "pending_review": pending,
                "naming_conflicts": conflicts,
                "manually_edited": manual,
            }

    def execute_rename_asset(self, asset_id: int, new_filename: str, user_approved: bool = True) -> Tuple[bool, str]:
        """
        Safely rename an individual asset on the filesystem and update SQLite.
        Never overwrites an existing file. Preserves original folder structure.
        Records operation in rename_history for rollback.
        """
        asset = self.get_asset(asset_id)
        if not asset:
            return False, f"Asset #{asset_id} not found."

        current_path_str = asset.get("current_path") or asset.get("original_path")
        current_file = Path(current_path_str)
        if not current_file.exists():
            return False, f"Source file does not exist on disk: {current_file}"

        original_filename = asset["filename"]
        clean_new_name = new_filename.strip()
        if not clean_new_name:
            return False, "Target filename cannot be empty."

        target_file = current_file.parent / clean_new_name

        # If already named this way, nothing to do
        if current_file.resolve() == target_file.resolve():
            return True, "Filename is already set to target."

        # Safety Check: Prevent overwriting any existing file
        if target_file.exists():
            err = f"Target file already exists on disk: {target_file.name}. Rename aborted to prevent overwrite."
            logger.error(err)
            return False, err

        try:
            # Perform safe filesystem rename
            current_file.rename(target_file)
            new_path_str = str(target_file.resolve())

            # Update database
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE assets SET
                        filename = ?,
                        approved_filename = ?,
                        current_path = ?,
                        rename_status = 'renamed',
                        naming_status = 'approved',
                        naming_conflict = 0,
                        last_rename_timestamp = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (clean_new_name, clean_new_name, new_path_str, asset_id))

                # Insert into rename_history
                cursor.execute("""
                    INSERT INTO rename_history (
                        asset_id, original_path, new_path, original_filename,
                        new_filename, operation_status, user_approval, rollback_status
                    ) VALUES (?, ?, ?, ?, ?, 'success', ?, 'active')
                """, (
                    asset_id, current_path_str, new_path_str,
                    original_filename, clean_new_name, 1 if user_approved else 0
                ))

            self.log_event(
                action="File Renamed",
                stage="renaming",
                message=f"Renamed: '{original_filename}' → '{clean_new_name}'",
                status="success",
                asset_id=asset_id
            )
            return True, f"Successfully renamed to {clean_new_name}"

        except Exception as e:
            err_msg = f"Filesystem rename error: {e}"
            logger.error(err_msg)
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO rename_history (
                        asset_id, original_path, new_path, original_filename,
                        new_filename, operation_status, user_approval, error_message
                    ) VALUES (?, ?, ?, ?, ?, 'failed', ?, ?)
                """, (
                    asset_id, current_path_str, str(target_file),
                    original_filename, clean_new_name, 1 if user_approved else 0, str(e)
                ))
            return False, err_msg

    def rollback_rename_asset(self, history_id: int) -> Tuple[bool, str]:
        """
        Revert a previous rename operation using its history record.
        Restores original filename, updates SQLite, and never overwrites files.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rename_history WHERE id = ?", (history_id,))
            record = cursor.fetchone()

        if not record:
            return False, f"Rename history entry #{history_id} not found."

        if record["rollback_status"] == "rolled_back":
            return False, "This rename operation has already been rolled back."

        asset_id = record["asset_id"]
        current_file = Path(record["new_path"])
        original_file = Path(record["original_path"])

        if not current_file.exists():
            return False, f"Renamed file no longer exists at: {current_file}"

        if original_file.exists() and original_file.resolve() != current_file.resolve():
            return False, f"Original file path already occupied by another file: {original_file.name}. Rollback aborted to prevent overwrite."

        try:
            current_file.rename(original_file)

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE rename_history SET
                        rollback_status = 'rolled_back'
                    WHERE id = ?
                """, (history_id,))

                cursor.execute("""
                    UPDATE assets SET
                        filename = ?,
                        current_path = ?,
                        rename_status = 'not_renamed',
                        naming_status = 'pending',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (record["original_filename"], str(original_file.resolve()), asset_id))

            self.log_event(
                action="Rename Rollback",
                stage="renaming",
                message=f"Rolled back '{record['new_filename']}' → '{record['original_filename']}'",
                status="info",
                asset_id=asset_id
            )
            return True, f"Successfully restored to {record['original_filename']}"

        except Exception as e:
            return False, f"Rollback failed: {e}"

    def get_rename_history(self, limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve recent rename history entries."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status and status != "all":
                cursor.execute("""
                    SELECT h.*, a.original_path as asset_orig_path
                    FROM rename_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    WHERE h.operation_status = ?
                    ORDER BY h.id DESC LIMIT ?
                """, (status, limit))
            else:
                cursor.execute("""
                    SELECT h.*, a.original_path as asset_orig_path
                    FROM rename_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    ORDER BY h.id DESC LIMIT ?
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # Stage 5 — Background Removal & Transparency Methods

    def update_background_eligibility(self, asset_id: int, eligibility: str) -> bool:
        """Update background eligibility recommendation for a single asset."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE assets SET
                    background_eligibility = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (eligibility, asset_id))
            return cursor.rowcount > 0

    def bulk_update_background_eligibility(self, updates: List[Tuple[int, str]]) -> int:
        """
        Batch update eligibility for multiple assets:
        updates is a list of (asset_id, eligibility_string).
        """
        if not updates:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                UPDATE assets SET
                    background_eligibility = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, [(elig, aid) for aid, elig in updates])
            count = cursor.rowcount

        self.log_event(
            action="Bulk Eligibility Evaluated",
            stage="transparency",
            message=f"Evaluated background eligibility for {len(updates)} assets.",
            status="info"
        )
        return len(updates)

    def update_transparency_result(self, asset_id: int, data: Dict[str, Any]) -> bool:
        """
        Save background removal processing results, record in transparency_history,
        and update asset metadata without modifying source files.
        """
        proc_status = data.get("bg_processing_status", "processed")
        method = data.get("background_method", "local_cv")
        proc_path = data.get("processed_path", "")
        width = int(data.get("processed_width", 0))
        height = int(data.get("processed_height", 0))
        file_size = int(data.get("processed_file_size", 0))
        alpha = int(data.get("alpha_detected", 1))
        quality = data.get("bg_quality_status", "valid" if proc_status == "processed" else "failed")
        error_msg = data.get("bg_processing_error", "")
        approval = data.get("bg_manual_approval", "unreviewed")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE assets SET
                    bg_processing_status = ?,
                    background_method = ?,
                    processed_path = ?,
                    processed_width = ?,
                    processed_height = ?,
                    processed_file_size = ?,
                    alpha_detected = ?,
                    bg_quality_status = ?,
                    bg_processing_error = ?,
                    bg_manual_approval = ?,
                    bg_processing_timestamp = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                proc_status, method, proc_path, width, height, file_size,
                alpha, quality, error_msg, approval, asset_id
            ))

            # Record in transparency_history table
            cursor.execute("""
                INSERT INTO transparency_history (
                    asset_id, method, processed_path, quality_status,
                    manual_approval, error_message
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (asset_id, method, proc_path, quality, approval, error_msg))

        self.log_event(
            action="Background Removed" if proc_status == "processed" else "Removal Failed",
            stage="transparency",
            message=f"Asset #{asset_id} -> {proc_status.upper()} ({method}) [{quality}]",
            status="success" if proc_status == "processed" else "error",
            asset_id=asset_id
        )
        return True

    def update_transparency_approval(self, asset_id: int, approval_status: str) -> bool:
        """Update manual review status of transparent asset ('approved', 'rejected', 'unreviewed')."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE assets SET
                    bg_manual_approval = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (approval_status, asset_id))

            cursor.execute("""
                INSERT INTO transparency_history (
                    asset_id, method, processed_path, manual_approval, quality_status
                )
                SELECT id, background_method, processed_path, ?, bg_quality_status
                FROM assets WHERE id = ?
            """, (approval_status, asset_id))

        self.log_event(
            action="Transparency Review",
            stage="transparency",
            message=f"Asset #{asset_id} transparent result marked as '{approval_status}'.",
            status="info",
            asset_id=asset_id
        )
        return True

    def get_transparency_stats(self) -> Dict[str, Any]:
        """
        Query real database metrics for the 6 Background Removal statistics cards.
        Never returns fabricated numbers.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as total FROM assets")
            total = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) as suitable
                FROM assets
                WHERE background_eligibility = 'Suitable for Background Removal'
            """)
            suitable = cursor.fetchone()["suitable"]

            cursor.execute("""
                SELECT COUNT(*) as review
                FROM assets
                WHERE background_eligibility LIKE '%Manual Review%'
                   OR background_eligibility = 'Possibly Suitable — Manual Review'
                   OR background_eligibility = 'Unknown — Manual Review'
            """)
            review = cursor.fetchone()["review"]

            cursor.execute("""
                SELECT COUNT(*) as transparent
                FROM assets
                WHERE background_eligibility = 'Already Transparent'
                   OR (alpha_detected = 1 AND bg_processing_status = 'processed')
            """)
            transparent = cursor.fetchone()["transparent"]

            cursor.execute("""
                SELECT COUNT(*) as processed
                FROM assets
                WHERE bg_processing_status = 'processed'
            """)
            processed = cursor.fetchone()["processed"]

            cursor.execute("""
                SELECT COUNT(*) as failed
                FROM assets
                WHERE bg_processing_status = 'failed'
            """)
            failed = cursor.fetchone()["failed"]

            return {
                "total_images": total,
                "suitable_images": suitable,
                "needs_review": review,
                "already_transparent": transparent,
                "successfully_processed": processed,
                "processing_failed": failed,
            }

    def get_transparency_history(self, asset_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve transparency processing history entries."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if asset_id is not None:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM transparency_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    WHERE h.asset_id = ?
                    ORDER BY h.id DESC LIMIT ?
                """, (asset_id, limit))
            else:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM transparency_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    ORDER BY h.id DESC LIMIT ?
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # Stage 6 — Text & Label Detection Methods

    def save_text_detection_result(
        self,
        asset_id: int,
        regions: List[Dict[str, Any]],
        model_name: str = "OpenCV_MSER",
        model_version: str = "1.0",
        status: str = "success",
        error_message: str = ""
    ) -> int:
        """
        Save detected text regions for an asset, update asset text metadata,
        and log entry in text_detection_history without modifying original files.
        """
        detected_cnt = len(regions)
        det_status = "failed" if status == "failed" else ("has_text" if detected_cnt > 0 else "no_text")
        has_wm = 1 if any(r.get("is_watermark_candidate") or r.get("category") == "Watermark-like text" for r in regions) else 0

        # Review status: flagged if watermark candidate, clean if 0 text, otherwise pending review
        review_status = "flagged" if has_wm else ("clean" if detected_cnt == 0 else "pending")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Update asset table
            cursor.execute("""
                UPDATE assets SET
                    text_detected_count = ?,
                    text_detection_status = ?,
                    text_review_status = ?,
                    has_watermark_text = ?,
                    text_detection_timestamp = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (detected_cnt, det_status, review_status, has_wm, asset_id))

            # 2. Clear old automated regions for this asset (preserve manual if flagged)
            cursor.execute("DELETE FROM text_regions WHERE asset_id = ?", (asset_id,))

            # 3. Insert new text regions
            for r in regions:
                cursor.execute("""
                    INSERT INTO text_regions (
                        asset_id, box_x, box_y, box_w, box_h, recognized_text,
                        confidence, category, review_status, is_watermark_candidate,
                        manual_correction, model_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset_id,
                    int(r.get("box_x", 0)),
                    int(r.get("box_y", 0)),
                    int(r.get("box_w", 0)),
                    int(r.get("box_h", 0)),
                    r.get("recognized_text", ""),
                    float(r.get("confidence", 0.8)),
                    r.get("category", "Unknown writing"),
                    r.get("review_status", "unreviewed"),
                    1 if r.get("is_watermark_candidate") else 0,
                    r.get("manual_correction", ""),
                    model_name
                ))

            # 4. Record history entry
            cursor.execute("""
                INSERT INTO text_detection_history (
                    asset_id, detected_count, model_name, model_version, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (asset_id, detected_cnt, model_name, model_version, status, error_message))

        self.log_event(
            action="Text Detection",
            stage="text_detection",
            message=f"Asset #{asset_id} -> {detected_cnt} text region(s) detected via {model_name}.",
            status="success" if status == "success" else "error",
            asset_id=asset_id
        )
        return detected_cnt

    def get_text_regions(self, asset_id: int) -> List[Dict[str, Any]]:
        """Retrieve all bounding box regions detected for a given asset."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM text_regions
                WHERE asset_id = ?
                ORDER BY id ASC
            """, (asset_id,))
            return [dict(row) for row in cursor.fetchall()]

    def update_text_region(self, region_id: int, updates: Dict[str, Any]) -> bool:
        """Update fields (category, review_status, recognized_text, etc.) of a specific text region."""
        valid_fields = [
            "recognized_text", "category", "review_status",
            "is_watermark_candidate", "manual_correction",
            "box_x", "box_y", "box_w", "box_h"
        ]
        set_clauses = []
        params = []
        for f in valid_fields:
            if f in updates:
                set_clauses.append(f"{f} = ?")
                params.append(updates[f])

        if not set_clauses:
            return False

        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params.append(region_id)
        query = f"UPDATE text_regions SET {', '.join(set_clauses)} WHERE id = ?"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            success = cursor.rowcount > 0

            # If watermark candidate or category was changed, sync asset watermark flag
            if success and ("is_watermark_candidate" in updates or "category" in updates):
                cursor.execute("SELECT asset_id FROM text_regions WHERE id = ?", (region_id,))
                row = cursor.fetchone()
                if row:
                    aid = row["asset_id"]
                    cursor.execute("""
                        SELECT COUNT(*) as wm_cnt FROM text_regions
                        WHERE asset_id = ? AND (is_watermark_candidate = 1 OR category = 'Watermark-like text')
                    """, (aid,))
                    wm_cnt = cursor.fetchone()["wm_cnt"]
                    cursor.execute("""
                        UPDATE assets SET
                            has_watermark_text = ?,
                            text_review_status = CASE WHEN ? > 0 THEN 'flagged' ELSE text_review_status END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (1 if wm_cnt > 0 else 0, wm_cnt, aid))

            return success

    def add_text_region(self, asset_id: int, region_data: Dict[str, Any]) -> int:
        """Add a manually defined text region to an asset."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO text_regions (
                    asset_id, box_x, box_y, box_w, box_h, recognized_text,
                    confidence, category, review_status, is_watermark_candidate,
                    manual_correction, model_name
                ) VALUES (?, ?, ?, ?, ?, ?, 1.0, ?, 'manual', ?, ?, 'Manual_Annotation')
            """, (
                asset_id,
                int(region_data.get("box_x", 0)),
                int(region_data.get("box_y", 0)),
                int(region_data.get("box_w", 50)),
                int(region_data.get("box_h", 20)),
                region_data.get("recognized_text", ""),
                region_data.get("category", "Vehicle labels"),
                1 if region_data.get("is_watermark_candidate") else 0,
                region_data.get("manual_correction", "")
            ))
            new_id = cursor.lastrowid

            # Sync asset detection count
            cursor.execute("""
                UPDATE assets SET
                    text_detected_count = text_detected_count + 1,
                    text_detection_status = 'has_text',
                    text_review_status = 'reviewed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (asset_id,))

        self.log_event(
            action="Manual Region Added",
            stage="text_detection",
            message=f"Added manual text region to Asset #{asset_id}.",
            status="info",
            asset_id=asset_id
        )
        return new_id

    def delete_text_region(self, region_id: int) -> bool:
        """Delete a text region (reject false positive detection)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id FROM text_regions WHERE id = ?", (region_id,))
            row = cursor.fetchone()
            if not row:
                return False
            aid = row["asset_id"]

            cursor.execute("DELETE FROM text_regions WHERE id = ?", (region_id,))
            # Sync asset count
            cursor.execute("SELECT COUNT(*) as rem FROM text_regions WHERE asset_id = ?", (aid,))
            rem = cursor.fetchone()["rem"]
            cursor.execute("""
                UPDATE assets SET
                    text_detected_count = ?,
                    text_detection_status = CASE WHEN ? = 0 THEN 'no_text' ELSE 'has_text' END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (rem, rem, aid))
            return True

    def update_asset_text_review(self, asset_id: int, review_status: str) -> bool:
        """Update review status of text detection for an asset ('clean', 'flagged', 'reviewed')."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE assets SET
                    text_review_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (review_status, asset_id))
            return cursor.rowcount > 0

    def get_text_detection_stats(self) -> Dict[str, Any]:
        """
        Query real database metrics for the 6 Text Detection statistics cards.
        Never returns fabricated numbers.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as total FROM assets")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as analyzed FROM assets WHERE text_detection_status != 'uninspected'")
            analyzed = cursor.fetchone()["analyzed"]

            cursor.execute("SELECT COUNT(*) as has_txt FROM assets WHERE text_detected_count > 0")
            has_txt = cursor.fetchone()["has_txt"]

            cursor.execute("""
                SELECT COUNT(*) as no_txt
                FROM assets
                WHERE text_detection_status != 'uninspected' AND text_detected_count == 0
            """)
            no_txt = cursor.fetchone()["no_txt"]

            cursor.execute("""
                SELECT COUNT(*) as review
                FROM assets
                WHERE (text_review_status IN ('pending', 'flagged') AND text_detected_count > 0)
                   OR has_watermark_text = 1
            """)
            review = cursor.fetchone()["review"]

            cursor.execute("SELECT COUNT(*) as failed FROM assets WHERE text_detection_status = 'failed'")
            failed = cursor.fetchone()["failed"]

            return {
                "total_images": total,
                "analyzed_images": analyzed,
                "images_with_text": has_txt,
                "images_without_text": no_txt,
                "needs_review": review,
                "detection_failed": failed,
            }

    def get_text_detection_history(self, asset_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve audit history entries for text detection runs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if asset_id is not None:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM text_detection_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    WHERE h.asset_id = ?
                    ORDER BY h.id DESC LIMIT ?
                """, (asset_id, limit))
            else:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM text_detection_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    ORDER BY h.id DESC LIMIT ?
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # STAGE 7: WATERMARK DETECTION & REVIEW SYSTEM
    # =========================================================================

    def save_watermark_detection_result(
        self,
        asset_id: int,
        regions: List[Dict[str, Any]],
        engine_version: str = "1.0",
        detection_method: str = "multi_signal_cv",
        status: str = "success",
        error_message: str = "",
    ) -> None:
        """
        Persist watermark candidate regions and detection audit history for an asset.
        Preserves existing user-confirmed or user-rejected regions.
        Synchronizes asset counters.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Record audit history
            cursor.execute("""
                INSERT INTO watermark_detection_history
                    (asset_id, engine_version, detection_method, candidate_count, processing_status, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (asset_id, engine_version, detection_method, len(regions), status, error_message))

            # Remove pending/unreviewed regions from previous runs, but preserve user reviews
            cursor.execute("""
                DELETE FROM watermark_regions
                WHERE asset_id = ? AND review_status IN ('pending', 'unreviewed')
            """, (asset_id,))

            # Insert new detected candidate regions
            for r in regions:
                cursor.execute("""
                    INSERT INTO watermark_regions
                        (asset_id, x, y, width, height, candidate_type, candidate_text,
                         candidate_score, detection_method, detection_reason, review_status, reviewer_notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset_id,
                    r.get("x", r.get("box_x", 0)),
                    r.get("y", r.get("box_y", 0)),
                    r.get("width", r.get("box_w", 0)),
                    r.get("height", r.get("box_h", 0)),
                    r.get("candidate_type", "Uncertain Mark"),
                    r.get("candidate_text", ""),
                    float(r.get("candidate_score", 0.5)),
                    r.get("detection_method", detection_method),
                    r.get("detection_reason", "Detected via visual signature analysis"),
                    r.get("review_status", "pending"),
                    r.get("reviewer_notes", ""),
                ))

            # Recalculate total candidate count for asset
            cursor.execute("SELECT COUNT(*) as total FROM watermark_regions WHERE asset_id = ?", (asset_id,))
            total_cand = cursor.fetchone()["total"]

            # Check if any confirmed watermark exists
            cursor.execute("""
                SELECT COUNT(*) as confirmed FROM watermark_regions
                WHERE asset_id = ? AND review_status = 'confirmed'
            """, (asset_id,))
            has_confirmed = cursor.fetchone()["confirmed"] > 0

            det_status = "has_candidates" if total_cand > 0 else "no_candidates"
            rev_status = "needs_replacement" if has_confirmed else ("pending" if total_cand > 0 else "clean")

            cursor.execute("""
                UPDATE assets SET
                    watermark_candidate_count = ?,
                    watermark_detection_status = ?,
                    watermark_review_status = CASE
                        WHEN watermark_review_status IN ('confirmed', 'needs_replacement') THEN watermark_review_status
                        ELSE ?
                    END,
                    watermark_detection_timestamp = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (total_cand, det_status, rev_status, asset_id))

    def get_watermark_regions(
        self,
        asset_id: Optional[int] = None,
        candidate_type: Optional[str] = None,
        review_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve watermark candidate regions matching criteria."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params = []

            if asset_id is not None:
                conditions.append("asset_id = ?")
                params.append(asset_id)
            if candidate_type and candidate_type != "all":
                conditions.append("candidate_type = ?")
                params.append(candidate_type)
            if review_status and review_status != "all":
                conditions.append("review_status = ?")
                params.append(review_status)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"SELECT * FROM watermark_regions {where} ORDER BY id ASC", params)
            return [dict(r) for r in cursor.fetchall()]




    def get_watermark_region(self, region_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single watermark candidate region by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watermark_regions WHERE id = ?", (region_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_watermark_region(self, region_id: int, updates: Dict[str, Any]) -> bool:
        """Update properties of a watermark candidate region."""
        if not updates:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id FROM watermark_regions WHERE id = ?", (region_id,))
            row = cursor.fetchone()
            if not row:
                return False
            aid = row["asset_id"]

            fields = []
            params = []
            for k, v in updates.items():
                if k in (
                    "x", "y", "width", "height", "candidate_type", "candidate_text",
                    "candidate_score", "detection_method", "detection_reason",
                    "review_status", "reviewer_notes"
                ):
                    fields.append(f"{k} = ?")
                    params.append(v)

            if not fields:
                return False

            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(region_id)
            query = f"UPDATE watermark_regions SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, params)

            # Sync asset-level review status if review_status changed
            if "review_status" in updates:
                new_st = updates["review_status"]
                if new_st == "confirmed":
                    cursor.execute("""
                        UPDATE assets SET
                            watermark_review_status = 'needs_replacement',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (aid,))
                else:
                    # Check if any confirmed remains
                    cursor.execute("SELECT COUNT(*) as c FROM watermark_regions WHERE asset_id = ? AND review_status = 'confirmed'", (aid,))
                    if cursor.fetchone()["c"] == 0:
                        cursor.execute("SELECT COUNT(*) as p FROM watermark_regions WHERE asset_id = ? AND review_status = 'pending'", (aid,))
                        has_pending = cursor.fetchone()["p"] > 0
                        cursor.execute("""
                            UPDATE assets SET
                                watermark_review_status = CASE WHEN ? THEN 'pending' ELSE 'reviewed' END,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (1 if has_pending else 0, aid))

            return True

    def add_watermark_region(self, asset_id: int, region: Dict[str, Any]) -> int:
        """Manually insert a user-defined watermark candidate region."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO watermark_regions
                    (asset_id, x, y, width, height, candidate_type, candidate_text,
                     candidate_score, detection_method, detection_reason, review_status, reviewer_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asset_id,
                int(region.get("x", 0)),
                int(region.get("y", 0)),
                int(region.get("width", 50)),
                int(region.get("height", 50)),
                region.get("candidate_type", "Uncertain Mark"),
                region.get("candidate_text", ""),
                float(region.get("candidate_score", 1.0)),
                region.get("detection_method", "manual"),
                region.get("detection_reason", "Manually flagged by user"),
                region.get("review_status", "pending"),
                region.get("reviewer_notes", region.get("notes", "")),
            ))
            new_id = cursor.lastrowid

            # Sync asset counters
            cursor.execute("SELECT COUNT(*) as c FROM watermark_regions WHERE asset_id = ?", (asset_id,))
            cnt = cursor.fetchone()["c"]
            cursor.execute("""
                UPDATE assets SET
                    watermark_candidate_count = ?,
                    watermark_detection_status = 'has_candidates',
                    watermark_review_status = 'pending',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (cnt, asset_id))

            return new_id

    def delete_watermark_region(self, region_id: int) -> bool:
        """Delete a watermark candidate region."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id FROM watermark_regions WHERE id = ?", (region_id,))
            row = cursor.fetchone()
            if not row:
                return False
            aid = row["asset_id"]

            cursor.execute("DELETE FROM watermark_regions WHERE id = ?", (region_id,))

            # Sync asset counters
            cursor.execute("SELECT COUNT(*) as c FROM watermark_regions WHERE asset_id = ?", (aid,))
            rem = cursor.fetchone()["c"]
            cursor.execute("""
                UPDATE assets SET
                    watermark_candidate_count = ?,
                    watermark_detection_status = CASE WHEN ? = 0 THEN 'no_candidates' ELSE 'has_candidates' END,
                    watermark_review_status = CASE WHEN ? = 0 THEN 'clean' ELSE watermark_review_status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (rem, rem, rem, aid))
            return True

    def update_asset_watermark_review(
        self, asset_id: int, review_status: str, replacement_status: Optional[str] = None
    ) -> bool:
        """Update top-level asset watermark review and clean replacement status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if replacement_status is not None:
                cursor.execute("""
                    UPDATE assets SET
                        watermark_review_status = ?,
                        watermark_replacement_status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (review_status, replacement_status, asset_id))
            else:
                cursor.execute("""
                    UPDATE assets SET
                        watermark_review_status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (review_status, asset_id))
            return cursor.rowcount > 0

    def get_watermark_detection_stats(self) -> Dict[str, Any]:
        """
        Query real database metrics for the 6 Watermark Review statistics cards.
        Never returns fabricated numbers.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Total Images
            cursor.execute("SELECT COUNT(*) as total FROM assets")
            total = cursor.fetchone()["total"]

            # 2. Analyzed Images
            cursor.execute("SELECT COUNT(*) as analyzed FROM assets WHERE watermark_detection_status != 'uninspected'")
            analyzed = cursor.fetchone()["analyzed"]

            # 3. Watermark Candidates
            cursor.execute("SELECT COUNT(*) as cands FROM assets WHERE watermark_candidate_count > 0")
            cands = cursor.fetchone()["cands"]

            # 4. Confirmed Watermarks
            cursor.execute("""
                SELECT COUNT(DISTINCT asset_id) as conf
                FROM watermark_regions
                WHERE review_status = 'confirmed'
            """)
            conf = cursor.fetchone()["conf"]

            # 5. Rejected Candidates
            cursor.execute("SELECT COUNT(*) as rej FROM watermark_regions WHERE review_status = 'rejected'")
            rej = cursor.fetchone()["rej"]

            # 6. Needs Review
            cursor.execute("""
                SELECT COUNT(*) as needs_rev
                FROM assets
                WHERE watermark_candidate_count > 0
                  AND watermark_review_status IN ('pending', 'unreviewed', 'uncertain')
            """)
            needs_rev = cursor.fetchone()["needs_rev"]

            return {
                "total_images": total,
                "analyzed_images": analyzed,
                "watermark_candidates": cands,
                "confirmed_watermarks": conf,
                "rejected_candidates": rej,
                "needs_review": needs_rev,
            }

    def get_watermark_detection_history(
        self, asset_id: Optional[int] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Retrieve audit history entries for watermark detection runs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if asset_id is not None:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM watermark_detection_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    WHERE h.asset_id = ?
                    ORDER BY h.id DESC LIMIT ?
                """, (asset_id, limit))
            else:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM watermark_detection_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    ORDER BY h.id DESC LIMIT ?
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]


    # =========================================================================
    # STAGE 8: COLLECTION SPLITTER & ASSET EXTRACTION SYSTEM
    # =========================================================================

    def save_collection_analysis_result(
        self,
        asset_id: int,
        composition_type: str,
        regions: List[Dict[str, Any]],
        detection_method: str = "multi_feature_cv",
        explanation: str = "",
        status: str = "success",
    ) -> None:
        """
        Persist collection composition classification, candidate object regions,
        and analysis audit history for an asset.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Record analysis history
            cursor.execute("""
                INSERT INTO collection_analysis_history
                    (asset_id, composition_type, candidate_count, detection_method, explanation, analysis_status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (asset_id, composition_type, len(regions), detection_method, explanation, status))

            # Delete unapproved/pending regions from prior automated runs, preserve approved/manual ones
            cursor.execute("""
                DELETE FROM collection_regions
                WHERE asset_id = ? AND review_status = 'pending' AND source_method != 'manual'
            """, (asset_id,))

            # Insert newly detected regions
            for r in regions:
                cursor.execute("""
                    INSERT INTO collection_regions
                        (asset_id, x, y, width, height, region_type, confidence_score, source_method, review_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset_id,
                    int(r.get("x", 0)),
                    int(r.get("y", 0)),
                    int(r.get("width", 50)),
                    int(r.get("height", 50)),
                    r.get("region_type", "object"),
                    float(r.get("confidence_score", 0.5)),
                    r.get("source_method", detection_method),
                    r.get("review_status", "pending"),
                ))

            # Count total candidate regions now attached to asset
            cursor.execute("SELECT COUNT(*) as total FROM collection_regions WHERE asset_id = ?", (asset_id,))
            total_cands = cursor.fetchone()["total"]

            # Set review status: if multi-object or sprite sheet, mark needs_review / ready_to_split
            if composition_type in ("Multiple Object Collection", "Overlapping Object Collection", "Sprite Sheet", "Animation Frame Grid"):
                rev_st = "ready_to_split" if total_cands > 1 else "needs_review"
            elif composition_type == "Single Object":
                rev_st = "single_object"
            elif composition_type == "Background Scene":
                rev_st = "scene_preserved"
            else:
                rev_st = "pending"

            cursor.execute("""
                UPDATE assets SET
                    splitter_composition_type = ?,
                    splitter_candidate_count = ?,
                    splitter_analysis_status = ?,
                    splitter_review_status = CASE
                        WHEN splitter_review_status IN ('rejected', 'approved', 'ready_to_split') THEN splitter_review_status
                        ELSE ?
                    END,
                    splitter_analysis_timestamp = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (composition_type, total_cands, status, rev_st, asset_id))

    def get_collection_regions(
        self, asset_id: Optional[int] = None, review_status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve collection candidate regions matching criteria."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params = []

            if asset_id is not None:
                conditions.append("asset_id = ?")
                params.append(asset_id)
            if review_status and review_status != "all":
                conditions.append("review_status = ?")
                params.append(review_status)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"SELECT * FROM collection_regions {where} ORDER BY id ASC", params)
            return [dict(r) for r in cursor.fetchall()]




    def get_collection_region(self, region_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single collection candidate region by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM collection_regions WHERE id = ?", (region_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_collection_region(
        self,
        asset_id: int,
        region: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> int:
        """Manually insert a user-drawn or custom candidate region."""
        reg = dict(region or {})
        reg.update(kwargs)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO collection_regions
                    (asset_id, x, y, width, height, region_type, confidence_score, source_method, review_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asset_id,
                int(reg.get("x", 0)),
                int(reg.get("y", 0)),
                int(reg.get("width", 50)),
                int(reg.get("height", 50)),
                reg.get("region_type", "manual"),
                float(reg.get("confidence_score", 1.0)),
                reg.get("source_method", "manual"),
                reg.get("review_status", "approved"),
            ))
            new_id = cursor.lastrowid

            # Sync asset candidate counter
            cursor.execute("SELECT COUNT(*) as c FROM collection_regions WHERE asset_id = ?", (asset_id,))
            cnt = cursor.fetchone()["c"]
            cursor.execute("""
                UPDATE assets SET
                    splitter_candidate_count = ?,
                    splitter_review_status = CASE WHEN ? > 1 THEN 'ready_to_split' ELSE splitter_review_status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (cnt, cnt, asset_id))

            return new_id

    def update_collection_region(self, region_id: int, updates: Dict[str, Any]) -> bool:
        """Update coordinates, review status, or type of a collection region."""
        if not updates:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            fields = []
            params = []
            for k, v in updates.items():
                if k in ("x", "y", "width", "height", "region_type", "confidence_score", "review_status"):
                    fields.append(f"{k} = ?")
                    params.append(v)

            if not fields:
                return False

            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(region_id)
            query = f"UPDATE collection_regions SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, params)
            return cursor.rowcount > 0

    def delete_collection_region(self, region_id: int) -> bool:
        """Delete an individual collection region."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id FROM collection_regions WHERE id = ?", (region_id,))
            row = cursor.fetchone()
            if not row:
                return False
            aid = row["asset_id"]

            cursor.execute("DELETE FROM collection_regions WHERE id = ?", (region_id,))

            # Resync counter on asset
            cursor.execute("SELECT COUNT(*) as c FROM collection_regions WHERE asset_id = ?", (aid,))
            rem = cursor.fetchone()["c"]
            cursor.execute("""
                UPDATE assets SET
                    splitter_candidate_count = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (rem, aid))
            return True

    def delete_all_collection_regions(self, asset_id: int) -> bool:
        """Clear all candidate regions for an asset."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM collection_regions WHERE asset_id = ?", (asset_id,))
            cursor.execute("""
                UPDATE assets SET
                    splitter_candidate_count = 0,
                    splitter_review_status = 'pending',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (asset_id,))
            return True

    def update_asset_splitter_status(
        self,
        asset_id: int,
        composition_type: Optional[str] = None,
        review_status: Optional[str] = None,
        extraction_status: Optional[str] = None,
    ) -> bool:
        """Update top-level asset composition, review, and extraction state."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            fields = []
            params = []

            if composition_type is not None:
                fields.append("splitter_composition_type = ?")
                params.append(composition_type)
            if review_status is not None:
                fields.append("splitter_review_status = ?")
                params.append(review_status)
            if extraction_status is not None:
                fields.append("splitter_extraction_status = ?")
                params.append(extraction_status)

            if not fields:
                return False

            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(asset_id)
            query = f"UPDATE assets SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, params)
            return cursor.rowcount > 0

    def record_extracted_asset(
        self,
        source_asset_id: int,
        source_region_id: Optional[int],
        output_path: str,
        output_filename: str,
        width: int,
        height: int,
        frame_index: int = 0,
        padding: int = 0,
        export_status: str = "exported",
    ) -> int:
        """
        Record an extracted child asset in the database, retaining full provenance
        and link to its original parent source image and crop region.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO extracted_assets
                    (source_asset_id, source_region_id, output_path, output_filename,
                     width, height, frame_index, padding, export_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_asset_id, source_region_id, output_path, output_filename,
                width, height, frame_index, padding, export_status
            ))
            ext_id = cursor.lastrowid

            # Sync parent asset extraction counters
            cursor.execute("SELECT COUNT(*) as c FROM extracted_assets WHERE source_asset_id = ?", (source_asset_id,))
            ext_cnt = cursor.fetchone()["c"]

            cursor.execute("""
                UPDATE assets SET
                    extracted_assets_count = ?,
                    splitter_extraction_status = 'extracted',
                    splitter_review_status = 'split_completed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (ext_cnt, source_asset_id))

            return ext_id

    def get_extracted_assets(self, source_asset_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve extracted assets metadata."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if source_asset_id is not None:
                cursor.execute("""
                    SELECT e.*, a.filename as source_filename, a.original_path as source_path
                    FROM extracted_assets e
                    LEFT JOIN assets a ON e.source_asset_id = a.id
                    WHERE e.source_asset_id = ?
                    ORDER BY e.frame_index ASC, e.id ASC
                """, (source_asset_id,))
            else:
                cursor.execute("""
                    SELECT e.*, a.filename as source_filename, a.original_path as source_path
                    FROM extracted_assets e
                    LEFT JOIN assets a ON e.source_asset_id = a.id
                    ORDER BY e.id DESC
                """)
            return [dict(r) for r in cursor.fetchall()]




    def get_collection_splitter_stats(self) -> Dict[str, Any]:
        """
        Query real database metrics for the 6 Collection Splitter statistics cards.
        Never returns fabricated numbers.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Total Images
            cursor.execute("SELECT COUNT(*) as total FROM assets")
            total = cursor.fetchone()["total"]

            # 2. Analyzed Images
            cursor.execute("SELECT COUNT(*) as analyzed FROM assets WHERE splitter_analysis_status != 'uninspected'")
            analyzed = cursor.fetchone()["analyzed"]

            # 3. Collection Candidates (multi-object collections)
            cursor.execute("""
                SELECT COUNT(*) as col_cands FROM assets
                WHERE splitter_composition_type IN ('Multiple Object Collection', 'Overlapping Object Collection')
                   OR splitter_candidate_count > 1
            """)
            col_cands = cursor.fetchone()["col_cands"]

            # 4. Sprite Sheets
            cursor.execute("""
                SELECT COUNT(*) as sprites FROM assets
                WHERE splitter_composition_type IN ('Sprite Sheet', 'Animation Frame Grid')
            """)
            sprites = cursor.fetchone()["sprites"]

            # 5. Ready to Split
            cursor.execute("""
                SELECT COUNT(*) as ready FROM assets
                WHERE splitter_review_status = 'ready_to_split'
                   OR (splitter_candidate_count > 1 AND splitter_review_status NOT IN ('rejected', 'split_completed'))
            """)
            ready = cursor.fetchone()["ready"]

            # 6. Extracted Assets (total extracted items generated)
            cursor.execute("SELECT COUNT(*) as ext FROM extracted_assets")
            ext = cursor.fetchone()["ext"]

            return {
                "total_images": total,
                "analyzed_images": analyzed,
                "collection_candidates": col_cands,
                "sprite_sheets": sprites,
                "ready_to_split": ready,
                "extracted_assets": ext,
            }

    def get_collection_analysis_history(
        self, asset_id: Optional[int] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Retrieve audit history entries for collection composition analysis runs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if asset_id is not None:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM collection_analysis_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    WHERE h.asset_id = ?
                    ORDER BY h.id DESC LIMIT ?
                """, (asset_id, limit))
            else:
                cursor.execute("""
                    SELECT h.*, a.filename, a.original_path
                    FROM collection_analysis_history h
                    LEFT JOIN assets a ON h.asset_id = a.id
                    ORDER BY h.id DESC LIMIT ?
                """, (limit,))
            return [dict(r) for r in cursor.fetchall()]





    def add_collection_analysis_history(
        self,
        asset_id: int,
        composition_type: str,
        candidate_count: int,
        detection_method: str = "manual",
        explanation: str = "",
        analysis_status: str = "completed",
    ) -> int:
        """Insert a single audit log entry into collection_analysis_history."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO collection_analysis_history
                    (asset_id, composition_type, candidate_count, detection_method, explanation, analysis_status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (asset_id, composition_type, candidate_count, detection_method, explanation, analysis_status))
            return cursor.lastrowid

    def add_extracted_asset(self, *args, **kwargs) -> int:
        """Alias for record_extracted_asset."""
        return self.record_extracted_asset(*args, **kwargs)

    def get_all_extracted_assets(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Retrieve all extracted asset records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT e.*, a.filename as source_filename, a.original_path as source_original_path
                FROM extracted_assets e
                LEFT JOIN assets a ON e.source_asset_id = a.id
                ORDER BY e.id DESC LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]



    def get_extracted_assets_for_source(self, source_asset_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Alias to retrieve extracted assets for a source asset."""
        return self.get_extracted_assets(source_asset_id)



    # =========================================================================
    # STAGE 9: SPRITE SHEET EDITOR & ANIMATION FRAME MANAGEMENT METHODS
    # =========================================================================

    def create_or_update_sprite_sheet_definition(
        self,
        asset_id: Optional[int] = None,
        name: str = "",
        image_path: str = "",
        sheet_type: str = "uniform_grid",
        source_image_path: str = "",
        **kwargs,
    ) -> int:
        """Create or update a sprite sheet configuration."""
        if not image_path and source_image_path:
            image_path = source_image_path
        with self.get_connection() as conn:
            cursor = conn.cursor()
            existing_id = None
            if asset_id:
                cursor.execute("SELECT id FROM sprite_sheet_definitions WHERE asset_id = ?", (asset_id,))
                row = cursor.fetchone()
                if row:
                    existing_id = row["id"]
            if not existing_id and image_path:
                cursor.execute("SELECT id FROM sprite_sheet_definitions WHERE image_path = ?", (image_path,))
                row = cursor.fetchone()
                if row:
                    existing_id = row["id"]

            cols = kwargs.get("columns", kwargs.get("cols", 1))
            rows = kwargs.get("rows", 1)
            img_w = kwargs.get("sheet_width", kwargs.get("image_width", 0))
            img_h = kwargs.get("sheet_height", kwargs.get("image_height", 0))
            frame_w = kwargs.get("frame_width", 0)
            frame_h = kwargs.get("frame_height", 0)
            h_spacing = kwargs.get("spacing_x", kwargs.get("h_spacing", 0))
            v_spacing = kwargs.get("spacing_y", kwargs.get("v_spacing", 0))
            m_left = kwargs.get("margin_left", 0)
            m_right = kwargs.get("margin_right", 0)
            m_top = kwargs.get("margin_top", 0)
            m_bottom = kwargs.get("margin_bottom", 0)
            default_fps = kwargs.get("default_fps", 10)
            loop_default = kwargs.get("loop_default", 1)
            status = kwargs.get("status", "draft")

            if existing_id:
                cursor.execute("""
                    UPDATE sprite_sheet_definitions SET
                        name = ?,
                        sheet_type = ?,
                        image_path = ?,
                        image_width = ?,
                        image_height = ?,
                        cols = ?,
                        rows = ?,
                        frame_width = ?,
                        frame_height = ?,
                        h_spacing = ?,
                        v_spacing = ?,
                        margin_left = ?,
                        margin_right = ?,
                        margin_top = ?,
                        margin_bottom = ?,
                        default_fps = ?,
                        loop_default = ?,
                        status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    name, sheet_type, image_path, img_w, img_h,
                    cols, rows, frame_w, frame_h, h_spacing, v_spacing,
                    m_left, m_right, m_top, m_bottom, default_fps, loop_default, status, existing_id
                ))
                sheet_id = existing_id
            else:
                cursor.execute("""
                    INSERT INTO sprite_sheet_definitions (
                        asset_id, name, sheet_type, image_path, image_width, image_height,
                        cols, rows, frame_width, frame_height, h_spacing, v_spacing,
                        margin_left, margin_right, margin_top, margin_bottom,
                        default_fps, loop_default, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset_id, name, sheet_type, image_path, img_w, img_h,
                    cols, rows, frame_w, frame_h, h_spacing, v_spacing,
                    m_left, m_right, m_top, m_bottom, default_fps, loop_default, status
                ))
                sheet_id = cursor.lastrowid

            if asset_id:
                cursor.execute("""
                    UPDATE assets SET
                        sprite_sheet_id = ?,
                        sprite_editor_status = 'configured',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (sheet_id, asset_id))

            return sheet_id

    def get_sprite_sheet_definition(self, sheet_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a sprite sheet definition by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.*, a.filename as asset_filename, a.collection as asset_collection
                FROM sprite_sheet_definitions s
                LEFT JOIN assets a ON s.asset_id = a.id
                WHERE s.id = ?
            """, (sheet_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            res["columns"] = res.get("cols", 1)
            res["source_image_path"] = res.get("image_path", "")
            res["source_filename"] = Path(res["image_path"]).name if res.get("image_path") else ""
            res["sheet_width"] = res.get("image_width", 0)
            res["sheet_height"] = res.get("image_height", 0)
            return res

    def get_sprite_sheet_by_asset(self, asset_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve sprite sheet definition associated with an asset ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.*, a.filename as asset_filename, a.collection as asset_collection
                FROM sprite_sheet_definitions s
                LEFT JOIN assets a ON s.asset_id = a.id
                WHERE s.asset_id = ?
            """, (asset_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_sprite_sheets(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve all defined sprite sheets."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.*,
                       a.filename as asset_filename,
                       a.collection as asset_collection,
                       (SELECT COUNT(*) FROM sprite_frames f WHERE f.sprite_sheet_id = s.id) as frame_count,
                       (SELECT COUNT(*) FROM sprite_animations an WHERE an.sprite_sheet_id = s.id) as animation_count
                FROM sprite_sheet_definitions s
                LEFT JOIN assets a ON s.asset_id = a.id
                ORDER BY s.id DESC LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def update_sprite_sheet_definition(self, sheet_id: int, updates: Dict[str, Any]) -> bool:
        """Update fields of an existing sprite sheet definition."""
        allowed = {
            "name", "sheet_type", "image_path", "image_width", "image_height",
            "cols", "rows", "frame_width", "frame_height", "h_spacing", "v_spacing",
            "margin_left", "margin_right", "margin_top", "margin_bottom"
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in filtered.keys())
        params = list(filtered.values()) + [sheet_id]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE sprite_sheet_definitions SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", params)
            return cursor.rowcount > 0

    def delete_sprite_sheet_definition(self, sheet_id: int) -> bool:
        """Delete a sprite sheet definition and its associated frames and animations."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Clear reference on assets
            cursor.execute("UPDATE assets SET sprite_sheet_id = NULL, sprite_frames_count = 0 WHERE sprite_sheet_id = ?", (sheet_id,))
            cursor.execute("DELETE FROM sprite_sheet_definitions WHERE id = ?", (sheet_id,))
            return cursor.rowcount > 0

    def add_sprite_frame(self, sheet_id: int, frame_data: Dict[str, Any]) -> int:
        """Add a single frame to a sprite sheet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sprite_frames (
                    sprite_sheet_id, frame_index, x, y, width, height,
                    pivot_x, pivot_y, frame_duration_ms, frame_name, transparency_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sheet_id,
                int(frame_data.get("frame_index", 0)),
                int(frame_data.get("x", 0)),
                int(frame_data.get("y", 0)),
                int(frame_data.get("width", 50)),
                int(frame_data.get("height", 50)),
                float(frame_data.get("pivot_x", 0.5)),
                float(frame_data.get("pivot_y", 0.5)),
                int(frame_data.get("frame_duration_ms", 100)),
                str(frame_data.get("frame_name", "")),
                str(frame_data.get("transparency_status", "opaque")),
            ))
            frame_id = cursor.lastrowid

            # Sync counter
            cursor.execute("SELECT COUNT(*) as c FROM sprite_frames WHERE sprite_sheet_id = ?", (sheet_id,))
            cnt = cursor.fetchone()["c"]
            cursor.execute("UPDATE assets SET sprite_frames_count = ? WHERE sprite_sheet_id = ?", (cnt, sheet_id))
            return frame_id

    def save_sprite_frames(self, sheet_id: int, frames: List[Dict[str, Any]], clear_existing: bool = True) -> int:
        """Save a batch of frames for a sprite sheet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if clear_existing:
                cursor.execute("DELETE FROM sprite_frames WHERE sprite_sheet_id = ?", (sheet_id,))

            inserted = 0
            for idx, f in enumerate(frames):
                f_idx = f.get("frame_index", idx)
                cursor.execute("""
                    INSERT INTO sprite_frames (
                        sprite_sheet_id, frame_index, x, y, width, height,
                        pivot_x, pivot_y, frame_duration_ms, frame_name, transparency_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sheet_id,
                    int(f_idx),
                    int(f.get("x", 0)),
                    int(f.get("y", 0)),
                    int(f.get("width", 50)),
                    int(f.get("height", 50)),
                    float(f.get("pivot_x", 0.5)),
                    float(f.get("pivot_y", 0.5)),
                    int(f.get("frame_duration_ms", 100)),
                    str(f.get("frame_name", f"frame_{f_idx:03d}")),
                    str(f.get("transparency_status", "opaque")),
                ))
                inserted += 1

            cursor.execute("UPDATE assets SET sprite_frames_count = ? WHERE sprite_sheet_id = ?", (inserted, sheet_id))
            return inserted

    def get_sprite_frames(self, sheet_id: int) -> List[Dict[str, Any]]:
        """Retrieve all frames for a sprite sheet in frame_index order."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sprite_frames
                WHERE sprite_sheet_id = ?
                ORDER BY frame_index ASC, id ASC
            """, (sheet_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_sprite_frame(self, frame_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve an individual frame by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sprite_frames WHERE id = ?", (frame_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_sprite_frame(self, frame_id: int, updates: Dict[str, Any]) -> bool:
        """Update properties of a sprite frame."""
        allowed = {
            "frame_index", "x", "y", "width", "height",
            "pivot_x", "pivot_y", "frame_duration_ms",
            "frame_name", "transparency_status"
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in filtered.keys())
        params = list(filtered.values()) + [frame_id]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE sprite_frames SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", params)
            return cursor.rowcount > 0

    def delete_sprite_frame(self, frame_id: int) -> bool:
        """Delete an individual frame definition."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sprite_sheet_id FROM sprite_frames WHERE id = ?", (frame_id,))
            row = cursor.fetchone()
            sheet_id = row["sprite_sheet_id"] if row else None

            cursor.execute("DELETE FROM sprite_frames WHERE id = ?", (frame_id,))
            res = cursor.rowcount > 0

            if sheet_id:
                cursor.execute("SELECT COUNT(*) as c FROM sprite_frames WHERE sprite_sheet_id = ?", (sheet_id,))
                cnt = cursor.fetchone()["c"]
                cursor.execute("UPDATE assets SET sprite_frames_count = ? WHERE sprite_sheet_id = ?", (cnt, sheet_id))

            return res

    def clear_sprite_frames(self, sheet_id: int) -> bool:
        """Remove all frames for a given sprite sheet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sprite_frames WHERE sprite_sheet_id = ?", (sheet_id,))
            cursor.execute("UPDATE assets SET sprite_frames_count = 0 WHERE sprite_sheet_id = ?", (sheet_id,))
            return True

    def reorder_sprite_frames(self, sheet_id: int, frame_id_order: List[int]) -> bool:
        """Update frame_index for all frames based on a specified ID sequence."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for idx, fid in enumerate(frame_id_order):
                cursor.execute(
                    "UPDATE sprite_frames SET frame_index = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND sprite_sheet_id = ?",
                    (idx, fid, sheet_id)
                )
            return True

    def create_sprite_animation(
        self,
        sheet_id: int,
        name: str = "",
        animation_name: str = "",
        animation_type: str = "custom",
        fps: int = 10,
        loop_enabled: bool = True,
        **kwargs,
    ) -> int:
        """Create an animation sequence container for a sprite sheet."""
        if not animation_name and name:
            animation_name = name
        if "loop" in kwargs:
            loop_enabled = bool(kwargs["loop"])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sprite_animations (sprite_sheet_id, animation_name, fps, loop_enabled)
                VALUES (?, ?, ?, ?)
            """, (sheet_id, animation_name, fps, 1 if loop_enabled else 0))
            return cursor.lastrowid

    def get_sprite_animations(self, sheet_id: int) -> List[Dict[str, Any]]:
        """Retrieve all animation definitions for a sprite sheet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT an.*,
                       (SELECT COUNT(*) FROM animation_frame_sequences sq WHERE sq.animation_id = an.id) as frame_count
                FROM sprite_animations an
                WHERE an.sprite_sheet_id = ?
                ORDER BY an.id ASC
            """, (sheet_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_sprite_animation(self, anim_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a specific animation definition by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sprite_animations WHERE id = ?", (anim_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_sprite_animation(self, anim_id: int, updates: Dict[str, Any]) -> bool:
        """Update animation metadata (name, fps, loop_enabled)."""
        allowed = {"animation_name", "fps", "loop_enabled"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return False

        if "loop_enabled" in filtered:
            filtered["loop_enabled"] = 1 if filtered["loop_enabled"] else 0

        set_clause = ", ".join(f"{k} = ?" for k in filtered.keys())
        params = list(filtered.values()) + [anim_id]

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE sprite_animations SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", params)
            return cursor.rowcount > 0

    def delete_sprite_animation(self, anim_id: int) -> bool:
        """Delete an animation definition and its frame sequences."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM animation_frame_sequences WHERE animation_id = ?", (anim_id,))
            cursor.execute("DELETE FROM sprite_animations WHERE id = ?", (anim_id,))
            return cursor.rowcount > 0

    def set_animation_frame_sequence(
        self, animation_id: int, frame_ids: List[int], durations: Optional[List[int]] = None
    ) -> bool:
        """Set or replace the ordered list of frames that compose an animation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM animation_frame_sequences WHERE animation_id = ?", (animation_id,))
            for idx, fid in enumerate(frame_ids):
                dur = durations[idx] if durations and idx < len(durations) else 0
                cursor.execute("""
                    INSERT INTO animation_frame_sequences (animation_id, frame_id, sequence_order, duration_override_ms)
                    VALUES (?, ?, ?, ?)
                """, (animation_id, fid, idx, dur))
            return True

    def get_animation_frame_sequence(self, animation_id: int) -> List[Dict[str, Any]]:
        """Retrieve the sequence of frames (with frame coordinates and overrides) for an animation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT sq.sequence_order, sq.duration_override_ms,
                       f.id as frame_id, f.frame_index, f.x, f.y, f.width, f.height,
                       f.pivot_x, f.pivot_y, f.frame_duration_ms, f.frame_name, f.transparency_status,
                       s.image_path
                FROM animation_frame_sequences sq
                JOIN sprite_frames f ON sq.frame_id = f.id
                JOIN sprite_sheet_definitions s ON f.sprite_sheet_id = s.id
                WHERE sq.animation_id = ?
                ORDER BY sq.sequence_order ASC
            """, (animation_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_sprite_sheet_stats(self) -> Dict[str, Any]:
        """Query real SQLite database metrics for Stage 9 statistics cards."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Total Sprite Sheets
            cursor.execute("SELECT COUNT(*) as c FROM sprite_sheet_definitions")
            total_sheets = cursor.fetchone()["c"]

            # 2. Total Defined Frames
            cursor.execute("SELECT COUNT(*) as c FROM sprite_frames")
            total_frames = cursor.fetchone()["c"]

            # 3. Total Animations
            cursor.execute("SELECT COUNT(*) as c FROM sprite_animations")
            total_anims = cursor.fetchone()["c"]

            # 4. Uniform Grid Sheets
            cursor.execute("SELECT COUNT(*) as c FROM sprite_sheet_definitions WHERE sheet_type = 'uniform_grid'")
            uniform_sheets = cursor.fetchone()["c"]

            # 5. Manual Sheets
            cursor.execute("SELECT COUNT(*) as c FROM sprite_sheet_definitions WHERE sheet_type = 'manual'")
            manual_sheets = cursor.fetchone()["c"]

            # 6. Candidate Sheets in Catalog (from Stage 8)
            cursor.execute("""
                SELECT COUNT(*) as c FROM assets
                WHERE splitter_composition_type IN ('Sprite Sheet', 'Animation Frame Grid')
            """)
            catalog_candidates = cursor.fetchone()["c"]

            return {
                "total_sheets": total_sheets,
                "total_frames": total_frames,
                "total_animations": total_anims,
                "uniform_sheets": uniform_sheets,
                "manual_sheets": manual_sheets,
                "catalog_candidates": catalog_candidates,
            }

    # -------------------------------------------------------------------------
    # Stage 10 — Asset Optimization, Validation & Flutter Export Methods
    # -------------------------------------------------------------------------

    def record_optimization_history(
        self,
        source_asset_id: Optional[int],
        input_path: str,
        output_path: str,
        input_size: int,
        output_size: int,
        input_format: str,
        output_format: str,
        input_width: int,
        input_height: int,
        output_width: int,
        output_height: int,
        compression_settings: Optional[Dict[str, Any]] = None,
        transparency_status: str = "opaque",
        optimization_status: str = "success",
        error_message: str = "",
        export_job_id: Optional[int] = None,
    ) -> int:
        """Record an optimization run for an asset copy."""
        settings_json = json.dumps(compression_settings or {})
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO optimization_history (
                    source_asset_id, input_path, output_path,
                    input_size, output_size, input_format, output_format,
                    input_width, input_height, output_width, output_height,
                    compression_settings, transparency_status,
                    optimization_status, error_message, export_job_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_asset_id, input_path, output_path,
                input_size, output_size, input_format, output_format,
                input_width, input_height, output_width, output_height,
                settings_json, transparency_status,
                optimization_status, error_message, export_job_id
            ))
            opt_id = cursor.lastrowid

            if source_asset_id and optimization_status == "success":
                cursor.execute("""
                    UPDATE assets SET
                        optimization_status = 'optimized',
                        optimized_size = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (output_size, source_asset_id))

            return opt_id

    def get_optimization_history(self, asset_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent optimization records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if asset_id is not None:
                cursor.execute("""
                    SELECT o.*, a.filename as asset_filename
                    FROM optimization_history o
                    LEFT JOIN assets a ON o.source_asset_id = a.id
                    WHERE o.source_asset_id = ?
                    ORDER BY o.created_at DESC
                    LIMIT ?
                """, (asset_id, limit))
            else:
                cursor.execute("""
                    SELECT o.*, a.filename as asset_filename
                    FROM optimization_history o
                    LEFT JOIN assets a ON o.source_asset_id = a.id
                    ORDER BY o.created_at DESC
                    LIMIT ?
                """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def get_optimization_stats(self) -> Dict[str, Any]:
        """Return cumulative optimization performance statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total_runs,
                    COUNT(DISTINCT source_asset_id) as total_unique_assets,
                    COALESCE(SUM(input_size), 0) as total_input_bytes,
                    COALESCE(SUM(output_size), 0) as total_output_bytes,
                    SUM(CASE WHEN output_format = 'PNG' THEN 1 ELSE 0 END) as png_count,
                    SUM(CASE WHEN output_format = 'WEBP' THEN 1 ELSE 0 END) as webp_count,
                    SUM(CASE WHEN output_format = 'JPEG' OR output_format = 'JPG' THEN 1 ELSE 0 END) as jpeg_count
                FROM optimization_history
                WHERE optimization_status = 'success'
            """)
            row = dict(cursor.fetchone())
            saved_bytes = max(0, row["total_input_bytes"] - row["total_output_bytes"])
            reduction_pct = (saved_bytes / max(1, row["total_input_bytes"])) * 100.0 if row["total_input_bytes"] > 0 else 0.0
            row["saved_bytes"] = saved_bytes
            row["reduction_pct"] = round(reduction_pct, 1)
            return row

    def create_flutter_export_job(
        self,
        job_name: str,
        target_flutter_dir: str,
        total_assets: int = 0,
        exported_assets: int = 0,
        total_input_bytes: int = 0,
        total_output_bytes: int = 0,
        pubspec_updated: int = 0,
        pubspec_backup_path: str = "",
        export_status: str = "staged",
        error_message: str = "",
    ) -> int:
        """Create a new flutter export job record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO flutter_export_jobs (
                    job_name, target_flutter_dir, total_assets, exported_assets,
                    total_input_bytes, total_output_bytes, pubspec_updated,
                    pubspec_backup_path, export_status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_name, target_flutter_dir, total_assets, exported_assets,
                total_input_bytes, total_output_bytes, pubspec_updated,
                pubspec_backup_path, export_status, error_message
            ))
            return cursor.lastrowid

    def update_flutter_export_job(self, job_id: int, **kwargs) -> bool:
        """Update fields on a flutter export job."""
        if not kwargs:
            return False
        with self.get_connection() as conn:
            cursor = conn.cursor()
            set_clauses = []
            params = []
            for k, v in kwargs.items():
                set_clauses.append(f"{k} = ?")
                params.append(v)
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            params.append(job_id)
            cursor.execute(f"UPDATE flutter_export_jobs SET {', '.join(set_clauses)} WHERE id = ?", params)
            return cursor.rowcount > 0

    def get_flutter_export_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a specific export job by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM flutter_export_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_flutter_export_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve all export jobs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM flutter_export_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def create_texture_atlas_definition(
        self,
        atlas_name: str,
        category: str = "general",
        output_image_path: str = "",
        output_metadata_path: str = "",
        atlas_width: int = 1024,
        atlas_height: int = 1024,
        padding: int = 2,
        spacing: int = 2,
        power_of_two: int = 0,
        allow_rotation: int = 0,
        packing_algorithm: str = "maxrects",
        packing_efficiency: float = 0.0,
        sprite_count: int = 0,
        status: str = "ready",
    ) -> int:
        """Create or update a texture atlas definition record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO texture_atlas_definitions (
                    atlas_name, category, output_image_path, output_metadata_path,
                    atlas_width, atlas_height, padding, spacing, power_of_two,
                    allow_rotation, packing_algorithm, packing_efficiency,
                    sprite_count, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                atlas_name, category, output_image_path, output_metadata_path,
                atlas_width, atlas_height, padding, spacing, power_of_two,
                allow_rotation, packing_algorithm, packing_efficiency,
                sprite_count, status
            ))
            return cursor.lastrowid

    def get_texture_atlas_definition(self, atlas_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve texture atlas definition by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM texture_atlas_definitions WHERE id = ?", (atlas_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_texture_atlases(self) -> List[Dict[str, Any]]:
        """Retrieve all texture atlas definitions."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM texture_atlas_definitions ORDER BY created_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def add_texture_atlas_entries(self, atlas_id: int, entries: List[Dict[str, Any]]) -> int:
        """Add packed sprite entries for a texture atlas."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM texture_atlas_entries WHERE atlas_id = ?", (atlas_id,))
            inserted = 0
            for e in entries:
                cursor.execute("""
                    INSERT INTO texture_atlas_entries (
                        atlas_id, source_asset_id, source_path, sprite_name,
                        x, y, width, height, is_rotated,
                        original_width, original_height, trim_offset_x, trim_offset_y
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    atlas_id, e.get("source_asset_id"), e.get("source_path", ""), e.get("sprite_name", ""),
                    e.get("x", 0), e.get("y", 0), e.get("width", 0), e.get("height", 0),
                    1 if e.get("is_rotated") else 0,
                    e.get("original_width", e.get("width", 0)),
                    e.get("original_height", e.get("height", 0)),
                    e.get("trim_offset_x", 0), e.get("trim_offset_y", 0)
                ))
                inserted += 1
            cursor.execute("UPDATE texture_atlas_definitions SET sprite_count = ? WHERE id = ?", (inserted, atlas_id))
            return inserted

    def get_texture_atlas_entries(self, atlas_id: int) -> List[Dict[str, Any]]:
        """Retrieve all sprite entries for an atlas."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM texture_atlas_entries WHERE atlas_id = ? ORDER BY sprite_name ASC", (atlas_id,))
            return [dict(r) for r in cursor.fetchall()]

    def save_asset_validation_results(self, asset_id: Optional[int], asset_path: str, results_list: List[Dict[str, Any]]):
        """Save quality validation results for an asset."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if asset_id:
                cursor.execute("DELETE FROM asset_validation_results WHERE source_asset_id = ?", (asset_id,))
            else:
                cursor.execute("DELETE FROM asset_validation_results WHERE asset_path = ?", (asset_path,))

            overall_status = "passed"
            for r in results_list:
                status = r.get("status", "passed").lower()
                if status == "failed":
                    overall_status = "failed"
                elif status in ("warning", "needs_review") and overall_status != "failed":
                    overall_status = status

                cursor.execute("""
                    INSERT INTO asset_validation_results (
                        source_asset_id, asset_path, validation_type,
                        status, message, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    asset_id, asset_path, r.get("validation_type", "general"),
                    status, r.get("message", ""), json.dumps(r.get("details", {}))
                ))

            if asset_id:
                cursor.execute("UPDATE assets SET validation_status = ? WHERE id = ?", (overall_status, asset_id))

    def get_asset_validation_results(self, asset_id: Optional[int] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve validation records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM asset_validation_results WHERE 1=1"
            params = []
            if asset_id is not None:
                query += " AND source_asset_id = ?"
                params.append(asset_id)
            if status is not None:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY checked_at DESC"
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_validation_summary_stats(self) -> Dict[str, Any]:
        """Return counts of passed, warning, failed, and needs_review validation items."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN validation_status = 'passed' THEN 1 ELSE 0 END) as passed_count,
                    SUM(CASE WHEN validation_status = 'warning' THEN 1 ELSE 0 END) as warning_count,
                    SUM(CASE WHEN validation_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN validation_status = 'needs_review' THEN 1 ELSE 0 END) as needs_review_count,
                    SUM(CASE WHEN validation_status = 'unvalidated' THEN 1 ELSE 0 END) as unvalidated_count,
                    COUNT(*) as total_assets
                FROM assets
            """)
            row = dict(cursor.fetchone())
            return row

    def set_asset_export_approval(self, asset_id: int, is_approved: bool) -> bool:
        """Mark an asset as approved (or unapproved) for Flutter export."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE assets SET is_approved_for_export = ? WHERE id = ?", (1 if is_approved else 0, asset_id))
            return cursor.rowcount > 0

    def get_approved_assets_for_optimization(self, category: Optional[str] = None, collection: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query assets eligible for optimization and Flutter export."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM assets WHERE (is_approved_for_export = 1 OR status = 'approved' OR bg_manual_approval = 'approved')"
            params = []
            if category and category != "All Categories":
                query += " AND main_category = ?"
                params.append(category)
            if collection and collection != "All Collections":
                query += " AND collection = ?"
                params.append(collection)
            query += " ORDER BY filename ASC"
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_stage10_dashboard_stats(self) -> Dict[str, Any]:
        """Aggregate 6 real-time metrics for Stage 10 dashboard cards."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as c FROM assets WHERE (is_approved_for_export = 1 OR status = 'approved' OR bg_manual_approval = 'approved')")
            approved_count = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) as c FROM assets WHERE optimization_status = 'optimized'")
            optimized_count = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) as c FROM texture_atlas_definitions")
            atlas_count = cursor.fetchone()["c"]

            cursor.execute("SELECT COALESCE(SUM(input_size - output_size), 0) as s FROM optimization_history WHERE optimization_status = 'success'")
            bytes_saved = max(0, cursor.fetchone()["s"])

            cursor.execute("SELECT COUNT(*) as c FROM assets WHERE validation_status = 'passed'")
            validated_clean = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) as c FROM flutter_export_jobs WHERE export_status = 'completed'")
            exported_jobs = cursor.fetchone()["c"]

            return {
                "approved_count": approved_count,
                "optimized_count": optimized_count,
                "atlas_count": atlas_count,
                "bytes_saved": bytes_saved,
                "validated_clean": validated_clean,
                "exported_jobs": exported_jobs,
            }

    # =========================================================================
    # STAGE 11: GAME INTEGRATION & RUNTIME VERIFICATION METHODS
    # =========================================================================

    def register_flutter_project(
        self,
        project_name: str,
        project_path: str,
        pubspec_path: str = "",
        is_valid_flutter: bool = True,
        has_lib: bool = True,
        has_assets: bool = True,
        flutter_version: str = "",
        flame_version: str = "",
        flame_detected: bool = False,
        declared_asset_dirs: Optional[List[str]] = None,
        status: str = "connected",
    ) -> int:
        """Register or update a connected Flutter project record."""
        import json
        dirs_json = json.dumps(declared_asset_dirs or [])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO flutter_project_connections (
                    project_name, project_path, pubspec_path, is_valid_flutter,
                    has_lib, has_assets, flutter_version, flame_version,
                    flame_detected, declared_asset_dirs, status, last_inspected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(project_path) DO UPDATE SET
                    project_name = excluded.project_name,
                    pubspec_path = excluded.pubspec_path,
                    is_valid_flutter = excluded.is_valid_flutter,
                    has_lib = excluded.has_lib,
                    has_assets = excluded.has_assets,
                    flutter_version = excluded.flutter_version,
                    flame_version = excluded.flame_version,
                    flame_detected = excluded.flame_detected,
                    declared_asset_dirs = excluded.declared_asset_dirs,
                    status = excluded.status,
                    last_inspected_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                project_name, project_path, pubspec_path, 1 if is_valid_flutter else 0,
                1 if has_lib else 0, 1 if has_assets else 0, flutter_version, flame_version,
                1 if flame_detected else 0, dirs_json, status
            ))
            cursor.execute("SELECT id FROM flutter_project_connections WHERE project_path = ?", (project_path,))
            row = cursor.fetchone()
            return row["id"] if row else cursor.lastrowid

    def get_flutter_project(self, project_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Retrieve Flutter project by ID or the most recently inspected one."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if project_id is not None:
                cursor.execute("SELECT * FROM flutter_project_connections WHERE id = ?", (project_id,))
            else:
                cursor.execute("SELECT * FROM flutter_project_connections ORDER BY last_inspected_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_active_flutter_project(self) -> Optional[Dict[str, Any]]:
        """Retrieve the primary connected Flutter project."""
        return self.get_flutter_project()

    def list_flutter_projects(self) -> List[Dict[str, Any]]:
        """List all connected Flutter projects."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM flutter_project_connections ORDER BY last_inspected_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def update_flutter_project(self, project_id: int, **fields) -> bool:
        """Update fields of a registered Flutter project."""
        if not fields:
            return False
        with self.get_connection() as conn:
            cursor = conn.cursor()
            set_clauses = [f"{k} = ?" for k in fields.keys()]
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE flutter_project_connections SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(query, list(fields.values()) + [project_id])
            return cursor.rowcount > 0

    def create_runtime_validation_session(
        self,
        session_name: str,
        target_asset_dir: str,
        project_id: Optional[int] = None,
        total_assets: int = 0,
    ) -> int:
        """Start a new runtime asset validation session."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO runtime_validation_sessions (
                    project_id, session_name, target_asset_dir, total_assets, overall_status
                ) VALUES (?, ?, ?, ?, 'in_progress')
            """, (project_id, session_name, target_asset_dir, total_assets))
            return cursor.lastrowid

    def add_runtime_validation_results(
        self,
        session_id: int,
        results: List[Dict[str, Any]],
    ) -> int:
        """Add validation result records and update session summary counts transactionally."""
        import json
        if not results:
            return 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            passed = 0
            warning = 0
            failed = 0
            not_tested = 0

            for r in results:
                status = (r.get("status") or "NOT TESTED").upper()
                if status == "PASS":
                    passed += 1
                elif status == "WARNING":
                    warning += 1
                elif status == "FAIL":
                    failed += 1
                else:
                    not_tested += 1

                details = r.get("details_json")
                if isinstance(details, (dict, list)):
                    details_str = json.dumps(details)
                else:
                    details_str = str(details or "{}")

                cursor.execute("""
                    INSERT INTO runtime_validation_results (
                        session_id, asset_id, asset_path, asset_type, check_category, status, message, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id,
                    r.get("asset_id"),
                    str(r.get("asset_path", "")),
                    r.get("asset_type", "image"),
                    r.get("check_category", "general"),
                    status,
                    r.get("message", ""),
                    details_str
                ))

            # Update session summary counts
            total = len(results)
            overall = "passed" if failed == 0 and warning == 0 and passed > 0 else ("failed" if failed > 0 else "warning")
            cursor.execute("""
                UPDATE runtime_validation_sessions SET
                    total_assets = ?,
                    passed_count = ?,
                    warning_count = ?,
                    failed_count = ?,
                    not_tested_count = ?,
                    overall_status = ?
                WHERE id = ?
            """, (total, passed, warning, failed, not_tested, overall, session_id))
            return total

    def get_runtime_validation_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Fetch validation session metadata by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runtime_validation_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_latest_runtime_validation_session(self, project_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Fetch the most recent validation session."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if project_id is not None:
                cursor.execute("SELECT * FROM runtime_validation_sessions WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,))
            else:
                cursor.execute("SELECT * FROM runtime_validation_sessions ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_runtime_validation_results(
        self,
        session_id: int,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch validation entries for a session with optional filtering."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM runtime_validation_results WHERE session_id = ?"
            params = [session_id]
            if category and category != "All":
                query += " AND check_category = ?"
                params.append(category)
            if status and status != "All":
                query += " AND status = ?"
                params.append(status.upper())
            query += " ORDER BY id ASC"
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def record_flame_compatibility(
        self,
        metadata_path: str,
        flame_version_detected: str,
        format_schema: str,
        is_compatible: bool,
        compatibility_status: str,
        issues: Optional[List[Dict[str, Any]]] = None,
        conversion_suggested: bool = False,
        converted_metadata_json: str = "",
        project_id: Optional[int] = None,
    ) -> int:
        """Record Flame JSON metadata compatibility check."""
        import json
        issues_str = json.dumps(issues or [])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO flame_compatibility_results (
                    project_id, metadata_path, flame_version_detected, format_schema,
                    is_compatible, compatibility_status, issues_json, conversion_suggested,
                    converted_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id, metadata_path, flame_version_detected, format_schema,
                1 if is_compatible else 0, compatibility_status, issues_str,
                1 if conversion_suggested else 0, converted_metadata_json
            ))
            return cursor.lastrowid

    def get_flame_compatibility_results(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve recorded Flame compatibility reports."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if project_id is not None:
                cursor.execute("SELECT * FROM flame_compatibility_results WHERE project_id = ? ORDER BY id DESC", (project_id,))
            else:
                cursor.execute("SELECT * FROM flame_compatibility_results ORDER BY id DESC")
            return [dict(r) for r in cursor.fetchall()]

    def assign_game_component(
        self,
        component_group: str,
        asset_id: int,
        source_file: str,
        exported_file: str = "",
        width: int = 0,
        height: int = 0,
        pivot_x: float = 0.5,
        pivot_y: float = 0.5,
        transparency_status: str = "transparent",
        validation_status: str = "approved",
        associated_animation: str = "",
        notes: str = "",
    ) -> int:
        """Assign an approved asset to a construction excavator component group."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Upsert by asset_id
            cursor.execute("""
                INSERT INTO game_component_assignments (
                    component_group, asset_id, source_file, exported_file,
                    width, height, pivot_x, pivot_y, transparency_status,
                    validation_status, associated_animation, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                component_group, asset_id, source_file, exported_file,
                width, height, pivot_x, pivot_y, transparency_status,
                validation_status, associated_animation, notes
            ))
            assignment_id = cursor.lastrowid

            # Update asset record
            cursor.execute("""
                UPDATE assets SET
                    game_component_group = ?,
                    game_component_status = 'assigned'
                WHERE id = ?
            """, (component_group, asset_id))

            return assignment_id

    def get_game_component_assignments(self, component_group: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query assigned excavator component assets."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if component_group and component_group != "All":
                cursor.execute("SELECT * FROM game_component_assignments WHERE component_group = ? ORDER BY id ASC", (component_group,))
            else:
                cursor.execute("SELECT * FROM game_component_assignments ORDER BY component_group ASC, id ASC")
            return [dict(r) for r in cursor.fetchall()]

    def remove_game_component_assignment(self, assignment_id: int) -> bool:
        """Remove a component assignment and clear asset flag."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id FROM game_component_assignments WHERE id = ?", (assignment_id,))
            row = cursor.fetchone()
            if row:
                asset_id = row["asset_id"]
                cursor.execute("DELETE FROM game_component_assignments WHERE id = ?", (assignment_id,))
                cursor.execute("UPDATE assets SET game_component_group = '', game_component_status = 'unassigned' WHERE id = ?", (asset_id,))
                return True
            return False

    def get_component_group_summary(self) -> Dict[str, int]:
        """Aggregate assignment counts per excavator component group."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT component_group, COUNT(*) as c FROM game_component_assignments GROUP BY component_group")
            return {row["component_group"]: row["c"] for row in cursor.fetchall()}

    def record_integration_test_result(
        self,
        test_type: str,
        status: str,
        tests_executed: int = 0,
        tests_passed: int = 0,
        tests_failed: int = 0,
        raw_output: str = "",
        test_package_path: str = "",
        flutter_executable: str = "",
        flame_compatible: bool = True,
        patch_preview_content: str = "",
        is_patch_approved: bool = False,
        project_id: Optional[int] = None,
    ) -> int:
        """Record integration test or fixture generation execution result."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO integration_test_results (
                    project_id, test_type, test_package_path, flutter_executable,
                    flame_compatible, tests_executed, tests_passed, tests_failed,
                    status, raw_output, patch_preview_content, is_patch_approved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id, test_type, test_package_path, flutter_executable,
                1 if flame_compatible else 0, tests_executed, tests_passed, tests_failed,
                status, raw_output, patch_preview_content, 1 if is_patch_approved else 0
            ))
            return cursor.lastrowid

    def get_latest_integration_test_result(self, project_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Retrieve latest integration test outcome."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if project_id is not None:
                cursor.execute("SELECT * FROM integration_test_results WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,))
            else:
                cursor.execute("SELECT * FROM integration_test_results ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_integration_test_results(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List past integration test executions."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if project_id is not None:
                cursor.execute("SELECT * FROM integration_test_results WHERE project_id = ? ORDER BY id DESC", (project_id,))
            else:
                cursor.execute("SELECT * FROM integration_test_results ORDER BY id DESC")
            return [dict(r) for r in cursor.fetchall()]

    def save_asset_performance_report(
        self,
        report_data: Dict[str, Any],
        project_id: Optional[int] = None,
    ) -> int:
        """Save asset budget & performance telemetry report."""
        import json
        anims_json = json.dumps(report_data.get("animation_ram_breakdown", {}))
        warn_json = json.dumps(report_data.get("warnings", []))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO asset_performance_reports (
                    project_id, total_asset_count, total_disk_bytes, png_bytes,
                    webp_bytes, atlas_count, sprite_count, atlas_avg_efficiency,
                    max_texture_width, max_texture_height, duplicate_count,
                    missing_ref_count, estimated_decoded_ram_bytes,
                    animation_ram_breakdown_json, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                report_data.get("total_asset_count", 0),
                report_data.get("total_disk_bytes", 0),
                report_data.get("png_bytes", 0),
                report_data.get("webp_bytes", 0),
                report_data.get("atlas_count", 0),
                report_data.get("sprite_count", 0),
                report_data.get("atlas_avg_efficiency", 0.0),
                report_data.get("max_texture_width", 0),
                report_data.get("max_texture_height", 0),
                report_data.get("duplicate_count", 0),
                report_data.get("missing_ref_count", 0),
                report_data.get("estimated_decoded_ram_bytes", 0),
                anims_json,
                warn_json
            ))
            return cursor.lastrowid

    def get_latest_asset_performance_report(self, project_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Retrieve most recent performance report."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if project_id is not None:
                cursor.execute("SELECT * FROM asset_performance_reports WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,))
            else:
                cursor.execute("SELECT * FROM asset_performance_reports ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_stage11_dashboard_stats(self, project_id: Optional[int] = None) -> Dict[str, Any]:
        """Aggregate metrics for Stage 11 Game Integration dashboard cards."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Active project info
            proj = self.get_flutter_project(project_id)
            project_name = proj.get("project_name", "No Project") if proj else "No Project"
            flame_version = proj.get("flame_version", "Not Detected") if proj else "Not Detected"

            # Validation stats from latest session
            sess = self.get_latest_runtime_validation_session(project_id)
            if sess:
                total_val = sess.get("total_assets", 0)
                passed = sess.get("passed_count", 0)
                warning = sess.get("warning_count", 0)
                failed = sess.get("failed_count", 0)
                not_tested = sess.get("not_tested_count", 0)
            else:
                total_val = passed = warning = failed = not_tested = 0

            # Component assignment count
            cursor.execute("SELECT COUNT(*) as c FROM game_component_assignments")
            comp_count = cursor.fetchone()["c"]

            # Memory estimate from latest performance report
            perf = self.get_latest_asset_performance_report(project_id)
            ram_bytes = perf.get("estimated_decoded_ram_bytes", 0) if perf else 0
            ram_mb = round(ram_bytes / (1024 * 1024), 1)

            return {
                "project_name": project_name,
                "flame_version": flame_version,
                "total_validated": total_val,
                "passed_count": passed,
                "warning_count": warning,
                "failed_count": failed,
                "not_tested_count": not_tested,
                "assigned_components_count": comp_count,
                "estimated_ram_mb": ram_mb,
            }

    def rollback_stage11_migration(self) -> bool:
        """Safely roll back Stage 11 tables for testing and disaster recovery."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            tables = [
                "asset_performance_reports",
                "integration_test_results",
                "game_component_assignments",
                "flame_compatibility_results",
                "runtime_validation_results",
                "runtime_validation_sessions",
                "flutter_project_connections",
            ]
            for t in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {t};")
            return True

    def get_all_assets(self) -> List[Dict[str, Any]]:
        """Convenience method to retrieve all catalog assets without pagination limit."""
        return self.get_assets(limit=10000)

    # -------------------------------------------------------------------------
    # STAGE 13: EXCAVATOR ASSET EXTRACTION & SPRITE PREPARATION METHODS
    # -------------------------------------------------------------------------

    def get_or_create_excavator_prep(self, asset_id: int) -> Dict[str, Any]:
        """Fetch or initialize preparation state for an asset in Stage 13."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM excavator_preparations WHERE asset_id = ?", (asset_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Retrieve asset provenance
            cursor.execute("SELECT original_path, file_hash FROM assets WHERE id = ?", (asset_id,))
            asset = cursor.fetchone()
            src_path = asset["original_path"] if asset else ""
            src_hash = asset["file_hash"] if asset else ""

            cursor.execute("""
                INSERT INTO excavator_preparations (
                    asset_id, source_path, source_hash, review_status, quality_status
                ) VALUES (?, ?, ?, 'Not Reviewed', 'Manual Review Required')
            """, (asset_id, src_path, src_hash))
            prep_id = cursor.lastrowid

            cursor.execute("SELECT * FROM excavator_preparations WHERE id = ?", (prep_id,))
            return dict(cursor.fetchone())

    def get_excavator_prep(self, prep_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve excavator preparation record by preparation ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM excavator_preparations WHERE id = ?", (prep_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_excavator_prep_by_asset(self, asset_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve excavator preparation record by asset ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM excavator_preparations WHERE asset_id = ?", (asset_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_excavator_prep(self, asset_id: int, update_dict: Dict[str, Any]) -> bool:
        """Update excavator preparation record and propagate status to assets table."""
        if not update_dict:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Ensure preparation record exists
            self.get_or_create_excavator_prep(asset_id)

            set_clauses = []
            values = []
            for k, v in update_dict.items():
                set_clauses.append(f"{k} = ?")
                values.append(v)
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values.append(asset_id)

            sql = f"UPDATE excavator_preparations SET {', '.join(set_clauses)} WHERE asset_id = ?"
            cursor.execute(sql, values)

            # Sync review status to assets table if present
            if "review_status" in update_dict:
                cursor.execute("""
                    UPDATE assets SET stage13_review_status = ? WHERE id = ?
                """, (update_dict["review_status"], asset_id))
            if "processed_image_path" in update_dict:
                cursor.execute("""
                    UPDATE assets SET stage13_prep_status = 'processed' WHERE id = ?
                """, (asset_id,))

            return True

    def save_extracted_component(self, comp_dict: Dict[str, Any]) -> int:
        """Save a new or updated extracted component record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            comp_id = comp_dict.get("id")

            if comp_id:
                # Update existing component
                fields = []
                values = []
                for k, v in comp_dict.items():
                    if k != "id":
                        fields.append(f"{k} = ?")
                        values.append(v)
                fields.append("updated_at = CURRENT_TIMESTAMP")
                values.append(comp_id)
                cursor.execute(f"UPDATE extracted_components SET {', '.join(fields)} WHERE id = ?", values)
                return comp_id
            else:
                # Insert new component
                cols = [
                    "asset_id", "preparation_id", "component_type", "component_name",
                    "source_path", "source_hash", "orig_width", "orig_height",
                    "export_width", "export_height", "bbox_x", "bbox_y", "bbox_w", "bbox_h",
                    "pivot_norm_x", "pivot_norm_y", "pivot_pixel_x", "pivot_pixel_y",
                    "pivot_status", "transparency_status", "processing_method",
                    "manual_review_status", "approval_status", "export_path",
                    "is_unavailable", "notes"
                ]
                insert_cols = []
                insert_vals = []
                placeholders = []
                for c in cols:
                    if c in comp_dict:
                        insert_cols.append(c)
                        insert_vals.append(comp_dict[c])
                        placeholders.append("?")

                sql = f"INSERT INTO extracted_components ({', '.join(insert_cols)}) VALUES ({', '.join(placeholders)})"
                cursor.execute(sql, insert_vals)
                new_id = cursor.lastrowid

                # Update extracted component count on assets table
                asset_id = comp_dict.get("asset_id")
                if asset_id:
                    cursor.execute("""
                        UPDATE assets SET stage13_components_count = (
                            SELECT COUNT(*) FROM extracted_components WHERE asset_id = ?
                        ) WHERE id = ?
                    """, (asset_id, asset_id))

                return new_id

    def get_extracted_component(self, comp_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single extracted component by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM extracted_components WHERE id = ?", (comp_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_extracted_components(
        self,
        asset_id: Optional[int] = None,
        approval_status: Optional[str] = None,
        component_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List extracted components matching filter criteria."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM extracted_components WHERE 1=1"
            params: List[Any] = []

            if asset_id is not None:
                query += " AND asset_id = ?"
                params.append(asset_id)
            if approval_status is not None and approval_status != "All":
                query += " AND approval_status = ?"
                params.append(approval_status)
            if component_type is not None and component_type != "All":
                query += " AND component_type = ?"
                params.append(component_type)

            query += " ORDER BY id DESC"
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def update_extracted_component(self, comp_id: int, update_dict: Dict[str, Any]) -> bool:
        """Update fields on an extracted component."""
        if not update_dict:
            return False
        with self.get_connection() as conn:
            cursor = conn.cursor()
            set_clauses = []
            values = []
            for k, v in update_dict.items():
                set_clauses.append(f"{k} = ?")
                values.append(v)
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values.append(comp_id)

            sql = f"UPDATE extracted_components SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(sql, values)
            return True

    def delete_extracted_component(self, comp_id: int) -> bool:
        """Delete an extracted component and update asset component count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id FROM extracted_components WHERE id = ?", (comp_id,))
            row = cursor.fetchone()
            asset_id = row["asset_id"] if row else None

            cursor.execute("DELETE FROM extracted_components WHERE id = ?", (comp_id,))

            if asset_id:
                cursor.execute("""
                    UPDATE assets SET stage13_components_count = (
                        SELECT COUNT(*) FROM extracted_components WHERE asset_id = ?
                    ) WHERE id = ?
                """, (asset_id, asset_id))

            return True

    def record_stage13_export_job(self, job_dict: Dict[str, Any]) -> int:
        """Record completed Stage 13 export operation into SQLite."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO stage13_export_jobs (
                    destination_path, components_count, manifest_path, status, details_json
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                job_dict.get("destination_path", ""),
                job_dict.get("components_count", 0),
                job_dict.get("manifest_path", ""),
                job_dict.get("status", "completed"),
                job_dict.get("details_json", "{}")
            ))
            return cursor.lastrowid

    def get_stage13_dashboard_stats(self) -> Dict[str, Any]:
        """Aggregate real-time statistics for Stage 13 metric cards."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Total catalog assets
            cursor.execute("SELECT COUNT(*) as c FROM assets")
            total_assets = cursor.fetchone()["c"]

            # Reviewed for prep
            cursor.execute("""
                SELECT COUNT(*) as c FROM excavator_preparations
                WHERE review_status != 'Not Reviewed'
            """)
            reviewed_count = cursor.fetchone()["c"]

            # Clean cutouts (background removed)
            cursor.execute("""
                SELECT COUNT(*) as c FROM excavator_preparations
                WHERE processed_image_path != '' AND processed_image_path IS NOT NULL
            """)
            clean_cutouts = cursor.fetchone()["c"]

            # Extracted sprites
            cursor.execute("SELECT COUNT(*) as c FROM extracted_components")
            extracted_sprites = cursor.fetchone()["c"]

            # Approved for export
            cursor.execute("""
                SELECT COUNT(*) as c FROM extracted_components
                WHERE approval_status = 'Approved'
            """)
            approved_for_export = cursor.fetchone()["c"]

            # Exported count across export jobs
            cursor.execute("SELECT SUM(components_count) as s FROM stage13_export_jobs")
            row = cursor.fetchone()
            exported_count = row["s"] if row and row["s"] is not None else 0

            return {
                "total_assets": total_assets,
                "reviewed_count": reviewed_count,
                "clean_cutouts": clean_cutouts,
                "extracted_sprites": extracted_sprites,
                "approved_for_export": approved_for_export,
                "exported_count": exported_count,
            }

    def rollback_stage13_migration(self) -> bool:
        """Safely roll back Stage 13 tables for testing and disaster recovery."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            tables = [
                "stage13_export_jobs",
                "extracted_components",
                "excavator_preparations",
            ]
            for t in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {t};")
            return True

    # -------------------------------------------------------------------------
    # Stage 13.2 — Global Sequential Asset Pipeline & Processing Queue
    # -------------------------------------------------------------------------

    WORKFLOW_STAGE_DEFS = [
        (1, "bg_removal", "Background Removal", "Detect solid/white backgrounds, GrabCut segmentation, and produce transparent PNG working copies."),
        (2, "watermark", "Watermark Detection & Cleanup", "Scan candidate watermark regions, review candidate overlays, and apply non-destructive cleanup."),
        (3, "text_detection", "Text & Label Detection", "Scan for Gemini text, labels, and captions; review and mask unwanted text overlays."),
        (4, "classification", "Image Classification", "Classify construction assets into machines, vehicles, components, scenes, and terrain."),
        (5, "extraction", "Collection & Sprite Extraction", "Detect multi-object collections and extract individual sprite elements."),
        (6, "sprite_prep", "Sprite Preparation", "Interactive foreground isolation, pivot point calibration, and component definitions (Stage 13)."),
        (7, "optimization", "Image Optimization", "Lossless PNG compression, texture atlas packing, dimension validation, and RAM estimation (Stage 10)."),
        (8, "export", "Final Export", "Safe export of approved assets to Flutter + Flame game project with verifiable manifest."),
    ]

    def _migrate_stage13_2_workflow(self, cursor: sqlite3.Cursor) -> None:
        """Seed workflow_stages and workflow_queue while preserving existing data."""
        # 1. Seed stages if missing
        cursor.execute("SELECT COUNT(*) as c FROM workflow_stages;")
        if cursor.fetchone()["c"] == 0:
            for s_id, s_key, s_name, s_desc in self.WORKFLOW_STAGE_DEFS:
                initial_status = "ready" if s_id == 1 else "locked"
                is_unlocked = 1 if s_id == 1 else 0
                cursor.execute("""
                    INSERT INTO workflow_stages (
                        stage_id, stage_key, stage_name, description, status, is_unlocked
                    ) VALUES (?, ?, ?, ?, ?, ?);
                """, (s_id, s_key, s_name, s_desc, initial_status, is_unlocked))

        # 2. Seed / sync workflow queue items for all assets
        cursor.execute("SELECT * FROM assets;")
        assets = cursor.fetchall()

        for a in assets:
            aid = a["id"]
            # Stage 1: Background Removal - preserve 48 processed outputs
            is_processed_bg = (a["bg_processing_status"] == "processed" and a["processed_path"] and os.path.exists(a["processed_path"]))
            s1_status = "completed" if is_processed_bg else "pending"
            s1_approval = a["bg_manual_approval"] if is_processed_bg else "unreviewed"
            s1_output = a["processed_path"] if is_processed_bg else ""
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 1, ?, ?, ?, ?);
            """, (aid, s1_status, s1_output, s1_approval, a["file_hash"] or ""))

            # Stage 2: Watermark
            cursor.execute("SELECT COUNT(*) as c FROM watermark_regions WHERE asset_id = ?;", (aid,))
            wm_count = cursor.fetchone()["c"]
            if wm_count > 0:
                s2_status = "needs_review"
            elif a["watermark_detection_status"] == "scanned":
                s2_status = "completed"
            else:
                s2_status = "pending"
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 2, ?, '', 'unreviewed', ?);
            """, (aid, s2_status, a["file_hash"] or ""))

            # Stage 3: Text Detection
            cursor.execute("SELECT COUNT(*) as c FROM text_regions WHERE asset_id = ?;", (aid,))
            txt_count = cursor.fetchone()["c"]
            if txt_count > 0:
                s3_status = "needs_review"
            elif a["text_detection_status"] == "scanned":
                s3_status = "completed"
            else:
                s3_status = "pending"
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 3, ?, '', 'unreviewed', ?);
            """, (aid, s3_status, a["file_hash"] or ""))

            # Stage 4: Classification
            if a["classification_status"] == "approved":
                s4_status = "completed"
                s4_appr = "approved"
            elif a["main_category"] and a["main_category"] != "Unclassified":
                s4_status = "needs_review"
                s4_appr = "unreviewed"
            else:
                s4_status = "pending"
                s4_appr = "unreviewed"
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 4, ?, '', ?, ?);
            """, (aid, s4_status, s4_appr, a["file_hash"] or ""))

            # Stage 5: Collection Splitter
            if a["splitter_extraction_status"] == "extracted":
                s5_status = "completed"
            elif a["splitter_analysis_status"] == "analyzed":
                s5_status = "needs_review"
            else:
                s5_status = "pending"
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 5, ?, '', 'unreviewed', ?);
            """, (aid, s5_status, a["file_hash"] or ""))

            # Stage 6: Sprite Preparation (Stage 13)
            if a["stage13_prep_status"] == "processed":
                s6_status = "completed"
                s6_appr = "approved" if a["stage13_review_status"] == "Approved for Export" else "unreviewed"
            else:
                s6_status = "pending"
                s6_appr = "unreviewed"
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 6, ?, '', ?, ?);
            """, (aid, s6_status, s6_appr, a["file_hash"] or ""))

            # Stage 7: Optimization
            if a["optimization_status"] == "optimized":
                s7_status = "completed"
            else:
                s7_status = "pending"
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 7, ?, '', 'unreviewed', ?);
            """, (aid, s7_status, a["file_hash"] or ""))

            # Stage 8: Export
            if a["is_approved_for_export"] == 1:
                s8_status = "completed"
                s8_appr = "approved"
            else:
                s8_status = "pending"
                s8_appr = "unreviewed"
            cursor.execute("""
                INSERT OR IGNORE INTO workflow_queue (
                    asset_id, stage_id, status, output_path, approval_status, source_hash
                ) VALUES (?, 8, ?, '', ?, ?);
            """, (aid, s8_status, s8_appr, a["file_hash"] or ""))

        # 3. Recalculate metrics for all stages
        for s_id in range(1, 9):
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status != 'skipped';", (s_id,))
            total_eligible = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'completed';", (s_id,))
            completed = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'needs_review';", (s_id,))
            needs_review = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'skipped';", (s_id,))
            skipped = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'failed';", (s_id,))
            failed = cursor.fetchone()["c"]

            cursor.execute("""
                UPDATE workflow_stages SET
                    total_eligible = ?,
                    completed_count = ?,
                    needs_review_count = ?,
                    skipped_count = ?,
                    failed_count = ?
                WHERE stage_id = ?;
            """, (total_eligible, completed, needs_review, skipped, failed, s_id))

    def get_workflow_stages(self) -> List[Dict[str, Any]]:
        """Retrieve all 8 workflow stages ordered by stage_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflow_stages ORDER BY stage_id ASC;")
            return [dict(r) for r in cursor.fetchall()]

    def get_workflow_stage(self, stage_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a specific workflow stage by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflow_stages WHERE stage_id = ?;", (stage_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_workflow_stage(self, stage_id: int, updates: Dict[str, Any]) -> bool:
        """Update fields for a workflow stage."""
        if not updates:
            return False
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values()) + [stage_id]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE workflow_stages SET {', '.join(set_clauses)} WHERE stage_id = ?;", values)
            return cursor.rowcount > 0

    def unlock_workflow_stage(self, stage_id: int) -> bool:
        """Unlock a workflow stage for execution."""
        return self.update_workflow_stage(stage_id, {"is_unlocked": 1, "status": "ready"})

    def recalculate_stage_metrics(self, stage_id: int) -> Dict[str, Any]:
        """Recalculate counts from workflow_queue and update workflow_stages."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status != 'skipped';", (stage_id,))
            total_eligible = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'completed';", (stage_id,))
            completed = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'needs_review';", (stage_id,))
            needs_review = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'skipped';", (stage_id,))
            skipped = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = ? AND status = 'failed';", (stage_id,))
            failed = cursor.fetchone()["c"]

            cursor.execute("""
                UPDATE workflow_stages SET
                    total_eligible = ?,
                    completed_count = ?,
                    needs_review_count = ?,
                    skipped_count = ?,
                    failed_count = ?
                WHERE stage_id = ?;
            """, (total_eligible, completed, needs_review, skipped, failed, stage_id))

            cursor.execute("SELECT * FROM workflow_stages WHERE stage_id = ?;", (stage_id,))
            row = cursor.fetchone()
            return dict(row) if row else {}

    def get_workflow_queue(
        self,
        stage_id: Optional[int] = None,
        status: Optional[str] = None,
        approval_status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query workflow queue joined with asset metadata."""
        query = """
            SELECT
                q.id as queue_id,
                q.asset_id,
                q.stage_id,
                q.status as queue_status,
                q.output_path,
                q.approval_status,
                q.error_message,
                q.retry_count,
                q.source_hash,
                q.updated_at as queue_updated_at,
                a.filename,
                a.original_path,
                a.collection,
                a.format,
                a.width,
                a.height,
                a.file_size,
                a.has_transparency,
                a.alpha_detected,
                a.thumbnail_path,
                a.main_category,
                a.subcategory,
                a.composition_type,
                a.background_eligibility,
                a.bg_processing_status
            FROM workflow_queue q
            JOIN assets a ON q.asset_id = a.id
            WHERE 1=1
        """
        params: List[Any] = []
        if stage_id is not None:
            query += " AND q.stage_id = ?"
            params.append(stage_id)
        if status is not None and status != "all":
            query += " AND q.status = ?"
            params.append(status)
        if approval_status is not None and approval_status != "all":
            query += " AND q.approval_status = ?"
            params.append(approval_status)
        if search:
            query += " AND (a.filename LIKE ? OR a.collection LIKE ? OR a.main_category LIKE ?)"
            term = f"%{search.strip()}%"
            params.extend([term, term, term])

        query += " ORDER BY q.asset_id ASC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_workflow_queue_count(
        self,
        stage_id: Optional[int] = None,
        status: Optional[str] = None,
        approval_status: Optional[str] = None,
        search: Optional[str] = None
    ) -> int:
        """Count total matching items in workflow_queue."""
        query = """
            SELECT COUNT(*) as c
            FROM workflow_queue q
            JOIN assets a ON q.asset_id = a.id
            WHERE 1=1
        """
        params: List[Any] = []
        if stage_id is not None:
            query += " AND q.stage_id = ?"
            params.append(stage_id)
        if status is not None and status != "all":
            query += " AND q.status = ?"
            params.append(status)
        if approval_status is not None and approval_status != "all":
            query += " AND q.approval_status = ?"
            params.append(approval_status)
        if search:
            query += " AND (a.filename LIKE ? OR a.collection LIKE ? OR a.main_category LIKE ?)"
            term = f"%{search.strip()}%"
            params.extend([term, term, term])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()["c"]

    def update_workflow_item_by_asset_stage(self, asset_id: int, stage_id: int, updates: Dict[str, Any]) -> bool:
        """Update a specific asset's stage record in workflow_queue."""
        if not updates:
            return False
        updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values()) + [asset_id, stage_id]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE workflow_queue SET {', '.join(set_clauses)} WHERE asset_id = ? AND stage_id = ?;", values)
            success = cursor.rowcount > 0
        if success:
            self.recalculate_stage_metrics(stage_id)
        return success

    def update_workflow_items_status(
        self,
        stage_id: int,
        asset_ids: List[int],
        status: str,
        error_message: str = "",
        output_path: str = ""
    ) -> int:
        """Bulk update status for a list of asset IDs in a stage."""
        if not asset_ids:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in asset_ids)
            query = f"""
                UPDATE workflow_queue SET
                    status = ?,
                    error_message = CASE WHEN ? != '' THEN ? ELSE error_message END,
                    output_path = CASE WHEN ? != '' THEN ? ELSE output_path END,
                    updated_at = ?
                WHERE stage_id = ? AND asset_id IN ({placeholders});
            """
            params = [status, error_message, error_message, output_path, output_path, now, stage_id] + asset_ids
            cursor.execute(query, params)
            count = cursor.rowcount
        self.recalculate_stage_metrics(stage_id)
        return count

    def update_workflow_items_approval(
        self,
        stage_id: int,
        asset_ids: List[int],
        approval_status: str
    ) -> int:
        """Bulk update approval status for asset IDs in a stage."""
        if not asset_ids:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in asset_ids)
            cursor.execute(f"""
                UPDATE workflow_queue SET
                    approval_status = ?,
                    updated_at = ?
                WHERE stage_id = ? AND asset_id IN ({placeholders});
            """, [approval_status, now, stage_id] + asset_ids)
            count = cursor.rowcount
        self.recalculate_stage_metrics(stage_id)
        return count

    def get_workflow_dashboard_stats(self) -> Dict[str, Any]:
        """
        Aggregate authentic database metrics for the Global Workflow Dashboard.
        Never returns fabricated values.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Total assets
            cursor.execute("SELECT COUNT(*) as c FROM assets;")
            total_assets = cursor.fetchone()["c"]

            # Original transparent source files (source files with alpha channel)
            cursor.execute("SELECT COUNT(*) as c FROM assets WHERE alpha_detected = 1 OR has_transparency = 1;")
            orig_transparent = cursor.fetchone()["c"]

            # Backgrounds processed (Stage 1 completed)
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = 1 AND status = 'completed';")
            bg_processed = cursor.fetchone()["c"]

            # Watermarks reviewed (Stage 2 reviewed/completed)
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = 2 AND status = 'completed';")
            watermarks_reviewed = cursor.fetchone()["c"]

            # Text reviewed (Stage 3 reviewed/completed)
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = 3 AND status = 'completed';")
            text_reviewed = cursor.fetchone()["c"]

            # Classified assets (Stage 4 completed or approved)
            cursor.execute("SELECT COUNT(*) as c FROM workflow_queue WHERE stage_id = 4 AND status = 'completed';")
            classified_assets = cursor.fetchone()["c"]

            # Extracted sprites (Stage 5 extracted or Stage 13 extracted components)
            cursor.execute("SELECT COUNT(*) as c FROM extracted_components;")
            c1 = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) as c FROM extracted_assets;")
            c2 = cursor.fetchone()["c"]
            extracted_sprites = c1 + c2

            # Approved assets
            cursor.execute("SELECT COUNT(*) as c FROM assets WHERE is_approved_for_export = 1 OR stage13_review_status = 'Approved for Export';")
            approved_assets = cursor.fetchone()["c"]

            # Failed assets across all active queues
            cursor.execute("SELECT COUNT(DISTINCT asset_id) as c FROM workflow_queue WHERE status = 'failed';")
            failed_assets = cursor.fetchone()["c"]

            # Needs manual review assets
            cursor.execute("SELECT COUNT(DISTINCT asset_id) as c FROM workflow_queue WHERE status = 'needs_review';")
            needs_review_assets = cursor.fetchone()["c"]

            # Stages
            cursor.execute("SELECT * FROM workflow_stages ORDER BY stage_id ASC;")
            stages = [dict(r) for r in cursor.fetchall()]

            return {
                "total_assets": total_assets,
                "original_transparent_assets": orig_transparent,
                "backgrounds_processed": bg_processed,
                "watermarks_reviewed": watermarks_reviewed,
                "text_reviewed": text_reviewed,
                "classified_assets": classified_assets,
                "extracted_sprites": extracted_sprites,
                "approved_assets": approved_assets,
                "failed_assets": failed_assets,
                "needs_review_assets": needs_review_assets,
                "stages": stages,
            }

    def sync_workflow_from_existing_data(self) -> Dict[str, Any]:
        """Manually trigger a sync/refresh of workflow queue from disk and DB records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            self._migrate_stage13_2_workflow(cursor)
        return self.get_workflow_dashboard_stats()

    def rollback_stage13_2_migration(self) -> bool:
        """Safely drop Stage 13.2 tables for regression testing."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS workflow_queue;")
            cursor.execute("DROP TABLE IF EXISTS workflow_stages;")
            return True


# Global database instance
db = DatabaseManager()