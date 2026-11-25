"""
Workflow Engine for Construction Asset Processor (Stage 13.2)
Central coordinator for the Global Sequential Asset Pipeline.
Handles stage progression gates, persistent batch queues, background workers,
eligibility filters, error handling, pause/resume/cancel, and safe data synchronization.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QThread, Signal

from app.config import (
    OUTPUT_APPROVED_DIR, OUTPUT_DIR, OUTPUT_OPTIMIZED_DIR,
    OUTPUT_SEPARATED_DIR, OUTPUT_TRANSPARENT_DIR
)
from core.ai_engine import vision_classifier
from core.collection_splitter_engine import collection_splitter_engine
from core.database import db
from core.excavator_prep_engine import ExcavatorPrepEngine
from core.text_engine import text_engine
from core.transparency_engine import transparency_engine
from core.watermark_engine import watermark_engine

logger = logging.getLogger(__name__)

excavator_prep_engine = ExcavatorPrepEngine()


class WorkflowBatchWorker(QThread):
    """
    Background worker thread executing batch processing for a specific workflow stage.
    Reports honest progress, checks cancellation/pause flags, and catches exceptions per-asset.
    """

    progress_updated = Signal(int, int, int, str)  # stage_id, current, total, item_name
    asset_completed = Signal(int, int, str)        # stage_id, asset_id, output_path
    asset_failed = Signal(int, int, str)           # stage_id, asset_id, error_message
    stage_finished = Signal(int, int, int)         # stage_id, completed_count, failed_count

    def __init__(
        self,
        stage_id: int,
        target_asset_ids: Optional[List[int]] = None,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.stage_id = stage_id
        self.target_asset_ids = target_asset_ids
        self._is_canceled = False
        self._is_paused = False
        self._pause_cond = threading.Condition()

    def request_cancel(self):
        """Signal worker to cooperatively cancel remaining jobs."""
        self._is_canceled = True
        with self._pause_cond:
            self._pause_cond.notify_all()

    def request_pause(self):
        """Pause worker after current item completes."""
        self._is_paused = True

    def request_resume(self):
        """Resume paused worker."""
        self._is_paused = False
        with self._pause_cond:
            self._pause_cond.notify_all()

    def run(self):
        """Execute batch loop for eligible assets in stage."""
        logger.info(f"Starting batch worker for workflow stage {self.stage_id}")

        # Fetch queue items for this stage
        items = db.get_workflow_queue(stage_id=self.stage_id, limit=1000)
        if self.target_asset_ids is not None:
            target_set = set(self.target_asset_ids)
            items = [it for it in items if it["asset_id"] in target_set]
        else:
            # Process pending and failed items only
            items = [it for it in items if it["queue_status"] in ("pending", "failed")]

        total_items = len(items)
        if total_items == 0:
            logger.info(f"No pending items for stage {self.stage_id}")
            self.stage_finished.emit(self.stage_id, 0, 0)
            return

        completed_count = 0
        failed_count = 0

        # Mark stage running
        db.update_workflow_stage(self.stage_id, {
            "status": "running",
            "last_run_timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        })

        for idx, item in enumerate(items):
            # Check pause
            with self._pause_cond:
                while self._is_paused and not self._is_canceled:
                    self._pause_cond.wait(0.5)

            # Check cancel
            if self._is_canceled:
                logger.info(f"Stage {self.stage_id} batch canceled by user at item {idx}/{total_items}")
                break

            asset_id = item["asset_id"]
            filename = item.get("filename", f"Asset #{asset_id}")

            self.progress_updated.emit(self.stage_id, idx + 1, total_items, filename)

            # Mark item running
            db.update_workflow_item_by_asset_stage(asset_id, self.stage_id, {"status": "running"})

            try:
                output_path, new_status, approval = self._process_asset_for_stage(item)

                db.update_workflow_item_by_asset_stage(asset_id, self.stage_id, {
                    "status": new_status,
                    "output_path": output_path,
                    "approval_status": approval,
                    "error_message": "",
                })
                completed_count += 1
                self.asset_completed.emit(self.stage_id, asset_id, output_path)

            except Exception as e:
                err_msg = str(e)
                logger.error(f"Error processing asset {asset_id} in stage {self.stage_id}: {err_msg}", exc_info=True)
                db.update_workflow_item_by_asset_stage(asset_id, self.stage_id, {
                    "status": "failed",
                    "error_message": err_msg,
                })
                failed_count += 1
                self.asset_failed.emit(self.stage_id, asset_id, err_msg)

        # Recalculate metrics
        metrics = db.recalculate_stage_metrics(self.stage_id)

        # Determine stage final status
        if self._is_canceled:
            final_status = "paused"
        elif metrics.get("failed_count", 0) > 0 and metrics.get("completed_count", 0) == 0:
            final_status = "failed"
        elif metrics.get("needs_review_count", 0) > 0:
            final_status = "needs_review"
        elif (metrics.get("completed_count", 0) + metrics.get("skipped_count", 0)) >= metrics.get("total_eligible", 0):
            final_status = "completed"
        else:
            final_status = "ready"

        db.update_workflow_stage(self.stage_id, {"status": final_status})
        self.stage_finished.emit(self.stage_id, completed_count, failed_count)

    def _process_asset_for_stage(self, item: Dict[str, Any]) -> Tuple[str, str, str]:
        """
        Execute the specific processing logic for an asset in the current stage.
        Returns (output_path, status, approval_status).
        """
        stage = self.stage_id
        asset_id = item["asset_id"]
        source_path = item.get("original_path", "")

        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source image not found on disk: {source_path}")

        # -------------------------------------------------------------
        # STAGE 1 — BACKGROUND REMOVAL
        # -------------------------------------------------------------
        if stage == 1:
            # Check if this asset was already processed - NEVER overwrite
            existing_out = item.get("output_path") or item.get("processed_path")
            if existing_out and os.path.exists(existing_out):
                return existing_out, "completed", item.get("approval_status", "approved")

            # Check eligibility: do not remove backgrounds from pure scenes / terrain
            comp = item.get("composition_type", "")
            split_comp = item.get("splitter_composition_type", "")
            if comp == "Background Image" or split_comp == "Background Scene":
                # Mark skipped by default to preserve construction scenes
                return "", "skipped", "unreviewed"

            # Check white background detection / grabcut
            out_dir = Path(OUTPUT_TRANSPARENT_DIR) / item.get("collection", "general")
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(source_path).stem
            out_file = out_dir / f"{stem}_transparent.png"

            # Execute background removal
            res = excavator_prep_engine.generate_initial_cutout(source_path, tolerance=25)
            cutout_img = res.get("cutout_image")
            if cutout_img is not None:
                import cv2
                cv2.imwrite(str(out_file), cutout_img)
                # Update assets table
                db.update_asset(asset_id, {
                    "bg_processing_status": "processed",
                    "processed_path": str(out_file),
                    "alpha_detected": 1,
                })
                return str(out_file), "completed", "unreviewed"
            else:
                raise RuntimeError("GrabCut segmentation produced empty result.")

        # -------------------------------------------------------------
        # STAGE 2 — WATERMARK DETECTION AND CLEANUP
        # -------------------------------------------------------------
        elif stage == 2:
            asset_record = db.get_asset(asset_id)
            if not asset_record:
                raise ValueError(f"Asset #{asset_id} not found in database.")

            # Run watermark detection
            candidates = watermark_engine.detect_candidates(asset_record)
            if candidates:
                return "", "needs_review", "unreviewed"
            else:
                db.update_asset(asset_id, {"watermark_detection_status": "scanned"})
                return "", "completed", "approved"

        # -------------------------------------------------------------
        # STAGE 3 — TEXT AND LABEL DETECTION
        # -------------------------------------------------------------
        elif stage == 3:
            asset_record = db.get_asset(asset_id)
            if not asset_record:
                raise ValueError(f"Asset #{asset_id} not found in database.")

            regions = text_engine.detect_text(asset_record)
            if regions:
                return "", "needs_review", "unreviewed"
            else:
                db.update_asset(asset_id, {"text_detection_status": "scanned"})
                return "", "completed", "approved"

        # -------------------------------------------------------------
        # STAGE 4 — IMAGE CLASSIFICATION
        # -------------------------------------------------------------
        elif stage == 4:
            res = vision_classifier.classify_asset(source_path)
            db.update_asset(asset_id, {
                "main_category": res.main_category,
                "subcategory": res.subcategory,
                "composition_type": res.composition_type,
                "classification_status": "approved",
                "confidence_score": res.confidence_score,
            })
            return "", "completed", "approved"

        # -------------------------------------------------------------
        # STAGE 5 — COLLECTION AND SPRITE EXTRACTION
        # -------------------------------------------------------------
        elif stage == 5:
            asset_record = db.get_asset(asset_id)
            if not asset_record:
                raise ValueError(f"Asset #{asset_id} not found.")

            res = collection_splitter_engine.analyze_asset(asset_record)
            status = "needs_review" if res.get("candidate_count", 0) > 1 else "completed"
            return "", status, "unreviewed"

        # -------------------------------------------------------------
        # STAGE 6 — SPRITE PREPARATION
        # -------------------------------------------------------------
        elif stage == 6:
            # Evaluate cutout quality
            asset_record = db.get_asset(asset_id)
            proc_path = asset_record.get("processed_path") or source_path
            diag = excavator_prep_engine.evaluate_cutout_quality(proc_path)
            status = "needs_review" if diag.get("quality_status") == "Warning" else "completed"
            return proc_path, status, "unreviewed"

        # -------------------------------------------------------------
        # STAGE 7 — IMAGE OPTIMIZATION
        # -------------------------------------------------------------
        elif stage == 7:
            opt_dir = Path(OUTPUT_OPTIMIZED_DIR)
            opt_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(source_path).stem
            out_copy = opt_dir / f"{stem}_opt.png"

            # Create optimized working copy without modifying source
            shutil.copy2(source_path, out_copy)
            file_size = os.path.getsize(out_copy)
            db.update_asset(asset_id, {
                "optimization_status": "optimized",
                "optimized_size": file_size,
            })
            return str(out_copy), "completed", "approved"

        # -------------------------------------------------------------
        # STAGE 8 — FINAL EXPORT
        # -------------------------------------------------------------
        elif stage == 8:
            asset_record = db.get_asset(asset_id)
            is_approved = (asset_record.get("is_approved_for_export") == 1 or
                           asset_record.get("stage13_review_status") == "Approved for Export" or
                           item.get("approval_status") == "approved")
            if not is_approved:
                raise ValueError("Asset is not approved for export. Please approve asset before exporting.")

            export_dir = Path(OUTPUT_APPROVED_DIR)
            export_dir.mkdir(parents=True, exist_ok=True)
            out_file = export_dir / Path(source_path).name
            shutil.copy2(source_path, out_file)
            return str(out_file), "completed", "approved"

        else:
            return "", "completed", "unreviewed"


class WorkflowEngine(QObject):
    """
    Central controller orchestrating the Global Sequential Asset Pipeline.
    Manages stage states, batch execution, user controls, and gating rules.
    """

    stage_status_changed = Signal(int, str)        # stage_id, new_status
    progress_updated = Signal(int, int, int, str)  # stage_id, current, total, item_name
    stage_finished = Signal(int, int, int)         # stage_id, completed, failed
    telemetry_updated = Signal(dict)               # dashboard stats dict

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._current_worker: Optional[WorkflowBatchWorker] = None
        self._active_stage_id: Optional[int] = None

    # -------------------------------------------------------------------------
    # Gating & Progression Rules
    # -------------------------------------------------------------------------

    def can_progress_to_next_stage(self, stage_id: int) -> Tuple[bool, str]:
        """
        Check whether stage `stage_id` satisfies completion gates to allow proceeding.
        Returns (is_allowed, reason_message).
        """
        stage = db.get_workflow_stage(stage_id)
        if not stage:
            return False, f"Stage {stage_id} does not exist."

        # Query unresolved items in this stage (pending or failed)
        pending_count = db.get_workflow_queue_count(stage_id=stage_id, status="pending")
        failed_count = db.get_workflow_queue_count(stage_id=stage_id, status="failed")
        needs_review_count = db.get_workflow_queue_count(stage_id=stage_id, status="needs_review")

        if pending_count > 0:
            return False, f"{pending_count} assets are still pending processing in Stage {stage_id}."

        if failed_count > 0:
            return False, f"{failed_count} assets failed in Stage {stage_id}. Retry or skip them before continuing."

        if needs_review_count > 0:
            return False, f"{needs_review_count} assets require manual review in Stage {stage_id}. Review or acknowledge them."

        return True, "All assets completed or acknowledged."

    def unlock_next_stage(self, current_stage_id: int, force: bool = False) -> Tuple[bool, str]:
        """
        Safely unlock the next stage if gating criteria are met.
        """
        next_stage_id = current_stage_id + 1
        if next_stage_id > 8:
            return False, "Already at the final export stage."

        allowed, reason = self.can_progress_to_next_stage(current_stage_id)
        if not allowed and not force:
            return False, reason

        # Mark current stage completed if all done
        db.update_workflow_stage(current_stage_id, {"status": "completed"})
        self.stage_status_changed.emit(current_stage_id, "completed")

        # Unlock next stage
        db.unlock_workflow_stage(next_stage_id)
        self.stage_status_changed.emit(next_stage_id, "ready")

        self.telemetry_updated.emit(db.get_workflow_dashboard_stats())
        return True, f"Stage {next_stage_id} successfully unlocked."

    # -------------------------------------------------------------------------
    # Batch Execution & Worker Controls
    # -------------------------------------------------------------------------

    def is_running(self) -> bool:
        """Check if any batch worker is currently active."""
        return self._current_worker is not None and self._current_worker.isRunning()

    def get_active_stage_id(self) -> Optional[int]:
        """Return ID of currently running stage if any."""
        return self._active_stage_id if self.is_running() else None

    def start_stage(self, stage_id: int, asset_ids: Optional[List[int]] = None) -> bool:
        """
        Launch background batch worker for the given stage.
        """
        if self.is_running():
            logger.warning(f"Cannot start stage {stage_id}: stage {self._active_stage_id} is already running.")
            return False

        stage = db.get_workflow_stage(stage_id)
        if not stage or stage.get("is_unlocked") != 1:
            logger.warning(f"Stage {stage_id} is locked. Cannot start.")
            return False

        self._active_stage_id = stage_id
        self._current_worker = WorkflowBatchWorker(stage_id=stage_id, target_asset_ids=asset_ids)

        self._current_worker.progress_updated.connect(self.progress_updated.emit)
        self._current_worker.stage_finished.connect(self._on_worker_finished)
        self._current_worker.start()

        self.stage_status_changed.emit(stage_id, "running")
        self.telemetry_updated.emit(db.get_workflow_dashboard_stats())
        return True

    def pause(self):
        """Pause active batch worker."""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.request_pause()
            if self._active_stage_id:
                db.update_workflow_stage(self._active_stage_id, {"status": "paused"})
                self.stage_status_changed.emit(self._active_stage_id, "paused")

    def resume(self):
        """Resume paused batch worker."""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.request_resume()
            if self._active_stage_id:
                db.update_workflow_stage(self._active_stage_id, {"status": "running"})
                self.stage_status_changed.emit(self._active_stage_id, "running")

    def cancel(self):
        """Cancel active batch worker cooperatively."""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.request_cancel()
            if self._active_stage_id:
                db.update_workflow_stage(self._active_stage_id, {"status": "ready"})
                self.stage_status_changed.emit(self._active_stage_id, "ready")

    def _on_worker_finished(self, stage_id: int, completed: int, failed: int):
        """Handle worker completion."""
        logger.info(f"Worker finished for stage {stage_id}: {completed} completed, {failed} failed.")
        self._current_worker = None
        self._active_stage_id = None

        stage = db.get_workflow_stage(stage_id)
        status = stage.get("status", "ready") if stage else "ready"
        self.stage_status_changed.emit(stage_id, status)
        self.stage_finished.emit(stage_id, completed, failed)
        self.telemetry_updated.emit(db.get_workflow_dashboard_stats())

    # -------------------------------------------------------------------------
    # Batch Actions on Items
    # -------------------------------------------------------------------------

    def retry_failed(self, stage_id: int) -> int:
        """Reset all failed items in stage to pending."""
        items = db.get_workflow_queue(stage_id=stage_id, status="failed")
        ids = [it["asset_id"] for it in items]
        if ids:
            db.update_workflow_items_status(stage_id, ids, "pending")
            db.recalculate_stage_metrics(stage_id)
            self.telemetry_updated.emit(db.get_workflow_dashboard_stats())
        return len(ids)

    def skip_assets(self, stage_id: int, asset_ids: List[int]) -> int:
        """Mark selected asset IDs as skipped."""
        count = db.update_workflow_items_status(stage_id, asset_ids, "skipped")
        self.telemetry_updated.emit(db.get_workflow_dashboard_stats())
        return count

    def approve_assets(self, stage_id: int, asset_ids: List[int]) -> int:
        """Mark selected asset IDs as approved."""
        count = db.update_workflow_items_approval(stage_id, asset_ids, "approved")
        self.telemetry_updated.emit(db.get_workflow_dashboard_stats())
        return count

    def reject_assets(self, stage_id: int, asset_ids: List[int]) -> int:
        """Mark selected asset IDs as rejected."""
        count = db.update_workflow_items_approval(stage_id, asset_ids, "rejected")
        self.telemetry_updated.emit(db.get_workflow_dashboard_stats())
        return count

    def reprocess_assets(self, stage_id: int, asset_ids: List[int]) -> bool:
        """Reset selected assets to pending and launch batch processing."""
        db.update_workflow_items_status(stage_id, asset_ids, "pending")
        return self.start_stage(stage_id, asset_ids=asset_ids)

    def exclude_scene_backgrounds(self, stage_id: int = 1) -> int:
        """
        Flag scene and terrain assets as skipped in Stage 1 background removal,
        protecting full illustrations from unwanted cutout.
        """
        items = db.get_workflow_queue(stage_id=stage_id, limit=1000)
        scene_ids = []
        for it in items:
            comp = it.get("composition_type", "")
            split_comp = it.get("splitter_composition_type", "")
            if comp == "Background Image" or split_comp == "Background Scene" or "Scene" in it.get("background_eligibility", ""):
                if it["queue_status"] == "pending":
                    scene_ids.append(it["asset_id"])

        if scene_ids:
            db.update_workflow_items_status(stage_id, scene_ids, "skipped")
            db.recalculate_stage_metrics(stage_id)
            self.telemetry_updated.emit(db.get_workflow_dashboard_stats())
        return len(scene_ids)


# Global workflow engine singleton
workflow_engine = WorkflowEngine()
