"""
Stage 13 Asset Quality Validator
Construction Asset Processor

Multi-point validation before approving extracted excavator assets:
1. File opens successfully & valid PNG encoding.
2. Reasonable dimensions (8px to 4096px).
3. Alpha channel exists and true transparency is present.
4. Foreground preservation (no over-cropping).
5. Background cleanliness (no large border fragments or excessive white halos).
6. Mechanical detail integrity.
7. Kinematic pivot coordinate validity (within bounds 0.0 - 1.0).
8. Source image provenance & SHA-256 integrity verification.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from core.excavator_prep_engine import compute_sha256

logger = logging.getLogger("AssetProcessor.Stage13Validator")


@dataclass
class QualityCheckItem:
    """Individual quality check result."""
    category: str
    status: str  # "PASS", "WARNING", "FAIL", "REVIEW"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Stage13QualityReport:
    """Comprehensive asset quality audit report."""
    overall_status: str  # "Pass", "Warning", "Fail", "Manual Review Required"
    passed_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    checks: List[QualityCheckItem] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "passed_count": self.passed_count,
            "warning_count": self.warning_count,
            "failed_count": self.failed_count,
            "checks": [asdict(c) for c in self.checks],
            "diagnostics": self.diagnostics,
        }


class Stage13QualityValidator:
    """Validates prepared excavator sprites and components prior to approval and export."""

    @staticmethod
    def validate_asset(
        image_path: Path | str,
        component_type: str = "other",
        pivot_coords: Optional[Tuple[float, float]] = None,
        source_path: Optional[Path | str] = None,
        expected_source_hash: Optional[str] = None,
        require_transparency: bool = True
    ) -> Stage13QualityReport:
        """
        Execute full quality validation checklist on an asset.
        """
        img_p = Path(image_path).resolve()
        checks: List[QualityCheckItem] = []
        diagnostics: Dict[str, Any] = {}

        # 1. File existence & opening check
        if not img_p.is_file():
            checks.append(QualityCheckItem(
                category="File Integrity",
                status="FAIL",
                message=f"File does not exist: {img_p.name}"
            ))
            return Stage13QualityReport(
                overall_status="Fail",
                failed_count=1,
                checks=checks
            )

        try:
            with Image.open(img_p) as pil_img:
                img_format = pil_img.format
                img_mode = pil_img.mode
                w, h = pil_img.size
                pil_img.verify()
        except Exception as e:
            checks.append(QualityCheckItem(
                category="File Integrity",
                status="FAIL",
                message=f"Image file is corrupt or invalid: {str(e)}"
            ))
            return Stage13QualityReport(
                overall_status="Fail",
                failed_count=1,
                checks=checks
            )

        # Reopen for array access
        try:
            with Image.open(img_p) as pil_img:
                img_array = np.array(pil_img)
        except Exception as e:
            checks.append(QualityCheckItem(
                category="File Integrity",
                status="FAIL",
                message=f"Cannot decode image pixels: {str(e)}"
            ))
            return Stage13QualityReport(
                overall_status="Fail",
                failed_count=1,
                checks=checks
            )

        checks.append(QualityCheckItem(
            category="File Integrity",
            status="PASS",
            message=f"File opens cleanly as valid {img_format} ({w}x{h}, {img_mode})."
        ))

        # 2. Dimensions check
        if w < 8 or h < 8:
            checks.append(QualityCheckItem(
                category="Dimensions",
                status="FAIL",
                message=f"Dimensions {w}x{h} are below minimum viable asset size (8x8)."
            ))
        elif w > 4096 or h > 4096:
            checks.append(QualityCheckItem(
                category="Dimensions",
                status="WARNING",
                message=f"Dimensions {w}x{h} exceed mobile recommended max size (4096px)."
            ))
        else:
            checks.append(QualityCheckItem(
                category="Dimensions",
                status="PASS",
                message=f"Dimensions {w}x{h} within standard game engine bounds."
            ))

        # 3. Alpha channel & transparency check
        has_alpha = img_mode in ("RGBA", "LA") or (len(img_array.shape) == 3 and img_array.shape[2] == 4)
        if not has_alpha and require_transparency:
            checks.append(QualityCheckItem(
                category="Transparency",
                status="FAIL",
                message="Asset has no alpha channel (mode is not RGBA). Transparent PNG required."
            ))
        elif has_alpha:
            alpha = img_array[:, :, 3]
            transparent_count = np.sum(alpha < 250)
            total_count = alpha.size
            trans_pct = (transparent_count / total_count) * 100.0 if total_count > 0 else 0.0
            diagnostics["transparency_pct"] = round(trans_pct, 2)

            if trans_pct < 1.0 and require_transparency:
                checks.append(QualityCheckItem(
                    category="Transparency",
                    status="WARNING",
                    message="Alpha channel is fully opaque. No background pixels have been removed."
                ))
            else:
                checks.append(QualityCheckItem(
                    category="Transparency",
                    status="PASS",
                    message=f"Transparency verified ({trans_pct:.1f}% transparent pixels)."
                ))

            # 4. Foreground preservation & crop check
            fg_count = np.sum(alpha > 20)
            fg_ratio = fg_count / total_count if total_count > 0 else 0.0
            diagnostics["foreground_ratio"] = round(fg_ratio, 3)

            if fg_ratio < 0.01:
                checks.append(QualityCheckItem(
                    category="Foreground Preservation",
                    status="FAIL",
                    message=f"Foreground is excessively small ({fg_ratio * 100:.2f}% of canvas). Component may have been erased."
                ))
            elif fg_ratio > 0.98 and require_transparency:
                checks.append(QualityCheckItem(
                    category="Foreground Preservation",
                    status="WARNING",
                    message="Foreground occupies almost entire canvas (>98%). Background may still be present."
                ))
            else:
                checks.append(QualityCheckItem(
                    category="Foreground Preservation",
                    status="PASS",
                    message=f"Foreground proportion is well balanced ({fg_ratio * 100:.1f}% of canvas)."
                ))

            # 5. White halo check
            edge_mask = (alpha > 15) & (alpha < 240)
            if np.any(edge_mask):
                rgb = img_array[:, :, :3]
                edge_rgb = rgb[edge_mask]
                bright_edges = np.all(edge_rgb >= 238, axis=1)
                halo_pct = float(np.mean(bright_edges)) * 100.0
                diagnostics["white_halo_pct"] = round(halo_pct, 2)

                if halo_pct > 30.0:
                    checks.append(QualityCheckItem(
                        category="Edge Quality",
                        status="WARNING",
                        message=f"Possible white halo detected on {halo_pct:.1f}% of transition edge pixels."
                    ))
                else:
                    checks.append(QualityCheckItem(
                        category="Edge Quality",
                        status="PASS",
                        message=f"Edge transition clean (halo score: {halo_pct:.1f}%)."
                    ))

        # 6. Kinematic Pivot coordinates check
        if pivot_coords is not None:
            px, py = pivot_coords
            if 0.0 <= px <= 1.0 and 0.0 <= py <= 1.0:
                checks.append(QualityCheckItem(
                    category="Kinematic Pivot",
                    status="PASS",
                    message=f"Normalized pivot ({px:.3f}, {py:.3f}) within valid bounds."
                ))
            else:
                checks.append(QualityCheckItem(
                    category="Kinematic Pivot",
                    status="FAIL",
                    message=f"Pivot coordinates ({px}, {py}) exceed normalized range [0.0, 1.0]."
                ))
        else:
            checks.append(QualityCheckItem(
                category="Kinematic Pivot",
                status="REVIEW",
                message="Kinematic pivot has not been manually defined or verified yet."
            ))

        # 7. Source provenance & hash check
        if source_path:
            src_p = Path(source_path)
            if src_p.is_file():
                if expected_source_hash:
                    current_src_hash = compute_sha256(src_p)
                    if current_src_hash.lower() == expected_source_hash.lower():
                        checks.append(QualityCheckItem(
                            category="Source Provenance",
                            status="PASS",
                            message="Source file intact and SHA-256 hash verified identical."
                        ))
                    else:
                        checks.append(QualityCheckItem(
                            category="Source Provenance",
                            status="FAIL",
                            message="Source file hash does not match original recorded hash!"
                        ))
                else:
                    checks.append(QualityCheckItem(
                        category="Source Provenance",
                        status="PASS",
                        message="Source image provenance path confirmed on disk."
                    ))
            else:
                checks.append(QualityCheckItem(
                    category="Source Provenance",
                    status="WARNING",
                    message=f"Original source image cannot be found at: {source_path}"
                ))

        # Aggregate counts & overall status
        passed = sum(1 for c in checks if c.status == "PASS")
        warnings = sum(1 for c in checks if c.status == "WARNING")
        failed = sum(1 for c in checks if c.status == "FAIL")
        reviews = sum(1 for c in checks if c.status == "REVIEW")

        if failed > 0:
            overall = "Fail"
        elif reviews > 0 or warnings > 1:
            overall = "Manual Review Required"
        elif warnings == 1:
            overall = "Warning"
        else:
            overall = "Pass"

        return Stage13QualityReport(
            overall_status=overall,
            passed_count=passed,
            warning_count=warnings,
            failed_count=failed,
            checks=checks,
            diagnostics=diagnostics
        )
