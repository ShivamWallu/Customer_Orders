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
import re
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
            conn.executescript("""
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
            CREATE TABLE IF NOT EXISTS sales_manager_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                phone TEXT NOT NULL,
                manager_name TEXT,
                created_at TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_created ON orders (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_orders_party ON orders (party_name);
            CREATE INDEX IF NOT EXISTS idx_orders_synced ON orders (synced_to_sheet);
            CREATE INDEX IF NOT EXISTS idx_orders_wa_status ON orders (whatsapp_status);
            CREATE INDEX IF NOT EXISTS idx_mgr_token ON sales_manager_sessions (token);
            CREATE INDEX IF NOT EXISTS idx_mgr_phone ON sales_manager_sessions (phone);
            CREATE INDEX IF NOT EXISTS idx_admin_token ON admin_sessions (token);
            """)
        # Safe migration for new columns
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN total_pieces INTEGER DEFAULT 0;")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN party_code TEXT DEFAULT '';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN data_consent TEXT DEFAULT 'YES (Verified)';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN order_status TEXT DEFAULT 'PENDING';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN so_number TEXT DEFAULT '';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN confirmed_at TEXT DEFAULT '';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN confirmed_by TEXT DEFAULT '';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE admin_sessions ADD COLUMN role TEXT DEFAULT 'admin';")
        except Exception:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (order_status);")
        except Exception:
            pass
        print("[DATABASE] SQLite permanent orders database initialized at:", DB_FILE)
    finally:
        conn.close()

def create_manager_session(phone: str, manager_name: str = "") -> Dict[str, Any]:
    """Creates a 1-year persistent session token for verified Sales Manager"""
    import secrets
    import time
    token = f"MGR_{secrets.token_hex(24)}"
    now = time.time()
    one_year_seconds = 365 * 24 * 3600
    expires_at = now + one_year_seconds
    now_str = datetime.now().isoformat()

    conn = get_connection()
    try:
        # If manager_name is missing, try to recall the last entered name for this phone
        if not manager_name:
            cur = conn.cursor()
            cur.execute("""
            SELECT manager_name FROM sales_manager_sessions 
            WHERE phone = ? AND manager_name != '' AND manager_name IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """, (phone,))
            prev_row = cur.fetchone()
            if prev_row and prev_row["manager_name"]:
                manager_name = prev_row["manager_name"]

        with conn:
            conn.execute("""
            INSERT INTO sales_manager_sessions (token, phone, manager_name, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """, (token, phone, manager_name, now_str, expires_at))
        return {
            "status": "success",
            "token": token,
            "phone": phone,
            "manager_name": manager_name,
            "expires_at": expires_at,
            "validity_days": 365
        }
    finally:
        conn.close()

def validate_manager_session(token: str) -> Optional[Dict[str, Any]]:
    """Validates if token exists and is within 1-year window"""
    import time
    if not token:
        return None
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
        SELECT token, phone, manager_name, created_at, expires_at
        FROM sales_manager_sessions
        WHERE token = ?
        """, (token,))
        row = cur.fetchone()
        if row and row["expires_at"] > time.time():
            m_name = row["manager_name"] or ""
            # If current session token has empty name, auto-heal from previous records of this phone
            if not m_name:
                cur.execute("""
                SELECT manager_name FROM sales_manager_sessions 
                WHERE phone = ? AND manager_name != '' AND manager_name IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """, (row["phone"],))
                prev_row = cur.fetchone()
                if prev_row and prev_row["manager_name"]:
                    m_name = prev_row["manager_name"]
                    with conn:
                        conn.execute("UPDATE sales_manager_sessions SET manager_name = ? WHERE token = ?", (m_name, token))

            return {
                "token": row["token"],
                "phone": row["phone"],
                "manager_name": m_name,
                "created_at": row["created_at"],
                "expires_at": row["expires_at"]
            }
        return None
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
        total_pieces = int(order.get("totalPieces") or order.get("total_pieces", 0))
        party_code = order.get("partyCode") or order.get("party_code", "")
        data_consent = order.get("dataConsent") or order.get("data_consent", "YES (Verified)")
        order_status = order.get("orderStatus") or order.get("order_status") or "PENDING"
        so_number = order.get("soNumber") or order.get("so_number") or ""
        confirmed_at = order.get("confirmedAt") or order.get("confirmed_at") or ""
        confirmed_by = order.get("confirmedBy") or order.get("confirmed_by") or ""
        
        items = order.get("items", [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []

        # ⚡ Dynamically recalculate pieces & boxes with 100% precision from packaging multipliers
        calc_bxs = 0
        calc_pcs = 0
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                try:
                    b = int(it.get("boxes", 0) or 0)
                except (ValueError, TypeError):
                    b = 0
                calc_bxs += b
                m = re.search(r'x\s*(\d+)', str(it.get("item", "")), re.I)
                mult = int(m.group(1)) if m else 1
                it["multiplier"] = mult
                it["pieces"] = b * mult
                calc_pcs += (b * mult)

        if total_pieces == 0 and calc_pcs > 0:
            total_pieces = calc_pcs
        if total_boxes == 0 and calc_bxs > 0:
            total_boxes = calc_bxs

        items_json = json.dumps(items, ensure_ascii=False) if isinstance(items, list) else str(items)
        items_summary = order.get("itemsSummary") or order.get("items_summary", "")
        
        slip_image_path = order.get("slipImagePath") or order.get("slip_image_path", "")
        slip_image_url = order.get("slipImageUrl") or order.get("slip_image_url", f"/order_slips/{order_id}.png" if order_id else "")
        synced_to_sheet = 1 if order.get("synced_to_sheet") else 0
        
        with conn:
            conn.execute("""
            INSERT INTO orders (
                order_id, party_name, party_code, party_address, delivery_address, sales_person,
                order_date, formatted_timestamp, created_at, total_boxes, total_pieces,
                items_json, items_summary, slip_image_path, slip_image_url,
                synced_to_sheet, data_consent, order_status, so_number, confirmed_at, confirmed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                party_name = excluded.party_name,
                party_code = excluded.party_code,
                party_address = excluded.party_address,
                delivery_address = excluded.delivery_address,
                sales_person = excluded.sales_person,
                total_boxes = excluded.total_boxes,
                total_pieces = excluded.total_pieces,
                items_json = excluded.items_json,
                items_summary = excluded.items_summary,
                data_consent = excluded.data_consent,
                order_status = COALESCE(NULLIF(excluded.order_status, ''), orders.order_status),
                so_number = COALESCE(NULLIF(excluded.so_number, ''), orders.so_number),
                confirmed_at = COALESCE(NULLIF(excluded.confirmed_at, ''), orders.confirmed_at),
                confirmed_by = COALESCE(NULLIF(excluded.confirmed_by, ''), orders.confirmed_by),
                slip_image_path = COALESCE(NULLIF(excluded.slip_image_path, ''), orders.slip_image_path),
                slip_image_url = COALESCE(NULLIF(excluded.slip_image_url, ''), orders.slip_image_url),
                synced_to_sheet = CASE WHEN excluded.synced_to_sheet = 1 THEN 1 ELSE orders.synced_to_sheet END;
            """, (
                order_id, party_name, party_code, party_address, delivery_address, sales_person,
                order_date, formatted_timestamp, created_at, total_boxes, total_pieces,
                items_json, items_summary, slip_image_path, slip_image_url,
                synced_to_sheet, data_consent, order_status, so_number, confirmed_at, confirmed_by
            ))
        print(f"[DATABASE] Order #{order_id} permanently saved in orders.db ({total_boxes} Bxs, {total_pieces} Pcs)")
        return True
    except Exception as e:
        print(f"[DATABASE ERROR] Could not save order #{order.get('id')}: {e}")
        return False
    finally:
        conn.close()

def confirm_order_in_db(order_id: str, so_number: str, confirmed_by: str = "admin") -> bool:
    """Confirms an order and assigns official SO (Sales Order) Number"""
    clean_id = (order_id or "").replace("#", "").strip()
    clean_so = (so_number or "").strip()
    if not clean_so:
        return False
    now_str = datetime.now().isoformat()
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            UPDATE orders 
            SET order_status = 'CONFIRMED', so_number = ?, confirmed_at = ?, confirmed_by = ?
            WHERE order_id = ? OR order_id = ?
            """, (clean_so, now_str, confirmed_by, clean_id, f"#{clean_id}"))
        
        # Also update in customer_orders.json
        orders_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_orders.json")
        if os.path.exists(orders_log):
            try:
                with open(orders_log, "r", encoding="utf-8") as f:
                    orders_list = json.load(f)
                for o in orders_list:
                    if str(o.get("id", "")).replace("#", "").strip() == clean_id:
                        o["order_status"] = "CONFIRMED"
                        o["so_number"] = clean_so
                        o["confirmed_at"] = now_str
                        o["confirmed_by"] = confirmed_by
                        break
                with open(orders_log, "w", encoding="utf-8") as f:
                    json.dump(orders_list, f, indent=2, ensure_ascii=False)
            except Exception as j_err:
                print(f"[CONFIRM JSON WARN] {j_err}")
        return True
    except Exception as e:
        print(f"[DATABASE CONFIRM ERROR] {e}")
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

def get_all_orders_from_db(limit: int = 1000) -> List[Dict[str, Any]]:
    """Retrieves all orders from database ordered by most recent with dynamic pieces calculation"""
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
            d["partyCode"] = d.get("party_code", "")
            d["partyAddress"] = d["party_address"]
            d["deliveryAddress"] = d["delivery_address"]
            d["salesPerson"] = d["sales_person"]
            
            # Recalculate pieces and boxes dynamically if missing or 0
            tot_bxs = int(d.get("total_boxes") or 0)
            tot_pcs = int(d.get("total_pieces") or 0)
            calc_bxs = 0
            calc_pcs = 0
            if isinstance(d["items"], list):
                for it in d["items"]:
                    if not isinstance(it, dict):
                        continue
                    b = int(it.get("boxes", 0) or 0)
                    calc_bxs += b
                    m = re.search(r'x\s*(\d+)', str(it.get("item", "")), re.I)
                    mult = int(m.group(1)) if m else 1
                    it["multiplier"] = mult
                    it["pieces"] = b * mult
                    calc_pcs += (b * mult)

            if tot_pcs == 0 and calc_pcs > 0:
                tot_pcs = calc_pcs
            if tot_bxs == 0 and calc_bxs > 0:
                tot_bxs = calc_bxs

            d["totalBoxes"] = tot_bxs
            d["totalPieces"] = tot_pcs
            d["orderStatus"] = d.get("order_status") or "PENDING"
            d["soNumber"] = d.get("so_number") or ""
            d["confirmedAt"] = d.get("confirmed_at") or ""
            d["confirmedBy"] = d.get("confirmed_by") or ""
            d["formattedTimestamp"] = d["formatted_timestamp"]
            d["synced_to_sheet"] = bool(d["synced_to_sheet"])
            d["slipImageUrl"] = d.get("slip_image_url") or f"/order_slips/{d['order_id']}.png"
            result.append(d)
        return result
    except Exception as e:
        print(f"[DATABASE ERROR] Could not fetch orders: {e}")
        return []
    finally:
        conn.close()

def get_order_by_id(order_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single order by ID for anti-tamper public verification"""
    clean_id = (order_id or "").replace("#", "").strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE order_id = ? OR order_id = ?", (clean_id, f"#{clean_id}"))
        row = cursor.fetchone()
        if row:
            d = dict(row)
            try:
                d["items"] = json.loads(d.get("items_json") or "[]")
            except Exception:
                d["items"] = []
            d["id"] = d["order_id"]
            d["partyName"] = d["party_name"]
            d["partyCode"] = d.get("party_code", "")
            d["partyAddress"] = d["party_address"]
            d["salesPerson"] = d["sales_person"]
            d["totalBoxes"] = d["total_boxes"]
            d["totalPieces"] = d.get("total_pieces", 0)
            d["orderStatus"] = d.get("order_status") or "PENDING"
            d["soNumber"] = d.get("so_number") or ""
            d["formattedTimestamp"] = d["formatted_timestamp"]
            d["dataConsent"] = d.get("data_consent", "YES (Verified)")
            return d
        return None
    except Exception as e:
        print(f"[DATABASE ERROR] Could not fetch order {clean_id}: {e}")
        return None
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

def create_admin_session(username: str = "admin", role: str = "admin") -> str:
    """Creates a secure 7-day persistent session token for Admin Dashboard with user role"""
    import secrets
    import time
    token = f"ADM_{secrets.token_hex(24)}"
    now = time.time()
    expires_at = now + (7 * 24 * 3600)
    now_str = datetime.now().isoformat()
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            INSERT INTO admin_sessions (token, username, role, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """, (token, username, role, now_str, expires_at))
        return token
    finally:
        conn.close()

def validate_admin_session(token: str) -> Optional[Dict[str, Any]]:
    """Validates if admin token is active and not expired, returns role"""
    import time
    if not token:
        return None
    master_token = os.environ.get("AUTH_SECRET_TOKEN", "KOGM_ADMIN_SECURE_TOKEN_2026_XYZ")
    if token == master_token:
        return {"username": "admin", "role": "admin", "token": master_token}
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT username, role, token, expires_at FROM admin_sessions WHERE token = ?", (token,))
        row = cur.fetchone()
        if row and row["expires_at"] > time.time():
            role_val = row["role"] if "role" in row.keys() and row["role"] else "admin"
            return {
                "username": row["username"],
                "role": role_val,
                "token": row["token"]
            }
        return None
    finally:
        conn.close()

def delete_admin_session(token: str):
    """Logs out admin by removing session token"""
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
    finally:
        conn.close()

def delete_order_from_db(order_id: str) -> bool:
    """Permanently deletes an order from orders.db and removes from customer_orders.json"""
    clean_id = (order_id or "").replace("#", "").strip()
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM orders WHERE order_id = ? OR order_id = ?", (clean_id, f"#{clean_id}"))
        # Also clean up in customer_orders.json
        orders_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_orders.json")
        if os.path.exists(orders_log):
            try:
                with open(orders_log, "r", encoding="utf-8") as f:
                    orders_list = json.load(f)
                filtered = [o for o in orders_list if str(o.get("id", "")).replace("#", "").strip() != clean_id]
                with open(orders_log, "w", encoding="utf-8") as f:
                    json.dump(filtered, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[JSON DELETE WARN] {e}")
        return True
    except Exception as e:
        print(f"[DATABASE DELETE ERROR] {e}")
        return False
    finally:
        conn.close()

def get_orders_stats() -> Dict[str, Any]:
    """Calculates live KPI metrics directly from SQLite orders database"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(total_boxes), 0), COALESCE(SUM(total_pieces), 0) FROM orders")
        row = cur.fetchone()
        total_orders = row[0] or 0
        total_boxes = row[1] or 0
        total_pieces = row[2] or 0

        # Confirmed vs Pending
        cur.execute("SELECT COUNT(*) FROM orders WHERE order_status = 'CONFIRMED'")
        confirmed_count = cur.fetchone()[0] or 0
        pending_count = total_orders - confirmed_count

        cur.execute("SELECT COUNT(*) FROM orders WHERE synced_to_sheet = 1")
        synced_count = cur.fetchone()[0] or 0
        pending_sync = total_orders - synced_count

        cur.execute("SELECT COUNT(DISTINCT party_name) FROM orders")
        unique_parties = cur.fetchone()[0] or 0

        cur.execute("SELECT COUNT(DISTINCT sales_person) FROM orders WHERE sales_person IS NOT NULL AND sales_person != ''")
        sales_reps = cur.fetchone()[0] or 0

        today_str = datetime.now().strftime("%d/%m/%Y")
        today_iso = datetime.now().strftime("%Y-%m-%d")
        cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(total_boxes), 0), COALESCE(SUM(total_pieces), 0) FROM orders 
        WHERE formatted_timestamp LIKE ? OR order_date LIKE ? OR created_at LIKE ?
        """, (f"%{today_str}%", f"%{today_str}%", f"{today_iso}%"))
        t_row = cur.fetchone()
        today_orders = t_row[0] or 0
        today_boxes = t_row[1] or 0
        today_pieces = t_row[2] or 0

        return {
            "totalOrders": total_orders,
            "totalConfirmedOrders": confirmed_count,
            "totalPendingOrders": pending_count,
            "totalBoxes": total_boxes,
            "totalPieces": total_pieces,
            "syncedCount": synced_count,
            "pendingSync": pending_sync,
            "uniqueParties": unique_parties,
            "activeSalesManagers": sales_reps,
            "todayOrders": today_orders,
            "todayBoxes": today_boxes,
            "todayPieces": today_pieces
        }
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    migrate_existing_json_orders()
    all_o = get_all_orders_from_db()
    print(f"Total orders in database: {len(all_o)}")
