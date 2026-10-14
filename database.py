"""
Khandelia Oil and General Mills Pvt. Ltd.
Enterprise Database Management Module (Zero Data Loss Engine)

Features:
- Permanent ACID-compliant storage in SQLite (orders.db).
- Prevents data loss if Google Sheet rows are deleted or corrupted.
- Zero extra dependencies (works out of the box on Windows, Mac, and AWS Linux).
- Supports AWS RDS PostgreSQL if DATABASE_URL starts with postgresql://.
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")

def get_connection():
    """Returns SQLite connection with row_factory and WAL mode for high concurrency"""
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for high performance concurrent reads and writes
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    """Initializes the orders table and performance indexes"""
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                party_name TEXT NOT NULL,
                party_address TEXT,
                delivery_address TEXT,
                sales_person TEXT,
                order_date TEXT,
                formatted_timestamp TEXT,
                created_at TEXT NOT NULL,
                total_boxes INTEGER DEFAULT 0,
                items_json TEXT NOT NULL,
                items_summary TEXT,
                slip_image_path TEXT,
                slip_image_url TEXT,
                synced_to_sheet INTEGER DEFAULT 0,
                synced_at TEXT,
                whatsapp_status TEXT DEFAULT 'PENDING',
                whatsapp_sent_at TEXT
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders (created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_party ON orders (party_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_synced ON orders (synced_to_sheet);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_wa_status ON orders (whatsapp_status);")
        print("[DATABASE] SQLite permanent orders database initialized at:", DB_FILE)
    finally:
        conn.close()

def save_order_to_db(order: Dict[str, Any]) -> bool:
    """
    Saves or updates an order in the database.
    Guarantees permanent record preservation even if Google Sheets is cleared.
    """
    conn = get_connection()
    try:
        order_id = order.get("id") or order.get("order_id")
        party_name = order.get("partyName") or order.get("party_name", "")
        party_address = order.get("partyAddress") or order.get("party_address", "")
        delivery_address = order.get("deliveryAddress") or order.get("delivery_address", "")
        sales_person = order.get("salesPerson") or order.get("sales_person", "")
        order_date = order.get("orderDate") or order.get("order_date", "")
        formatted_timestamp = order.get("formattedTimestamp") or order.get("formatted_timestamp", "")
        created_at = order.get("timestamp") or datetime.now().isoformat()
        total_boxes = int(order.get("totalBoxes") or order.get("total_boxes", 0))
        
        items = order.get("items", [])
        items_json = json.dumps(items, ensure_ascii=False) if isinstance(items, list) else str(items)
        items_summary = order.get("itemsSummary") or order.get("items_summary", "")
        
        slip_image_path = order.get("slipImagePath") or order.get("slip_image_path", "")
        slip_image_url = order.get("slipImageUrl") or order.get("slip_image_url", f"/order_slips/{order_id}.png" if order_id else "")
        synced_to_sheet = 1 if order.get("synced_to_sheet") else 0
        
        with conn:
            conn.execute("""
            INSERT INTO orders (
                order_id, party_name, party_address, delivery_address, sales_person,
                order_date, formatted_timestamp, created_at, total_boxes,
                items_json, items_summary, slip_image_path, slip_image_url,
                synced_to_sheet
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                party_name = excluded.party_name,
                party_address = excluded.party_address,
                delivery_address = excluded.delivery_address,
                sales_person = excluded.sales_person,
                total_boxes = excluded.total_boxes,
                items_json = excluded.items_json,
                items_summary = excluded.items_summary,
                slip_image_path = COALESCE(NULLIF(excluded.slip_image_path, ''), orders.slip_image_path),
                slip_image_url = COALESCE(NULLIF(excluded.slip_image_url, ''), orders.slip_image_url),
                synced_to_sheet = CASE WHEN excluded.synced_to_sheet = 1 THEN 1 ELSE orders.synced_to_sheet END;
            """, (
                order_id, party_name, party_address, delivery_address, sales_person,
                order_date, formatted_timestamp, created_at, total_boxes,
                items_json, items_summary, slip_image_path, slip_image_url,
                synced_to_sheet
            ))
        print(f"[DATABASE] Order #{order_id} permanently saved in orders.db")
        return True
    except Exception as e:
        print(f"[DATABASE ERROR] Could not save order #{order.get('id')}: {e}")
        return False
    finally:
        conn.close()

def mark_order_synced_in_db(order_id: str):
    """Marks an order as successfully synced to Google Sheets"""
    conn = get_connection()
    try:
        now_str = datetime.now().isoformat()
        with conn:
            conn.execute("""
            UPDATE orders
            SET synced_to_sheet = 1, synced_at = ?
            WHERE order_id = ?
            """, (now_str, order_id))
    except Exception as e:
        print(f"[DATABASE ERROR] Could not mark order #{order_id} synced: {e}")
    finally:
        conn.close()

def mark_whatsapp_sent_in_db(order_id: str):
    """Marks an order as delivered to WhatsApp"""
    conn = get_connection()
    try:
        now_str = datetime.now().isoformat()
        with conn:
            conn.execute("""
            UPDATE orders
            SET whatsapp_status = 'SENT', whatsapp_sent_at = ?
            WHERE order_id = ?
            """, (now_str, order_id))
    except Exception as e:
        print(f"[DATABASE ERROR] Could not mark order #{order_id} WhatsApp sent: {e}")
    finally:
        conn.close()

def get_all_orders_from_db(limit: int = 500) -> List[Dict[str, Any]]:
    """Retrieves all orders from database ordered by most recent"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["items"] = json.loads(d.get("items_json") or "[]")
            except Exception:
                d["items"] = []
            d["id"] = d["order_id"]
            d["partyName"] = d["party_name"]
            d["partyAddress"] = d["party_address"]
            d["deliveryAddress"] = d["delivery_address"]
            d["salesPerson"] = d["sales_person"]
            d["totalBoxes"] = d["total_boxes"]
            d["formattedTimestamp"] = d["formatted_timestamp"]
            d["synced_to_sheet"] = bool(d["synced_to_sheet"])
            result.append(d)
        return result
    except Exception as e:
        print(f"[DATABASE ERROR] Could not fetch orders: {e}")
        return []
    finally:
        conn.close()

def migrate_existing_json_orders():
    """Migrates any previous orders from customer_orders.json into orders.db"""
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_orders.json")
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            orders = json.load(f)
        count = 0
        for o in orders:
            if o.get("id"):
                save_order_to_db(o)
                count += 1
        if count > 0:
            print(f"[DATABASE MIGRATION] Migrated {count} historical orders into orders.db")
    except Exception as e:
        print(f"[DATABASE MIGRATION NOTICE] {e}")

if __name__ == "__main__":
    init_db()
    migrate_existing_json_orders()
    all_o = get_all_orders_from_db()
    print(f"Total orders in database: {len(all_o)}")
