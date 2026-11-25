from core.database import db

with db.get_connection() as conn:
    c = conn.cursor()
    c.execute('SELECT main_category, count(*) as cnt FROM assets GROUP BY main_category')
    print("Categories:", [dict(r) for r in c.fetchall()])
    c.execute('SELECT composition_type, count(*) as cnt FROM assets GROUP BY composition_type')
    print("Composition:", [dict(r) for r in c.fetchall()])
    c.execute('SELECT subcategory, count(*) as cnt FROM assets GROUP BY subcategory')
    print("Subcategories:", [dict(r) for r in c.fetchall()[:10]])
    c.execute('SELECT object_name, count(*) as cnt FROM assets GROUP BY object_name')
    print("Object names:", [dict(r) for r in c.fetchall()[:10]])
