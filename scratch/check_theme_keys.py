import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import THEME_COLORS

files = [
    'ui/views/renaming_view.py',
    'ui/components/renaming_inspector.py',
    'ui/components/rename_preview_dialog.py',
    'ui/components/rename_history_dialog.py'
]

pattern = re.compile(r"THEME_COLORS\[['\"]([^'\"]+)['\"]\]")
for fpath in files:
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    matches = pattern.findall(content)
    for m in matches:
        if m not in THEME_COLORS:
            print(f'MISSING KEY in {fpath}: {m}')
print('Done scanning keys.')
