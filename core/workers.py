"""
Background Workers for Construction Asset Processor
Runs heavy filesystem scanning, metadata extraction, and thumbnail generation
on dedicated QThreads to ensure the UI remains 100% fluid and responsive.
"""

import logging
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional
from PySide6.QtCore import QMutex, QObject, QThread, QWaitCondition, Signal

from core.ai_engine import vision_classifier
from core.database import db
from core.scanner import scanner
from core.text_engine import text_engine
from core.thumbnail import thumbnail_engine
from core.transparency_engine import transparency_engine
from core.watermark_engine import watermark_engine
from core.collection_splitter_engine import collection_splitter_engine

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """
    Background worker thread to scan folders, parse image metadata,
    generate thumbnails, and record items into the SQLite database.
    """

    # Signals
    scan_started = Signal(int)  # Total files found
    progress = Signal(int, int, str)  # current, total, filename
    asset_imported = Signal(dict)  # single asset record dict
    log_message = Signal(str, str, str)  # action, message, level (info, warning, error, success)
    scan_finished = Signal(dict)  # summary dictionary
    scan_error = Signal(str)  # critical error message

    def __init__(
        self,
        folder_path: str,
        recursive: bool = True,
        collection_override: Optional[str] = None,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.folder_path = folder_path
        self.recursive = recursive
        self.collection_override = collection_override
        self._is_cancelled = False

    def request_cancel(self):
        """Signal the worker to halt scanning gracefully."""
        self._is_cancelled = True
        logger.info("Scan cancellation requested.")

    def run(self):
        """Worker thread execution logic."""
        try:
            folder = Path(self.folder_path)
            if not folder.exists() or not folder.is_dir():
                self.scan_error.emit(f"Selected folder does not exist or is not a directory: {self.folder_path}")
                return

            self.log_message.emit("Scan Initiated", f"Discovering image files in '{folder.name}'...", "info")
            image_files = scanner.discover_image_files(str(folder), recursive=self.recursive)
            total_files = len(image_files)

            if total_files == 0:
                self.log_message.emit("Scan Completed", "No supported image assets found in folder.", "warning")
                self.scan_finished.emit({
                    "total_scanned": 0,
                    "new_imported": 0,
                    "updated": 0,
                    "errors": 0,
                    "total_bytes": 0,
                    "folder": str(folder),
                })
                return

            self.scan_started.emit(total_files)
            self.log_message.emit("Files Found", f"Found {total_files} candidate images. Beginning extraction...", "info")

            new_count = 0
            updated_count = 0
            error_count = 0
            total_bytes = 0

            for idx, file_path in enumerate(image_files, start=1):
                if self._is_cancelled:
                    self.log_message.emit("Scan Cancelled", f"Process stopped by user at file {idx}/{total_files}.", "warning")
                    break

                try:
                    self.progress.emit(idx, total_files, file_path.name)

                    # Extract metadata
                    meta = scanner.extract_metadata(file_path, target_collection=self.collection_override)
                    if not meta:
                        error_count += 1
                        self.log_message.emit("Extraction Error", f"Could not read metadata from {file_path.name}", "error")
                        continue

                    # Generate cached thumbnail
                    thumb_path = thumbnail_engine.create_thumbnail(meta["original_path"])
                    meta["thumbnail_path"] = thumb_path

                    # Upsert into SQLite
                    asset_id, is_new = db.upsert_asset(meta)
                    meta["id"] = asset_id

                    if is_new:
                        new_count += 1
                    else:
                        updated_count += 1

                    total_bytes += meta["file_size"]
                    self.asset_imported.emit(meta)

                except Exception as file_err:
                    error_count += 1
                    logger.error(f"Error processing {file_path.name}: {file_err}")
                    self.log_message.emit("File Error", f"{file_path.name}: {file_err}", "error")

            # Record scan in database history
            db.record_scan(str(folder), len(image_files), new_count, total_bytes)
            db.log_event(
                action="Folder Scan",
                stage="import",
                message=f"Scanned {len(image_files)} files in {folder.name}. Imported: {new_count}, Updated: {updated_count}, Errors: {error_count}.",
                status="success" if error_count == 0 else "warning"
            )

            summary = {
                "total_scanned": len(image_files),
                "processed_count": idx,
                "new_imported": new_count,
                "updated": updated_count,
                "errors": error_count,
                "total_bytes": total_bytes,
                "folder": str(folder),
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "Scan Completed",
                f"Completed scan. {new_count} new assets added, {updated_count} existing records updated.",
                "success"
            )
            self.scan_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error(f"Fatal scanning thread error: {err_trace}")
            self.scan_error.emit(f"Scan failed unexpectedly: {str(e)}")


class ClassificationWorker(QThread):
    """
    Background worker thread to perform AI vision classification on asset batches
    without freezing the main UI thread. Supports pause, resume, and cancellation.
    """

    analysis_started = Signal(int)  # total count
    progress = Signal(int, int, str, dict)  # current, total, filename, result_dict
    asset_classified = Signal(dict)  # full updated asset dict
    log_message = Signal(str, str, str)  # action, message, level
    analysis_finished = Signal(dict)  # summary dict
    analysis_paused = Signal(bool)  # is_paused
    analysis_error = Signal(str)

    def __init__(
        self,
        asset_ids: Optional[List[int]] = None,
        collection: Optional[str] = None,
        mode: str = "unclassified",  # "unclassified", "all", "rejected", "selected"
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.asset_ids = asset_ids
        self.collection = collection
        self.mode = mode

        self._is_cancelled = False
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_cond = QWaitCondition()

    def request_cancel(self):
        """Request graceful cancellation."""
        self._is_cancelled = True
        self.resume()  # unpause if paused so thread can exit
        logger.info("Classification worker cancellation requested.")

    def pause(self):
        """Pause worker processing loop."""
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()
        self.analysis_paused.emit(True)
        self.log_message.emit("AI Processing", "Batch classification paused.", "info")

    def resume(self):
        """Resume worker processing loop."""
        self._mutex.lock()
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.analysis_paused.emit(False)
        self.log_message.emit("AI Processing", "Batch classification resumed.", "info")

    def run(self):
        """Execution logic for batch classification."""
        try:
            # Query targets based on mode
            if self.mode == "selected" and self.asset_ids:
                placeholders = ",".join(["?"] * len(self.asset_ids))
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT * FROM assets WHERE id IN ({placeholders}) ORDER BY id ASC", list(self.asset_ids))
                    targets = [dict(r) for r in cursor.fetchall()]
            elif self.mode == "rejected":
                targets = db.get_assets(
                    collection=self.collection,
                    classification_status="rejected",
                    limit=10000
                )
            elif self.mode == "all":
                targets = db.get_assets(
                    collection=self.collection,
                    limit=10000
                )
            else:  # "unclassified"
                targets = db.get_assets(
                    collection=self.collection,
                    classification_status="unclassified",
                    limit=10000
                )

            total = len(targets)
            if total == 0:
                self.log_message.emit("AI Recognition", "No matching assets found for analysis.", "warning")
                self.analysis_finished.emit({
                    "total": 0, "processed": 0, "classified": 0, "errors": 0, "cancelled": False
                })
                return

            self.analysis_started.emit(total)
            self.log_message.emit(
                "AI Recognition Started",
                f"Starting vision analysis for {total} assets (mode: {self.mode})...",
                "info"
            )

            processed = 0
            classified_count = 0
            error_count = 0

            for idx, asset in enumerate(targets, start=1):
                if self._is_cancelled:
                    self.log_message.emit("AI Recognition", f"Processing halted by user at item {idx-1}/{total}.", "warning")
                    break

                # Handle pause
                self._mutex.lock()
                while self._is_paused and not self._is_cancelled:
                    self._pause_cond.wait(self._mutex)
                self._mutex.unlock()

                if self._is_cancelled:
                    break

                try:
                    asset_id = asset["id"]
                    filename = asset["filename"]

                    # Execute Computer Vision recognition
                    result = vision_classifier.analyze_asset(asset)

                    # Persist to SQLite
                    db.save_classification(asset_id, result.to_dict(), action="ai_suggestion")

                    processed += 1
                    classified_count += 1

                    # Fetch updated asset record
                    updated_asset = db.get_asset(asset_id) or asset

                    self.progress.emit(idx, total, filename, result.to_dict())
                    self.asset_classified.emit(updated_asset)

                except Exception as item_err:
                    error_count += 1
                    logger.error(f"Error classifying asset #{asset.get('id')}: {item_err}")
                    self.log_message.emit("Analysis Error", f"{asset.get('filename')}: {item_err}", "error")

            summary = {
                "total": total,
                "processed": processed,
                "classified": classified_count,
                "errors": error_count,
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "AI Recognition Completed",
                f"Processed {processed}/{total} assets. {classified_count} classified, {error_count} errors.",
                "success" if error_count == 0 else "warning"
            )
            self.analysis_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error(f"Fatal error in classification worker: {err_trace}")
            self.analysis_error.emit(f"AI classification failed: {str(e)}")


class TransparencyWorker(QThread):
    """
    Dedicated background worker for non-blocking batch background removal
    and transparency processing (Stage 5).
    """

    # Signals
    processing_started = Signal(int)  # Total targets count
    progress = Signal(int, int, str, int, int, int)  # current, total, filename, success_cnt, fail_cnt, remaining_cnt
    asset_processed = Signal(dict)  # Updated asset dictionary
    processing_paused = Signal(bool)  # Paused state
    processing_finished = Signal(dict)  # Final summary metrics
    processing_error = Signal(str)  # Fatal error message
    log_message = Signal(str, str, str)  # action, message, status (info, success, warning, error)

    def __init__(
        self,
        mode: str = "selected",
        asset_ids: Optional[List[int]] = None,
        method: str = "auto",
        collection: Optional[str] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.asset_ids = asset_ids or []
        self.method = method
        self.collection = collection

        self._is_cancelled = False
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_cond = QWaitCondition()

    def cancel(self):
        """Request immediate thread termination."""
        self._mutex.lock()
        self._is_cancelled = True
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.log_message.emit("Transparency", "Cancellation requested...", "warning")

    def pause(self):
        """Pause worker processing loop."""
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()
        self.processing_paused.emit(True)
        self.log_message.emit("Transparency", "Background removal paused.", "info")

    def resume(self):
        """Resume worker processing loop."""
        self._mutex.lock()
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.processing_paused.emit(False)
        self.log_message.emit("Transparency", "Background removal resumed.", "info")

    def run(self):
        """Execution logic for batch background removal."""
        try:
            # Query targets based on mode
            if self.mode == "selected" and self.asset_ids:
                placeholders = ",".join(["?"] * len(self.asset_ids))
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"SELECT * FROM assets WHERE id IN ({placeholders}) ORDER BY id ASC",
                        list(self.asset_ids),
                    )
                    targets = [dict(r) for r in cursor.fetchall()]
            elif self.mode == "suitable":
                targets = db.get_assets(
                    collection=self.collection,
                    bg_eligibility="Suitable for Background Removal",
                    limit=10000,
                )
            elif self.mode == "approved":
                targets = db.get_assets(
                    collection=self.collection,
                    bg_manual_approval="approved",
                    limit=10000,
                )
            elif self.mode == "retry_failed":
                targets = db.get_assets(
                    collection=self.collection,
                    bg_processing_status="failed",
                    limit=10000,
                )
            else:  # "all"
                targets = db.get_assets(
                    collection=self.collection,
                    limit=10000,
                )

            total = len(targets)
            if total == 0:
                self.log_message.emit("Transparency", "No matching assets found for background removal.", "warning")
                self.processing_finished.emit({
                    "total": 0, "processed": 0, "success": 0, "failed": 0, "cancelled": False
                })
                return

            self.processing_started.emit(total)
            self.log_message.emit(
                "Transparency Started",
                f"Starting background removal for {total} assets (mode: {self.mode}, method: {self.method})...",
                "info",
            )

            success_cnt = 0
            failed_cnt = 0

            for idx, asset in enumerate(targets, start=1):
                if self._is_cancelled:
                    self.log_message.emit("Transparency", f"Halted by user at item {idx-1}/{total}.", "warning")
                    break

                # Handle pause
                self._mutex.lock()
                while self._is_paused and not self._is_cancelled:
                    self._pause_cond.wait(self._mutex)
                self._mutex.unlock()

                if self._is_cancelled:
                    break

                try:
                    asset_id = asset["id"]
                    filename = asset["filename"]
                    remaining = total - idx

                    # Execute background removal safely
                    success, res_data, msg = transparency_engine.process_asset(
                        asset, method=self.method
                    )

                    if success:
                        success_cnt += 1
                    else:
                        failed_cnt += 1

                    # Fetch updated asset record from database
                    updated_asset = db.get_asset(asset_id) or asset

                    self.progress.emit(idx, total, filename, success_cnt, failed_cnt, remaining)
                    self.asset_processed.emit(updated_asset)

                except Exception as item_err:
                    failed_cnt += 1
                    logger.error("Error processing asset #%s for transparency: %s", asset.get("id"), item_err)
                    self.log_message.emit("Process Error", f"{asset.get('filename')}: {item_err}", "error")

            summary = {
                "total": total,
                "processed": success_cnt + failed_cnt,
                "success": success_cnt,
                "failed": failed_cnt,
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "Transparency Completed",
                f"Finished background removal: {success_cnt} successful, {failed_cnt} failed.",
                "success" if failed_cnt == 0 else "warning",
            )
            self.processing_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error("Fatal error in transparency worker: %s", err_trace)
            self.processing_error.emit(f"Background removal worker failed: {str(e)}")


class TextDetectionWorker(QThread):
    """
    Background worker thread to run text and label detection across assets.
    Analyzes images for text regions, watermark candidates, brand names, and labels.
    Thread-safe pause, resume, and cancellation.
    """

    # Signals
    detection_started = Signal(int)  # total count
    progress = Signal(int, int, str, int, int, int)  # current, total, filename, with_text_count, clean_count, remaining
    asset_detected = Signal(dict)  # single updated asset dict
    detection_paused = Signal(bool)  # is_paused
    detection_finished = Signal(dict)  # summary dictionary
    detection_error = Signal(str)  # critical error message
    log_message = Signal(str, str, str)  # action, message, level

    def __init__(
        self,
        mode: str = "all",
        asset_ids: Optional[List[int]] = None,
        collection: Optional[str] = None,
        method: str = "auto",
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.mode = mode  # "all", "selected", "uninspected", "retry_failed"
        self.asset_ids = asset_ids or []
        self.collection = collection
        self.method = method  # "auto", "opencv", "easyocr"

        self._is_cancelled = False
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_cond = QWaitCondition()

    def cancel(self):
        """Request immediate thread termination."""
        self._mutex.lock()
        self._is_cancelled = True
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.log_message.emit("Text Detection", "Cancellation requested...", "warning")

    def pause(self):
        """Pause worker processing loop."""
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()
        self.detection_paused.emit(True)
        self.log_message.emit("Text Detection", "Text detection paused.", "info")

    def resume(self):
        """Resume worker processing loop."""
        self._mutex.lock()
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.detection_paused.emit(False)
        self.log_message.emit("Text Detection", "Text detection resumed.", "info")

    def run(self):
        """Execution logic for batch text and label detection."""
        try:
            # Query targets based on mode
            if self.mode == "selected" and self.asset_ids:
                placeholders = ",".join(["?"] * len(self.asset_ids))
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"SELECT * FROM assets WHERE id IN ({placeholders}) ORDER BY id ASC",
                        list(self.asset_ids),
                    )
                    targets = [dict(r) for r in cursor.fetchall()]
            elif self.mode == "uninspected":
                targets = db.get_assets(
                    collection=self.collection,
                    text_detection_status="uninspected",
                    limit=10000,
                )
            elif self.mode == "retry_failed":
                targets = db.get_assets(
                    collection=self.collection,
                    text_detection_status="failed",
                    limit=10000,
                )
            else:  # "all"
                targets = db.get_assets(
                    collection=self.collection,
                    limit=10000,
                )

            total = len(targets)
            if total == 0:
                self.log_message.emit("Text Detection", "No matching assets found for text analysis.", "warning")
                self.detection_finished.emit({
                    "total": 0, "processed": 0, "with_text": 0, "clean": 0, "failed": 0, "cancelled": False
                })
                return

            self.detection_started.emit(total)
            self.log_message.emit(
                "Detection Started",
                f"Starting text & label detection for {total} assets (mode: {self.mode}, method: {self.method})...",
                "info",
            )

            with_text_cnt = 0
            clean_cnt = 0
            failed_cnt = 0

            for idx, asset in enumerate(targets, start=1):
                if self._is_cancelled:
                    self.log_message.emit("Text Detection", f"Halted by user at item {idx-1}/{total}.", "warning")
                    break

                # Handle pause
                self._mutex.lock()
                while self._is_paused and not self._is_cancelled:
                    self._pause_cond.wait(self._mutex)
                self._mutex.unlock()

                if self._is_cancelled:
                    break

                try:
                    asset_id = asset["id"]
                    filename = asset["filename"]
                    remaining = total - idx

                    # Run text detection and persist to SQLite
                    success, region_count, _ = text_engine.process_and_save_asset(
                        asset, method=self.method
                    )

                    if success:
                        if region_count > 0:
                            with_text_cnt += 1
                        else:
                            clean_cnt += 1
                    else:
                        failed_cnt += 1

                    # Fetch updated record
                    updated_asset = db.get_asset(asset_id) or asset

                    self.progress.emit(idx, total, filename, with_text_cnt, clean_cnt, remaining)
                    self.asset_detected.emit(updated_asset)

                except Exception as item_err:
                    failed_cnt += 1
                    logger.error("Error detecting text for asset #%s: %s", asset.get("id"), item_err)
                    self.log_message.emit("Detection Error", f"{asset.get('filename')}: {item_err}", "error")

            summary = {
                "total": total,
                "processed": with_text_cnt + clean_cnt + failed_cnt,
                "with_text": with_text_cnt,
                "clean": clean_cnt,
                "failed": failed_cnt,
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "Detection Completed",
                f"Finished text analysis: {with_text_cnt} with text, {clean_cnt} clean, {failed_cnt} failed.",
                "success" if failed_cnt == 0 else "warning",
            )
            self.detection_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error("Fatal error in text detection worker: %s", err_trace)
            self.detection_error.emit(f"Text detection worker failed: {str(e)}")


class WatermarkDetectionWorker(QThread):
    """
    Background worker thread to run watermark candidate detection across assets.
    Analyzes images for corner attribution marks, logos, semi-transparent overlays,
    and Stage 6 text region correlations.
    Thread-safe pause, resume, and cancellation.
    """

    # Signals
    detection_started = Signal(int)  # total count
    progress = Signal(int, int, str, int, int, int)  # current, total, filename, with_candidates_count, clean_count, remaining
    asset_detected = Signal(dict)  # single updated asset dict
    detection_paused = Signal(bool)  # is_paused
    detection_finished = Signal(dict)  # summary dictionary
    detection_error = Signal(str)  # critical error message
    log_message = Signal(str, str, str)  # action, message, level

    def __init__(
        self,
        mode: str = "all",
        asset_ids: Optional[List[int]] = None,
        collection: Optional[str] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.mode = mode  # "all", "selected", "uninspected", "retry_failed"
        self.asset_ids = asset_ids or []
        self.collection = collection

        self._is_cancelled = False
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_cond = QWaitCondition()

    def cancel(self):
        """Request immediate thread termination."""
        self._mutex.lock()
        self._is_cancelled = True
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.log_message.emit("Watermark Detection", "Cancellation requested...", "warning")

    def pause(self):
        """Pause worker processing loop."""
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()
        self.detection_paused.emit(True)
        self.log_message.emit("Watermark Detection", "Watermark detection paused.", "info")

    def resume(self):
        """Resume worker processing loop."""
        self._mutex.lock()
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.detection_paused.emit(False)
        self.log_message.emit("Watermark Detection", "Watermark detection resumed.", "info")

    def run(self):
        """Execution logic for batch watermark candidate detection."""
        try:
            # Query targets based on mode
            if self.mode == "selected" and self.asset_ids:
                placeholders = ",".join(["?"] * len(self.asset_ids))
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"SELECT * FROM assets WHERE id IN ({placeholders}) ORDER BY id ASC",
                        list(self.asset_ids),
                    )
                    targets = [dict(r) for r in cursor.fetchall()]
            elif self.mode == "uninspected":
                targets = db.get_assets(
                    collection=self.collection,
                    watermark_detection_status="uninspected",
                    limit=10000,
                )
            elif self.mode == "retry_failed":
                targets = db.get_assets(
                    collection=self.collection,
                    watermark_detection_status="failed",
                    limit=10000,
                )
            else:  # "all"
                targets = db.get_assets(
                    collection=self.collection,
                    limit=10000,
                )

            total = len(targets)
            if total == 0:
                self.log_message.emit("Watermark Detection", "No matching assets found for watermark analysis.", "warning")
                self.detection_finished.emit({
                    "total": 0, "processed": 0, "with_candidates": 0, "clean": 0, "failed": 0, "cancelled": False
                })
                return

            self.detection_started.emit(total)
            self.log_message.emit(
                "Detection Started",
                f"Starting watermark candidate detection for {total} assets (mode: {self.mode})...",
                "info",
            )

            with_candidates_cnt = 0
            clean_cnt = 0
            failed_cnt = 0

            for idx, asset in enumerate(targets, start=1):
                if self._is_cancelled:
                    self.log_message.emit("Watermark Detection", f"Halted by user at item {idx-1}/{total}.", "warning")
                    break

                # Handle pause
                self._mutex.lock()
                while self._is_paused and not self._is_cancelled:
                    self._pause_cond.wait(self._mutex)
                self._mutex.unlock()

                if self._is_cancelled:
                    break

                try:
                    asset_id = asset["id"]
                    filename = asset["filename"]
                    remaining = total - idx

                    # Run watermark detection and persist to SQLite
                    success, cand_count, _ = watermark_engine.process_and_save_asset(asset)

                    if success:
                        if cand_count > 0:
                            with_candidates_cnt += 1
                        else:
                            clean_cnt += 1
                    else:
                        failed_cnt += 1

                    # Fetch updated record
                    updated_asset = db.get_asset(asset_id) or asset

                    self.progress.emit(idx, total, filename, with_candidates_cnt, clean_cnt, remaining)
                    self.asset_detected.emit(updated_asset)

                except Exception as item_err:
                    failed_cnt += 1
                    logger.error("Error detecting watermarks for asset #%s: %s", asset.get("id"), item_err)
                    self.log_message.emit("Detection Error", f"{asset.get('filename')}: {item_err}", "error")

            summary = {
                "total": total,
                "processed": with_candidates_cnt + clean_cnt + failed_cnt,
                "with_candidates": with_candidates_cnt,
                "clean": clean_cnt,
                "failed": failed_cnt,
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "Detection Completed",
                f"Finished watermark analysis: {with_candidates_cnt} with candidates, {clean_cnt} clean, {failed_cnt} failed.",
                "success" if failed_cnt == 0 else "warning",
            )
            self.detection_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error("Fatal error in watermark detection worker: %s", err_trace)
            self.detection_error.emit(f"Watermark detection worker failed: {str(e)}")


class CollectionAnalysisWorker(QThread):
    """
    Background worker thread to run collection composition analysis,
    object segmentation, sprite sheet grid detection, and region candidate extraction.
    Strictly non-destructive and records candidates to SQLite.
    """

    # Signals
    analysis_started = Signal(int)  # Total assets to analyze
    progress = Signal(int, int, str, int, int, int)  # current, total, filename, collection_cnt, single_cnt, remaining
    asset_analyzed = Signal(dict)  # Updated asset dictionary
    analysis_paused = Signal(bool)  # Paused state (True/False)
    analysis_finished = Signal(dict)  # Summary dictionary
    analysis_error = Signal(str)  # Critical error message
    log_message = Signal(str, str, str)  # action, message, level

    def __init__(
        self,
        mode: str = "all",
        asset_ids: Optional[List[int]] = None,
        collection: Optional[str] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.asset_ids = asset_ids or []
        self.collection = collection
        self._is_cancelled = False
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_cond = QWaitCondition()

    def cancel(self):
        """Request immediate thread cancellation."""
        self._mutex.lock()
        self._is_cancelled = True
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.log_message.emit("Collection Splitter", "Cancellation requested...", "warning")

    def pause(self):
        """Pause worker processing loop."""
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()
        self.analysis_paused.emit(True)
        self.log_message.emit("Collection Splitter", "Analysis paused.", "info")

    def resume(self):
        """Resume worker processing loop."""
        self._mutex.lock()
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()
        self.analysis_paused.emit(False)
        self.log_message.emit("Collection Splitter", "Analysis resumed.", "info")

    def run(self):
        """Worker thread execution logic."""
        try:
            # Query targets based on mode
            if self.mode == "selected" and self.asset_ids:
                placeholders = ",".join(["?"] * len(self.asset_ids))
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"SELECT * FROM assets WHERE id IN ({placeholders}) ORDER BY id ASC",
                        list(self.asset_ids),
                    )
                    targets = [dict(r) for r in cursor.fetchall()]
            elif self.mode == "uninspected":
                targets = db.get_assets(
                    collection=self.collection,
                    splitter_analysis_status="uninspected",
                    limit=10000,
                )
            elif self.mode == "retry_failed":
                targets = db.get_assets(
                    collection=self.collection,
                    splitter_analysis_status="failed",
                    limit=10000,
                )
            else:  # "all"
                targets = db.get_assets(
                    collection=self.collection,
                    limit=10000,
                )

            total = len(targets)
            if total == 0:
                self.log_message.emit("Collection Splitter", "No matching assets found for collection analysis.", "warning")
                self.analysis_finished.emit({
                    "total": 0, "processed": 0, "collections": 0, "single_objects": 0, "sprite_sheets": 0, "scenes": 0, "failed": 0, "cancelled": False
                })
                return

            self.analysis_started.emit(total)
            self.log_message.emit(
                "Analysis Started",
                f"Starting collection analysis for {total} assets (mode: {self.mode})...",
                "info",
            )

            collection_cnt = 0
            single_cnt = 0
            sprite_sheet_cnt = 0
            scene_cnt = 0
            failed_cnt = 0

            for idx, asset in enumerate(targets, start=1):
                if self._is_cancelled:
                    self.log_message.emit("Collection Splitter", f"Halted by user at item {idx-1}/{total}.", "warning")
                    break

                # Handle pause
                self._mutex.lock()
                while self._is_paused and not self._is_cancelled:
                    self._pause_cond.wait(self._mutex)
                self._mutex.unlock()

                if self._is_cancelled:
                    break

                try:
                    asset_id = asset["id"]
                    filename = asset["filename"]
                    remaining = total - idx

                    # Run collection analysis and persist candidates to SQLite
                    success, comp_type, cand_count, msg = collection_splitter_engine.process_and_save_asset(asset)

                    if success:
                        if comp_type in ("Multiple Object Collection", "Overlapping Object Collection"):
                            collection_cnt += 1
                        elif comp_type in ("Sprite Sheet", "Animation Frame Grid"):
                            sprite_sheet_cnt += 1
                        elif comp_type == "Background Scene":
                            scene_cnt += 1
                        else:
                            single_cnt += 1
                    else:
                        failed_cnt += 1

                    # Fetch updated record
                    updated_asset = db.get_asset(asset_id) or asset

                    self.progress.emit(idx, total, filename, collection_cnt + sprite_sheet_cnt, single_cnt, remaining)
                    self.asset_analyzed.emit(updated_asset)

                except Exception as item_err:
                    failed_cnt += 1
                    logger.error("Error analyzing collection for asset #%s: %s", asset.get("id"), item_err)
                    self.log_message.emit("Analysis Error", f"{asset.get('filename')}: {item_err}", "error")

            summary = {
                "total": total,
                "processed": collection_cnt + single_cnt + sprite_sheet_cnt + scene_cnt + failed_cnt,
                "collections": collection_cnt,
                "single_objects": single_cnt,
                "sprite_sheets": sprite_sheet_cnt,
                "scenes": scene_cnt,
                "failed": failed_cnt,
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "Analysis Completed",
                f"Finished collection analysis: {collection_cnt} collections, {sprite_sheet_cnt} sprite sheets, {single_cnt} single objects, {scene_cnt} scenes.",
                "success" if failed_cnt == 0 else "warning",
            )
            self.analysis_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error("Fatal error in collection analysis worker: %s", err_trace)
            self.analysis_error.emit(f"Collection analysis worker failed: {str(e)}")


class OptimizationBatchWorker(QThread):
    """
    Background worker thread executing batch optimization (format conversion,
    scaling, transparent margin trimming) on copies without blocking the UI.
    """

    progress = Signal(int, int, str, int, int)  # current, total, filename, bytes_saved, remaining
    item_optimized = Signal(dict)  # single optimization telemetry dict
    log_message = Signal(str, str, str)  # action, message, level
    batch_finished = Signal(dict)  # summary dictionary
    batch_error = Signal(str)

    def __init__(
        self,
        assets: List[Dict[str, Any]],
        settings: Dict[str, Any],
        output_dir: Optional[Path] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.assets = assets
        self.settings = settings
        self.output_dir = output_dir

        self._is_cancelled = False
        self._is_paused = False
        self._mutex = QMutex()
        self._pause_cond = QWaitCondition()

    def cancel(self):
        self._is_cancelled = True
        self.resume()

    def pause(self):
        self._mutex.lock()
        self._is_paused = True
        self._mutex.unlock()

    def resume(self):
        self._mutex.lock()
        self._is_paused = False
        self._pause_cond.wakeAll()
        self._mutex.unlock()

    def is_paused(self) -> bool:
        return self._is_paused

    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def run(self):
        from core.asset_optimizer import asset_optimizer

        total = len(self.assets)
        total_saved_bytes = 0
        success_cnt = 0
        failed_cnt = 0

        self.log_message.emit("Optimization Started", f"Starting batch optimization for {total} assets...", "info")

        try:
            for idx, asset in enumerate(self.assets, 1):
                if self._is_cancelled:
                    break

                # Handle pause
                self._mutex.lock()
                while self._is_paused and not self._is_cancelled:
                    self._pause_cond.wait(self._mutex)
                self._mutex.unlock()

                if self._is_cancelled:
                    break

                asset_id = asset.get("id")
                src_path = asset.get("current_path") or asset.get("original_path")
                filename = asset.get("filename", Path(src_path).name)

                try:
                    telemetry = asset_optimizer.optimize_image(
                        input_path=src_path,
                        output_path=None,  # default to output_dir
                        format_target=self.settings.get("format", "PNG"),
                        quality=self.settings.get("quality", 90),
                        lossless=self.settings.get("lossless", True),
                        scale=self.settings.get("scale", 1.0),
                        target_width=self.settings.get("target_width"),
                        target_height=self.settings.get("target_height"),
                        lock_aspect_ratio=self.settings.get("lock_aspect_ratio", True),
                        trim_margins=self.settings.get("trim_margins", False),
                        margin_padding=self.settings.get("margin_padding", 0),
                    )

                    # Record in SQLite database
                    db.record_optimization_history(
                        source_asset_id=asset_id,
                        input_path=telemetry["source_path"],
                        output_path=telemetry["output_path"],
                        input_size=telemetry["input_size"],
                        output_size=telemetry["output_size"],
                        input_format=telemetry["input_format"],
                        output_format=telemetry["output_format"],
                        input_width=telemetry["input_dimensions"][0],
                        input_height=telemetry["input_dimensions"][1],
                        output_width=telemetry["output_dimensions"][0],
                        output_height=telemetry["output_dimensions"][1],
                        compression_settings=telemetry.get("compression_settings"),
                        transparency_status=telemetry.get("transparency_status", "opaque"),
                        optimization_status="success",
                    )

                    saved = telemetry.get("size_difference", 0)
                    total_saved_bytes += max(0, saved)
                    success_cnt += 1

                    remaining = total - idx
                    self.progress.emit(idx, total, filename, total_saved_bytes, remaining)
                    self.item_optimized.emit(telemetry)

                except Exception as item_err:
                    failed_cnt += 1
                    logger.error("Error optimizing asset #%s: %s", asset_id, item_err)
                    self.log_message.emit("Optimization Error", f"{filename}: {item_err}", "error")

            summary = {
                "total": total,
                "processed": success_cnt + failed_cnt,
                "success_count": success_cnt,
                "failed_count": failed_cnt,
                "total_saved_bytes": total_saved_bytes,
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "Optimization Finished",
                f"Optimized {success_cnt}/{total} assets ({total_saved_bytes / 1024:.1f} KB saved).",
                "success" if failed_cnt == 0 else "warning",
            )
            self.batch_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error("Fatal error in optimization batch worker: %s", err_trace)
            self.batch_error.emit(f"Optimization worker failed: {str(e)}")


class ValidationBatchWorker(QThread):
    """
    Background worker validating assets for corruption, dimensions, and duplicates.
    """

    progress = Signal(int, int, str)
    item_validated = Signal(dict)
    log_message = Signal(str, str, str)
    validation_finished = Signal(dict)
    validation_error = Signal(str)

    def __init__(
        self,
        assets: List[Dict[str, Any]],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.assets = assets
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        from core.asset_validator import asset_validator

        total = len(self.assets)
        passed_cnt = 0
        warn_cnt = 0
        fail_cnt = 0
        needs_review_cnt = 0

        self.log_message.emit("Validation Started", f"Validating quality of {total} assets...", "info")

        try:
            # Build fast lookup hash caches across batch
            asset_paths = [a.get("current_path") or a.get("original_path") for a in self.assets]
            metadata_map = {
                (a.get("current_path") or a.get("original_path")): a for a in self.assets
            }

            reports = asset_validator.validate_batch(asset_paths, metadata_map)

            for idx, rep in enumerate(reports, 1):
                if self._is_cancelled:
                    break

                # Save results in SQLite database
                asset_obj = metadata_map.get(rep.file_path, {})
                asset_id = asset_obj.get("id")

                issues_data = [
                    {"validation_type": i.check_type, "status": i.status, "message": i.message, "details": i.details}
                    for i in rep.issues
                ]
                db.save_asset_validation_results(asset_id, rep.file_path, issues_data)

                if rep.overall_status == "passed":
                    passed_cnt += 1
                elif rep.overall_status == "warning":
                    warn_cnt += 1
                elif rep.overall_status == "failed":
                    fail_cnt += 1
                else:
                    needs_review_cnt += 1

                self.progress.emit(idx, total, rep.filename)
                self.item_validated.emit(rep.to_dict())

            summary = {
                "total": total,
                "passed": passed_cnt,
                "warning": warn_cnt,
                "failed": fail_cnt,
                "needs_review": needs_review_cnt,
                "cancelled": self._is_cancelled,
            }

            self.log_message.emit(
                "Validation Completed",
                f"Validation finished: {passed_cnt} passed, {warn_cnt} warnings, {fail_cnt} failed, {needs_review_cnt} needs review.",
                "success" if fail_cnt == 0 else "warning",
            )
            self.validation_finished.emit(summary)

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error("Fatal error in validation batch worker: %s", err_trace)
            self.validation_error.emit(f"Validation worker failed: {str(e)}")






