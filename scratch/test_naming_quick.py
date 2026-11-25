import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import py_compile
py_compile.compile('core/naming_engine.py', doraise=True)

from core.naming_engine import naming_engine, clean_filename
from core.database import db

print('Cleaned 1:', clean_filename('Excavator Yellow Side View!!!', '.PNG'))
print('Cleaned 2:', clean_filename('dump--truck  __red!!', '.jpg'))
print('Cleaned 3:', clean_filename('123__abc__---__def', 'png'))

assets = db.get_assets(limit=10)
proposals = naming_engine.process_all_assets(assets)
for p in proposals:
    orig = p['original_filename']
    sug = p['suggested_filename']
    conf = p['naming_conflict']
    print(f"#{p['asset_id']}: {orig[:25]}... -> {sug} (conflict={conf})")
