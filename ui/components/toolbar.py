"""
Top Application Toolbar Component
Displays breadcrumb navigation, quick action triggers, and inspector toggle.
Responsive design ensures buttons never overlap or get clipped.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QWidget
)

from app.config import THEME_COLORS


class TopToolbar(QWidget):
    """Application top toolbar with breadcrumbs and primary shortcuts."""

    import_clicked = Signal()
    refresh_clicked = Signal()
    open_output_clicked = Signal()
    toggle_inspector_clicked = Signal()
    toggle_sidebar_clicked = Signal()
    workflow_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("top_toolbar")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        # Sidebar Toggle Hamburger Button
        self.btn_sidebar = QPushButton("☰")
        self.btn_sidebar.setFixedSize(30, 30)
        self.btn_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_sidebar.setToolTip("Toggle Compact Sidebar (Ctrl+B)")
        self.btn_sidebar.setStyleSheet(f"""
            QPushButton {{
                background: {THEME_COLORS['bg_card_hover']};
                color: {THEME_COLORS['text_primary']};
                border: 1px solid {THEME_COLORS['border_subtle']};
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {THEME_COLORS['accent_primary']};
                color: {THEME_COLORS['accent_primary']};
            }}
        """)
        self.btn_sidebar.clicked.connect(self.toggle_sidebar_clicked.emit)
        layout.addWidget(self.btn_sidebar)

        # Breadcrumb / Section Header
        self.breadcrumb_label = QLabel("Construction Asset Processor  /  Asset Workflow")
        self.breadcrumb_label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 600;
            color: {THEME_COLORS['text_primary']};
        """)
        layout.addWidget(self.breadcrumb_label)

        layout.addStretch()

        # Quick Action Buttons
        self.btn_workflow = QPushButton("🚀 Workflow")
        self.btn_workflow.setProperty("class", "btn_secondary")
        self.btn_workflow.setCursor(Qt.PointingHandCursor)
        self.btn_workflow.setFixedHeight(30)
        self.btn_workflow.clicked.connect(self.workflow_clicked.emit)
        layout.addWidget(self.btn_workflow)

        self.btn_import = QPushButton("📥 Import")
        self.btn_import.setProperty("class", "btn_secondary")
        self.btn_import.setCursor(Qt.PointingHandCursor)
        self.btn_import.setFixedHeight(30)
        self.btn_import.clicked.connect(self.import_clicked.emit)
        layout.addWidget(self.btn_import)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setProperty("class", "btn_secondary")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setFixedHeight(30)
        self.btn_refresh.clicked.connect(self.refresh_clicked.emit)
        layout.addWidget(self.btn_refresh)

        self.btn_output = QPushButton("📁 Output")
        self.btn_output.setProperty("class", "btn_secondary")
        self.btn_output.setCursor(Qt.PointingHandCursor)
        self.btn_output.setFixedHeight(30)
        self.btn_output.clicked.connect(self.open_output_clicked.emit)
        layout.addWidget(self.btn_output)

        # Toggle Inspector Button
        self.btn_inspector = QPushButton("🔍 Inspector")
        self.btn_inspector.setProperty("class", "btn_secondary")
        self.btn_inspector.setCursor(Qt.PointingHandCursor)
        self.btn_inspector.setFixedHeight(30)
        self.btn_inspector.setToolTip("Toggle Right Asset Inspector Panel")
        self.btn_inspector.clicked.connect(self.toggle_inspector_clicked.emit)
        layout.addWidget(self.btn_inspector)

    def set_breadcrumb(self, title: str):
        """Update top breadcrumb trail."""
        self.breadcrumb_label.setText(f"Construction Asset Processor  /  {title}")
