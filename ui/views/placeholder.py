"""
Placeholder View for Subsequent Development Stages
Provides structured documentation, feature previews, and readiness status
for stages 3 through 13 of the Construction Asset Processor pipeline.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS


STAGE_DESCRIPTIONS = {
    "gallery": {
        "title": "Image Gallery & Grid Inspection",
        "stage": "Stage 2 Deliverable",
        "icon": "🖼️",
        "description": (
            "Interactive high-performance thumbnail gallery with dynamic filtering by collection, "
            "status, aspect ratio, and resolution. Features smooth zoom, batch selection, and "
            "instant visual inspection."
        ),
        "features": [
            "Responsive virtual grid layout with lazy thumbnail loading",
            "Real-time search and filter by filename, collection, and dimensions",
            "Full-screen image preview with pan and zoom capabilities",
            "Batch approval and categorization actions"
        ]
    },
    "classification": {
        "title": "AI Image Classification",
        "stage": "Stage 3 Planned",
        "icon": "🏷️",
        "description": (
            "Automated object classification and tagging tailored for construction simulator assets. "
            "Identifies excavators, dump trucks, cranes, tools, worker sprites, and site terrain."
        ),
        "features": [
            "Zero-shot and local vision model inference",
            "Category tagging: Excavator, Truck, Bulldozer, Terrain, Tool, Character",
            "Confidence scoring and manual verification pipeline",
            "Automated collection assignment"
        ]
    },
    "renaming": {
        "title": "Smart Asset Renaming",
        "stage": "Stage 4 Planned",
        "icon": "✏️",
        "description": (
            "Transforms generic Gemini-generated filenames (e.g. Gemini_Generated_Image_1pjuvw.png) "
            "into standardized, Flame-engine-ready asset filenames using structured schemas."
        ),
        "features": [
            "Rule-based renaming template: {category}_{model}_{angle}_{variant}.png",
            "Safe preview table showing Before / After renames before committing",
            "Copy-based renaming that never alters or overwrites original assets",
            "Flutter asset manifest generator"
        ]
    },
    "background": {
        "title": "Background Removal & Matting",
        "stage": "Stage 5 Planned",
        "icon": "✂️",
        "description": (
            "Cleans solid backgrounds, AI gradients, and sky backdrops to isolate vehicle bodies, "
            "booms, buckets, and tracks with transparent PNG alpha channels."
        ),
        "features": [
            "High-precision alpha matting with edge feathering",
            "Transparent output exported to output/transparent/",
            "Checkerboard transparency inspection viewport",
            "Mask editing and threshold adjustments"
        ]
    },
    "text_detect": {
        "title": "Text & Label Detection",
        "stage": "Stage 6 Planned",
        "icon": "🔍",
        "description": (
            "Locates AI hallucinated text, random letters, and watermarks on equipment hulls, "
            "flags them for removal, and isolates clean machine assets."
        ),
        "features": [
            "OCR bounding-box detection on vehicle bodies and borders",
            "Inpainting coordinates generation",
            "Side-by-side verification viewer"
        ]
    },
    "watermark": {
        "title": "Watermark & Border Review",
        "stage": "Stage 7 Planned",
        "icon": "🛡️",
        "description": (
            "Detects subtle watermarks, synthetic AI border artifacts, and perimeter crops, "
            "ensuring pristine asset quality for 2D game rendering."
        ),
        "features": [
            "Edge scanning and watermark artifact detection",
            "Auto-crop margin recommendations",
            "One-click defect flagging"
        ]
    },
    "splitter": {
        "title": "Collection & Object Splitter",
        "stage": "Stage 8 Planned",
        "icon": "🔀",
        "description": (
            "Detects images containing multiple vehicles or components, automatically segmenting "
            "them into individual asset files (e.g. boom, arm, bucket, cabin, tracks)."
        ),
        "features": [
            "Connected component and contour bounding segmentation",
            "Individual sprite extraction into output/separated/",
            "Pivot point definition for game joint articulation"
        ]
    },
    "spritesheet": {
        "title": "Sprite Sheet Editor",
        "stage": "Stage 9 Planned",
        "icon": "🎞️",
        "description": (
            "Packs separated animation frames (digging cycle, track rolling, hydraulic lifting) "
            "into optimized sprite sheets ready for Flame AnimationComponent."
        ),
        "features": [
            "MaxRects bin packing algorithm",
            "JSON metadata atlas export for Flame / Flutter",
            "Live animation playback preview at configurable FPS"
        ]
    },
    "optimization": {
        "title": "Image Optimization & Compression",
        "stage": "Stage 10 Planned",
        "icon": "⚡",
        "description": (
            "Optimizes asset file sizes using PNG quantization, WebP encoding, and resolution scaling "
            "without visible quality degradation for mobile performance."
        ),
        "features": [
            "PNG quant / WebP compression benchmarks",
            "Mipmap and multi-resolution generation (@1x, @2x, @3x)",
            "Memory footprint estimation for Flutter Flame runtime"
        ]
    },
    "export": {
        "title": "Export Manager & Flutter Packaging",
        "stage": "Stage 11 Planned",
        "icon": "📦",
        "description": (
            "Packages approved assets directly into your Flutter project's assets/images folder, "
            "generating pubspec.yaml asset entries and Dart asset constants."
        ),
        "features": [
            "Direct export to Flutter Flame project folder",
            "Automatic pubspec.yaml assets entry generation",
            "Dart code generation for typed asset paths (e.g. Assets.excavatorArm)"
        ]
    },
    "settings": {
        "title": "Application Settings & Preferences",
        "stage": "Settings",
        "icon": "⚙️",
        "description": (
            "Configure default workspace paths, thumbnail cache policies, concurrency limits, "
            "and theme preferences."
        ),
        "features": [
            "Default input and output directory paths",
            "Background thread pool size configuration",
            "Thumbnail cache purging and size limits",
            "Database maintenance and vacuuming"
        ]
    }
}


class StagePlaceholderView(QWidget):
    """Clean, informatively styled placeholder view for future pipeline stages."""

    def __init__(self, stage_id: str, parent=None):
        super().__init__(parent)
        info = STAGE_DESCRIPTIONS.get(stage_id, {
            "title": stage_id.replace("_", " ").title(),
            "stage": "Planned Stage",
            "icon": "🛠️",
            "description": "This feature module is scheduled for development in upcoming stages.",
            "features": ["Stage 1 foundation established."]
        })

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setProperty("class", "card")
        card.setMaximumWidth(700)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(16)

        # Stage Badge
        badge = QLabel(f"  {info['stage']}  ")
        badge.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
            background-color: rgba(229, 169, 60, 0.15);
            border-radius: 4px;
            padding: 4px 8px;
        """)
        badge.setFixedHeight(24)
        card_layout.addWidget(badge)

        # Title & Icon
        title_row = QHBoxLayout()
        icon = QLabel(info["icon"])
        icon.setStyleSheet("font-size: 28px;")
        title_row.addWidget(icon)

        title = QLabel(info["title"])
        title.setStyleSheet(f"""
            font-size: 22px;
            font-weight: 700;
            color: {THEME_COLORS['text_primary']};
        """)
        title_row.addWidget(title, stretch=1)
        card_layout.addLayout(title_row)

        # Description
        desc = QLabel(info["description"])
        desc.setStyleSheet(f"font-size: 14px; color: {THEME_COLORS['text_secondary']}; line-height: 1.5;")
        desc.setWordWrap(True)
        card_layout.addWidget(desc)

        # Features List
        features_header = QLabel("PLANNED CAPABILITIES:")
        features_header.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            color: {THEME_COLORS['accent_primary']};
            letter-spacing: 0.5px;
            margin-top: 10px;
        """)
        card_layout.addWidget(features_header)

        for feat in info["features"]:
            feat_lbl = QLabel(f"•  {feat}")
            feat_lbl.setStyleSheet(f"font-size: 13px; color: {THEME_COLORS['text_primary']};")
            feat_lbl.setWordWrap(True)
            card_layout.addWidget(feat_lbl)

        card_layout.addSpacing(10)
        status_note = QLabel("✓ Stage 1 Foundation Active. Awaiting user approval to commence next stage.")
        status_note.setStyleSheet(f"font-size: 12px; color: {THEME_COLORS['status_success']}; font-weight: 500;")
        card_layout.addWidget(status_note)

        main_layout.addWidget(card)
