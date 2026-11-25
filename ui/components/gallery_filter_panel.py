"""
Gallery Filter Panel Component
Provides extensive filtering controls (formats, transparency, dimensions,
review statuses, and collections) mapped directly to SQLite database queries.
"""

from typing import Any, Dict, List, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QScrollArea,
    QVBoxLayout, QWidget
)

from app.config import THEME_COLORS


class GalleryFilterPanel(QWidget):
    """Filter sidebar to refine visible assets by format, size, status, and collections."""

    filters_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filter_panel")
        self.setFixedWidth(230)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(12)

        # Header with Reset Button
        header_row = QHBoxLayout()
        lbl_title = QLabel("FILTERS")
        lbl_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.8px;
            color: {THEME_COLORS['accent_primary']};
        """)
        header_row.addWidget(lbl_title)
        header_row.addStretch()

        self.btn_reset = QPushButton("Reset All")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.setStyleSheet(f"""
            border: none;
            color: {THEME_COLORS['text_muted']};
            font-size: 11px;
            background: transparent;
            font-weight: 600;
        """)
        self.btn_reset.clicked.connect(self.reset_filters)
        header_row.addWidget(self.btn_reset)
        self.layout.addLayout(header_row)

        # 1. Collection Filter Group
        grp_coll = self._create_group("COLLECTION")
        coll_layout = QVBoxLayout(grp_coll)
        coll_layout.setContentsMargins(10, 8, 10, 8)
        coll_layout.setSpacing(6)

        self.chk_coll_excavator = QCheckBox("🚜 Excavator")
        self.chk_coll_excavator.setChecked(True)
        self.chk_coll_excavator.stateChanged.connect(self._emit_change)
        coll_layout.addWidget(self.chk_coll_excavator)

        self.chk_coll_other = QCheckBox("🧱 Other Images")
        self.chk_coll_other.setChecked(True)
        self.chk_coll_other.stateChanged.connect(self._emit_change)
        coll_layout.addWidget(self.chk_coll_other)

        self.layout.addWidget(grp_coll)

        # 2. Review Status Group
        grp_status = self._create_group("REVIEW STATUS")
        status_layout = QVBoxLayout(grp_status)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(6)

        self.chk_st_pending = QCheckBox("⏳ Pending")
        self.chk_st_pending.setChecked(True)
        self.chk_st_pending.stateChanged.connect(self._emit_change)
        status_layout.addWidget(self.chk_st_pending)

        self.chk_st_approved = QCheckBox("✓ Approved")
        self.chk_st_approved.setChecked(True)
        self.chk_st_approved.stateChanged.connect(self._emit_change)
        status_layout.addWidget(self.chk_st_approved)

        self.chk_st_rejected = QCheckBox("✕ Rejected")
        self.chk_st_rejected.setChecked(True)
        self.chk_st_rejected.stateChanged.connect(self._emit_change)
        status_layout.addWidget(self.chk_st_rejected)

        self.layout.addWidget(grp_status)

        # 3. File Format Group
        grp_format = self._create_group("FILE FORMAT")
        format_layout = QVBoxLayout(grp_format)
        format_layout.setContentsMargins(10, 8, 10, 8)
        format_layout.setSpacing(6)

        self.chk_fmt_png = QCheckBox("PNG")
        self.chk_fmt_png.setChecked(True)
        self.chk_fmt_png.stateChanged.connect(self._emit_change)
        format_layout.addWidget(self.chk_fmt_png)

        self.chk_fmt_jpg = QCheckBox("JPG / JPEG")
        self.chk_fmt_jpg.setChecked(True)
        self.chk_fmt_jpg.stateChanged.connect(self._emit_change)
        format_layout.addWidget(self.chk_fmt_jpg)

        self.chk_fmt_webp = QCheckBox("WebP")
        self.chk_fmt_webp.setChecked(True)
        self.chk_fmt_webp.stateChanged.connect(self._emit_change)
        format_layout.addWidget(self.chk_fmt_webp)

        self.layout.addWidget(grp_format)

        # 4. Transparency Group
        grp_trans = self._create_group("TRANSPARENCY")
        trans_layout = QVBoxLayout(grp_trans)
        trans_layout.setContentsMargins(10, 8, 10, 8)
        trans_layout.setSpacing(6)

        self.trans_group = QButtonGroup(self)
        self.rb_trans_all = QRadioButton("All (Any)")
        self.rb_trans_yes = QRadioButton("Transparent (Alpha)")
        self.rb_trans_no = QRadioButton("Opaque Only")
        self.rb_trans_all.setChecked(True)

        self.trans_group.addButton(self.rb_trans_all)
        self.trans_group.addButton(self.rb_trans_yes)
        self.trans_group.addButton(self.rb_trans_no)
        self.trans_group.buttonClicked.connect(self._emit_change)

        trans_layout.addWidget(self.rb_trans_all)
        trans_layout.addWidget(self.rb_trans_yes)
        trans_layout.addWidget(self.rb_trans_no)

        self.layout.addWidget(grp_trans)

        # 5. Dimensions Preset & Custom Range Group
        grp_dim = self._create_group("DIMENSIONS")
        dim_layout = QVBoxLayout(grp_dim)
        dim_layout.setContentsMargins(10, 8, 10, 8)
        dim_layout.setSpacing(8)

        self.cmb_dim_preset = QComboBox()
        self.cmb_dim_preset.addItem("All Sizes", None)
        self.cmb_dim_preset.addItem("Small (≤ 512px)", "small")
        self.cmb_dim_preset.addItem("Medium (512–1920px)", "medium")
        self.cmb_dim_preset.addItem("Large (> 1920px)", "large")
        self.cmb_dim_preset.currentIndexChanged.connect(self._emit_change)
        dim_layout.addWidget(self.cmb_dim_preset)

        lbl_custom = QLabel("Custom Bounds (W × H):")
        lbl_custom.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']}; margin-top: 4px;")
        dim_layout.addWidget(lbl_custom)

        custom_grid = QGridLayout()
        custom_grid.setSpacing(6)

        self.txt_min_w = QLineEdit()
        self.txt_min_w.setPlaceholderText("Min W")
        self.txt_min_w.returnPressed.connect(self._emit_change)
        custom_grid.addWidget(self.txt_min_w, 0, 0)

        self.txt_max_w = QLineEdit()
        self.txt_max_w.setPlaceholderText("Max W")
        self.txt_max_w.returnPressed.connect(self._emit_change)
        custom_grid.addWidget(self.txt_max_w, 0, 1)

        self.txt_min_h = QLineEdit()
        self.txt_min_h.setPlaceholderText("Min H")
        self.txt_min_h.returnPressed.connect(self._emit_change)
        custom_grid.addWidget(self.txt_min_h, 1, 0)

        self.txt_max_h = QLineEdit()
        self.txt_max_h.setPlaceholderText("Max H")
        self.txt_max_h.returnPressed.connect(self._emit_change)
        custom_grid.addWidget(self.txt_max_h, 1, 1)

        dim_layout.addLayout(custom_grid)

        self.btn_apply_dims = QPushButton("Apply Bounds")
        self.btn_apply_dims.setProperty("class", "btn_secondary")
        self.btn_apply_dims.setCursor(Qt.PointingHandCursor)
        self.btn_apply_dims.clicked.connect(self._emit_change)
        dim_layout.addWidget(self.btn_apply_dims)

        self.layout.addWidget(grp_dim)
        self.layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _create_group(self, title: str) -> QFrame:
        """Helper to create visually structured card-like filter section."""
        frame = QFrame()
        frame.setProperty("class", "card")
        frame.setStyleSheet(f"""
            QFrame.card {{
                background-color: {THEME_COLORS['bg_card']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(4)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: {THEME_COLORS['text_muted']};
            letter-spacing: 0.5px;
            padding-left: 4px;
        """)
        vbox.addWidget(lbl)
        return frame

    def get_filters(self) -> Dict[str, Any]:
        """Aggregate current UI state into filter dictionary."""
        # Collections
        collections = []
        if self.chk_coll_excavator.isChecked():
            collections.append("excavator")
        if self.chk_coll_other.isChecked():
            collections.append("other_images")

        # Statuses
        statuses = []
        if self.chk_st_pending.isChecked():
            statuses.append("pending")
        if self.chk_st_approved.isChecked():
            statuses.append("approved")
        if self.chk_st_rejected.isChecked():
            statuses.append("rejected")

        # Formats
        formats = []
        if self.chk_fmt_png.isChecked():
            formats.append("PNG")
        if self.chk_fmt_jpg.isChecked():
            formats.extend(["JPG", "JPEG"])
        if self.chk_fmt_webp.isChecked():
            formats.append("WEBP")

        # Transparency
        has_trans = None
        if self.rb_trans_yes.isChecked():
            has_trans = 1
        elif self.rb_trans_no.isChecked():
            has_trans = 0

        # Dimensions preset
        dim_preset = self.cmb_dim_preset.currentData()

        # Custom bounds
        def safe_int(txt: str) -> Optional[int]:
            try:
                v = int(txt.strip())
                return v if v > 0 else None
            except Exception:
                return None

        min_w = safe_int(self.txt_min_w.text())
        max_w = safe_int(self.txt_max_w.text())
        min_h = safe_int(self.txt_min_h.text())
        max_h = safe_int(self.txt_max_h.text())

        return {
            "collections": collections if len(collections) < 2 else None,
            "statuses": statuses if len(statuses) < 3 else None,
            "formats": formats if len(formats) < 4 else None,
            "has_transparency": has_trans,
            "dim_category": dim_preset,
            "min_width": min_w,
            "max_width": max_w,
            "min_height": min_h,
            "max_height": max_h,
        }

    def reset_filters(self):
        """Reset all filter controls to show all records."""
        self.blockSignals(True)
        self.chk_coll_excavator.setChecked(True)
        self.chk_coll_other.setChecked(True)
        self.chk_st_pending.setChecked(True)
        self.chk_st_approved.setChecked(True)
        self.chk_st_rejected.setChecked(True)
        self.chk_fmt_png.setChecked(True)
        self.chk_fmt_jpg.setChecked(True)
        self.chk_fmt_webp.setChecked(True)
        self.rb_trans_all.setChecked(True)
        self.cmb_dim_preset.setCurrentIndex(0)
        self.txt_min_w.clear()
        self.txt_max_w.clear()
        self.txt_min_h.clear()
        self.txt_max_h.clear()
        self.blockSignals(False)
        self._emit_change()

    def _emit_change(self):
        self.filters_changed.emit(self.get_filters())
