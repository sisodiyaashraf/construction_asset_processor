import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import db

with db.get_connection() as conn:
    c = conn.cursor()
    c.execute("PRAGMA table_info(assets)")
    cols = [r[1] for r in c.fetchall()]
    print("All assets columns:", cols)
    
    # Check category column
    cat_cols = [col for col in cols if 'cat' in col or 'class' in col or 'type' in col]
    print("Category-like columns:", cat_cols)
    for col in cat_cols:
        c.execute(f"SELECT {col}, COUNT(*) FROM assets GROUP BY {col}")
        print(f"Values in {col}:", [tuple(r) for r in c.fetchall()])
