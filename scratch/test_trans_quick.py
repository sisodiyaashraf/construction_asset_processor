import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import py_compile
py_compile.compile('core/transparency_engine.py', doraise=True)
print("Transparency engine compiled successfully.")

from core.transparency_engine import transparency_engine, REMBG_AVAILABLE
from core.database import db

print(f"rembg available in environment: {REMBG_AVAILABLE}")

# Test eligibility evaluation on first 10 assets
assets = db.get_assets(limit=10)
for a in assets:
    elig, exp = transparency_engine.evaluate_eligibility(a)
    print(f"#{a['id']}: {a['filename'][:20]}... -> [{elig}] ({exp[:40]}...)")

# Run batch eligibility evaluation across all assets
count = transparency_engine.batch_evaluate_eligibility()
print(f"Batch evaluated {count} assets.")
stats = db.get_transparency_stats()
print("Updated Transparency Stats:", stats)
