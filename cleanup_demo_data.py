import sqlite3
import shutil
import os
import json
from datetime import datetime

DB_PATH = 'orders.db'
BACKUP_PATH = f'orders_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'

# 1. Safety Backup
if os.path.exists(DB_PATH):
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"✅ Safety backup created: {BACKUP_PATH}")

# 2. Rebuild clean database while purging demo orders
temp_rebuilt_path = 'orders_rebuilt_clean.db'
if os.path.exists(temp_rebuilt_path):
    os.remove(temp_rebuilt_path)

src = sqlite3.connect(DB_PATH)
dst = sqlite3.connect(temp_rebuilt_path)

demo_keywords = ['diana', 'test1', 'shivam wallu', 'manat', 'mukesh', 'kogm-20261103-8457', 'kogm-20261103-4862', 'kogm-20261103-2809', 'kogm-20261103-4053', 'kogm-20261113-3815']

for line in src.iterdump():
    line_lower = line.lower()
    
    # 🔒 NEVER DELETE PANKAJ ORDERS!
    if 'pankaj' in line_lower:
        dst.execute(line)
        continue
        
    # Skip any line containing demo keywords
    if any(k in line_lower for k in demo_keywords):
        continue
        
    try:
        dst.execute(line)
    except Exception as e:
        pass

dst.commit()

# Clean notifications table
try:
    dst.execute("DELETE FROM notifications WHERE type = 'TEST_ALERT' OR LOWER(message) LIKE '%diana%' OR LOWER(message) LIKE '%test1%'")
    dst.commit()
except Exception:
    pass

# Verify integrity
check = dst.execute("PRAGMA integrity_check").fetchall()
print(f"✅ Database integrity: {check}")

cur = dst.cursor()
cur.execute("SELECT order_id, sales_person, party_name, total_boxes FROM orders")
remaining_orders = cur.fetchall()
print(f"\n🛡️ PRESERVED AUTHENTIC ORDERS ({len(remaining_orders)} Total):")
for r in remaining_orders:
    print(f"   [KEPT] {r[0]} | {r[1]} | {r[2]} | {r[3]} Boxes")

src.close()
dst.close()

# Replace original orders.db with clean database
shutil.copy2(DB_PATH, 'orders.db.before_replace')
shutil.move(temp_rebuilt_path, DB_PATH)
print("\n🎉 orders.db successfully updated! All demo data purged. Pankaj's orders remain 100% safe.")

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
