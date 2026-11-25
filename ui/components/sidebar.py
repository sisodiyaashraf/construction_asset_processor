"""
Left Navigation Sidebar Component
Houses 13 stage navigation items with industrial styling, icons, and status badges.
Supports expanded (210px) and compact (58px icon-only) responsive modes.
"""

from typing import Dict, List
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget
)

from app.config import APP_NAME, APP_VERSION, NAVIGATION_ITEMS, THEME_COLORS


class NavButton(QPushButton):
    """Custom navigation button with icon, label, and stage indicator badge."""

    def __init__(self, item_id: str, title: str, icon_symbol: str, badge: str = "", parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.title_text = title
        self.icon_symbol = icon_symbol
        self.badge_text = badge
        self.setProperty("class", "nav_btn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(38)

        self.btn_layout = QHBoxLayout(self)
        self.btn_layout.setContentsMargins(12, 6, 12, 6)
        self.btn_layout.setSpacing(10)

        # Icon Label
        self.icon_label = QLabel(icon_symbol)
        self.icon_label.setStyleSheet("font-size: 15px; background: transparent;")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.btn_layout.addWidget(self.icon_label)

        # Title Label
        self.text_label = QLabel(title)
        self.text_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {THEME_COLORS['text_primary']}; background: transparent;")
        self.btn_layout.addWidget(self.text_label, stretch=1)

        # Badge Label (e.g., Active, Planned, Stage 2)
        if badge:
            self.badge_label = QLabel(badge)
            badge_color = THEME_COLORS['accent_primary'] if badge == "Active" else THEME_COLORS['text_muted']
            badge_bg = "rgba(229, 169, 60, 0.15)" if badge == "Active" else "rgba(107, 114, 128, 0.15)"
            self.badge_label.setStyleSheet(f"""
                font-size: 9px;
                font-weight: 600;
                color: {badge_color};
                background-color: {badge_bg};
                padding: 1px 5px;
                border-radius: 3px;
            """)
            self.btn_layout.addWidget(self.badge_label)

    def set_active(self, active: bool):
        """Toggle active visual state."""
        if active:
            self.setProperty("class", "nav_btn active")
            self.text_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {THEME_COLORS['accent_primary']}; background: transparent;")
        else:
            self.setProperty("class", "nav_btn")
            self.text_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {THEME_COLORS['text_secondary']}; background: transparent;")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_compact(self, compact: bool):
        """Toggle compact icon-only representation."""
        if compact:
            self.text_label.setVisible(False)
            if hasattr(self, "badge_label"):
                self.badge_label.setVisible(False)
            self.btn_layout.setContentsMargins(4, 6, 4, 6)
            self.setToolTip(f"{self.title_text} ({self.badge_text})" if self.badge_text else self.title_text)
        else:
            self.text_label.setVisible(True)
            if hasattr(self, "badge_label"):
                self.badge_label.setVisible(True)
            self.btn_layout.setContentsMargins(12, 6, 12, 6)
            self.setToolTip("")


class Sidebar(QWidget):
    """
    Left navigation sidebar containing brand header and all application views.
    Supports responsive expanded (210px) and compact (58px) modes.
    """

    navigation_changed = Signal(str, int)  # page_id, index
    collapsed_changed = Signal(bool)

    EXPANDED_WIDTH = 210
    COMPACT_WIDTH = 58

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.buttons: List[NavButton] = []
        self._current_index = 0
        self.is_compact = False

        self.setFixedWidth(self.EXPANDED_WIDTH)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header / Brand
        self.header = QFrame()
        self.header.setObjectName("sidebar_header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 10, 10)
        header_layout.setSpacing(6)

        # Brand title text container
        self.brand_box = QVBoxLayout()
        self.brand_box.setSpacing(2)

        app_title = QLabel("🏗️ ASSET PROC.")
        app_title.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.6px;
            color: {THEME_COLORS['accent_primary']};
        """)
        self.brand_box.addWidget(app_title)

        subtitle = QLabel("Construction 2D")
        subtitle.setStyleSheet(f"font-size: 10px; color: {THEME_COLORS['text_muted']};")
        self.brand_box.addWidget(subtitle)
        header_layout.addLayout(self.brand_box, stretch=1)

        # Collapse / Expand Toggle Button
        self.btn_toggle_collapse = QPushButton("◀")
        self.btn_toggle_collapse.setFixedSize(24, 24)
        self.btn_toggle_collapse.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_collapse.setToolTip("Collapse/Expand Sidebar")
        self.btn_toggle_collapse.setStyleSheet(f"""
            QPushButton {{
                background: {THEME_COLORS['bg_card_hover']};
                color: {THEME_COLORS['text_secondary']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: {THEME_COLORS['accent_primary']};
                border-color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_toggle_collapse.clicked.connect(self.toggle_compact_mode)
        header_layout.addWidget(self.btn_toggle_collapse)

        main_layout.addWidget(self.header)

        # Scrollable Navigation List
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        nav_container = QWidget()
        self.nav_layout = QVBoxLayout(nav_container)
        self.nav_layout.setContentsMargins(0, 6, 0, 6)
        self.nav_layout.setSpacing(2)

        for idx, item in enumerate(NAVIGATION_ITEMS):
            btn = NavButton(item["id"], item["title"], item["icon"], item["badge"], nav_container)
            btn.clicked.connect(lambda checked=False, i=idx, pid=item["id"]: self._on_button_clicked(pid, i))
            self.buttons.append(btn)
            self.nav_layout.addWidget(btn)

        self.nav_layout.addStretch()
        scroll_area.setWidget(nav_container)
        main_layout.addWidget(scroll_area, stretch=1)

        # Set first button active by default (Dashboard)
        if self.buttons:
            self.buttons[0].set_active(True)

    def toggle_compact_mode(self):
        """Toggle between expanded (210px) and compact icon-only (58px) modes."""
        self.set_compact(not self.is_compact)

    def set_compact(self, compact: bool):
        """Apply compact or expanded mode."""
        self.is_compact = compact
        if compact:
            self.setFixedWidth(self.COMPACT_WIDTH)
            self.btn_toggle_collapse.setText("▶")
            # Hide brand title text, show only collapse button
            for i in range(self.brand_box.count()):
                w = self.brand_box.itemAt(i).widget()
                if w:
                    w.setVisible(False)
        else:
            self.setFixedWidth(self.EXPANDED_WIDTH)
            self.btn_toggle_collapse.setText("◀")
            for i in range(self.brand_box.count()):
                w = self.brand_box.itemAt(i).widget()
                if w:
                    w.setVisible(True)

        for btn in self.buttons:
            btn.set_compact(compact)

        self.collapsed_changed.emit(compact)

    def _on_button_clicked(self, page_id: str, index: int):
        """Handle sidebar item click."""
        self.select_index(index)
        self.navigation_changed.emit(page_id, index)

    def select_index(self, index: int):
        """Programmatically switch active button."""
        if 0 <= index < len(self.buttons):
            for i, btn in enumerate(self.buttons):
                btn.set_active(i == index)
            self._current_index = index

    def select_id(self, page_id: str, emit_signal: bool = True):
        """Programmatically select by page id and optionally emit navigation change."""
        for idx, btn in enumerate(self.buttons):
            if btn.item_id == page_id:
                self.select_index(idx)
                if emit_signal:
                    self.navigation_changed.emit(page_id, idx)
                break
