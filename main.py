"""
Construction Asset Processor - Application Launcher
Entry point for launching the desktop application with logging, high-DPI
scaling, and unhandled exception safety traps.
"""

import logging
import sys
import traceback
from pathlib import Path

# Add root directory to sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import APP_NAME, APP_VERSION, ORGANIZATION
from core.database import db
from ui.main_window import MainWindow

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("main")


def exception_hook(exctype, value, tb):
    """Global unhandled exception hook to log crashes and display error dialog."""
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    logger.critical(f"Unhandled critical exception:\n{error_msg}")

    # Show GUI dialog if QApplication is active
    if QApplication.instance():
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Application Error")
        box.setText("An unexpected error occurred in the application.")
        box.setInformativeText(str(value))
        box.setDetailedText(error_msg)
        box.exec()
    if sys.stderr is not None:
        try:
            sys.__excepthook__(exctype, value, tb)
        except Exception:
            pass


def main():
    """Main application lifecycle runner."""
    sys.excepthook = exception_hook

    logger.info("=" * 60)
    logger.info(f"Starting {APP_NAME} {APP_VERSION}")
    logger.info("=" * 60)

    # Initialize SQLite database schema
    try:
        db.init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    # Initialize PySide6 Application
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION)

    # Instantiate and display Main Window
    window = MainWindow()
    window.show()

    logger.info("Main application window displayed.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
