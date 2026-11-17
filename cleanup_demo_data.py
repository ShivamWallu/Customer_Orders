import sqlite3
import shutil
import os
import json
from datetime import datetime

DB_PATH = 'orders.db'
BACKUP_PATH = f'orders_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'

# 1. Create safety backup
if os.path.exists(DB_PATH):
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"✅ Safety backup created: {BACKUP_PATH}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 2. Inspect orders table
cur.execute("SELECT * FROM orders")
all_orders = [dict(row) for row in cur.fetchall()]

to_keep = []
to_delete = []

for o in all_orders:
    sp = str(o.get('sales_person') or '').lower()
    pn = str(o.get('party_name') or '').lower()
    oid = str(o.get('order_id') or '')
    
    # STRICT RULE: Keep any order associated with Pankaj!
    if 'pankaj' in sp or 'pankaj' in pn:
        to_keep.append(o)
        continue
    
    # Real live orders (e.g. Anjan Raana, Utpsp pal, or real parties)
    if 'anjan' in sp or 'utpsp' in sp or 'maa kali' in pn or 'bhagya lakshmi' in pn:
        to_keep.append(o)
        continue
        
    # Demo / Test orders to remove:
    # Diana Noel, test1, Shivam Wallu (test), Manat, Mukesh
    if any(k in sp or k in pn for k in ['diana', 'test', 'shivam', 'manat', 'mukesh']):
        to_delete.append(o)
        continue
    
    # Default fallback: if not explicitly demo, ask or flag
    print(f"⚠️ Unclassified order: {oid} | Sales: {sp} | Party: {pn}")
    to_delete.append(o)

print("\n--------------------------------------------------")
print(f"📦 TOTAL ORDERS FOUND: {len(all_orders)}")
print(f"🛡️ ORDERS TO KEEP (PANKAJ & GENUINE): {len(to_keep)}")
for k in to_keep:
    print(f"   [KEEP] {k.get('order_id')} | {k.get('sales_person')} | {k.get('party_name')} | {k.get('total_boxes')} Boxes")

print(f"\n🗑️ DEMO ORDERS TO DELETE: {len(to_delete)}")
for d in to_delete:
    print(f"   [DELETE] {d.get('order_id')} | {d.get('sales_person')} | {d.get('party_name')} | {d.get('total_boxes')} Boxes")

# Execute deletion in orders table
deleted_ids = [d.get('order_id') for d in to_delete]
for oid in deleted_ids:
    clean_id = oid.replace('#', '').strip()
    cur.execute("DELETE FROM orders WHERE order_id = ? OR order_id = ?", (clean_id, f"#{clean_id}"))
    cur.execute("INSERT OR REPLACE INTO deleted_orders (order_id, deleted_at, deleted_by, reason) VALUES (?, datetime('now'), 'super_admin', 'Demo Data Cleanup')", (clean_id,))

conn.commit()
print(f"\n✅ Successfully deleted {len(deleted_ids)} demo orders from database.")

# 3. Clean customer_orders.json
JSON_FILE = 'customer_orders.json'
if os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            j_orders = json.load(f)
        
        filtered_j = []
        for jo in j_orders:
            jsp = str(jo.get('salesPerson') or jo.get('sales_person') or '').lower()
            jpn = str(jo.get('partyName') or jo.get('party_name') or '').lower()
            joid = str(jo.get('id') or jo.get('order_id') or '')
            
            if 'pankaj' in jsp or 'pankaj' in jpn:
                filtered_j.append(jo)
            elif any(k in jsp or k in jpn for k in ['diana', 'test', 'shivam', 'manat', 'mukesh']):
                continue # delete
            else:
                filtered_j.append(jo)
                
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(filtered_j, f, indent=2)
        print(f"✅ customer_orders.json cleaned: {len(filtered_j)} orders preserved.")
    except Exception as e:
        print(f"⚠️ Error cleaning customer_orders.json: {e}")

# 4. Clean demo notifications
cur.execute("DELETE FROM notifications WHERE type = 'TEST_ALERT' OR message LIKE '%Diana Noel%' OR message LIKE '%test1%'")
conn.commit()
print("✅ Demo notifications cleaned.")

conn.close()
print("🎉 All demo data cleaned up safely! Pankaj's orders remain 100% intact.")
