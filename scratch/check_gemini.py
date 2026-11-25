from core.database import db

cnt = db.get_asset_count(search='Gemini')
print('Gemini count from db.get_asset_count:', cnt)

with db.get_connection() as conn:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM assets WHERE filename LIKE '%Gemini%'")
    print("Filename LIKE Gemini:", c.fetchone()[0])
    c.execute("SELECT filename FROM assets WHERE filename NOT LIKE '%Gemini%'")
    rows = c.fetchall()
    print("Non gemini count:", len(rows))
    for r in rows[:10]:
        print("  ", r[0])
