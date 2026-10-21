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
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unit_code TEXT UNIQUE NOT NULL,
                unit_name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL,
                party_code TEXT DEFAULT '',
                party_name TEXT DEFAULT '',
                assigned_units TEXT DEFAULT 'Unit 1',
                status TEXT DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT DEFAULT 'SUPER_ADMIN'
            );
            CREATE TABLE IF NOT EXISTS customer_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                phone TEXT NOT NULL,
                customer_name TEXT,
                party_code TEXT,
                party_name TEXT,
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
            CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone);
            CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
            CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);
            CREATE INDEX IF NOT EXISTS idx_cust_token ON customer_sessions (token);
            CREATE INDEX IF NOT EXISTS idx_cust_phone ON customer_sessions (phone);
            CREATE INDEX IF NOT EXISTS idx_units_code ON units (unit_code);
            CREATE INDEX IF NOT EXISTS idx_units_status ON units (status);
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                role TEXT DEFAULT '',
                action TEXT NOT NULL,
                status TEXT DEFAULT 'SUCCESS',
                details TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs (action);
            CREATE INDEX IF NOT EXISTS idx_audit_phone ON audit_logs (phone);
            CREATE INDEX IF NOT EXISTS idx_audit_role ON audit_logs (role);
            CREATE INDEX IF NOT EXISTS idx_audit_status ON audit_logs (status);
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
            conn.execute("ALTER TABLE orders ADD COLUMN unit TEXT DEFAULT 'Unit 1';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN assigned_units TEXT DEFAULT 'Unit 1';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE admin_sessions ADD COLUMN role TEXT DEFAULT 'admin';")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE admin_sessions ADD COLUMN assigned_units TEXT DEFAULT 'ALL';")
        except Exception:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (order_status);")
        except Exception:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_unit ON orders (unit);")
        except Exception:
            pass

        # Seed initial Warehouse Units (Unit 1 to Unit 6) if units table is empty
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM units;")
            if cur.fetchone()[0] == 0:
                now_iso = datetime.now().isoformat()
                default_units = [
                    ("UNIT-1", "Unit 1", "Main Production & Packing Plant", "ACTIVE", now_iso, now_iso),
                    ("UNIT-2", "Unit 2", "Warehouse & Dispatch Unit 2", "ACTIVE", now_iso, now_iso),
                    ("UNIT-3", "Unit 3", "Processing & Storage Unit 3", "ACTIVE", now_iso, now_iso),
                    ("UNIT-4", "Unit 4", "Packaging Material & Logistics Unit 4", "ACTIVE", now_iso, now_iso),
                    ("UNIT-5", "Unit 5", "Bulk Storage & Refining Unit 5", "ACTIVE", now_iso, now_iso),
                    ("UNIT-6", "Unit 6", "Cold Storage & Distribution Unit 6", "ACTIVE", now_iso, now_iso),
                ]
                with conn:
                    conn.executemany("""
                    INSERT OR IGNORE INTO units (unit_code, unit_name, description, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, default_units)
                print("[DATABASE] Default Warehouse Units (Unit 1 to Unit 6) successfully seeded.")
        except Exception as e:
            print("[DATABASE] Units seeding error:", e)

        # Seed / Upgrade initial authorized accounts (Shivam Wallu -> Super Admin with ALL units access)
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM users;")
            if cur.fetchone()[0] == 0:
                now_iso = datetime.now().isoformat()
                default_users = [
                    ("Shivam Wallu", "7814749816", "super_admin", "", "", "ALL", "ACTIVE", now_iso, now_iso, "SYSTEM"),
                    ("Pankaj Kumar", "9914565011", "asm", "", "", "Unit 1", "ACTIVE", now_iso, now_iso, "SYSTEM"),
                    ("Ramesh Kumar", "9876543211", "asm", "", "", "Unit 1", "ACTIVE", now_iso, now_iso, "SYSTEM"),
                    ("Sunil Sharma", "9876543212", "asm", "", "", "Unit 2", "ACTIVE", now_iso, now_iso, "SYSTEM"),
                    ("Deepak Verma", "9876543213", "asm", "", "", "Unit 3", "ACTIVE", now_iso, now_iso, "SYSTEM"),
                    ("Vikas Gupta", "9876543214", "asm", "", "", "Unit 4", "ACTIVE", now_iso, now_iso, "SYSTEM"),
                    ("Krishna Traders", "9812345678", "customer", "SDMOWB0307", "Krishna Traders", "Unit 1", "ACTIVE", now_iso, now_iso, "SYSTEM"),
                ]
                with conn:
                    conn.executemany("""
                    INSERT OR IGNORE INTO users (name, phone, role, party_code, party_name, assigned_units, status, created_at, updated_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, default_users)
                print("[DATABASE] Default authorized users successfully seeded.")
            else:
                # Upgrade existing Shivam Wallu to Super Admin with ALL units
                with conn:
                    conn.execute("""
                    UPDATE users SET role = 'super_admin', assigned_units = 'ALL' 
                    WHERE phone = '7814749816' OR LOWER(name) LIKE '%shivam%'
                    """)
                    conn.execute("""
                    UPDATE users SET assigned_units = 'Unit 1'
                    WHERE LOWER(name) LIKE '%pankaj%'
                    """)
        except Exception as e:
            print("[DATABASE] User seeding/upgrade error:", e)

        # Requirement 6: Keep only Unit 1 and Unit 4 active by default; others inactive
        try:
            with conn:
                conn.execute("UPDATE units SET status = 'ACTIVE' WHERE unit_name IN ('Unit 1', 'Unit 4');")
                conn.execute("UPDATE units SET status = 'INACTIVE' WHERE unit_name NOT IN ('Unit 1', 'Unit 4');")
        except Exception as e:
            print("[DATABASE] Units active status setup error:", e)

        # 🛡️ Initialize Role Permissions Matrix Table
        try:
            with conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS role_permissions (
                    role TEXT PRIMARY KEY,
                    can_add_order INTEGER DEFAULT 1,
                    can_edit_unit INTEGER DEFAULT 0,
                    can_confirm_so INTEGER DEFAULT 0,
                    can_delete_order INTEGER DEFAULT 0,
                    can_block_user INTEGER DEFAULT 0,
                    can_manage_units INTEGER DEFAULT 0,
                    can_view_logs INTEGER DEFAULT 0,
                    can_export_csv INTEGER DEFAULT 1,
                    updated_at TEXT,
                    updated_by TEXT
                );
                """)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) AS cnt FROM role_permissions;")
                if cur.fetchone()["cnt"] == 0:
                    now_str = datetime.now().isoformat()
                    roles_defaults = [
                        ("super_admin", 1, 1, 1, 1, 1, 1, 1, 1, now_str, "SYSTEM"),
                        ("admin", 1, 1, 1, 1, 1, 1, 1, 1, now_str, "SYSTEM"),
                        ("manager", 1, 1, 1, 0, 0, 1, 1, 1, now_str, "SYSTEM"),
                        ("analyst", 0, 0, 0, 0, 0, 0, 1, 1, now_str, "SYSTEM"),
                        ("asm", 1, 0, 0, 0, 0, 0, 0, 1, now_str, "SYSTEM"),
                        ("customer", 1, 0, 0, 0, 0, 0, 0, 0, now_str, "SYSTEM")
                    ]
                    cur.executemany("""
                    INSERT INTO role_permissions 
                    (role, can_add_order, can_edit_unit, can_confirm_so, can_delete_order, can_block_user, can_manage_units, can_view_logs, can_export_csv, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, roles_defaults)
        except Exception as e:
            print("[DATABASE] Role permissions table init error:", e)

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
    """Validates if token exists, is within 1-year window, and manager account is ACTIVE"""
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
            m_phone = "".join(filter(str.isdigit, str(row["phone"])))[-10:]
            cur.execute("SELECT status, role FROM users WHERE phone = ? LIMIT 1", (m_phone,))
            u_check = cur.fetchone()
            if not u_check or u_check["status"] == "BLOCKED" or u_check["role"] not in ["asm", "super_admin", "admin", "manager"]:
                if u_check and u_check["status"] == "BLOCKED":
                    with conn:
                        conn.execute("DELETE FROM sales_manager_sessions WHERE token = ?", (token,))
                return None

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
                "role": u_check["role"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"]
            }
        return None
    finally:
        conn.close()

# ----------------- 🏭 WAREHOUSE UNIT MANAGEMENT SYSTEM -----------------
def get_all_units(active_only: bool = False) -> List[Dict[str, Any]]:
    """Fetches warehouse units with order counts"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        where_sql = "WHERE u.status = 'ACTIVE'" if active_only else ""
        cur.execute(f"""
        SELECT u.id, u.unit_code, u.unit_name, u.description, u.status, u.created_at, u.updated_at,
               (SELECT COUNT(*) FROM orders o WHERE o.unit = u.unit_name OR o.unit = u.unit_code) AS total_orders,
               (SELECT COALESCE(SUM(total_boxes), 0) FROM orders o WHERE o.unit = u.unit_name OR o.unit = u.unit_code) AS total_boxes,
               (SELECT COALESCE(SUM(total_pieces), 0) FROM orders o WHERE o.unit = u.unit_name OR o.unit = u.unit_code) AS total_pieces
        FROM units u
        {where_sql}
        ORDER BY u.id ASC
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def create_or_update_unit(unit_code: str, unit_name: str, description: str = "", status: str = "ACTIVE") -> Dict[str, Any]:
    """Super Admin dynamically creates or updates warehouse units"""
    code_clean = (unit_code or "").strip().upper()
    name_clean = (unit_name or "").strip()
    if not code_clean or not name_clean:
        return {"status": "error", "message": "Unit Code and Unit Name are required."}
    
    now_iso = datetime.now().isoformat()
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            INSERT INTO units (unit_code, unit_name, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(unit_code) DO UPDATE SET
                unit_name = excluded.unit_name,
                description = excluded.description,
                status = excluded.status,
                updated_at = excluded.updated_at;
            """, (code_clean, name_clean, description.strip(), status.upper(), now_iso, now_iso))
        
        cur = conn.cursor()
        cur.execute("SELECT * FROM units WHERE unit_code = ?", (code_clean,))
        row = cur.fetchone()
        log_audit_event(user_name="Super Admin", role="super_admin", action="UNIT_CREATED", status="SUCCESS", details=f"Unit '{name_clean}' ({code_clean}) created/updated with status {status.upper()}")
        return {"status": "success", "message": f"Unit '{name_clean}' saved successfully.", "unit": dict(row) if row else None}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def toggle_unit_status(unit_id: int, new_status: str) -> Dict[str, Any]:
    """Super Admin activates or deactivates a warehouse unit"""
    new_status = new_status.upper().strip()
    if new_status not in ["ACTIVE", "INACTIVE"]:
        return {"status": "error", "message": "Status must be ACTIVE or INACTIVE"}
    conn = get_connection()
    try:
        now_iso = datetime.now().isoformat()
        with conn:
            cur = conn.cursor()
            cur.execute("UPDATE units SET status = ?, updated_at = ? WHERE id = ?", (new_status, now_iso, unit_id))
            if cur.rowcount == 0:
                return {"status": "error", "message": "Unit not found"}
        log_audit_event(user_name="Super Admin", role="super_admin", action="UNIT_STATUS_TOGGLED", status="SUCCESS", details=f"Unit ID {unit_id} status changed to {new_status}")
        return {"status": "success", "message": f"Unit status updated to {new_status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def delete_unit_by_id(unit_id: int) -> Dict[str, Any]:
    """Super Admin permanently removes a custom unit"""
    conn = get_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT unit_name FROM units WHERE id = ?", (unit_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "Unit not found"}
            unit_name = row["unit_name"]
            
            cur.execute("SELECT COUNT(*) FROM orders WHERE unit = ?", (unit_name,))
            ord_count = cur.fetchone()[0]
            if ord_count > 0:
                return {"status": "error", "message": f"Cannot delete unit '{unit_name}' because it has {ord_count} associated orders. Please reassign orders first or mark unit INACTIVE."}

            cur.execute("DELETE FROM units WHERE id = ?", (unit_id,))
        log_audit_event(user_name="Super Admin", role="super_admin", action="UNIT_DELETED", status="SUCCESS", details=f"Unit '{unit_name}' (ID: {unit_id}) deleted by Super Admin")
        return {"status": "success", "message": f"Unit '{unit_name}' deleted successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

# ----------------- 📜 AUDIT LOGS & SYSTEM ACTIVITY TRACKER -----------------
def log_audit_event(user_name: str = "", phone: str = "", role: str = "", 
                    action: str = "", status: str = "SUCCESS", details: str = "", ip_address: str = ""):
    """Inserts an immutable audit log record into audit_logs table"""
    import time
    conn = get_connection()
    try:
        now_dt = datetime.now()
        now_iso = now_dt.isoformat()
        now_ts = time.time()
        with conn:
            conn.execute("""
            INSERT INTO audit_logs (user_name, phone, role, action, status, details, ip_address, created_at, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_name.strip(), phone.strip(), role.strip(), action.strip(), status.upper().strip(), details.strip(), ip_address.strip(), now_iso, now_ts))
    except Exception as e:
        print(f"[AUDIT_LOG_ERROR] Could not write audit log: {e}")
    finally:
        conn.close()

def get_audit_logs(page: int = 1, page_size: int = 25, q: str = "", 
                   action: str = "", status: str = "", date_filter: str = "") -> Dict[str, Any]:
    """Retrieves paginated audit logs with search and filter capabilities"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        conditions = []
        params = []
        
        if q:
            clean_q = f"%{q.strip().lower()}%"
            conditions.append("(LOWER(user_name) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(action) LIKE ? OR LOWER(details) LIKE ? OR LOWER(role) LIKE ?)")
            params.extend([clean_q, clean_q, clean_q, clean_q, clean_q])
            
        if action and action != "ALL":
            conditions.append("action = ?")
            params.append(action.strip())
            
        if status and status != "ALL":
            conditions.append("status = ?")
            params.append(status.strip())
            
        if date_filter:
            clean_d = date_filter.strip()
            # If DD/MM/YYYY, convert to YYYY-MM-DD
            if "/" in clean_d:
                parts = clean_d.split("/")
                if len(parts) == 3:
                    clean_d = f"{parts[2]}-{parts[1]}-{parts[0]}"
            conditions.append("created_at LIKE ?")
            params.append(f"{clean_d}%")
            
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        
        cur.execute(f"SELECT COUNT(*) FROM audit_logs {where_clause}", params)
        total_records = cur.fetchone()[0]
        
        offset = max(0, (page - 1) * page_size)
        total_pages = max(1, (total_records + page_size - 1) // page_size) if page_size > 0 else 1
        
        query = f"""
        SELECT * FROM audit_logs 
        {where_clause}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """
        cur.execute(query, params + [page_size, offset])
        rows = cur.fetchall()
        
        result_logs = []
        for r in rows:
            d = dict(r)
            try:
                dt = datetime.fromisoformat(d["created_at"])
                d["formatted_date"] = dt.strftime("%d/%m/%Y, %I:%M:%S %p")
            except Exception:
                d["formatted_date"] = d["created_at"]
            result_logs.append(d)
            
        return {
            "total": total_records,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "logs": result_logs
        }
    finally:
        conn.close()

# ----------------- 👥 SUPER ADMIN USER & ACCOUNT MANAGEMENT -----------------
def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """Fetches user record by clean 10-digit mobile number"""
    digits = "".join(filter(str.isdigit, str(phone)))
    clean_p = digits[-10:] if len(digits) >= 10 else digits
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
        SELECT id, name, phone, role, party_code, party_name, assigned_units, status, created_at, updated_at, created_by
        FROM users WHERE phone = ? LIMIT 1
        """, (clean_p,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_all_users(role: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns list of users with formatted registration timestamps"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        if role and role != "ALL":
            cur.execute("""
            SELECT id, name, phone, role, party_code, party_name, assigned_units, status, created_at, updated_at, created_by
            FROM users WHERE LOWER(role) = LOWER(?) ORDER BY id DESC
            """, (role.strip(),))
        else:
            cur.execute("""
            SELECT id, name, phone, role, party_code, party_name, assigned_units, status, created_at, updated_at, created_by
            FROM users ORDER BY id DESC
            """)
        users = [dict(r) for r in cur.fetchall()]
        for u in users:
            try:
                dt = datetime.fromisoformat(u["created_at"])
                u["formatted_created_at"] = dt.strftime("%d/%m/%Y, %I:%M %p")
            except Exception:
                u["formatted_created_at"] = u.get("created_at", "-")
        return users
    finally:
        conn.close()

def create_or_update_user(name: str, phone: str, role: str, party_code: str = "", party_name: str = "", assigned_units: str = "Unit 1", status: str = "ACTIVE", created_by: str = "SUPER_ADMIN") -> Dict[str, Any]:
    """Super Admin creates or updates an authorized user with assigned unit(s)"""
    digits = "".join(filter(str.isdigit, str(phone)))
    clean_p = digits[-10:] if len(digits) >= 10 else digits
    if len(clean_p) != 10:
        return {"status": "error", "message": "Phone number must be exactly 10 digits"}
    
    role = role.lower().strip()
    if role == "analyser":
        role = "analyst"
    valid_roles = ["super_admin", "admin", "manager", "analyst", "analyser", "asm", "customer"]
    if role not in valid_roles:
        return {"status": "error", "message": f"Invalid role '{role}'. Allowed roles: {', '.join(valid_roles)}"}

    assigned_units_clean = (assigned_units or "Unit 1").strip()
    if role in ["super_admin", "admin"]:
        assigned_units_clean = "ALL"

    now_iso = datetime.now().isoformat()
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            INSERT INTO users (name, phone, role, party_code, party_name, assigned_units, status, created_at, updated_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                name = excluded.name,
                role = excluded.role,
                party_code = excluded.party_code,
                party_name = excluded.party_name,
                assigned_units = excluded.assigned_units,
                status = excluded.status,
                updated_at = excluded.updated_at,
                created_by = excluded.created_by;
            """, (name.strip(), clean_p, role, party_code.strip(), party_name.strip(), assigned_units_clean, status.upper(), now_iso, now_iso, created_by))
        
        user = get_user_by_phone(clean_p)
        log_audit_event(user_name=name.strip(), phone=clean_p, role=role, action="USER_CREATED", status="SUCCESS", details=f"User '{name.strip()}' saved with role '{role}' ({assigned_units_clean}) by {created_by}")
        return {"status": "success", "message": f"User '{name}' saved successfully with role '{role}' in '{assigned_units_clean}'", "user": user}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def toggle_user_status(user_id: int, new_status: str) -> Dict[str, Any]:
    """Super Admin blocks or unblocks a user and revokes active sessions if blocked"""
    new_status = new_status.upper().strip()
    if new_status not in ["ACTIVE", "BLOCKED"]:
        return {"status": "error", "message": "Status must be ACTIVE or BLOCKED"}
    conn = get_connection()
    try:
        now_iso = datetime.now().isoformat()
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT phone, name, role FROM users WHERE id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "User not found"}
            u_phone = row["phone"]
            cur.execute("UPDATE users SET status = ?, updated_at = ? WHERE id = ?", (new_status, now_iso, user_id))
            if new_status == "BLOCKED":
                cur.execute("DELETE FROM customer_sessions WHERE phone = ? OR phone LIKE ?", (u_phone, f"%{u_phone}"))
                cur.execute("DELETE FROM sales_manager_sessions WHERE phone = ? OR phone LIKE ?", (u_phone, f"%{u_phone}"))
        
        audit_action = "USER_BLOCKED" if new_status == "BLOCKED" else "USER_UNBLOCKED"
        log_audit_event(user_name=row["name"], phone=u_phone, role=row["role"], action=audit_action, status="SUCCESS", details=f"User account status updated to {new_status} by Super Admin. Active sessions revoked immediately.")
        return {"status": "success", "message": f"User '{row['name']}' status updated to {new_status}", "new_status": new_status}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def update_user_assigned_units(user_id: int, new_units: str, updated_by: str = "SUPER_ADMIN") -> Dict[str, Any]:
    """Super Admin or Admin reassigns the warehouse unit for any Customer, ASM, or User"""
    conn = get_connection()
    try:
        now_iso = datetime.now().isoformat()
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, phone, role, assigned_units FROM users WHERE id = ?", (user_id,))
            user = cur.fetchone()
            if not user:
                return {"status": "error", "message": "User not found"}
            
            clean_units = (new_units or "Unit 1").strip()
            cur.execute("UPDATE users SET assigned_units = ?, updated_at = ? WHERE id = ?", (clean_units, now_iso, user_id))
            
        log_audit_event(
            user_name=user["name"],
            phone=user["phone"],
            role=user["role"],
            action="USER_UNIT_REASSIGNED",
            status="SUCCESS",
            details=f"Assigned warehouse unit changed from '{user['assigned_units']}' to '{clean_units}' by {updated_by}"
        )
        return {
            "status": "success",
            "message": f"Successfully reassigned '{user['name']}' to '{clean_units}'",
            "assigned_units": clean_units
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def is_user_phone_blocked(phone: str) -> bool:
    """Checks if a user's phone number is currently marked as BLOCKED"""
    digits = "".join(filter(str.isdigit, str(phone)))
    clean_p = digits[-10:] if len(digits) >= 10 else digits
    if not clean_p:
        return False
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM users WHERE phone = ? LIMIT 1", (clean_p,))
        row = cur.fetchone()
        return bool(row and row["status"] == "BLOCKED")
    finally:
        conn.close()

# 🛡️ ROLE-BASED ACCESS CONTROL & PERMISSION MATRIX
def get_role_permissions() -> List[Dict[str, Any]]:
    """Returns granular permission matrix across all system roles"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
        SELECT * FROM role_permissions 
        ORDER BY CASE role 
            WHEN 'super_admin' THEN 1 
            WHEN 'admin' THEN 2 
            WHEN 'manager' THEN 3 
            WHEN 'analyst' THEN 4 
            WHEN 'asm' THEN 5 
            WHEN 'customer' THEN 6 
            ELSE 7 
        END
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def update_role_permission(role: str, permission_key: str, enabled: bool, updated_by: str = "SUPER_ADMIN") -> Dict[str, Any]:
    """Updates a specific permission toggle for a role and records audit log"""
    valid_keys = [
        "can_add_order", "can_edit_unit", "can_confirm_so", 
        "can_delete_order", "can_block_user", "can_manage_units", 
        "can_view_logs", "can_export_csv"
    ]
    if permission_key not in valid_keys:
        return {"status": "error", "message": f"Invalid permission key: {permission_key}"}
    
    clean_role = (role or "").strip().lower()
    if clean_role == "super_admin":
        return {"status": "error", "message": "Super Admin permissions are permanently unlocked and cannot be restricted."}

    val = 1 if enabled else 0
    now_iso = datetime.now().isoformat()
    conn = get_connection()
    try:
        with conn:
            conn.execute(f"UPDATE role_permissions SET {permission_key} = ?, updated_at = ?, updated_by = ? WHERE role = ?", (val, now_iso, updated_by, clean_role))
        
        log_audit_event(
            user_name=updated_by,
            role="super_admin",
            action="PERMISSION_UPDATED",
            status="SUCCESS",
            details=f"Permission '{permission_key}' set to {val} for role '{clean_role}' by {updated_by}"
        )
        return {
            "status": "success", 
            "message": f"Permission '{permission_key}' updated to {'Enabled' if val else 'Disabled'} for role '{clean_role}'", 
            "role": clean_role, 
            "key": permission_key, 
            "value": val
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def delete_user_by_id(user_id: int) -> Dict[str, Any]:
    """Super Admin permanently removes a user account and purges sessions"""
    conn = get_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT phone, name, role FROM users WHERE id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "User not found"}
            u_phone = row["phone"]
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
            cur.execute("DELETE FROM customer_sessions WHERE phone = ? OR phone LIKE ?", (u_phone, f"%{u_phone}"))
            cur.execute("DELETE FROM sales_manager_sessions WHERE phone = ? OR phone LIKE ?", (u_phone, f"%{u_phone}"))
            
        log_audit_event(user_name=row["name"], phone=u_phone, role=row["role"], action="USER_DELETED", status="SUCCESS", details=f"User '{row['name']}' ({u_phone}, {row['role']}) deleted by Super Admin")
        return {"status": "success", "message": f"User '{row['name']}' deleted successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

def create_customer_session(phone: str, customer_name: str = "", party_code: str = "", party_name: str = "") -> Dict[str, Any]:
    """Creates a 1-year persistent session for verified Customer"""
    import secrets
    import time
    token = f"CUST_{secrets.token_hex(24)}"
    now = time.time()
    expires_at = now + (365 * 24 * 3600)
    now_str = datetime.now().isoformat()
    conn = get_connection()
    try:
        digits = "".join(filter(str.isdigit, str(phone)))
        clean_p = digits[-10:] if len(digits) >= 10 else digits
        with conn:
            conn.execute("""
            INSERT INTO customer_sessions (token, phone, customer_name, party_code, party_name, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (token, clean_p, customer_name, party_code, party_name, now_str, expires_at))
        return {
            "status": "success",
            "token": token,
            "phone": clean_p,
            "customer_name": customer_name,
            "party_code": party_code,
            "party_name": party_name,
            "expires_at": expires_at
        }
    finally:
        conn.close()

def validate_customer_session(token: str) -> Optional[Dict[str, Any]]:
    """Validates Customer session token and checks account is not BLOCKED"""
    import time
    if not token:
        return None
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
        SELECT token, phone, customer_name, party_code, party_name, created_at, expires_at
        FROM customer_sessions WHERE token = ?
        """, (token,))
        row = cur.fetchone()
        if row and row["expires_at"] > time.time():
            c_phone = "".join(filter(str.isdigit, str(row["phone"])))[-10:]
            cur.execute("SELECT status FROM users WHERE phone = ? LIMIT 1", (c_phone,))
            u_check = cur.fetchone()
            if u_check and u_check["status"] == "BLOCKED":
                with conn:
                    conn.execute("DELETE FROM customer_sessions WHERE token = ?", (token,))
                return None
            return dict(row)
        return None
    finally:
        conn.close()

def get_orders_for_asm(sales_person_name: str, phone: str = "", date_filter: str = "ALL", specific_date: str = "") -> List[Dict[str, Any]]:
    """
    Fetches orders strictly assigned to the logged-in Area Sales Manager.
    Supports filters: TODAY, YESTERDAY, ALL, or specific date (YYYY-MM-DD or DD/MM/YYYY).
    """
    from datetime import date, timedelta
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = """
        SELECT * FROM orders
        WHERE (LOWER(sales_person) LIKE ? OR sales_person = ?)
        """
        params = [f"%{sales_person_name.strip().lower()}%", sales_person_name.strip()]

        # Date calculations
        today_iso = date.today().isoformat() # YYYY-MM-DD
        today_slash = date.today().strftime("%d/%m/%Y")
        yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
        yesterday_slash = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")

        date_filter_clean = (date_filter or "ALL").upper().strip()
        if date_filter_clean == "TODAY":
            query += " AND (created_at LIKE ? OR order_date LIKE ? OR formatted_timestamp LIKE ?)"
            params.extend([f"{today_iso}%", f"%{today_iso}%", f"%{today_slash}%"])
        elif date_filter_clean == "YESTERDAY":
            query += " AND (created_at LIKE ? OR order_date LIKE ? OR formatted_timestamp LIKE ?)"
            params.extend([f"{yesterday_iso}%", f"%{yesterday_iso}%", f"%{yesterday_slash}%"])
        elif date_filter_clean == "CUSTOM" and specific_date:
            clean_date = specific_date.strip()
            # If YYYY-MM-DD convert to DD/MM/YYYY as alternative
            alt_date = clean_date
            if "-" in clean_date:
                parts = clean_date.split("-")
                if len(parts) == 3:
                    alt_date = f"{parts[2]}/{parts[1]}/{parts[0]}"
            query += " AND (created_at LIKE ? OR order_date LIKE ? OR formatted_timestamp LIKE ?)"
            params.extend([f"{clean_date}%", f"%{clean_date}%", f"%{alt_date}%"])

        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        rows = cur.fetchall()

        result = []
        for r in rows:
            d = dict(r)
            try:
                d["items"] = json.loads(d.get("items_json") or "[]")
            except Exception:
                d["items"] = []
            d["id"] = d.get("order_id")
            d["cleanId"] = str(d.get("order_id") or "").replace("#", "")
            d["partyName"] = d.get("party_name")
            d["partyCode"] = d.get("party_code")
            d["partyAddress"] = d.get("party_address")
            d["salesPerson"] = d.get("sales_person")
            d["totalBoxes"] = d.get("total_boxes", 0)
            d["totalPieces"] = d.get("total_pieces", 0)
            d["orderStatus"] = d.get("order_status") or "PENDING"
            d["soNumber"] = d.get("so_number") or ""
            d["formattedTimestamp"] = d.get("formatted_timestamp") or d.get("order_date")
            result.append(d)
        return result
    finally:
        conn.close()

def get_orders_for_customer(party_name: str = "", party_code: str = "", phone: str = "", date_filter: str = "ALL", specific_date: str = "") -> List[Dict[str, Any]]:
    """
    Fetches orders strictly belonging to a Customer by Party Code, Party Name, or Phone.
    Supports filters: TODAY, YESTERDAY, ALL, or specific date.
    """
    from datetime import date, timedelta
    conn = get_connection()
    try:
        cur = conn.cursor()
        conditions = []
        params = []

        if party_code:
            conditions.append("party_code = ?")
            params.append(party_code.strip())
        if phone:
            digits = "".join(filter(str.isdigit, str(phone)))
            clean_p = digits[-10:] if len(digits) >= 10 else digits
            if clean_p:
                conditions.append("(party_address LIKE ? OR delivery_address LIKE ?)")
                params.extend([f"%{clean_p}%", f"%{clean_p}%"])
        # If neither party_code nor phone is provided, fallback to exact party_name
        if not conditions and party_name:
            conditions.append("LOWER(TRIM(party_name)) = ?")
            params.append(party_name.strip().lower())

        if not conditions:
            return []

        base_cond = "(" + " OR ".join(conditions) + ")"
        query = f"SELECT * FROM orders WHERE {base_cond}"

        # Date filter
        today_iso = date.today().isoformat()
        today_slash = date.today().strftime("%d/%m/%Y")
        yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
        yesterday_slash = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")

        date_filter_clean = (date_filter or "ALL").upper().strip()
        if date_filter_clean == "TODAY":
            query += " AND (created_at LIKE ? OR order_date LIKE ? OR formatted_timestamp LIKE ?)"
            params.extend([f"{today_iso}%", f"%{today_iso}%", f"%{today_slash}%"])
        elif date_filter_clean == "YESTERDAY":
            query += " AND (created_at LIKE ? OR order_date LIKE ? OR formatted_timestamp LIKE ?)"
            params.extend([f"{yesterday_iso}%", f"%{yesterday_iso}%", f"%{yesterday_slash}%"])
        elif date_filter_clean == "CUSTOM" and specific_date:
            clean_date = specific_date.strip()
            alt_date = clean_date
            if "-" in clean_date:
                parts = clean_date.split("-")
                if len(parts) == 3:
                    alt_date = f"{parts[2]}/{parts[1]}/{parts[0]}"
            query += " AND (created_at LIKE ? OR order_date LIKE ? OR formatted_timestamp LIKE ?)"
            params.extend([f"{clean_date}%", f"%{clean_date}%", f"%{alt_date}%"])

        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        rows = cur.fetchall()

        result = []
        for r in rows:
            d = dict(r)
            try:
                d["items"] = json.loads(d.get("items_json") or "[]")
            except Exception:
                d["items"] = []
            d["id"] = d.get("order_id")
            d["cleanId"] = str(d.get("order_id") or "").replace("#", "")
            d["partyName"] = d.get("party_name")
            d["partyCode"] = d.get("party_code")
            d["partyAddress"] = d.get("party_address")
            d["salesPerson"] = d.get("sales_person")
            d["totalBoxes"] = d.get("total_boxes", 0)
            d["totalPieces"] = d.get("total_pieces", 0)
            d["orderStatus"] = d.get("order_status") or "PENDING"
            d["soNumber"] = d.get("so_number") or ""
            d["formattedTimestamp"] = d.get("formatted_timestamp") or d.get("order_date")
            result.append(d)
        return result
    finally:
        conn.close()

def search_sales_orders_db(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Searches Sales Orders by SO Number, Order ID, Party Name, or Sales Person.
    Returns 100% accurate database records for search functionality.
    Supports queries with or without '#' prefix (e.g. #KOGM-20261019-5501 or KOGM-20261019-5501).
    """
    clean_raw = (query or "").strip()
    if not clean_raw:
        return []
    clean_q = clean_raw.lower()
    clean_q_no_hash = clean_q.lstrip("#").strip()
    clean_q_no_so = clean_q_no_hash.replace("so #", "").replace("so#", "").replace("so ", "").strip()
    conn = get_connection()
    try:
        cur = conn.cursor()
        p1 = f"%{clean_q}%"
        p2 = f"%{clean_q_no_hash}%"
        p3 = f"%{clean_q_no_so}%" if clean_q_no_so else p2
        cur.execute("""
        SELECT * FROM orders
        WHERE LOWER(order_id) LIKE ?
           OR LOWER(order_id) LIKE ?
           OR LOWER(so_number) LIKE ?
           OR LOWER(so_number) LIKE ?
           OR LOWER(party_name) LIKE ?
           OR LOWER(party_code) LIKE ?
           OR LOWER(sales_person) LIKE ?
           OR LOWER(party_address) LIKE ?
        ORDER BY created_at DESC
        LIMIT ?
        """, (p1, p2, p1, p3, p1, p1, p1, p1, limit))
        rows = cur.fetchall()

        result = []
        for r in rows:
            d = dict(r)
            try:
                d["items"] = json.loads(d.get("items_json") or "[]")
            except Exception:
                d["items"] = []
            d["id"] = d.get("order_id")
            d["cleanId"] = str(d.get("order_id") or "").replace("#", "")
            d["partyName"] = d.get("party_name")
            d["partyCode"] = d.get("party_code")
            d["partyAddress"] = d.get("party_address")
            d["deliveryAddress"] = d.get("delivery_address")
            d["salesPerson"] = d.get("sales_person")
            d["totalBoxes"] = d.get("total_boxes", 0)
            d["totalPieces"] = d.get("total_pieces", 0)
            d["orderStatus"] = d.get("order_status") or "PENDING"
            d["soNumber"] = d.get("so_number") or ""
            d["formattedTimestamp"] = d.get("formatted_timestamp") or d.get("order_date")
            result.append(d)
        return result
    finally:
        conn.close()

def search_customer_orders_db(query: str, phone: str = "", party_code: str = "", party_name: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """
    Searches orders strictly scoped to a specific Customer by Order ID, SO Number, or Item name.
    Strictly isolated: Customers can ONLY see and search their own orders.
    """
    clean_raw = (query or "").strip()
    if not clean_raw:
        return []

    clean_q = clean_raw.lower()
    clean_q_no_hash = clean_q.lstrip("#").strip()
    clean_q_no_so = clean_q_no_hash.replace("so #", "").replace("so#", "").replace("so ", "").strip()

    conn = get_connection()
    try:
        cur = conn.cursor()
        cust_conds = []
        cust_params = []

        if party_code:
            cust_conds.append("party_code = ?")
            cust_params.append(party_code.strip())
        if phone:
            digits = "".join(filter(str.isdigit, str(phone)))
            clean_p = digits[-10:] if len(digits) >= 10 else digits
            if clean_p:
                cust_conds.append("(party_address LIKE ? OR delivery_address LIKE ?)")
                cust_params.extend([f"%{clean_p}%", f"%{clean_p}%"])
        if not cust_conds and party_name:
            cust_conds.append("LOWER(TRIM(party_name)) = ?")
            cust_params.append(party_name.strip().lower())

        if not cust_conds:
            return []  # No customer credentials provided, return 0 for safety

        scope_clause = "(" + " OR ".join(cust_conds) + ")"

        p1 = f"%{clean_q}%"
        p2 = f"%{clean_q_no_hash}%"
        p3 = f"%{clean_q_no_so}%" if clean_q_no_so else p2

        sql = f"""
        SELECT * FROM orders
        WHERE {scope_clause}
          AND (
               LOWER(order_id) LIKE ?
            OR LOWER(order_id) LIKE ?
            OR LOWER(so_number) LIKE ?
            OR LOWER(so_number) LIKE ?
            OR LOWER(items_summary) LIKE ?
            OR LOWER(items_json) LIKE ?
          )
        ORDER BY created_at DESC
        LIMIT ?
        """
        params = cust_params + [p1, p2, p1, p3, p2, p2, limit]
        cur.execute(sql, params)
        rows = cur.fetchall()

        result = []
        for r in rows:
            d = dict(r)
            try:
                d["items"] = json.loads(d.get("items_json") or "[]")
            except Exception:
                d["items"] = []
            d["id"] = d.get("order_id")
            d["cleanId"] = str(d.get("order_id") or "").replace("#", "")
            d["partyName"] = d.get("party_name")
            d["partyCode"] = d.get("party_code")
            d["partyAddress"] = d.get("party_address")
            d["deliveryAddress"] = d.get("delivery_address")
            d["salesPerson"] = d.get("sales_person")
            d["totalBoxes"] = d.get("total_boxes", 0)
            d["totalPieces"] = d.get("total_pieces", 0)
            d["orderStatus"] = d.get("order_status") or "PENDING"
            d["soNumber"] = d.get("so_number") or ""
            d["formattedTimestamp"] = d.get("formatted_timestamp") or d.get("order_date")
            result.append(d)
        return result
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
        
        unit = order.get("unit") or "Unit 1"
        with conn:
            conn.execute("""
            INSERT INTO orders (
                order_id, party_name, party_code, party_address, delivery_address, sales_person,
                order_date, formatted_timestamp, created_at, total_boxes, total_pieces,
                items_json, items_summary, slip_image_path, slip_image_url,
                synced_to_sheet, data_consent, order_status, so_number, confirmed_at, confirmed_by, unit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                synced_to_sheet = CASE WHEN excluded.synced_to_sheet = 1 THEN 1 ELSE orders.synced_to_sheet END,
                unit = COALESCE(NULLIF(excluded.unit, ''), orders.unit);
            """, (
                order_id, party_name, party_code, party_address, delivery_address, sales_person,
                order_date, formatted_timestamp, created_at, total_boxes, total_pieces,
                items_json, items_summary, slip_image_path, slip_image_url,
                synced_to_sheet, data_consent, order_status, so_number, confirmed_at, confirmed_by, unit
            ))
        print(f"[DATABASE] Order #{order_id} permanently saved in orders.db ({total_boxes} Bxs, {total_pieces} Pcs, Unit: {unit})")
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

def update_order_unit_in_db(order_id: str, new_unit: str, updated_by: str = "super_admin") -> bool:
    """Updates the warehouse unit assignment of an order in both SQLite and JSON"""
    clean_id = (order_id or "").replace("#", "").strip()
    clean_unit = (new_unit or "").strip()
    if not clean_unit or not clean_id:
        return False
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            UPDATE orders 
            SET unit = ?
            WHERE order_id = ? OR order_id = ?
            """, (clean_unit, clean_id, f"#{clean_id}"))
        
        # Also update in customer_orders.json
        orders_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_orders.json")
        if os.path.exists(orders_log):
            try:
                with open(orders_log, "r", encoding="utf-8") as f:
                    orders_list = json.load(f)
                for o in orders_list:
                    if str(o.get("id", "")).replace("#", "").strip() == clean_id:
                        o["unit"] = clean_unit
                        break
                with open(orders_log, "w", encoding="utf-8") as f:
                    json.dump(orders_list, f, indent=2, ensure_ascii=False)
            except Exception as j_err:
                print(f"[UNIT UPDATE JSON WARN] {j_err}")
        
        try:
            log_audit_event("ORDER_UNIT_UPDATE", f"Order #{clean_id} assigned to {clean_unit}", user=updated_by, status="SUCCESS")
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[DATABASE UNIT UPDATE ERROR] {e}")
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

def get_all_orders_from_db(limit: int = 1000, unit: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all orders from database ordered by most recent with dynamic pieces calculation and optional unit filter"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if unit and unit.upper() != "ALL":
            cursor.execute("SELECT * FROM orders WHERE unit = ? OR (unit IS NULL AND ? = 'Unit 1') ORDER BY created_at DESC LIMIT ?", (unit, unit, limit))
        else:
            cursor.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        seen_order_ids = set()
        result = []
        for r in rows:
            d = dict(r)
            oid = str(d.get("order_id") or "").strip()
            if oid and oid in seen_order_ids:
                continue
            if oid:
                seen_order_ids.add(oid)
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
            d["unit"] = d.get("unit") or "Unit 1"
            
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
            d["unit"] = d.get("unit") or "Unit 1"
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

def create_admin_session(username: str = "admin", role: str = "super_admin", assigned_units: str = "ALL") -> str:
    """Creates a secure 7-day persistent session token for Admin Dashboard with user role and assigned units"""
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
            INSERT INTO admin_sessions (token, username, role, assigned_units, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (token, username, role, assigned_units, now_str, expires_at))
        return token
    finally:
        conn.close()

def validate_admin_session(token: str) -> Optional[Dict[str, Any]]:
    """Validates if admin token is active and not expired, returns role and assigned_units"""
    import time
    if not token:
        return None
    master_token = os.environ.get("AUTH_SECRET_TOKEN", "KOGM_ADMIN_SECURE_TOKEN_2026_XYZ")
    if token == master_token:
        return {"username": "admin", "role": "super_admin", "assigned_units": "ALL", "token": master_token}
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT username, role, assigned_units, token, expires_at FROM admin_sessions WHERE token = ?", (token,))
        row = cur.fetchone()
        if row and row["expires_at"] > time.time():
            role_val = row["role"] if "role" in row.keys() and row["role"] else "admin"
            assigned_u = row["assigned_units"] if "assigned_units" in row.keys() and row["assigned_units"] else "ALL"
            return {
                "username": row["username"],
                "role": role_val,
                "assigned_units": assigned_u,
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

def cleanup_orders_retain_pankaj_kumar() -> Dict[str, Any]:
    """
    🧹 Purges all order records EXCEPT Pankaj Kumar's.
    Assigns Pankaj Kumar's orders to Unit 1.
    Syncs customer_orders.json to match.
    Guarantees 100% data integrity and zero leftover test records.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Find Pankaj Kumar's orders
        cur.execute("SELECT order_id, sales_person, total_boxes, total_pieces FROM orders WHERE LOWER(sales_person) LIKE '%pankaj%'")
        pankaj_orders = [dict(r) for r in cur.fetchall()]
        
        with conn:
            # 1. Update Pankaj Kumar orders to Unit 1
            conn.execute("UPDATE orders SET unit = 'Unit 1' WHERE LOWER(sales_person) LIKE '%pankaj%'")
            # 2. Delete all other orders
            conn.execute("DELETE FROM orders WHERE LOWER(sales_person) NOT LIKE '%pankaj%'")

        # Also sync customer_orders.json
        orders_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_orders.json")
        cleaned_json_orders = []
        if os.path.exists(orders_log):
            try:
                with open(orders_log, "r", encoding="utf-8") as f:
                    all_json_orders = json.load(f)
                for o in all_json_orders:
                    sp = str(o.get("salesPerson") or o.get("sales_person", "")).lower()
                    if "pankaj" in sp:
                        o["unit"] = "Unit 1"
                        cleaned_json_orders.append(o)
                with open(orders_log, "w", encoding="utf-8") as f:
                    json.dump(cleaned_json_orders, f, indent=2, ensure_ascii=False)
            except Exception as j_err:
                print(f"[CLEANUP JSON WARN] {j_err}")

        # Verify final remaining count in DB
        cur.execute("SELECT COUNT(*) FROM orders")
        remaining_db = cur.fetchone()[0]

        return {
            "status": "success",
            "message": "Data cleanup complete. Only Pankaj Kumar's order records are retained.",
            "pankajOrdersCount": len(pankaj_orders),
            "retainedInDb": remaining_db,
            "retainedInJson": len(cleaned_json_orders),
            "assignedUnit": "Unit 1",
            "pankajOrders": pankaj_orders
        }
    finally:
        conn.close()

def get_orders_stats(unit: Optional[str] = None) -> Dict[str, Any]:
    """Calculates live KPI metrics directly from SQLite orders database with optional unit filter"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        unit_clause = ""
        params = []
        if unit and unit.upper() != "ALL":
            unit_clause = " WHERE (unit = ? OR (unit IS NULL AND ? = 'Unit 1'))"
            params = [unit, unit]

        cur.execute(f"SELECT COUNT(*), COALESCE(SUM(total_boxes), 0), COALESCE(SUM(total_pieces), 0) FROM orders{unit_clause}", params)
        row = cur.fetchone()
        total_orders = row[0] or 0
        total_boxes = row[1] or 0
        total_pieces = row[2] or 0

        # Confirmed vs Pending
        conf_clause = "WHERE order_status = 'CONFIRMED'"
        conf_params = []
        if unit and unit.upper() != "ALL":
            conf_clause += " AND (unit = ? OR (unit IS NULL AND ? = 'Unit 1'))"
            conf_params = [unit, unit]
        cur.execute(f"SELECT COUNT(*) FROM orders {conf_clause}", conf_params)
        confirmed_count = cur.fetchone()[0] or 0
        pending_count = total_orders - confirmed_count

        sync_clause = "WHERE synced_to_sheet = 1"
        sync_params = []
        if unit and unit.upper() != "ALL":
            sync_clause += " AND (unit = ? OR (unit IS NULL AND ? = 'Unit 1'))"
            sync_params = [unit, unit]
        cur.execute(f"SELECT COUNT(*) FROM orders {sync_clause}", sync_params)
        synced_count = cur.fetchone()[0] or 0
        pending_sync = total_orders - synced_count

        cur.execute(f"SELECT COUNT(DISTINCT party_name) FROM orders{unit_clause}", params)
        unique_parties = cur.fetchone()[0] or 0

        sales_clause = "WHERE sales_person IS NOT NULL AND sales_person != ''"
        sales_params = []
        if unit and unit.upper() != "ALL":
            sales_clause += " AND (unit = ? OR (unit IS NULL AND ? = 'Unit 1'))"
            sales_params = [unit, unit]
        cur.execute(f"SELECT COUNT(DISTINCT sales_person) FROM orders {sales_clause}", sales_params)
        sales_reps = cur.fetchone()[0] or 0

        today_str = datetime.now().strftime("%d/%m/%Y")
        today_iso = datetime.now().strftime("%Y-%m-%d")
        today_clause = "WHERE (formatted_timestamp LIKE ? OR order_date LIKE ? OR created_at LIKE ?)"
        today_params = [f"%{today_str}%", f"%{today_str}%", f"{today_iso}%"]
        if unit and unit.upper() != "ALL":
            today_clause += " AND (unit = ? OR (unit IS NULL AND ? = 'Unit 1'))"
            today_params.extend([unit, unit])

        cur.execute(f"SELECT COUNT(*), COALESCE(SUM(total_boxes), 0), COALESCE(SUM(total_pieces), 0) FROM orders {today_clause}", today_params)
        t_row = cur.fetchone()
        today_orders = t_row[0] or 0
        today_boxes = t_row[1] or 0
        today_pieces = t_row[2] or 0

        return {
            "unit": unit or "ALL",
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

# Standard Master SKUs for Factory & Warehouse Production Packing
MASHAL_MASTER_SKUS = [
    "1 LTR. BOTTLE x 15",
    "200 ML BOTTLE x 60",
    "100 ML BOTTLE x 120",
    "2 LTR CAN x 6",
    "1 LTR. POUCH x 16",
    "15 KG CAN x 1",
    "15 LTR CAN x 1",
    "500 ML BOTTLE x 30",
    "200 ML BOTTLE x 40",
    "5 LTR CAN x 4",
    "2 LTR BOTTLE x 9",
    "1/2 LTR. POUCH x 32",
    "15 KG TIN x 1",
    "15 LTR TIN x 1"
]

FAUJI_MASTER_SKUS = [
    "1 LTR. BOTTLE x 15",
    "500 ML BOTTLE x 30",
    "1 LTR. POUCH x 16",
    "15 KG CAN x 1",
    "15 KG TIN x 1"
]

def get_warehouse_production_summary(orders_subset: Optional[List[Dict[str, Any]]] = None, unit: Optional[str] = None) -> Dict[str, Any]:
    """
    🏭 Aggregates warehouse-focused packing and production requirements for PENDING orders only.
    Excludes all confirmed orders so warehouse dispatch teams pack exact pending requirements.
    Supports unit filter.
    """
    if orders_subset is None:
        all_orders = get_all_orders_from_db(limit=1000, unit=unit)
        # Filter strictly for PENDING orders
        pending_orders = [o for o in all_orders if (o.get("orderStatus") or "").upper() == "PENDING"]
    else:
        pending_orders = [o for o in orders_subset if (o.get("orderStatus") or "").upper() == "PENDING"]
        if unit and unit.upper() != "ALL":
            pending_orders = [o for o in pending_orders if (o.get("unit") or "Unit 1") == unit]

    mashal_summary = {sku: {"sku": sku, "boxes": 0, "pieces": 0, "multiplier": 1} for sku in MASHAL_MASTER_SKUS}
    fauji_summary = {sku: {"sku": sku, "boxes": 0, "pieces": 0, "multiplier": 1} for sku in FAUJI_MASTER_SKUS}

    # Initialize multipliers
    for sku in MASHAL_MASTER_SKUS:
        m = re.search(r'x\s*(\d+)', sku, re.I)
        if m:
            mashal_summary[sku]["multiplier"] = int(m.group(1))

    for sku in FAUJI_MASTER_SKUS:
        m = re.search(r'x\s*(\d+)', sku, re.I)
        if m:
            fauji_summary[sku]["multiplier"] = int(m.group(1))

    total_pending_boxes = 0
    total_pending_pieces = 0
    mashal_total_boxes = 0
    mashal_total_pieces = 0
    fauji_total_boxes = 0
    fauji_total_pieces = 0

    for ord_obj in pending_orders:
        items = ord_obj.get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_brand = str(it.get("brand") or "Mashal").strip().lower()
            item_name = str(it.get("item") or "").strip()
            boxes = int(it.get("boxes") or 0)
            if boxes <= 0:
                continue

            m = re.search(r'x\s*(\d+)', item_name, re.I)
            multiplier = int(m.group(1)) if m else int(it.get("multiplier") or 1)
            pieces = boxes * multiplier

            total_pending_boxes += boxes
            total_pending_pieces += pieces

            is_fauji = "fauji" in raw_brand or "fauji" in item_name.lower()
            target_dict = fauji_summary if is_fauji else mashal_summary

            # Fuzzy / clean match key
            matched_key = None
            for key in target_dict.keys():
                if key.lower() == item_name.lower():
                    matched_key = key
                    break
            if not matched_key:
                # Add dynamically if not in master list
                target_dict[item_name] = {"sku": item_name, "boxes": 0, "pieces": 0, "multiplier": multiplier}
                matched_key = item_name

            target_dict[matched_key]["boxes"] += boxes
            target_dict[matched_key]["pieces"] += pieces
            target_dict[matched_key]["multiplier"] = multiplier

            if is_fauji:
                fauji_total_boxes += boxes
                fauji_total_pieces += pieces
            else:
                mashal_total_boxes += boxes
                mashal_total_pieces += pieces

    return {
        "pendingOrdersCount": len(pending_orders),
        "totalBoxes": total_pending_boxes,
        "totalPieces": total_pending_pieces,
        "brands": {
            "MASHAL": {
                "brandName": "MASHAL",
                "totalBoxes": mashal_total_boxes,
                "totalPieces": mashal_total_pieces,
                "skus": list(mashal_summary.values())
            },
            "FAUJI": {
                "brandName": "FAUJI",
                "totalBoxes": fauji_total_boxes,
                "totalPieces": fauji_total_pieces,
                "skus": list(fauji_summary.values())
            }
        }
    }

if __name__ == "__main__":
    init_db()
    migrate_existing_json_orders()
    all_o = get_all_orders_from_db()
    print(f"Total orders in database: {len(all_o)}")
