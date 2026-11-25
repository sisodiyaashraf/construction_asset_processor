"""
Gallery Top Toolbar Component
Provides search, collection quick-switch, sort options, view toggle,
selected asset counter, and bulk action triggers.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPushButton, QWidget
)

from app.config import THEME_COLORS


class GalleryToolbar(QWidget):
    """Header toolbar for the Asset Gallery with search, sort, and bulk actions."""

    search_changed = Signal(str)
    collection_changed = Signal(str)  # all, excavator, other_images
    sort_changed = Signal(str)
    size_changed = Signal(str)  # "small", "medium", "large"
    view_toggled = Signal(str)  # "grid" or "list"
    refresh_clicked = Signal()
    bulk_action_triggered = Signal(str)  # approve, pending, reject, export_csv, open_explorer, select_all, select_eligible, deselect_all

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("gallery_toolbar")
        self.setFixedHeight(54)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # 1. Gallery Title & Total Count Pill
        title_box = QHBoxLayout()
        title_box.setSpacing(6)

        title = QLabel("Asset Gallery")
        title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 700;
            color: {THEME_COLORS['text_primary']};
        """)
        title_box.addWidget(title)

        self.lbl_count = QLabel("0 images")
        self.lbl_count.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 600;
            color: {THEME_COLORS['accent_primary']};
            background-color: rgba(229, 169, 60, 0.12);
            padding: 2px 8px;
            border-radius: 10px;
        """)
        title_box.addWidget(self.lbl_count)
        layout.addLayout(title_box)

        # 2. Search Field
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Search filename...")
        self.txt_search.setFixedWidth(200)
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self.txt_search)

        # 3. Collection Selector Dropdown
        self.cmb_collection = QComboBox()
        self.cmb_collection.setFixedWidth(140)
        self.cmb_collection.addItem("All Collections", "all")
        self.cmb_collection.addItem("🚜 Excavator", "excavator")
        self.cmb_collection.addItem("🧱 Other Images", "other_images")
        self.cmb_collection.currentIndexChanged.connect(
            lambda: self.collection_changed.emit(self.cmb_collection.currentData())
        )
        layout.addWidget(self.cmb_collection)

        # 4. Sort Options Dropdown
        self.cmb_sort = QComboBox()
        self.cmb_sort.setFixedWidth(160)
        self.cmb_sort.addItem("Filename (A → Z)", "filename_asc")
        self.cmb_sort.addItem("Filename (Z → A)", "filename_desc")
        self.cmb_sort.addItem("Largest File First", "size_desc")
        self.cmb_sort.addItem("Smallest File First", "size_asc")
        self.cmb_sort.addItem("Newest Indexed First", "newest")
        self.cmb_sort.addItem("Oldest Indexed First", "oldest")
        self.cmb_sort.addItem("Width (Largest First)", "width_desc")
        self.cmb_sort.addItem("Height (Largest First)", "height_desc")
        self.cmb_sort.currentIndexChanged.connect(
            lambda: self.sort_changed.emit(self.cmb_sort.currentData())
        )
        layout.addWidget(self.cmb_sort)

        # 4b. Thumbnail Size Dropdown
        self.cmb_thumb_size = QComboBox()
        self.cmb_thumb_size.setFixedWidth(100)
        self.cmb_thumb_size.addItem("🔍 Med", "medium")
        self.cmb_thumb_size.addItem("🔍 Small", "small")
        self.cmb_thumb_size.addItem("🔍 Large", "large")
        self.cmb_thumb_size.currentIndexChanged.connect(
            lambda: self.size_changed.emit(self.cmb_thumb_size.currentData())
        )
        layout.addWidget(self.cmb_thumb_size)

        layout.addStretch()

        # 5. Selection Count Badge
        self.lbl_selected = QLabel("0 selected")
        self.lbl_selected.setStyleSheet(f"""
            font-size: 11px;
            color: {THEME_COLORS['text_muted']};
            font-weight: 500;
        """)
        layout.addWidget(self.lbl_selected)

        # 6. Bulk Actions Dropdown Menu Button
        self.btn_bulk = QPushButton("⚡ Actions ▾")
        self.btn_bulk.setProperty("class", "btn_secondary")
        self.btn_bulk.setCursor(Qt.PointingHandCursor)

        bulk_menu = QMenu(self)
        bulk_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {THEME_COLORS['bg_card']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_medium']};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 16px;
            }}
            QMenu::item:selected {{
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
            }}
        """)

        act_app = bulk_menu.addAction("✓ Approve Selected")
        act_app.triggered.connect(lambda: self.bulk_action_triggered.emit("approve"))

        act_pend = bulk_menu.addAction("⏳ Mark Selected as Pending")
        act_pend.triggered.connect(lambda: self.bulk_action_triggered.emit("pending"))

        act_rej = bulk_menu.addAction("✕ Reject Selected")
        act_rej.triggered.connect(lambda: self.bulk_action_triggered.emit("reject"))

        bulk_menu.addSeparator()

        act_csv = bulk_menu.addAction("📊 Export Selected to CSV")
        act_csv.triggered.connect(lambda: self.bulk_action_triggered.emit("export_csv"))

        act_exp = bulk_menu.addAction("📁 Open Selected in Explorer")
        act_exp.triggered.connect(lambda: self.bulk_action_triggered.emit("open_explorer"))

        bulk_menu.addSeparator()

        act_sel_all = bulk_menu.addAction("Select All Visible")
        act_sel_all.triggered.connect(lambda: self.bulk_action_triggered.emit("select_all"))

        act_sel_elig = bulk_menu.addAction("Select All Eligible")
        act_sel_elig.triggered.connect(lambda: self.bulk_action_triggered.emit("select_eligible"))

        act_desel = bulk_menu.addAction("Deselect All")
        act_desel.triggered.connect(lambda: self.bulk_action_triggered.emit("deselect_all"))

        self.btn_bulk.setMenu(bulk_menu)
        layout.addWidget(self.btn_bulk)

        # 7. View Mode Toggle (Grid vs List)
        view_frame = QFrame()
        view_frame.setProperty("class", "card")
        view_frame.setStyleSheet(f"""
            QFrame.card {{
                background-color: {THEME_COLORS['bg_input']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 6px;
                padding: 1px;
            }}
        """)
        view_box = QHBoxLayout(view_frame)
        view_box.setContentsMargins(2, 2, 2, 2)
        view_box.setSpacing(2)

        self.btn_grid = QPushButton("▦ Grid")
        self.btn_grid.setCheckable(True)
        self.btn_grid.setChecked(True)
        self.btn_grid.setCursor(Qt.PointingHandCursor)
        self.btn_grid.setStyleSheet(self._view_btn_style(True))

        self.btn_list = QPushButton("☰ List")
        self.btn_list.setCheckable(True)
        self.btn_list.setCursor(Qt.PointingHandCursor)
        self.btn_list.setStyleSheet(self._view_btn_style(False))

        self.btn_grid.clicked.connect(self._on_grid_selected)
        self.btn_list.clicked.connect(self._on_list_selected)

        view_box.addWidget(self.btn_grid)
        view_box.addWidget(self.btn_list)
        layout.addWidget(view_frame)

        # 8. Refresh Button
        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setProperty("class", "btn_secondary")
        self.btn_refresh.setFixedSize(32, 32)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip("Reload Gallery")
        self.btn_refresh.clicked.connect(self.refresh_clicked.emit)
        layout.addWidget(self.btn_refresh)

    def _view_btn_style(self, active: bool) -> str:
        if active:
            return f"""
                background-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['text_inverse']};
                font-weight: 700;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
            """
        else:
            return f"""
                background-color: transparent;
                color: {THEME_COLORS['text_secondary']};
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
            """

    def _on_grid_selected(self):
        self.btn_grid.setChecked(True)
        self.btn_list.setChecked(False)
        self.btn_grid.setStyleSheet(self._view_btn_style(True))
        self.btn_list.setStyleSheet(self._view_btn_style(False))
        self.view_toggled.emit("grid")

    def _on_list_selected(self):
        self.btn_grid.setChecked(False)
        self.btn_list.setChecked(True)
        self.btn_grid.setStyleSheet(self._view_btn_style(False))
        self.btn_list.setStyleSheet(self._view_btn_style(True))
        self.view_toggled.emit("list")

    def update_counts(self, total_count: int, selected_count: int):
        """Update top count and selection indicator."""
        self.lbl_count.setText(f"{total_count} images")
        self.lbl_selected.setText(f"{selected_count} selected")
        if selected_count > 0:
            self.lbl_selected.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['accent_primary']}; font-weight: 600;")
        else:
            self.lbl_selected.setStyleSheet(f"font-size: 11px; color: {THEME_COLORS['text_muted']}; font-weight: 500;")
