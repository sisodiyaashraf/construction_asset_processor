"""
GUI Integration Test for Stage 4: MainWindow & RenamingView
Verifies PySide6 application initialization in offscreen mode.
"""

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.components.rename_preview_dialog import RenamePreviewDialog
from ui.components.rename_history_dialog import RenameHistoryDialog
from core.database import db

app = QApplication.instance() or QApplication(sys.argv)

print("1. Instantiating MainWindow...")
window = MainWindow()
assert window.renaming_view is not None
print("   MainWindow instantiated with RenamingView at index 4.")

print("2. Switching to RenamingView...")
window.sidebar.select_id("renaming")
assert window.workspace_stack.currentIndex() == 4
print("   Workspace switched to index 4 successfully.")

print("3. Checking RenamingView components...")
rv = window.renaming_view
assert rv.table.rowCount() > 0
print(f"   Renaming table loaded {rv.table.rowCount()} rows.")
assert rv.inspector is not None
assert rv.card_total.value_label.text() == "161"
print(f"   Stat card Total Images: {rv.card_total.value_label.text()}")

print("4. Testing RenamePreviewDialog instantiation...")
sample_assets = db.get_assets(limit=5)
preview_dlg = RenamePreviewDialog(sample_assets, window)
assert preview_dlg.table.rowCount() == 5
print(f"   Preview dialog loaded {preview_dlg.table.rowCount()} candidate rows.")

print("5. Testing RenameHistoryDialog instantiation...")
hist_dlg = RenameHistoryDialog(window)
print(f"   History dialog loaded {hist_dlg.table.rowCount()} rows.")

print("ALL GUI INTEGRATION TESTS PASSED SUCCESSFULLY!")
