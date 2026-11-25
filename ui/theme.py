"""
Theme and Styling Engine for Construction Asset Processor
Premium dark theme with industrial amber/yellow construction accents.
"""

from app.config import THEME_COLORS


def get_application_stylesheet() -> str:
    """Generate the global Qt Style Sheet (QSS) for the application."""
    c = THEME_COLORS
    return f"""
    /* Global Application Styles */
    QMainWindow, QDialog {{
        background-color: {c['bg_main']};
        color: {c['text_primary']};
        font-family: 'Segoe UI', 'SF Pro Display', -apple-system, 'Inter', sans-serif;
        font-size: 13px;
    }}

    QWidget {{
        background-color: transparent;
        color: {c['text_primary']};
        selection-background-color: {c['accent_primary']};
        selection-color: {c['text_inverse']};
    }}

    /* Top Toolbar */
    #top_toolbar {{
        background-color: {c['bg_toolbar']};
        border-bottom: 1px solid {c['border_subtle']};
        min-height: 52px;
        max-height: 52px;
        padding: 0 16px;
    }}

    /* Left Sidebar */
    #sidebar {{
        background-color: {c['bg_sidebar']};
        border-right: 1px solid {c['border_subtle']};
    }}

    #sidebar_header {{
        padding: 16px 14px 12px 14px;
        border-bottom: 1px solid {c['border_subtle']};
    }}

    /* Sidebar Navigation Button */
    QPushButton.nav_btn {{
        background-color: transparent;
        color: {c['text_secondary']};
        border: none;
        border-left: 3px solid transparent;
        text-align: left;
        padding: 9px 14px;
        font-size: 13px;
        font-weight: 500;
        border-radius: 0px;
    }}

    QPushButton.nav_btn:hover {{
        background-color: {c['bg_card_hover']};
        color: {c['text_primary']};
    }}

    QPushButton.nav_btn.active {{
        background-color: {c['bg_card']};
        color: {c['accent_primary']};
        font-weight: 600;
        border-left: 3px solid {c['accent_primary']};
    }}

    /* Right Inspector */
    #inspector {{
        background-color: {c['bg_inspector']};
        border-left: 1px solid {c['border_subtle']};
    }}

    /* Bottom Status Bar */
    #status_bar {{
        background-color: {c['bg_toolbar']};
        border-top: 1px solid {c['border_subtle']};
        min-height: 32px;
        max-height: 32px;
        padding: 0 12px;
        font-size: 12px;
        color: {c['text_secondary']};
    }}

    /* Cards & Containers */
    QFrame.card {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border_subtle']};
        border-radius: 8px;
        padding: 14px;
    }}

    QFrame.card:hover {{
        border-color: {c['border_medium']};
    }}

    /* Primary Buttons (Industrial Amber) */
    QPushButton.btn_primary {{
        background-color: {c['accent_primary']};
        color: {c['text_inverse']};
        font-weight: 600;
        padding: 8px 18px;
        border-radius: 6px;
        border: none;
        font-size: 13px;
    }}

    QPushButton.btn_primary:hover {{
        background-color: {c['accent_hover']};
    }}

    QPushButton.btn_primary:pressed {{
        background-color: {c['accent_pressed']};
    }}

    QPushButton.btn_primary:disabled {{
        background-color: {c['border_medium']};
        color: {c['text_muted']};
    }}

    /* Secondary Buttons */
    QPushButton.btn_secondary {{
        background-color: {c['bg_card_hover']};
        color: {c['text_primary']};
        border: 1px solid {c['border_subtle']};
        padding: 8px 16px;
        border-radius: 6px;
        font-size: 13px;
    }}

    QPushButton.btn_secondary:hover {{
        background-color: {c['border_medium']};
        border-color: {c['accent_primary']};
    }}

    QPushButton.btn_secondary:pressed {{
        background-color: {c['bg_card']};
    }}

    QPushButton.btn_secondary:disabled {{
        color: {c['text_muted']};
        border-color: {c['border_subtle']};
    }}

    /* Danger / Stop Buttons */
    QPushButton.btn_danger {{
        background-color: rgba(239, 68, 68, 0.15);
        color: {c['status_error']};
        border: 1px solid {c['status_error']};
        padding: 8px 16px;
        border-radius: 6px;
    }}

    QPushButton.btn_danger:hover {{
        background-color: {c['status_error']};
        color: #FFFFFF;
    }}

    QPushButton.btn_danger:disabled {{
        border-color: {c['border_subtle']};
        color: {c['text_muted']};
        background-color: transparent;
    }}

    /* Inputs & LineEdits */
    QLineEdit, QComboBox {{
        background-color: {c['bg_input']};
        color: {c['text_primary']};
        border: 1px solid {c['border_subtle']};
        border-radius: 6px;
        padding: 7px 12px;
        font-size: 13px;
    }}

    QLineEdit:focus, QComboBox:focus {{
        border: 1px solid {c['accent_primary']};
        background-color: {c['bg_main']};
    }}

    /* Combo Box Dropdown */
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border_medium']};
        color: {c['text_primary']};
        selection-background-color: {c['accent_primary']};
        selection-color: {c['text_inverse']};
        padding: 4px;
    }}

    /* Progress Bar */
    QProgressBar {{
        background-color: {c['bg_input']};
        border: 1px solid {c['border_subtle']};
        border-radius: 4px;
        text-align: center;
        color: {c['text_primary']};
        font-size: 11px;
        font-weight: 600;
        height: 14px;
    }}

    QProgressBar::chunk {{
        background-color: {c['accent_primary']};
        border-radius: 3px;
    }}

    /* Tables */
    QTableWidget, QTableView {{
        background-color: {c['bg_card']};
        gridline-color: {c['border_subtle']};
        border: 1px solid {c['border_subtle']};
        border-radius: 6px;
        color: {c['text_primary']};
    }}

    QTableWidget::item {{
        padding: 6px 10px;
        border-bottom: 1px solid {c['border_subtle']};
    }}

    QTableWidget::item:selected {{
        background-color: rgba(229, 169, 60, 0.2);
        color: {c['accent_primary']};
    }}

    QHeaderView::section {{
        background-color: {c['bg_input']};
        color: {c['text_secondary']};
        padding: 8px 10px;
        border: none;
        border-bottom: 1px solid {c['border_medium']};
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
        border: none;
        background: {c['bg_main']};
        width: 8px;
        margin: 0px;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical {{
        background: {c['border_medium']};
        min-height: 25px;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {c['accent_primary']};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar:horizontal {{
        border: none;
        background: {c['bg_main']};
        height: 8px;
        margin: 0px;
        border-radius: 4px;
    }}

    QScrollBar::handle:horizontal {{
        background: {c['border_medium']};
        min-width: 25px;
        border-radius: 4px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {c['accent_primary']};
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* CheckBox */
    QCheckBox {{
        color: {c['text_primary']};
        spacing: 8px;
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {c['border_medium']};
        border-radius: 3px;
        background-color: {c['bg_input']};
    }}

    QCheckBox::indicator:checked {{
        background-color: {c['accent_primary']};
        border-color: {c['accent_primary']};
    }}

    /* Tooltips */
    QToolTip {{
        background-color: {c['bg_card']};
        color: {c['text_primary']};
        border: 1px solid {c['border_medium']};
        padding: 6px 10px;
        border-radius: 4px;
        font-size: 12px;
    }}

    /* Text Edit / Log Area */
    QTextEdit, QPlainTextEdit {{
        background-color: {c['bg_input']};
        color: {c['text_secondary']};
        border: 1px solid {c['border_subtle']};
        border-radius: 6px;
        font-family: 'Consolas', 'Cascadia Code', monospace;
        font-size: 12px;
        padding: 8px;
    }}
    """
