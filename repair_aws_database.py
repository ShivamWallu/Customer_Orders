import sqlite3
import shutil
import os
import json
from datetime import datetime

DB_PATH = 'orders.db'
BACKUP_PATH = f'orders_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'

print("🔧 STARTING DATABASE REPAIR & DEMO CLEANUP...")

# 1. Backup
if os.path.exists(DB_PATH):
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"✅ Safety backup created: {BACKUP_PATH}")

# 2. Fix corrupted schema (invalid rootpage on deleted_orders)
try:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA writable_schema = ON;")
    conn.execute("DELETE FROM sqlite_master WHERE name LIKE '%deleted_orders%';")
    conn.execute("PRAGMA writable_schema = OFF;")
    conn.commit()
    conn.execute("VACUUM;")
    conn.close()
    print("✅ Corrupted deleted_orders index removed & database vacuumed.")
except Exception as e:
    print(f"⚠️ Note on writable_schema: {e}")

# 3. Open healthy connection and recreate clean deleted_orders table
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS deleted_orders (
    order_id TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL,
    deleted_by TEXT DEFAULT 'super_admin',
    reason TEXT DEFAULT 'Permanently deleted by Super Admin'
);
""")
conn.commit()

# 4. Clean demo orders while preserving all Pankaj and genuine orders
cur.execute("SELECT rowid, * FROM orders")
all_rows = [dict(row) for row in cur.fetchall()]
print(f"📦 Total orders found: {len(all_rows)}")

to_delete = []
to_keep = []

for r in all_rows:
    sp = str(r.get('sales_person') or '').lower()
    pn = str(r.get('party_name') or '').lower()
    oid = str(r.get('order_id') or '').replace("'", "").replace('"', '').strip()
    
    # 🔒 NEVER DELETE PANKAJ ORDERS
    if 'pankaj' in sp or 'pankaj' in pn:
        to_keep.append(r)
        continue
        
    # Genuine orders from today or real parties
    if 'anjan' in sp or 'utpsp' in sp or 'maa kali' in pn or 'bhagya lakshmi' in pn:
        to_keep.append(r)
        continue
        
    # Demo orders
    if any(k in sp or k in pn or k in oid.lower() for k in ['diana', 'test', 'shivam wallu', 'manat', 'mukesh', '8457', '4862']):
        to_delete.append(r)
        continue
        
    to_delete.append(r)

print(f"🛡️ Genuine Orders Preserved ({len(to_keep)} Total):")
for k in to_keep:
    clean_id = str(k.get('order_id')).replace("'", "").replace('"', '')
    print(f"   [KEPT] {clean_id} | {k.get('sales_person')} | {k.get('party_name')}")

print(f"\n🗑️ Demo Orders Being Removed ({len(to_delete)} Total):")
for d in to_delete:
    clean_id = str(d.get('order_id')).replace("'", "").replace('"', '')
    print(f"   [DELETED] {clean_id} | {d.get('sales_person')} | {d.get('party_name')}")

for d in to_delete:
    r_id = d.get('rowid')
    clean_id = str(d.get('order_id') or '').replace("'", "").replace('"', '').replace('#', '').strip()
    if r_id:
        cur.execute("DELETE FROM orders WHERE rowid = ?", (r_id,))
    if clean_id:
        cur.execute("DELETE FROM orders WHERE order_id LIKE ?", (f"%{clean_id}%",))
        cur.execute("INSERT OR REPLACE INTO deleted_orders (order_id, deleted_at, deleted_by, reason) VALUES (?, datetime('now'), 'super_admin', 'Demo Data Cleanup')", (clean_id,))

# Clean demo notifications
cur.execute("DELETE FROM notifications WHERE type = 'TEST_ALERT' OR LOWER(message) LIKE '%diana%' OR LOWER(message) LIKE '%test1%'")
conn.commit()

# Final integrity check
integrity = cur.execute("PRAGMA integrity_check;").fetchall()
print(f"\n🔍 Final SQLite Integrity Check: {integrity}")

conn.close()

# 5. Clean customer_orders.json
JSON_FILE = 'customer_orders.json'
if os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            j_orders = json.load(f)
        
        filtered_j = []
        for jo in j_orders:
            jsp = str(jo.get('salesPerson') or jo.get('sales_person') or '').lower()
            jpn = str(jo.get('partyName') or jo.get('party_name') or '').lower()
            joid = str(jo.get('id') or jo.get('order_id') or '').lower()
            
            if 'pankaj' in jsp or 'pankaj' in jpn:
                filtered_j.append(jo)
            elif any(k in jsp or k in jpn or k in joid for k in ['diana', 'test', 'shivam wallu', 'manat', 'mukesh']):
                continue
            else:
                filtered_j.append(jo)
                
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(filtered_j, f, indent=2)
        print(f"✅ customer_orders.json cleaned: {len(filtered_j)} authentic orders preserved.")
    except Exception as e:
        print(f"⚠️ Note on customer_orders.json: {e}")

print("\n🚀 REPAIR COMPLETE! You can now restart mashal-backend.")
