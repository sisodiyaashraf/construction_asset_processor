"""
Application Configuration and Constants
Construction Asset Processor
"""

from pathlib import Path

# Base Paths
ROOT_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = ROOT_DIR / "input"
INPUT_EXCAVATOR_DIR = INPUT_DIR / "excavator" / "original"
INPUT_OTHER_DIR = INPUT_DIR / "other_images" / "original"

OUTPUT_DIR = ROOT_DIR / "output"
OUTPUT_CLASSIFIED_DIR = OUTPUT_DIR / "classified"
OUTPUT_RENAMED_DIR = OUTPUT_DIR / "renamed"
OUTPUT_TRANSPARENT_DIR = OUTPUT_DIR / "transparent"
OUTPUT_SEPARATED_DIR = OUTPUT_DIR / "separated"
OUTPUT_OPTIMIZED_DIR = OUTPUT_DIR / "optimized"
OUTPUT_SPRITES_DIR = OUTPUT_DIR / "sprite_sheets"
OUTPUT_APPROVED_DIR = OUTPUT_DIR / "approved"

THUMBNAILS_DIR = ROOT_DIR / "thumbnails"
REPORTS_DIR = ROOT_DIR / "reports"
DATA_DIR = ROOT_DIR / "data"
DATABASE_PATH = DATA_DIR / "assets.db"

# Ensure all critical folders exist
for folder in [
    INPUT_DIR, INPUT_EXCAVATOR_DIR, INPUT_OTHER_DIR,
    OUTPUT_DIR, OUTPUT_CLASSIFIED_DIR, OUTPUT_RENAMED_DIR,
    OUTPUT_TRANSPARENT_DIR, OUTPUT_SEPARATED_DIR, OUTPUT_OPTIMIZED_DIR,
    OUTPUT_SPRITES_DIR, OUTPUT_APPROVED_DIR,
    THUMBNAILS_DIR, REPORTS_DIR, DATA_DIR
]:
    folder.mkdir(parents=True, exist_ok=True)

# Image Formats
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# Application Information
APP_NAME = "Construction Asset Processor"
APP_VERSION = "1.0.0 (Stage 1 Foundation)"
ORGANIZATION = "Construction Simulator Team"

# Dark Theme Design System (Premium Palette)
THEME_COLORS = {
    # Surfaces
    "bg_main": "#121417",          # Deepest charcoal base
    "bg_sidebar": "#181B1F",       # Left navigation sidebar
    "bg_card": "#1E2228",          # Elevated cards and containers
    "bg_card_hover": "#262C34",    # Hover state for cards
    "bg_input": "#15181C",         # Text input and table headers
    "bg_inspector": "#16191D",     # Right inspector background
    "bg_toolbar": "#1A1D22",       # Top toolbar
    
    # Borders & Dividers
    "border_subtle": "#2B313A",    # Subtle borders
    "border_medium": "#38414D",    # Active / input borders
    "border_focus": "#E5A93C",     # Industrial amber accent focus
    
    # Industrial Accent Colors (Construction Theme)
    "accent_primary": "#E5A93C",   # Construction Amber / Golden Yellow
    "accent_hover": "#F5BA4E",     # Lighter amber for button hover
    "accent_pressed": "#CC8F27",   # Darker amber for click
    "accent_secondary": "#3B82F6", # Blueprint Blue
    
    # Status Colors
    "status_success": "#10B981",   # Emerald Green
    "status_warning": "#F59E0B",   # Caution Amber
    "status_error": "#EF4444",     # Safety Red
    "status_info": "#06B6D4",      # Sky Cyan
    
    # Typography
    "text_primary": "#F3F4F6",     # Primary text (nearly white)
    "text_secondary": "#9CA3AF",   # Secondary metadata text (gray)
    "text_muted": "#6B7280",       # Muted / disabled text
    "text_inverse": "#111827",     # Dark text on bright accents
}

# Navigation Items (13 Sections)
NAVIGATION_ITEMS = [
    {"id": "workflow", "title": "Asset Workflow", "icon": "🚀", "badge": "Pipeline"},
    {"id": "import", "title": "Asset Import", "icon": "📥", "badge": "Active"},
    {"id": "gallery", "title": "Image Gallery", "icon": "🖼️", "badge": "Active"},
    {"id": "classification", "title": "AI Classification", "icon": "🏷️", "badge": "Active"},
    {"id": "renaming", "title": "Smart Renaming", "icon": "✏️", "badge": "Active"},
    {"id": "background", "title": "Background Removal", "icon": "✂️", "badge": "Active"},
    {"id": "text_detect", "title": "Text Detection", "icon": "🔍", "badge": "Active"},
    {"id": "watermark", "title": "Watermark Review", "icon": "🛡️", "badge": "Active"},
    {"id": "splitter", "title": "Collection Splitter", "icon": "🔀", "badge": "Active"},
    {"id": "spritesheet", "title": "Sprite Sheet Editor", "icon": "🎞️", "badge": "Active"},
    {"id": "optimization", "title": "Image Optimization", "icon": "⚡", "badge": "Active"},
    {"id": "integration", "title": "Game Integration", "icon": "🎮", "badge": "Active"},
    {"id": "sprite_prep", "title": "Sprite Preparation", "icon": "🚜", "badge": "Active"},
    {"id": "settings", "title": "Settings", "icon": "⚙️", "badge": ""},
]


def format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if num_bytes <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"
