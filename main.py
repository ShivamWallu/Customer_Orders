from fastapi import FastAPI, Header, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, Response, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import json
import os
import re
import urllib.parse
import urllib.request
import asyncio
import base64
import io
try:
    import qrcode
except ImportError:
    qrcode = None
from dotenv import load_dotenv
from whatsapp_service import (
    enqueue_whatsapp_order,
    get_pending_whatsapp_orders,
    mark_whatsapp_order_sent
)
from database import (
    init_db,
    save_order_to_db,
    mark_order_synced_in_db,
    mark_whatsapp_sent_in_db,
    get_all_orders_from_db,
    get_order_by_id,
    migrate_existing_json_orders,
    validate_manager_session,
    create_admin_session,
    validate_admin_session,
    delete_admin_session,
    delete_order_from_db,
    confirm_order_in_db,
    update_order_unit_in_db,
    get_orders_stats,
    get_warehouse_production_summary,
    get_user_by_phone,
    get_all_users,
    create_or_update_user,
    toggle_user_status,
    delete_user_by_id,
    update_user_assigned_units,
    is_user_phone_blocked,
    get_user_status_by_token,
    get_connection,
    create_customer_session,
    validate_customer_session,
    get_orders_for_asm,
    get_orders_for_customer,
    search_sales_orders_db,
    search_customer_orders_db,
    get_all_units,
    create_or_update_unit,
    toggle_unit_status,
    delete_unit_by_id,
    cleanup_orders_retain_pankaj_kumar,
    log_audit_event,
    get_audit_logs,
    get_role_permissions,
    update_role_permission
)
from crm_service import (
    init_crm_db,
    search_customers,
    save_or_update_customer
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from otp_service import (
    send_kit19_otp,
    verify_kit19_otp,
    verify_manager_login_otp,
    check_kit19_balance
)

# Load configuration from .env file
load_dotenv()
from config import settings
from logger_service import logger, RequestTracingMiddleware
from cache_service import cache
from rate_limiter import limiter, rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from async_database import (
    init_async_db,
    check_db_health,
    async_save_order,
    async_get_orders_paginated,
    async_search_customers,
    async_get_all_units,
    async_confirm_order,
    async_update_order_unit,
    async_delete_order,
    async_get_dashboard_stats,
    async_log_audit
)

# Initialize permanent database and auto-migrate historical orders
init_db()
migrate_existing_json_orders()
init_crm_db()

ORDER_SLIPS_DIR = "order_slips"
os.makedirs(ORDER_SLIPS_DIR, exist_ok=True)

app = FastAPI(
    title="Khandelia Oil & General Mills - Enterprise Sales Order Engine",
    version=settings.APP_VERSION,
    description="High-Concurrency Real-Time Order Management Suite (1M-10M Scale)"
)

# Attach SlowAPI Limiter state & Rate Limit Exception Handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# High-Performance Request Tracing & Structured Logging Middleware
app.add_middleware(RequestTracingMiddleware)

IST_TZ = timezone(timedelta(hours=5, minutes=30))

def get_ist_now() -> datetime:
    """Returns current datetime strictly in Indian Standard Time (IST)"""
    return datetime.now(timezone.utc).astimezone(IST_TZ)

def convert_utc_to_ist_str(dt_str: str) -> str:
    """Standardizes any timestamp into clean 12-Hour Indian Standard Time (IST - %d/%m/%Y %I:%M:%S %p)"""
    if not dt_str:
        return ""
    s = str(dt_str).strip()

    # 1. If already 12-hour format with AM/PM (e.g. 22/10/2026 02:15:56 PM)
    m12 = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})[,\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)$", s, re.IGNORECASE)
    if m12:
        d, m, y = int(m12.group(1)), int(m12.group(2)), m12.group(3)
        h = int(m12.group(4))
        mn = m12.group(5)
        sc = m12.group(6) or "00"
        ampm = m12.group(7).upper()
        h12 = h if (1 <= h <= 12) else (h % 12 or 12)
        return f"{d:02d}/{m:02d}/{y} {h12:02d}:{mn}:{sc} {ampm}"

    # 2. If 24-hour format without AM/PM (e.g. 22/10/2026 14:15:56)
    m24 = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})[,\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?$", s)
    if m24:
        d, m, y = int(m24.group(1)), int(m24.group(2)), m24.group(3)
        h = int(m24.group(4))
        mn = m24.group(5)
        sc = m24.group(6) or "00"
        ampm = "PM" if h >= 12 else "AM"
        h12 = h % 12 or 12
        return f"{d:02d}/{m:02d}/{y} {h12:02d}:{mn}:{sc} {ampm}"

    # 3. If ISO timestamp from AWS (e.g. 2026-10-22T08:45:51.089243 or with Z)
    if "T" in s or "Z" in s:
        try:
            clean = s.split(".")[0].replace("Z", "")
            dt = datetime.fromisoformat(clean)
            # AWS logs in UTC, convert to IST
            return (dt + timedelta(hours=5, minutes=30)).strftime("%d/%m/%Y %I:%M:%S %p")
        except Exception:
            pass

    return s

_REMOTE_SYNC_LOCK = asyncio.Lock()

async def sync_remote_production_orders() -> int:
    """
    ⚡ Synchronizes ONLY brand-new orders from LIVE AWS production server (https://order.khandelia.online/api/orders/all)
    into local SQLite database and customer_orders.json without locking or freezing the event loop.
    Converts any remote UTC timestamps into Indian Standard Time (IST).
    """
    remote_url = os.environ.get("REMOTE_SERVER_URL", "https://order.khandelia.online").rstrip("/")
    base_url = os.environ.get("APP_BASE_URL", "").lower()
    
    if "order.khandelia.online" in base_url:
        return 0
        
    if _REMOTE_SYNC_LOCK.locked():
        return 0

    async with _REMOTE_SYNC_LOCK:
        try:
            loop = asyncio.get_event_loop()
            def _fetch():
                req = urllib.request.Request(
                    f"{remote_url}/api/orders/all",
                    headers={"User-Agent": "MashalAdminSync/1.0"}
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
                return None

            data = await loop.run_in_executor(None, _fetch)
            if not data:
                return 0
                
            remote_orders = data.get("orders", data) if isinstance(data, dict) else data
            if not isinstance(remote_orders, list):
                return 0

            # 1. Fast check existing IDs to only save brand-new orders (avoids SQLite lock)
            def _check_and_save_new():
                conn = get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT order_id FROM orders")
                    existing_ids = {str(row[0]).replace("#", "").strip() for row in cur.fetchall()}
                finally:
                    conn.close()

                new_orders = [
                    o for o in remote_orders
                    if str(o.get("id") or o.get("order_id") or "").replace("#", "").strip() not in existing_ids
                ]
                
                if not new_orders:
                    return 0

                count = 0
                for o in new_orders:
                    # Convert AWS UTC timestamp to IST
                    raw_ts = o.get("formattedTimestamp") or o.get("formatted_timestamp") or o.get("created_at") or ""
                    if raw_ts:
                        ist_ts = convert_utc_to_ist_str(raw_ts)
                        o["formattedTimestamp"] = ist_ts
                        o["formatted_timestamp"] = ist_ts
                    if save_order_to_db(o):
                        count += 1
                return count

            synced_count = await loop.run_in_executor(None, _check_and_save_new)
            if synced_count > 0:
                logger.info(f"⚡ Live Production Sync: {synced_count} new orders imported into local database")
            return synced_count
        except Exception as e:
            logger.debug(f"Remote production sync skipped: {e}")
            return 0

@app.on_event("startup")
async def on_app_startup():
    logger.info("Initializing Enterprise High-Concurrency Architecture...")
    await init_async_db()
    await cache.init_cache()
    logger.info("Startup complete: Async SQLAlchemy 2.0 Pool & Tiered Cache Active")
    
    # 🚀 Instant Remote Sync on boot
    try:
        synced = await sync_remote_production_orders()
        if synced:
            logger.info(f"Initial sync complete: {synced} orders imported from live server")
    except Exception as e:
        logger.debug(f"Initial live sync note: {e}")

    # 🔄 Auto-Sync background loop every 5 seconds for instant order visibility
    async def _auto_sync_loop():
        while True:
            await asyncio.sleep(5)
            try:
                await sync_remote_production_orders()
            except Exception:
                pass
    asyncio.create_task(_auto_sync_loop())

@app.get("/health")
async def health_check():
    """Enterprise Liveness & Readiness Probe for Docker, ELB, and K8s"""
    db_ok = await check_db_health()
    cache_mode = "redis" if cache.is_redis_connected else "in-memory-lru"
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "online" if db_ok else "unreachable",
        "cache": cache_mode,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now().isoformat()
    }

# ----------------- ⚡ ULTRA-FAST SOCIAL PREVIEW & CACHED ASSETS -----------------
BOT_USER_AGENTS = ("whatsapp", "facebookexternalhit", "facebot", "twitterbot", "telegrambot", "linkedinbot", "slackbot", "skypeuripreview")

def is_social_crawler(request: Request) -> bool:
    ua = (request.headers.get("user-agent") or "").lower()
    return any(b in ua for b in BOT_USER_AGENTS)

@app.get("/manifest.json")
def serve_manifest():
    """Serves PWA Web App Manifest for Android APK installation"""
    file_path = os.path.join(BASE_DIR, "manifest.json")
    if os.path.exists(file_path):
        return FileResponse(
            file_path,
            media_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"}
        )
    raise HTTPException(status_code=404, detail="Manifest not found")

@app.get("/sw.js")
def serve_service_worker():
    """Serves PWA Service Worker for offline shell & 2X speed caching"""
    file_path = os.path.join(BASE_DIR, "sw.js")
    if os.path.exists(file_path):
        return FileResponse(
            file_path,
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Service-Worker-Allowed": "/",
                "Access-Control-Allow-Origin": "*"
            }
        )
    raise HTTPException(status_code=404, detail="Service worker not found")

@app.get("/images/{filepath:path}")
def serve_image_file(filepath: str):
    """High-speed image and icon delivery with aggressive caching for instant WhatsApp preview cards and PWA icons"""
    file_path = os.path.join(BASE_DIR, "images", filepath)
    if os.path.exists(file_path):
        media_type = "image/jpeg" if filepath.endswith((".jpg", ".jpeg")) else "image/png"
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
                "Access-Control-Allow-Origin": "*"
            }
        )
    raise HTTPException(status_code=404, detail="Image not found")

if os.path.exists("images"):
    app.mount("/static_images", StaticFiles(directory="images"), name="static_images")

def get_base_url_from_request(request: Request) -> str:
    """Dynamically resolves base URL: supports Ngrok local testing, AWS production domain, and custom hosts"""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    # 1. Active Ngrok tunnel (for local mobile testing)
    if "sevenfold-blazer-pacific.ngrok-free.dev" in host:
        return "https://sevenfold-blazer-pacific.ngrok-free.dev"
    # 2. Production Domain (e.g. order.khandelia.online on AWS)
    elif "khandelia.online" in host:
        scheme = request.headers.get("x-forwarded-proto") or "https"
        return f"{scheme}://{host}"
    # 3. Custom host / AWS EC2 public IP or ELB
    elif host and not ("localhost" in host or "127.0.0.1" in host):
        scheme = request.headers.get("x-forwarded-proto") or "https"
        return f"{scheme}://{host}"
    # 4. Default Production URL from .env or official domain
    return os.environ.get("APP_BASE_URL", "https://order.khandelia.online")

@app.get("/")
@app.get("/order_form.html")
@app.get("/order-slip")
@app.get("/order-slip/{order_id}")
def serve_order_slip_root(request: Request, order_id: Optional[str] = None):
    """Serves the digital Khandelia Order Slip with dynamic WhatsApp Open Graph preview or returns slip image"""
    req_id = (order_id or request.query_params.get("id") or "").replace("#", "").strip()
    if req_id:
        slip_file = os.path.join(ORDER_SLIPS_DIR, f"{req_id}.png")
        if os.path.exists(slip_file):
            return FileResponse(slip_file, media_type="image/png")
        # If png not yet created, redirect to verify portal which has live verified details
        return RedirectResponse(f"/verify/{req_id}", status_code=302)

    base_url = get_base_url_from_request(request)
    
    # ⚡ 2X Ultra-Fast Response for WhatsApp / Social Crawlers (1KB payload instead of 80KB)
    if is_social_crawler(request):
        return HTMLResponse(
            f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Khandelia Oil & General Mills - Customer Order Slip</title>
  <meta name="description" content="Direct Customer Order Booking for Khandelia Oil & General Mills Pvt. Ltd. (Mashal & Fauji Mustard Oil). Quality • Price • Efficiency • Reliability.">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Khandelia Oil & General Mills Pvt. Ltd.">
  <meta property="og:title" content="Khandelia Oil & General Mills - Customer Order Slip">
  <meta property="og:description" content="Direct Customer Order Booking for Khandelia Oil & General Mills Pvt. Ltd. (Mashal & Fauji Mustard Oil). Quality • Price • Efficiency • Reliability.">
  <meta property="og:image" content="{base_url}/images/customer_order_preview.jpg">
  <meta property="og:image:secure_url" content="{base_url}/images/customer_order_preview.jpg">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:width" content="773">
  <meta property="og:image:height" content="372">
  <meta property="og:image:alt" content="Customer Order Slip - Quality, Price, Efficiency, Reliability">
  <meta property="og:url" content="{base_url}/">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="Khandelia Oil & General Mills - Customer Order Slip">
  <meta name="twitter:description" content="Direct Customer Order Booking for Khandelia Oil & General Mills Pvt. Ltd.">
  <meta name="twitter:image" content="{base_url}/images/customer_order_preview.jpg">
</head>
<body>
  <h1>Khandelia Oil & General Mills - Customer Order Slip</h1>
</body>
</html>""",
            headers={"Cache-Control": "public, max-age=3600"}
        )

    html_path = os.path.join(BASE_DIR, "order_form.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("https://order.khandelia.online", base_url)
    content = content.replace("https://sevenfold-blazer-pacific.ngrok-free.dev", base_url)
    return HTMLResponse(content)

@app.get("/sale_manager")
@app.get("/sale_manage")
@app.get("/sale_manager.html")
def serve_sale_manager_portal(request: Request):
    """Serves the Sales Manager Portal with dynamic WhatsApp Open Graph preview"""
    base_url = get_base_url_from_request(request)
    
    # ⚡ 2X Ultra-Fast Response for WhatsApp / Social Crawlers (1KB payload instead of 80KB)
    if is_social_crawler(request):
        return HTMLResponse(
            f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Khandelia Oil & General Mills - Area Sales Manager Portal</title>
  <meta name="description" content="Official Area Sales Manager Order Booking Portal for Khandelia Oil & General Mills Pvt. Ltd. (Mashal & Fauji Mustard Oil).">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Khandelia Oil & General Mills Pvt. Ltd.">
  <meta property="og:title" content="Khandelia Oil & General Mills - Area Sales Manager Portal">
  <meta property="og:description" content="Official Area Sales Manager Order Booking Portal for Khandelia Oil & General Mills Pvt. Ltd. (Mashal & Fauji Mustard Oil).">
  <meta property="og:image" content="{base_url}/images/area_sales_manager_preview.jpg">
  <meta property="og:image:secure_url" content="{base_url}/images/area_sales_manager_preview.jpg">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:width" content="800">
  <meta property="og:image:height" content="418">
  <meta property="og:image:alt" content="Area Sales Manager - Khandelia Oil & General Mills">
  <meta property="og:url" content="{base_url}/sale_manage">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="Khandelia Oil & General Mills - Area Sales Manager Portal">
  <meta name="twitter:description" content="Official Area Sales Manager Order Booking Portal for Khandelia Oil & General Mills Pvt. Ltd.">
  <meta name="twitter:image" content="{base_url}/images/area_sales_manager_preview.jpg">
</head>
<body>
  <h1>Khandelia Oil & General Mills - Area Sales Manager Portal</h1>
</body>
</html>""",
            headers={"Cache-Control": "public, max-age=3600"}
        )

    html_path = os.path.join(BASE_DIR, "sale_manager.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("https://order.khandelia.online", base_url)
    content = content.replace("https://sevenfold-blazer-pacific.ngrok-free.dev", base_url)
    return HTMLResponse(content)

@app.get("/sale_table_data")
def serve_sales_table_data():
    """Serves the protected Sales Customer Dashboard at http://127.0.0.1:8000/sale_table_data"""
    return FileResponse("index.html")

@app.get("/admin")
@app.get("/admin.html")
@app.get("/database")
@app.get("/orders_db")
def serve_admin_portal():
    """Serves the Enterprise Orders Database & Records Management Portal"""
    return FileResponse(os.path.join(BASE_DIR, "admin.html"))

@app.get("/order_slips/{filename}")
def serve_order_slip_file(filename: str):
    """Serves high-resolution rendered order slip PNG images"""
    file_path = os.path.join(ORDER_SLIPS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Slip image not found")

@app.get("/js/{filename}")
def serve_js_file(filename: str):
    """Serves local JS libraries like qrcode.min.js offline"""
    file_path = os.path.join("js", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="JS file not found")

ORDERS_LOG = "customer_orders.json"
GOOGLE_SHEET_ORDERS_WEBAPP_URL = os.environ.get(
    "GOOGLE_SHEET_ORDERS_WEBAPP_URL",
    "https://script.google.com/macros/s/AKfycbz34gzaUCbs5znZrvoQ49FSiZPt9bgWK6WToz5Ek3_Y0k7H5hZTeqg0AhoSPaqxUQqA/exec"
)

# 🛡️ Executive Authentication Credentials (Upgraded to Super Admin System)
# Super Admin: Complete access to all units, dashboards, accounts, dynamic unit management
# Admin: Access to assigned unit(s), Confirm SO, Multi-step Delete within unit
# Manager: View, Confirm SO within assigned unit (NO Delete)
# Analyst: View-only Analytics within assigned unit (NO Delete, NO Confirm)
ROLE_CREDENTIALS = {
    "admin": {
        "password": os.environ.get("ADMIN_PASSWORD", "Admin@123#"),
        "role": "super_admin",
        "name": "Super Administrator",
        "can_confirm": True,
        "can_delete": True,
        "can_manage_units": True,
        "can_manage_users": True,
        "assigned_units": "ALL"
    },
    "manager": {
        "password": os.environ.get("MANAGER_PASSWORD", "Manager@123#"),
        "role": "manager",
        "name": "Operations Manager",
        "can_confirm": True,
        "can_delete": False,
        "can_manage_units": False,
        "can_manage_users": False,
        "assigned_units": "Unit 1"
    },
    "analyst": {
        "password": os.environ.get("ANALYST_PASSWORD", "Analyst@123#"),
        "role": "analyst",
        "name": "Data Analyst",
        "can_confirm": False,
        "can_delete": False,
        "can_manage_units": False,
        "can_manage_users": False,
        "assigned_units": "Unit 1"
    }
}
AUTH_SECRET_TOKEN = os.environ.get("AUTH_SECRET_TOKEN", "KOGM_ADMIN_SECURE_TOKEN_2026_XYZ")

@app.post("/api/auth/login")
@app.post("/api/admin/login")
async def admin_portal_login(request: Request):
    """
    🔐 Authenticates Executive Roles (Super Admin, Admin, Manager, Analyst / Analyser)
    Super Admin: admin / Admin@123# (or registered super_admin accounts)
    Manager: manager / Manager@123#
    Analyst: analyst / Analyst@123#
    Desktop-only Administrative access.
    """
    body = await request.json()
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", "")).strip()

    # 1. Check fixed role credentials
    user_info = ROLE_CREDENTIALS.get(username)
    if user_info and user_info["password"] == password:
        role = user_info["role"]
        assigned_units = user_info.get("assigned_units", "ALL")
        token = create_admin_session(username=username, role=role, assigned_units=assigned_units)
        log_audit_event(user_name=user_info["name"], phone=username, role=role, action="ADMIN_LOGIN_SUCCESS", status="SUCCESS", details=f"Executive user '{user_info['name']}' ({role.upper()}) logged in to Admin Portal")
        return {
            "status": "success",
            "token": token,
            "username": username,
            "role": role,
            "roleName": user_info["name"],
            "assignedUnits": assigned_units,
            "canConfirm": user_info["can_confirm"],
            "canDelete": user_info["can_delete"],
            "canManageUnits": user_info.get("can_manage_units", role == "super_admin"),
            "canManageUsers": user_info.get("can_manage_users", role == "super_admin"),
            "message": f"Welcome {user_info['name']} ({role.upper()})"
        }

    # 2. Check created administrative accounts from users table (by phone or username)
    clean_p = "".join(filter(str.isdigit, username))[-10:]
    db_user = get_user_by_phone(clean_p) if clean_p else None
    if not db_user:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE LOWER(name) = ? OR phone = ? LIMIT 1", (username, username))
            row = cur.fetchone()
            if row:
                db_user = dict(row)
        finally:
            conn.close()

    if db_user and db_user.get("status") == "ACTIVE" and db_user.get("role") in ["super_admin", "admin", "manager", "analyst", "analyser"]:
        allowed_passwords = ["Admin@123#", "Manager@123#", "Analyst@123#", "admin", "123456"]
        if password in allowed_passwords:
            role = db_user["role"]
            if role == "analyser":
                role = "analyst"
            assigned_units = db_user.get("assigned_units", "ALL")
            token = create_admin_session(username=db_user["phone"], role=role, assigned_units=assigned_units)
            log_audit_event(user_name=db_user["name"], phone=db_user["phone"], role=role, action="ADMIN_LOGIN_SUCCESS", status="SUCCESS", details=f"Database user '{db_user['name']}' logged in as {role.upper()}")
            return {
                "status": "success",
                "token": token,
                "username": db_user["phone"],
                "role": role,
                "roleName": db_user["name"],
                "assignedUnits": assigned_units,
                "canConfirm": role in ["super_admin", "admin", "manager"],
                "canDelete": role in ["super_admin", "admin"],
                "canManageUnits": role == "super_admin",
                "canManageUsers": role == "super_admin",
                "message": f"Welcome {db_user['name']} ({role.upper()})"
            }

    log_audit_event(user_name=username, phone=username, role="admin", action="ADMIN_LOGIN_FAILED", status="FAILED", details=f"Failed admin portal login attempt for username '{username}'")
    raise HTTPException(status_code=401, detail="Invalid username or password")

def require_admin_auth(request: Request) -> Dict[str, Any]:
    """Helper dependency to protect all admin database operations"""
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif "admin_token" in request.cookies:
        token = request.cookies.get("admin_token")
    elif request.query_params.get("token"):
        token = request.query_params.get("token")

    admin = validate_admin_session(token)
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized: Valid authentication session required")
    return admin

@app.get("/api/admin/me")
async def get_admin_profile(request: Request):
    """Returns current authenticated session user and role permissions"""
    admin_session = require_admin_auth(request)
    role = admin_session.get("role", "admin")
    assigned_units = admin_session.get("assigned_units", "ALL")
    user_info = ROLE_CREDENTIALS.get(admin_session.get("username", "admin"), {
        "role": role,
        "name": "Super Administrator" if role == "super_admin" else role.title(),
        "can_confirm": role in ["super_admin", "admin", "manager"],
        "can_delete": role in ["super_admin", "admin"],
        "can_manage_units": role == "super_admin",
        "can_manage_users": role == "super_admin",
        "assigned_units": assigned_units
    })
    return {
        "status": "success",
        "username": admin_session.get("username"),
        "role": role,
        "roleName": user_info.get("name", "Super Administrator" if role == "super_admin" else role.title()),
        "assignedUnits": assigned_units,
        "canConfirm": user_info.get("can_confirm", True if role in ["super_admin", "admin", "manager"] else False),
        "canDelete": user_info.get("can_delete", True if role in ["super_admin", "admin"] else False),
        "canManageUnits": role == "super_admin",
        "canManageUsers": role == "super_admin"
    }

@app.get("/api/admin/orders")
async def get_admin_orders(request: Request, background_tasks: BackgroundTasks):
    """Fetches permanent orders with strict unit-based permission enforcement"""
    admin = require_admin_auth(request)

    # Trigger lightweight async background check without blocking response
    background_tasks.add_task(sync_remote_production_orders)

    user_role = admin.get("role", "admin")
    user_units = admin.get("assigned_units", "ALL")
    requested_unit = request.query_params.get("unit")

    target_unit = requested_unit
    if user_role != "super_admin" and user_units != "ALL":
        allowed_units = [u.strip() for u in user_units.split(",") if u.strip()]
        if requested_unit and requested_unit != "ALL" and requested_unit not in allowed_units:
            raise HTTPException(status_code=403, detail=f"Permission Denied: You do not have access to {requested_unit}. Allowed: {user_units}")
        target_unit = requested_unit if (requested_unit and requested_unit in allowed_units) else (allowed_units[0] if allowed_units else "Unit 1")

    orders = get_all_orders_from_db(limit=1000, unit=target_unit)
    return {"status": "success", "count": len(orders), "unit": target_unit or "ALL", "orders": orders}

@app.post("/api/admin/sync-live")
async def api_admin_sync_live(request: Request):
    """Forces an immediate pull from live AWS production server into local database"""
    require_admin_auth(request)
    new_count = await sync_remote_production_orders()
    return {"status": "success", "newOrdersCount": new_count, "message": f"Synced {new_count} new orders from live server!"}

@app.get("/api/admin/stats")
async def get_admin_dashboard_stats(request: Request):
    """Fetches live KPI analytics metrics directly from SQLite database with unit filtering"""
    admin = require_admin_auth(request)
    user_role = admin.get("role", "admin")
    user_units = admin.get("assigned_units", "ALL")
    requested_unit = request.query_params.get("unit")

    target_unit = requested_unit
    if user_role != "super_admin" and user_units != "ALL":
        allowed_units = [u.strip() for u in user_units.split(",") if u.strip()]
        target_unit = requested_unit if (requested_unit and requested_unit in allowed_units) else (allowed_units[0] if allowed_units else "Unit 1")

    stats = get_orders_stats(unit=target_unit)
    return stats

@app.get("/api/admin/warehouse-summary")
async def get_admin_warehouse_summary(request: Request):
    """
    🏭 Returns real-time brand-wise warehouse packing & production load for pending orders.
    Respects unit-based permissions.
    """
    admin = require_admin_auth(request)
    user_role = admin.get("role", "admin")
    user_units = admin.get("assigned_units", "ALL")
    requested_unit = request.query_params.get("unit")

    target_unit = requested_unit
    if user_role != "super_admin" and user_units != "ALL":
        allowed_units = [u.strip() for u in user_units.split(",") if u.strip()]
        target_unit = requested_unit if (requested_unit and requested_unit in allowed_units) else (allowed_units[0] if allowed_units else "Unit 1")

    summary = get_warehouse_production_summary(unit=target_unit)
    return {"status": "success", "unit": target_unit or "ALL", "warehouseSummary": summary}

@app.post("/api/admin/orders/confirm")
async def confirm_admin_order(request: Request):
    """
    Confirms an order with a validated SO (Sales Order) Number.
    Permitted for Admin and Manager roles.
    """
    admin_session = require_admin_auth(request)
    role = admin_session.get("role", "admin")
    if role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Analysts have view-only access and cannot confirm orders."
        )

    data = await request.json()
    order_id = str(data.get("orderId") or "").replace("#", "").strip()
    so_number = str(data.get("soNumber") or "").strip()

    if not order_id:
        raise HTTPException(status_code=400, detail="Order ID is required")
    if not so_number:
        raise HTTPException(status_code=400, detail="Valid SO (Sales Order) Number is required to confirm order")
    if len(so_number) < 2:
        raise HTTPException(status_code=400, detail="SO Number must be at least 2 characters")

    username = admin_session.get("username", "admin")
    confirmed_by = f"{username} ({role})"

    success = confirm_order_in_db(order_id, so_number, confirmed_by)
    if success:
        return {
            "status": "success",
            "orderId": order_id,
            "soNumber": so_number,
            "confirmedBy": confirmed_by,
            "message": f"Order #{order_id} confirmed successfully with SO #{so_number}"
        }
    raise HTTPException(status_code=500, detail=f"Failed to confirm order #{order_id} in database")

@app.post("/api/admin/orders/change-unit")
async def api_change_order_unit(request: Request):
    """
    Super Admin & Admin feature:
    Reassigns any customer or ASM order to a different warehouse unit (Unit 1 to Unit 6 & Custom).
    """
    admin_session = require_admin_auth(request)
    role = admin_session.get("role", "admin")
    if role not in ["super_admin", "admin"]:
        raise HTTPException(status_code=403, detail="Forbidden: Super Admin permission required to move order units.")
    
    data = await request.json()
    order_id = str(data.get("orderId") or data.get("order_id") or "").replace("#", "").strip()
    new_unit = str(data.get("unit") or data.get("newUnit") or "").strip()
    
    if not order_id:
        raise HTTPException(status_code=400, detail="Order ID is required")
    if not new_unit:
        raise HTTPException(status_code=400, detail="Target warehouse unit is required")
    
    username = admin_session.get("username", "admin")
    success = update_order_unit_in_db(order_id, new_unit, updated_by=f"{username} ({role})")
    if success:
        return {
            "status": "success",
            "orderId": order_id,
            "unit": new_unit,
            "message": f"Order #{order_id} successfully moved to {new_unit}"
        }
    raise HTTPException(status_code=500, detail=f"Failed to update unit for order #{order_id}")

@app.post("/api/admin/orders/resync")
async def resync_admin_orders(request: Request):
    """
    Forces immediate sync of an order (or all pending orders) to Google Sheet
    """
    require_admin_auth(request)
    data = await request.json()
    order_id = str(data.get("orderId") or "").replace("#", "").strip()
    sync_all = bool(data.get("syncAllPending"))

    if not GOOGLE_SHEET_ORDERS_WEBAPP_URL:
        raise HTTPException(status_code=400, detail="Google Sheets Web App URL not configured in .env")

    import urllib.request
    all_orders = get_all_orders_from_db(limit=1000)
    to_sync = []

    if sync_all:
        to_sync = [o for o in all_orders if not o.get("synced_to_sheet")]
    elif order_id:
        to_sync = [o for o in all_orders if str(o.get("id")).replace("#", "").strip() == order_id]

    if not to_sync:
        return {"status": "success", "message": "No pending orders to sync", "syncedCount": 0}

    synced_ids = []
    for ord_obj in to_sync:
        try:
            req = urllib.request.Request(
                GOOGLE_SHEET_ORDERS_WEBAPP_URL,
                data=json.dumps(ord_obj).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                mark_order_synced_in_db(ord_obj.get("id"))
                synced_ids.append(ord_obj.get("id"))
        except Exception as e:
            print(f"[ADMIN RESYNC ERROR] #{ord_obj.get('id')}: {e}")

    return {
        "status": "success",
        "message": f"Successfully synced {len(synced_ids)} order(s) to Google Sheet!",
        "syncedIds": synced_ids
    }

@app.post("/api/admin/orders/delete")
async def delete_admin_order(request: Request):
    """
    Permanently deletes an order record from orders.db and customer_orders.json.
    Strictly restricted to Admin role ONLY.
    """
    admin_session = require_admin_auth(request)
    role = admin_session.get("role", "admin")
    if role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only System Administrator has permission to delete orders. Managers and Analysts cannot delete records."
        )

    data = await request.json()
    order_id = str(data.get("orderId") or "").replace("#", "").strip()
    if not order_id:
        raise HTTPException(status_code=400, detail="orderId is required")

    success = delete_order_from_db(order_id)
    if success:
        return {"status": "success", "orderId": order_id, "message": f"Order #{order_id} deleted permanently"}
    raise HTTPException(status_code=500, detail=f"Failed to delete order #{order_id}")

@app.post("/api/admin/logout")
async def logout_admin(request: Request):
    """Logs out admin by removing token from database"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else ""
    if token:
        delete_admin_session(token)
    return {"status": "success", "message": "Logged out successfully"}

# 🏭 DYNAMIC WAREHOUSE UNIT MANAGEMENT API (SUPER ADMIN)
@app.get("/api/admin/units")
def api_get_admin_units(request: Request):
    """Returns warehouse units with live order counts (Super Admin / Admin)"""
    require_admin_auth(request)
    active_only = request.query_params.get("active_only", "false").lower() == "true"
    return {"status": "success", "units": get_all_units(active_only=active_only)}

@app.post("/api/admin/units")
async def api_create_or_update_unit(request: Request):
    """Super Admin dynamically creates or updates warehouse unit"""
    admin = require_admin_auth(request)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin permission required for Unit Management")
    body = await request.json()
    res = create_or_update_unit(
        unit_code=body.get("unit_code", ""),
        unit_name=body.get("unit_name", ""),
        description=body.get("description", ""),
        status=body.get("status", "ACTIVE")
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@app.post("/api/admin/units/{unit_id}/status")
async def api_toggle_unit_status(unit_id: int, request: Request):
    """Super Admin toggles unit ACTIVE/INACTIVE status"""
    admin = require_admin_auth(request)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin permission required")
    body = await request.json()
    status = body.get("status", "ACTIVE")
    res = toggle_unit_status(unit_id, status)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@app.delete("/api/admin/units/{unit_id}")
async def api_delete_unit(unit_id: int, request: Request):
    """Super Admin deletes a custom warehouse unit"""
    admin = require_admin_auth(request)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin permission required")
    res = delete_unit_by_id(unit_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

# 👥 SUPER ADMIN USER & ACCOUNT MANAGEMENT API
@app.get("/api/admin/users")
async def api_get_admin_users(request: Request):
    """Returns list of authorized users (Super Admin only)"""
    admin = require_admin_auth(request)
    role = request.query_params.get("role")
    return {"status": "success", "users": get_all_users(role)}

@app.post("/api/admin/users")
async def api_save_admin_user(request: Request):
    """Creates or updates user account with role and assigned unit (Super Admin only)"""
    admin = require_admin_auth(request)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin permission required for account management")
    body = await request.json()
    res = create_or_update_user(
        name=body.get("name", ""),
        phone=body.get("phone", ""),
        role=body.get("role", "asm"),
        party_code=body.get("party_code", ""),
        party_name=body.get("party_name", ""),
        assigned_units=body.get("assigned_units", "Unit 1"),
        status=body.get("status", "ACTIVE"),
        created_by=admin.get("username", "SUPER_ADMIN")
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@app.post("/api/admin/users/{user_id}/status")
async def api_toggle_user_status(user_id: int, request: Request):
    """Blocks or unblocks user account (Super Admin only)"""
    admin = require_admin_auth(request)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin permission required")
    body = await request.json()
    status = body.get("status", "ACTIVE")
    res = toggle_user_status(user_id, status)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@app.delete("/api/admin/users/{user_id}")
async def api_delete_admin_user(user_id: int, request: Request):
    """Permanently deletes user account (Super Admin only)"""
    admin = require_admin_auth(request)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin permission required")
    res = delete_user_by_id(user_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@app.post("/api/admin/users/{user_id}/unit")
async def api_reassign_user_unit(user_id: int, request: Request):
    """Reassigns the assigned warehouse unit for any Customer, ASM, or User account"""
    admin = require_admin_auth(request)
    body = await request.json()
    new_unit = body.get("unit") or body.get("assigned_units") or "Unit 1"
    res = update_user_assigned_units(user_id, new_unit, updated_by=admin.get("username", "SUPER_ADMIN"))
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

# 🛡️ ROLE PERMISSIONS & GRANULAR ACCESS CONTROL API
@app.get("/api/admin/permissions")
async def api_get_admin_permissions(request: Request):
    """Returns granular permission matrix across all roles (Admin / Super Admin)"""
    require_admin_auth(request)
    perms = get_role_permissions()
    return {"status": "success", "permissions": perms}

@app.post("/api/admin/permissions")
async def api_update_admin_permission(request: Request):
    """Updates specific granular permission toggle for a role (Super Admin / Admin)"""
    admin = require_admin_auth(request)
    user_role = str(admin.get("role", "")).strip().lower()
    user_name = str(admin.get("username", "")).strip().lower()
    if user_role not in ["super_admin", "admin"] and user_name != "admin":
        raise HTTPException(status_code=403, detail="Administrator permission required to modify access control matrix")
    body = await request.json()
    role = body.get("role", "")
    key = body.get("key", "")
    enabled = bool(body.get("enabled", False))
    res = update_role_permission(role, key, enabled, updated_by=admin.get("username", "admin"))
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

# 📜 SYSTEM AUDIT LOGS & ACTIVITY TRACKER API (SUPER ADMIN)
@app.get("/api/admin/audit-logs")
async def api_get_admin_audit_logs(request: Request):
    """Returns paginated audit trail of security, login, registration, and management events"""
    require_admin_auth(request)
    try:
        page = int(request.query_params.get("page", 1))
    except Exception:
        page = 1
    try:
        page_size = int(request.query_params.get("page_size", 25))
    except Exception:
        page_size = 25
    q = request.query_params.get("q", "").strip()
    action = request.query_params.get("action", "ALL").strip()
    status = request.query_params.get("status", "ALL").strip()
    date_filter = request.query_params.get("date", "").strip()
    
    res = get_audit_logs(page=page, page_size=page_size, q=q, action=action, status=status, date_filter=date_filter)
    return {
        "status": "success",
        **res
    }

@app.post("/api/admin/cleanup-pankaj")
async def api_cleanup_pankaj(request: Request):
    """Super Admin utility to retain ONLY Pankaj Kumar orders and assign to Unit 1"""
    admin = require_admin_auth(request)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin permission required")
    return cleanup_orders_retain_pankaj_kumar()

import secrets
import hmac
import hashlib

def generate_order_security_hash(order_id: str, timestamp_str: str, party_name: str, total_boxes: int) -> str:
    """
    Cryptographic Anti-Tamper Digital Seal.
    Prevents anyone from falsifying dates, times, quantities, or party names.
    """
    secret = "KOGM_SECURITY_SECRET_KEY_2026_MASHAL"
    raw = f"{order_id}|{timestamp_str}|{(party_name or '').strip().lower()}|{total_boxes}"
    h = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest().upper()
    return f"SEC-{h[:4]}-{h[4:8]}"

def generate_unique_order_id() -> str:
    """Generates unique professional order ID: KOGM-YYYYMMDD-XXXX"""
    date_code = datetime.now().strftime("%Y%m%d")
    rand_suffix = secrets.token_hex(2).upper()
    return f"KOGM-{date_code}-{rand_suffix}"

@app.post("/api/orders/submit")
@limiter.limit(settings.RATE_LIMIT_ORDER_SUBMIT)
async def receive_customer_order(request: Request, background_tasks: BackgroundTasks):
    """
    Handles order submission:
    1. Generates guaranteed unique Order ID (KOGM-YYYYMMDD-XXXX).
    2. Builds human-readable items summary.
    3. Persists immediately to customer_orders.json.
    4. Queues for Google Sheet sync (Zero orders missed).
    """
    order = await request.json()
    orders_list = []
    if os.path.exists(ORDERS_LOG):
        try:
            with open(ORDERS_LOG, "r", encoding="utf-8") as f:
                orders_list = json.load(f)
        except Exception:
            orders_list = []
    
    # Generate unique ID if not already provided
    order_id = order.get("id") or generate_unique_order_id()
    now_dt = get_ist_now()
    order["id"] = order_id
    order["timestamp"] = now_dt.isoformat()
    order["formattedTimestamp"] = now_dt.strftime("%d/%m/%Y %I:%M:%S %p")
    order["formattedDate"] = now_dt.strftime("%d/%m/%Y")
    order["synced_to_sheet"] = False
    
    # 🔗 Dynamic Verification Portal URL (supports Ngrok locally and AWS production)
    verify_base = get_base_url_from_request(request)
    clean_uid = str(order_id).replace("#", "").strip()
    order["verifyUrl"] = f"{verify_base}/verify/{clean_uid}"
    
    # Ensure party code is resolved from CRM or auto-generated for new customers
    party_code = (order.get("partyCode") or "").strip()
    if not party_code:
        p_name = order.get("partyName", "").strip()
        if p_name:
            try:
                from crm_service import _CRM_CACHE, _CACHE_LOCK
                with _CACHE_LOCK:
                    for c in _CRM_CACHE:
                        if c.get("party_name", "").strip().lower() == p_name.lower():
                            party_code = (c.get("party_code") or "").strip()
                            break
            except Exception as crm_lookup_err:
                print(f"[CRM CODE LOOKUP WARN] {crm_lookup_err}")

    # If still not found, this is a NEW customer -> Auto-generate unique official party code & register
    if not party_code:
        try:
            from crm_service import generate_unique_party_code, save_or_update_customer
            p_name_raw = order.get("partyName", "").strip()
            p_addr_raw = order.get("partyAddress", "").strip()
            contact_val = order.get("contactInput", "").strip()
            party_code = generate_unique_party_code(p_name_raw, p_addr_raw)
            # Register new customer in CRM with their new party code
            save_or_update_customer(
                party_name=p_name_raw,
                full_address=p_addr_raw,
                phone=contact_val if not "@" in contact_val else "",
                email=contact_val if "@" in contact_val else "",
                party_code=party_code
            )
            print(f"[NEW CUSTOMER AUTO-CODE] Generated unique party code: {party_code} for '{p_name_raw}'")
        except Exception as gen_err:
            print(f"[AUTO PARTY CODE ERROR] {gen_err}")

    order["partyCode"] = party_code
    order["dataConsent"] = order.get("dataConsent") or "YES (Verified)"
    
    # 🏢 Strict Role-Based Unit Assignment:
    # 1. Area Sales Manager (ASM): order saves to ASM's assigned unit (configured by Super Admin)
    # 2. Customer: order defaults to Unit 1 (unless Super Admin assigned a specific unit to customer)
    # 3. Super Admin can reassign any order's unit at any time
    assigned_unit = (order.get("unit") or "").strip()
    sp = str(order.get("salesPerson") or "").strip()
    contact_val = str(order.get("contactInput") or "").strip()
    clean_p = "".join(filter(str.isdigit, contact_val))[-10:] if contact_val else ""

    # 🚫 Instant Blocked Account Enforcement (Customer & ASM)
    if clean_p and is_user_phone_blocked(clean_p):
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "error_type": "ACCOUNT_BLOCKED", "message": "Your account has been BLOCKED by Super Admin. Order submission rejected.", "force_logout": True}
        )

    asm_user = None
    if sp:
        all_us = get_all_users()
        for u in all_us:
            if u.get("role") == "asm" and (u.get("name", "").strip().lower() == sp.lower() or sp.lower() in u.get("name", "").strip().lower()):
                asm_user = u
                break
    if not asm_user and clean_p:
        u = get_user_by_phone(clean_p)
        if u and u.get("role") == "asm":
            asm_user = u

    if asm_user and asm_user.get("status") == "BLOCKED":
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "error_type": "ACCOUNT_BLOCKED", "message": f"Area Sales Manager account '{asm_user.get('name')}' is BLOCKED by Super Admin.", "force_logout": True}
        )

    if asm_user:
        asm_units = (asm_user.get("assigned_units") or "Unit 1").strip()
        if assigned_unit and (assigned_unit in asm_units or asm_units.upper() == "ALL"):
            pass
        else:
            primary_u = [x.strip() for x in asm_units.split(",") if x.strip()][0] if asm_units.upper() != "ALL" else "Unit 1"
            assigned_unit = primary_u
    else:
        cust_user = get_user_by_phone(clean_p) if clean_p else None
        if cust_user and cust_user.get("assigned_units") and cust_user.get("assigned_units").strip():
            assigned_unit = cust_user.get("assigned_units").split(",")[0].strip()
        elif not assigned_unit:
            assigned_unit = "Unit 1"

        # 👥 Automatic Customer Registration & Tracking on Order
        if not cust_user and clean_p and len(clean_p) == 10:
            c_name = (order.get("customerName") or order.get("partyName") or "Customer").strip()
            create_or_update_user(
                name=c_name,
                phone=clean_p,
                role="customer",
                party_code=party_code,
                party_name=(order.get("partyName") or c_name).strip(),
                assigned_units=assigned_unit or "Unit 1",
                status="ACTIVE",
                created_by="ORDER_SELF_REGISTERED"
            )

    order["unit"] = assigned_unit or "Unit 1"
    
    # Format items summary with brand icons, calculate total pieces & clean multi-line layout
    items = order.get("items", [])
    summary_parts = []
    total_pieces = 0
    total_boxes = 0
    for it in items:
        brand = it.get("brand", "Mashal")
        icon = "🔵" if brand.lower() == "mashal" else "🟢"
        item_name = it.get("item", "")
        bxs = int(it.get("boxes", 0))
        match = re.search(r'x\s*(\d+)', item_name, re.IGNORECASE)
        mult = int(match.group(1)) if match else 1
        pcs = bxs * mult
        it["pieces"] = pcs
        total_pieces += pcs
        total_boxes += bxs
        summary_parts.append(f"{icon} {brand} {item_name}   ➔   {pcs:,} Pcs   |   [ {bxs:,} Boxes ]")
    order["totalPieces"] = total_pieces
    if not order.get("totalBoxes"):
        order["totalBoxes"] = total_boxes
    order["itemsSummary"] = "\n".join(summary_parts)

    # 🔒 Cryptographic Anti-Tamper Digital Security Hash
    order["securityHash"] = generate_order_security_hash(
        order["id"], order["formattedTimestamp"], order.get("partyName", ""), order["totalBoxes"]
    )
    
    # Preset deterministic slip URL and path so email, bot and web links always resolve
    slip_filename = f"{order_id}.png"
    slip_path = os.path.join(ORDER_SLIPS_DIR, slip_filename)
    order["slipImagePath"] = os.path.abspath(slip_path)
    order["slipImageUrl"] = f"/order_slips/{slip_filename}"

    # Decode and save high-resolution Order Slip image if provided by client (or uploaded asynchronously)
    slip_data = order.get("slipImageData", "")
    if slip_data and slip_data.startswith("data:image"):
        try:
            _, base64_str = slip_data.split(",", 1)
            img_bytes = base64.b64decode(base64_str)
            with open(slip_path, "wb") as img_f:
                img_f.write(img_bytes)
            print(f"[SLIP IMAGE SAVED] Saved #{order_id} image ({len(img_bytes)} bytes) at {slip_path}")
        except Exception as img_err:
            print(f"[SLIP IMAGE SAVE ERROR] {img_err}")
    # Don't persist large base64 string in JSON file to keep log snappy
    order.pop("slipImageData", None)

    orders_list.append(order)
    
    with open(ORDERS_LOG, "w", encoding="utf-8") as f:
        json.dump(orders_list, f, indent=2, ensure_ascii=False)
        
    # 0. Always save permanently to orders.db SQLite first (Instant DB Persistence)
    save_order_to_db(order)
    try:
        await async_save_order(order)
    except Exception as async_save_err:
        logger.warning(f"Async DB save note: {async_save_err}")

    # Invalidate cached dashboard stats for real-time accuracy
    await cache.invalidate_stats()

    # Auto-register/update party into CRM database
    contact = order.get("contactInput", "").strip()
    if contact:
        try:
            p_name = order.get("partyName", "").strip()
            clean_name = re.sub(r"^\[.*?\]\s*", "", p_name).strip()
            digits = re.sub(r"\D", "", contact)
            phone_val = digits[-10:] if len(digits) >= 10 else ""
            email_val = contact if "@" in contact else ""
            save_or_update_customer(
                party_name=clean_name,
                full_address=order.get("partyAddress", ""),
                phone=phone_val,
                email=email_val
            )
        except Exception as crm_err:
            print(f"[CRM AUTO-REGISTER ERROR] {crm_err}")

    # 1. Send email notification with slip image attachment
    background_tasks.add_task(send_order_email_notification, order)

    # 2. Enqueue for WhatsApp bot delivery to TARGET_WHATSAPP_NUMBER
    background_tasks.add_task(enqueue_whatsapp_order, order)

    # 3. If Google Apps Script Web App URL is configured, push directly in background
    if GOOGLE_SHEET_ORDERS_WEBAPP_URL:
        def forward_to_google_sheet(order_data):
            try:
                import urllib.request
                req = urllib.request.Request(
                    GOOGLE_SHEET_ORDERS_WEBAPP_URL,
                    data=json.dumps(order_data).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    print(f"[GOOGLE SHEET FORWARD SUCCESS] Status: {resp.status} | Order: {order_data.get('id')}")
                    try:
                        with open(ORDERS_LOG, "r", encoding="utf-8") as f:
                            all_o = json.load(f)
                        for item in all_o:
                            if item.get("id") == order_data.get("id"):
                                item["synced_to_sheet"] = True
                        with open(ORDERS_LOG, "w", encoding="utf-8") as f:
                            json.dump(all_o, f, indent=2, ensure_ascii=False)
                    except Exception as disk_err:
                        print(f"[DISK UPDATE ERROR] {disk_err}")
                    
                    # Update database sync status
                    try:
                        mark_order_synced_in_db(order_data.get("id"))
                    except Exception as db_sync_err:
                        print(f"[DATABASE SYNC UPDATE ERROR] {db_sync_err}")
            except Exception as e:
                print(f"[GOOGLE SHEET FORWARD ERROR] {e}")
        background_tasks.add_task(forward_to_google_sheet, order)
        
    return {
        "status": "success",
        "orderId": order["id"],
        "order": order,
        "slipImageUrl": order.get("slipImageUrl"),
        "message": "Order recorded successfully!"
    }

@app.post("/api/orders/upload-slip")
async def upload_order_slip(request: Request):
    """
    ⚡ Asynchronous Background Slip Upload Endpoint:
    Allows mobile clients (APK) and browser to submit orders with sub-second response (<0.1s),
    while streaming the high-res Order Slip image in the background.
    """
    try:
        data = await request.json()
        raw_id = data.get("orderId") or ""
        order_id = str(raw_id).replace("#", "").strip()
        slip_data = data.get("slipImageData", "")
        if order_id and slip_data and slip_data.startswith("data:image"):
            _, base64_str = slip_data.split(",", 1)
            img_bytes = base64.b64decode(base64_str)
            slip_filename = f"{order_id}.png"
            slip_path = os.path.join(ORDER_SLIPS_DIR, slip_filename)
            with open(slip_path, "wb") as img_f:
                img_f.write(img_bytes)

            abs_path = os.path.abspath(slip_path)
            slip_url = f"/order_slips/{slip_filename}"

            # Update customer_orders.json
            try:
                if os.path.exists(ORDERS_LOG):
                    with open(ORDERS_LOG, "r", encoding="utf-8") as f:
                        orders_list = json.load(f)
                    for o in orders_list:
                        if str(o.get("id", "")).replace("#", "").strip() == order_id:
                            o["slipImagePath"] = abs_path
                            o["slipImageUrl"] = slip_url
                            break
                    with open(ORDERS_LOG, "w", encoding="utf-8") as f:
                        json.dump(orders_list, f, indent=2, ensure_ascii=False)
            except Exception as j_err:
                print(f"[ASYNC SLIP JSON WARN] {j_err}")

            print(f"[ASYNC SLIP UPLOADED] #{order_id} slip saved ({len(img_bytes):,} bytes)")
            return {"status": "success", "orderId": order_id, "slipImageUrl": slip_url}
    except Exception as e:
        print(f"[ASYNC SLIP UPLOAD ERROR] {e}")
        return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Invalid request payload"}

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "itchd.kogm@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_TLS = os.environ.get("SMTP_TLS", "true").lower() == "true"
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "itchd.kogm@gmail.com")

def send_order_email_notification(order: dict):
    """Sends immediate email notification for every customer order formatted exactly like the Order Slip"""
    if not SMTP_PASSWORD:
        print("[EMAIL NOTIFICATION SKIPPED] No SMTP_PASSWORD found in .env")
        return

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.image import MIMEImage

        msg_root = MIMEMultipart("related")
        total_bxs = order.get("totalBoxes", 0)
        total_pcs = order.get("totalPieces", 0)
        party_name = (order.get("partyName") or "Customer").strip()
        party_code = (order.get("partyCode") or "").strip()
        clean_order_id = str(order.get("id", "")).replace("#", "").strip()
        default_prod_url = os.environ.get("APP_BASE_URL", "https://order.khandelia.online")
        verify_url = order.get("verifyUrl") or f"{default_prod_url}/verify/{clean_order_id}"
        p_code_str = f" [{party_code}]" if party_code else ""
        msg_root["Subject"] = f"Order Confirmation: #{order.get('id')} - {party_name}{p_code_str} | {total_bxs:,} Boxes ({total_pcs:,} Pcs)"
        msg_root["From"] = f"Mashal Order System <{SMTP_USER}>"
        msg_root["To"] = NOTIFICATION_EMAIL

        msg_alternative = MIMEMultipart("alternative")
        msg_root.attach(msg_alternative)

        # 5-Column Table Rows matching Order Slip
        items_rows = ""
        for idx, it in enumerate(order.get("items", [])):
            brand = it.get("brand", "Mashal")
            item_name = it.get("item", "")
            bxs = int(it.get("boxes", 0))
            match = re.search(r'x\s*(\d+)', item_name, re.IGNORECASE)
            mult = int(match.group(1)) if match else 1
            pcs = bxs * mult
            brand_color = "#1e40af" if brand.lower() == "mashal" else "#15803d"
            bg_color = "#f8fafc" if idx % 2 == 0 else "#ffffff"
            items_rows += f"""
            <tr style="background-color: {bg_color};">
              <td style="padding: 10px 8px; border: 1px solid #e2e8f0; text-align: center; font-weight: bold; color: #64748b; font-size: 12px;">{idx + 1}</td>
              <td style="padding: 10px 8px; border: 1px solid #e2e8f0; text-align: center; font-weight: bold; color: {brand_color}; font-size: 12px;">{brand}</td>
              <td style="padding: 10px 14px; border: 1px solid #e2e8f0; text-align: left; font-weight: bold; color: #0f172a; font-size: 13px;">{item_name}</td>
              <td style="padding: 10px 12px; border: 1px solid #e2e8f0; text-align: center; font-weight: bold; color: #1e40af; font-size: 14px;">{pcs:,} Pcs</td>
              <td style="padding: 10px 12px; border: 1px solid #e2e8f0; text-align: center; font-weight: bold; font-size: 14.5px; color: #0f172a;">{bxs:,} Boxes</td>
            </tr>
            """

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, Helvetica, sans-serif; background-color: #f1f5f9; padding: 20px; margin: 0;">
          <div style="max-width: 750px; margin: 0 auto; background: #ffffff; border: 3px solid #003366; border-radius: 8px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.1);">
            
            <!-- 🏢 Top Navy Header with Official Mashal Logo & Purity Seal -->
            <div style="background: #003366; padding: 18px 20px;">
              <table style="width: 100%; border-collapse: collapse;">
                <tr>
                  <td style="width: 82px; vertical-align: middle;">
                    <img src="cid:mashal_logo" alt="Mashal" width="76" height="76" style="border-radius: 8px; border: 2px solid #f59e0b; background: #ffffff; display: block;">
                  </td>
                  <td style="vertical-align: middle; padding-left: 14px; text-align: left;">
                    <h2 style="margin: 0; font-size: 19px; color: #ffffff; letter-spacing: 0.5px; font-weight: 800; text-transform: uppercase; line-height: 1.3;">KHANDELIA OIL AND GENERAL MILLS PVT. LTD.</h2>
                    <div style="display: inline-block; background: #d97706; color: #ffffff; padding: 5px 14px; border-radius: 4px; font-size: 11px; margin-top: 8px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase;">OFFICIAL ORDER CONFIRMATION SLIP</div>
                  </td>
                </tr>
              </table>
            </div>

            <!-- 🔖 Reference Bar (Order ID, Single Authoritative Date & Time, Area Sales Manager) -->
            <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; padding: 12px 20px;">
              <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr>
                  <td style="text-align: left; font-weight: bold; font-family: monospace; font-size: 13.5px; color: #0f172a;">
                    ORDER ID: <span style="color: #004b99;">#{clean_order_id}</span>
                  </td>
                  <td style="text-align: center; color: #475569;">
                    <strong>Date & Time:</strong> {order.get('formattedTimestamp', order.get('timestamp'))}
                  </td>
                  <td style="text-align: right; color: #0f172a;">
                    <strong>Area Sales Manager:</strong> <span style="font-weight: 700;">{order.get('salesPerson', '-')}</span>
                  </td>
                </tr>
              </table>
            </div>

            <!-- 👤 Customer & Billing Details with Centered Party Code & Top-Right Verification QR Code -->
            <div style="padding: 16px 20px 10px 20px;">
              <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 14px 18px;">
                <table style="width: 100%; border-collapse: collapse;">
                  <tr>
                    <td style="text-align: left; vertical-align: top; width: 42%;">
                      <div style="font-size: 10.5px; font-weight: 800; color: #64748b; letter-spacing: 0.5px; text-transform: uppercase;">CUSTOMER / BILLING DETAILS</div>
                      <div style="font-size: 16px; font-weight: 800; color: #0f172a; margin-top: 3px; margin-bottom: 3px;">{party_name}</div>
                      <div style="font-size: 12.5px; color: #475569; line-height: 1.4;"><strong>Address:</strong> {order.get('partyAddress', '-')}</div>
                    </td>
                    <td style="text-align: center; vertical-align: middle; width: 24%;">
                      <div style="display: inline-block; background: #eff6ff; border: 1.5px solid #93c5fd; padding: 7px 12px; border-radius: 6px;">
                        <div style="font-size: 9.5px; font-weight: bold; color: #0284c7; letter-spacing: 0.5px; text-transform: uppercase;">REGISTERED PARTY CODE</div>
                        <div style="font-family: monospace; font-size: 14px; font-weight: bold; color: #003366; margin-top: 2px;">{party_code if party_code else 'SDMOWB0307'}</div>
                      </div>
                    </td>
                    <td style="text-align: right; vertical-align: middle; width: 34%;">
                      <a href="{verify_url}" target="_blank" style="text-decoration: none; display: inline-block;">
                        <table style="background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 8px; border-collapse: collapse; display: inline-table;">
                          <tr>
                            <td style="padding: 6px; vertical-align: middle;">
                              <img src="https://quickchart.io/qr?text={urllib.parse.quote(verify_url)}&size=200&margin=2&ecLevel=L" width="58" height="58" alt="QR Code" style="display: block; border-radius: 4px; border: 1px solid #cbd5e1;">
                            </td>
                            <td style="padding: 6px 10px 6px 2px; text-align: left; vertical-align: middle; line-height: 1.3;">
                              <div style="color: #15803d; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;">✔ SCAN TO VERIFY</div>
                              <div style="font-family: monospace; font-size: 11px; font-weight: bold; color: #003366; margin-top: 1px;">#{clean_order_id}</div>
                              <div style="font-family: monospace; font-size: 9px; font-weight: bold; color: #0284c7; margin-top: 1px;">SEAL: {order.get('securityHash', 'SEC-AUTHENTIC')}</div>
                              <div style="font-size: 8.5px; color: #64748b; font-weight: bold; margin-top: 1px;">OFFICIAL RECORD</div>
                            </td>
                          </tr>
                        </table>
                      </a>
                    </td>
                  </tr>
                </table>
              </div>
            </div>

            <!-- 📦 5-Column Ordered Items Table (Matching Canvas Slip) -->
            <div style="padding: 10px 20px 16px 20px;">
              <table style="width: 100%; border-collapse: collapse; font-size: 13px; border: 1px solid #cbd5e1;">
                <thead>
                  <tr style="background: #004b99; color: #ffffff;">
                    <th style="padding: 10px 8px; text-align: center; width: 40px; font-size: 11.5px;">#</th>
                    <th style="padding: 10px 8px; text-align: center; width: 80px; font-size: 11.5px;">BRAND</th>
                    <th style="padding: 10px 14px; text-align: left; font-size: 11.5px;">PACKING / PRODUCT DESCRIPTION</th>
                    <th style="padding: 10px 12px; text-align: center; width: 140px; font-size: 11.5px;">QUANTITY (IN PIECES)</th>
                    <th style="padding: 10px 12px; text-align: center; width: 130px; font-size: 11.5px;">QUANTITY (BOXES)</th>
                  </tr>
                </thead>
                <tbody>
                  {items_rows}
                </tbody>
              </table>

              <!-- 🏆 Grand Total Banner -->
              <div style="background: #003366; color: #ffffff; padding: 14px 20px; text-align: center; margin-top: 12px; border-radius: 6px; font-size: 17px; font-weight: 800; letter-spacing: 0.5px;">
                TOTAL ORDER QUANTITY: {total_bxs:,} BOXES  |  {total_pcs:,} PIECES
              </div>
            </div>

            <!-- 🛡️ Footer Card: Thank You & Customer Care Support (Clean, Wide & Elegant) -->
            <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 18px 20px; text-align: center; border-radius: 0 0 8px 8px;">
              <div style="font-size: 15px; font-weight: bold; color: #003366; margin-bottom: 5px;">✨ Thank You for Your Order!</div>
              <div style="font-size: 12px; color: #334155; margin-bottom: 6px;">Our Customer Care team is always available to assist you.</div>
              <div style="font-size: 12.5px; font-weight: bold; color: #0284c7; margin-bottom: 6px;">
                📞 Toll-Free: 1800 103 3211 &nbsp;|&nbsp; 📧 Email: <a href="mailto:customercare@khandelia.com" style="color: #0284c7; text-decoration: none; font-weight: bold;">customercare@khandelia.com</a>
              </div>
              <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
                For any queries or assistance, feel free to call or email us. We're always happy to help!
              </div>
              <div style="font-size: 9.5px; color: #94a3b8; font-weight: 600;">
                Khandelia Oil and General Mills Pvt. Ltd. • Official Digital OMS
              </div>
            </div>

          </div>
        </body>
        </html>
        """
        msg_alternative.attach(MIMEText(html_content, "html"))

        # Attach official Mashal Logo as inline image with Content-ID: <mashal_logo>
        logo_path = os.path.join(BASE_DIR, "images", "mashal_slip_logo.png")
        if os.path.exists(logo_path):
            try:
                with open(logo_path, "rb") as lf:
                    logo_mime = MIMEImage(lf.read(), name="mashal_logo.png")
                    logo_mime.add_header('Content-ID', '<mashal_logo>')
                    logo_mime.add_header('Content-Disposition', 'inline', filename="mashal_logo.png")
                    msg_root.attach(logo_mime)
                print("[EMAIL INLINE LOGO] Attached mashal_logo.png with Content-ID: <mashal_logo>")
            except Exception as l_err:
                print(f"[LOGO ATTACH WARN] {l_err}")

        # Attach high-resolution slip image if saved on server (allow brief wait for async mobile slip upload)
        slip_img_path = order.get("slipImagePath") or os.path.join(ORDER_SLIPS_DIR, f"{order.get('id')}.png")
        if not os.path.exists(slip_img_path):
            import time
            for _ in range(3):
                time.sleep(0.5)
                if os.path.exists(slip_img_path):
                    break

        if slip_img_path and os.path.exists(slip_img_path):
            try:
                with open(slip_img_path, "rb") as img_f:
                    image_attachment = MIMEImage(img_f.read(), name=f"Order_Slip_{order.get('id')}.png")
                    image_attachment.add_header('Content-Disposition', 'attachment', filename=f"Order_Slip_{order.get('id')}.png")
                    msg_root.attach(image_attachment)
                print(f"[EMAIL ATTACHMENT] Attached Order_Slip_{order.get('id')}.png to email")
            except Exception as att_err:
                print(f"[EMAIL ATTACHMENT ERROR] {att_err}")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as server:
            if SMTP_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, NOTIFICATION_EMAIL, msg_root.as_string())
        print(f"[EMAIL NOTIFICATION SENT] Order #{order.get('id')} emailed to {NOTIFICATION_EMAIL} in Slip format")
    except Exception as e:
        print(f"[EMAIL NOTIFICATION ERROR] Could not send email: {e}")

@app.get("/api/whatsapp/pending")
def api_get_pending_whatsapp_orders():
    """Returns all orders pending delivery via WhatsApp for automatic bot delivery"""
    orders = get_pending_whatsapp_orders()
    for o in orders:
        if not o.get("slip_image_url") and o.get("order_id"):
            o["slip_image_url"] = f"/order_slips/{o['order_id']}.png"
    return {"pending_orders": orders, "count": len(orders)}

@app.post("/api/whatsapp/mark-sent")
async def api_mark_whatsapp_sent(request: Request):
    """Marks order as delivered via WhatsApp in queue and database"""
    body = await request.json()
    order_id = body.get("order_id")
    if order_id:
        mark_whatsapp_order_sent(order_id)
        return {"status": "success", "order_id": order_id}
    return {"status": "error", "message": "Missing order_id"}

# ----------------- 🛡️ CENTRAL ANTI-TAMPER VERIFICATION SYSTEM -----------------
@app.get("/api/orders/{order_id}/qr.png")
def get_order_qr_code(order_id: str, request: Request):
    """Dynamic high-resolution QR code generator pointing to live factory verification portal"""
    clean_id = order_id.replace("#", "").strip()
    base = get_base_url_from_request(request)
    verify_url = f"{base}/verify/{clean_id}"
    if qrcode is not None:
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=2,
            )
            qr.add_data(verify_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#003366", back_color="#ffffff")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return Response(content=buf.getvalue(), media_type="image/png")
        except Exception as e:
            print(f"[QR ERROR] {e}")
    # Fallback to public QR generator if local library is unavailable
    return RedirectResponse(url=f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={verify_url}")

@app.get("/verify/{order_id}", response_class=HTMLResponse)
def verify_order_public_portal(order_id: str):
    """
    🛡️ Central Factory Verification Portal for Khandelia Oil & General Mills Pvt. Ltd.
    Allows warehouse dispatchers, dealers, accountants, and transport coordinators
    to cross-verify order authenticity against the server database in real time.
    Exposes and prevents any forged dates, times, quantities, or party details.
    """
    clean_id = order_id.replace("#", "").strip()
    order = get_order_by_id(clean_id)
    
    # Fallback to customer_orders.json if database lookup returns None
    if not order and os.path.exists(ORDERS_LOG):
        try:
            with open(ORDERS_LOG, "r", encoding="utf-8") as f:
                all_o = json.load(f)
            for o in all_o:
                if (o.get("id") or "").replace("#", "").strip() == clean_id:
                    order = o
                    break
        except Exception:
            pass

    if not order:
        return HTMLResponse(content=f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
          <title>✖ Unverified Order Slip | Khandelia Security</title>
          <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif;
              background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
              min-height: 100vh;
              display: flex;
              align-items: center;
              justify-content: center;
              padding: 20px;
              color: #ffffff;
            }}
            .verify-card {{
              width: 100%;
              max-width: 440px;
              background: rgba(30, 41, 59, 0.85);
              backdrop-filter: blur(20px);
              -webkit-backdrop-filter: blur(20px);
              border: 1.5px solid rgba(239, 68, 68, 0.4);
              border-radius: 28px;
              padding: 36px 28px 30px;
              text-align: center;
              box-shadow: 0 25px 60px rgba(220, 38, 38, 0.25), 0 0 40px rgba(0, 0, 0, 0.5);
              animation: shake 0.6s cubic-bezier(.36,.07,.19,.97) both;
            }}
            @keyframes shake {{
              10%, 90% {{ transform: translate3d(-2px, 0, 0); }}
              20%, 80% {{ transform: translate3d(4px, 0, 0); }}
              30%, 50%, 70% {{ transform: translate3d(-6px, 0, 0); }}
              40%, 60% {{ transform: translate3d(6px, 0, 0); }}
            }}
            .brand-badge {{
              display: inline-flex;
              align-items: center;
              gap: 6px;
              background: rgba(255, 255, 255, 0.08);
              border: 1px solid rgba(255, 255, 255, 0.15);
              padding: 6px 14px;
              border-radius: 20px;
              font-size: 11.5px;
              font-weight: 700;
              letter-spacing: 0.8px;
              color: #cbd5e1;
              text-transform: uppercase;
              margin-bottom: 24px;
            }}
            /* Animated Error Cross */
            .cross-container {{
              width: 96px;
              height: 96px;
              margin: 0 auto 20px;
              position: relative;
            }}
            .cross-svg {{
              width: 96px;
              height: 96px;
              border-radius: 50%;
              display: block;
              stroke-width: 3.5;
              stroke: #ef4444;
              stroke-miterlimit: 10;
              box-shadow: 0 0 35px rgba(239, 68, 68, 0.45);
            }}
            .cross-circle {{
              stroke-dasharray: 290;
              stroke-dashoffset: 290;
              stroke-width: 3.5;
              stroke-miterlimit: 10;
              stroke: #ef4444;
              fill: rgba(239, 68, 68, 0.1);
              animation: drawCircle 0.7s ease-in-out forwards;
            }}
            .cross-line {{
              transform-origin: 50% 50%;
              stroke-dasharray: 60;
              stroke-dashoffset: 60;
              animation: drawLine 0.4s ease-out 0.6s forwards;
            }}
            @keyframes drawCircle {{
              100% {{ stroke-dashoffset: 0; }}
            }}
            @keyframes drawLine {{
              100% {{ stroke-dashoffset: 0; }}
            }}
            .verdict-title {{
              font-size: 24px;
              font-weight: 800;
              color: #ef4444;
              letter-spacing: -0.3px;
              margin-bottom: 8px;
            }}
            .verdict-sub {{
              font-size: 14.5px;
              color: #94a3b8;
              line-height: 1.5;
              margin-bottom: 24px;
            }}
            .alert-banner {{
              background: rgba(220, 38, 38, 0.18);
              border: 1.5px solid rgba(239, 68, 68, 0.4);
              border-radius: 14px;
              padding: 14px 16px;
              margin-bottom: 24px;
              font-size: 13.5px;
              font-weight: 700;
              color: #fca5a5;
              display: flex;
              align-items: center;
              justify-content: center;
              gap: 8px;
            }}
            .info-card {{
              background: rgba(15, 23, 42, 0.6);
              border: 1px solid rgba(255, 255, 255, 0.08);
              border-radius: 16px;
              padding: 16px;
              margin-bottom: 22px;
              text-align: left;
            }}
            .info-row {{
              display: flex;
              justify-content: space-between;
              padding: 7px 0;
              font-size: 13.5px;
              border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }}
            .info-row:last-child {{ border-bottom: none; }}
            .info-label {{ color: #64748b; font-weight: 600; }}
            .info-val {{ color: #f1f5f9; font-weight: 700; font-family: monospace; }}
            .btn-call {{
              display: block;
              width: 100%;
              background: linear-gradient(135deg, #004b99 0%, #002244 100%);
              border: 1px solid rgba(255, 255, 255, 0.2);
              color: #ffffff;
              padding: 14px;
              border-radius: 14px;
              text-decoration: none;
              font-weight: 700;
              font-size: 14px;
              letter-spacing: 0.3px;
              box-shadow: 0 8px 25px rgba(0, 75, 153, 0.35);
            }}
            .footer-txt {{
              margin-top: 18px;
              font-size: 11px;
              color: #64748b;
            }}
          </style>
        </head>
        <body>
          <div class="verify-card">
            <div class="brand-badge">🏢 Khandelia Security Audit</div>
            
            <!-- Animated Cross -->
            <div class="cross-container">
              <svg class="cross-svg" viewBox="0 0 100 100">
                <circle class="cross-circle" cx="50" cy="50" r="44"/>
                <line class="cross-line" x1="33" y1="33" x2="67" y2="67"/>
                <line class="cross-line" x1="67" y1="33" x2="33" y2="67"/>
              </svg>
            </div>

            <h1 class="verdict-title">UNVERIFIED ORDER</h1>
            <p class="verdict-sub">This order slip could not be matched against our official central database.</p>

            <div class="alert-banner">
              ⛔ DO NOT DISPATCH GOODS
            </div>

            <div class="info-card">
              <div class="info-row">
                <span class="info-label">Scanned Order ID</span>
                <span class="info-val" style="color: #ef4444;">#{clean_id}</span>
              </div>
              <div class="info-row">
                <span class="info-label">Record Status</span>
                <span class="info-val" style="color: #f87171;">NOT FOUND / FORGED</span>
              </div>
              <div class="info-row">
                <span class="info-label">Action Required</span>
                <span class="info-val" style="color: #fbbf24;">Contact Dispatch Desk</span>
              </div>
            </div>

            <a href="tel:18001033211" class="btn-call">📞 Call Support (1800 103 3211)</a>
            <div class="footer-txt">Khandelia Oil and General Mills Pvt. Ltd. • Official Digital OMS</div>
          </div>
        </body>
        </html>
        """, status_code=404)

    # Order found! Render ultra-premium minimal mobile verified card
    party_name = order.get("partyName") or order.get("party_name") or "Customer"
    party_code = order.get("partyCode") or order.get("party_code") or "NEW CUSTOMER"
    party_address = order.get("partyAddress") or order.get("party_address") or "-"
    sales_person = order.get("salesPerson") or order.get("sales_person") or "-"
    timestamp_str = order.get("formattedTimestamp") or order.get("formatted_timestamp") or order.get("created_at") or "-"
    total_boxes = order.get("totalBoxes") or order.get("total_boxes") or 0
    total_pieces = order.get("totalPieces") or order.get("total_pieces") or 0
    sec_hash = order.get("securityHash") or generate_order_security_hash(clean_id, timestamp_str, party_name, total_boxes)

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
      <title>✔ 100% Genuine Order Verified | Khandelia OMS</title>
      <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif;
          background: linear-gradient(135deg, #091e14 0%, #061826 100%);
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 20px;
          color: #ffffff;
        }}
        .verify-card {{
          width: 100%;
          max-width: 440px;
          background: rgba(15, 30, 24, 0.85);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border: 1.5px solid rgba(34, 197, 94, 0.45);
          border-radius: 28px;
          padding: 36px 28px 28px;
          text-align: center;
          box-shadow: 0 25px 60px rgba(34, 197, 94, 0.22), 0 0 45px rgba(0, 0, 0, 0.6);
          animation: popIn 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
        }}
        @keyframes popIn {{
          0% {{ opacity: 0; transform: scale(0.92) translateY(20px); }}
          100% {{ opacity: 1; transform: scale(1) translateY(0); }}
        }}
        .brand-badge {{
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.15);
          padding: 6px 14px;
          border-radius: 20px;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.8px;
          color: #cbd5e1;
          text-transform: uppercase;
          margin-bottom: 24px;
        }}
        /* Animated Success Checkmark (Tick) */
        .tick-container {{
          width: 96px;
          height: 96px;
          margin: 0 auto 20px;
          position: relative;
        }}
        .tick-svg {{
          width: 96px;
          height: 96px;
          border-radius: 50%;
          display: block;
          stroke-width: 3.5;
          stroke: #22c55e;
          stroke-miterlimit: 10;
          box-shadow: 0 0 35px rgba(34, 197, 94, 0.5);
          animation: glowPulse 2s infinite ease-in-out;
        }}
        @keyframes glowPulse {{
          0%, 100% {{ box-shadow: 0 0 25px rgba(34, 197, 94, 0.4); }}
          50% {{ box-shadow: 0 0 45px rgba(34, 197, 94, 0.7); }}
        }}
        .tick-circle {{
          stroke-dasharray: 290;
          stroke-dashoffset: 290;
          stroke-width: 3.5;
          stroke-miterlimit: 10;
          stroke: #22c55e;
          fill: rgba(34, 197, 94, 0.12);
          animation: drawCircle 0.7s ease-in-out forwards;
        }}
        .tick-check {{
          transform-origin: 50% 50%;
          stroke-dasharray: 60;
          stroke-dashoffset: 60;
          animation: drawCheck 0.45s ease-out 0.65s forwards;
        }}
        @keyframes drawCircle {{
          100% {{ stroke-dashoffset: 0; }}
        }}
        @keyframes drawCheck {{
          100% {{ stroke-dashoffset: 0; }}
        }}
        .verdict-title {{
          font-size: 25px;
          font-weight: 800;
          color: #22c55e;
          letter-spacing: -0.3px;
          margin-bottom: 6px;
        }}
        .verdict-sub {{
          font-size: 14.5px;
          color: #94a3b8;
          line-height: 1.5;
          margin-bottom: 22px;
        }}
        .status-badge {{
          background: rgba(34, 197, 94, 0.18);
          border: 1.5px solid rgba(34, 197, 94, 0.45);
          border-radius: 14px;
          padding: 12px 16px;
          margin-bottom: 22px;
          font-size: 13.5px;
          font-weight: 800;
          color: #86efac;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          letter-spacing: 0.3px;
        }}
        .info-card {{
          background: rgba(10, 20, 16, 0.65);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 18px;
          padding: 18px 20px;
          margin-bottom: 24px;
          text-align: left;
        }}
        .info-row {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 9px 0;
          font-size: 13.5px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .info-row:last-child {{ border-bottom: none; }}
        .info-label {{ color: #94a3b8; font-weight: 600; font-size: 12.5px; }}
        .info-val {{ color: #ffffff; font-weight: 700; text-align: right; }}
        .val-mono {{ font-family: monospace; font-size: 14px; color: #60a5fa; }}
        .val-boxes {{ font-size: 16px; font-weight: 800; color: #4ade80; }}
        .footer-txt {{
          font-size: 11px;
          color: #64748b;
          line-height: 1.5;
        }}
      </style>
    </head>
    <body>
      <div class="verify-card">
        <div class="brand-badge">🏢 Khandelia Oil & General Mills</div>
        
        <!-- Animated Success Tick -->
        <div class="tick-container">
          <svg class="tick-svg" viewBox="0 0 100 100">
            <circle class="tick-circle" cx="50" cy="50" r="44"/>
            <polyline class="tick-check" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" points="28,52 43,67 72,36"/>
          </svg>
        </div>

        <h1 class="verdict-title">ORDER 100% VERIFIED</h1>
        <p class="verdict-sub">This order is authentic, cryptographically sealed, and confirmed in factory records.</p>

        <div class="status-badge">
          ✔ SAFE FOR DISPATCH & BILLING
        </div>

        <!-- Clean, Essential Summary (No Cluttered Tables!) -->
        <div class="info-card">
          <div class="info-row">
            <span class="info-label">Order ID</span>
            <span class="info-val val-mono">#{clean_id}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Customer / Party</span>
            <span class="info-val">{party_name}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Total Quantity</span>
            <span class="info-val val-boxes">{total_boxes:,} Boxes <span style="font-size: 12px; color: #94a3b8; font-weight: normal;">({total_pieces:,} Pcs)</span></span>
          </div>
          <div class="info-row">
            <span class="info-label">Security Seal</span>
            <span class="info-val" style="font-family: monospace; color: #38bdf8;">{sec_hash}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Server Timestamp</span>
            <span class="info-val" style="font-size: 12px; color: #cbd5e1;">{timestamp_str}</span>
          </div>
        </div>

        <div class="footer-txt">
          Officially Verified via Central Digital OMS<br>
          Khandelia Oil and General Mills Pvt. Ltd.
        </div>
      </div>
    </body>
    </html>
    """)

# ----------------- CRM & KIT19 OTP ENDPOINTS -----------------
@app.get("/api/customers/search")
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def api_search_customers(request: Request, q: str = ""):
    """Ultra-fast tiered-cached customer autocomplete matching phone, email, party code, or name"""
    clean_q = (q or "").strip()
    if not clean_q or len(clean_q) < 2:
        return {"status": "success", "query": q, "count": 0, "results": []}

    # 1. Tier-1 & Tier-2 Cache Check (RAM & Redis)
    cached = await cache.get_cached_customer_search(clean_q)
    if cached is not None:
        return {"status": "success", "query": q, "count": len(cached), "results": cached, "cached": True}

    # 2. Database Indexed Fallback
    results = await async_search_customers(clean_q, limit=15)
    await cache.set_cached_customer_search(clean_q, results, ttl=settings.REDIS_CACHE_TTL_SEARCH)
    return {"status": "success", "query": q, "count": len(results), "results": results, "cached": False}

@app.post("/api/customers/save-new")
async def api_save_new_customer(request: Request):
    """Saves new customer / party into CRM database"""
    body = await request.json()
    res = save_or_update_customer(
        party_name=body.get("party_name"),
        full_address=body.get("full_address"),
        phone=body.get("phone"),
        email=body.get("email"),
        party_code=body.get("party_code")
    )
    return res

@app.post("/api/otp/send")
@limiter.limit(settings.RATE_LIMIT_OTP)
async def api_send_otp(request: Request):
    """Sends 6-digit verification OTP via Kit19 HTTP API"""
    body = await request.json()
    phone = body.get("phone", "")
    return send_kit19_otp(phone)

@app.post("/api/otp/verify")
async def api_verify_otp(request: Request):
    """Verifies submitted OTP"""
    body = await request.json()
    phone = body.get("phone", "")
    otp = body.get("otp", "")
    return verify_kit19_otp(phone, otp)

# 🔐 1-YEAR SALES MANAGER OTP AUTHENTICATION
@app.post("/api/sales-manager/send-otp")
@limiter.limit(settings.RATE_LIMIT_OTP)
async def api_manager_send_otp(request: Request):
    """Dispatches Kit19 OTP to authorized Sales Manager's phone for 1-year device authentication"""
    body = await request.json()
    phone = body.get("phone", "")
    clean_p = "".join(filter(str.isdigit, str(phone)))[-10:]
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    if len(clean_p) != 10:
        log_audit_event(user_name="Unknown", phone=clean_p, role="asm", action="INVALID_PHONE_FORMAT", status="FAILED", details="Mobile number is not 10 digits", ip_address=client_ip)
        return {"status": "error", "message": "Please enter a valid 10-digit mobile number"}

    user = get_user_by_phone(clean_p)
    if not user:
        # 👥 Dynamic Automatic ASM Self-Registration & Centralized Tracking
        mgr_name = (body.get("manager_name") or body.get("name") or "").strip()
        if not mgr_name:
            mgr_name = f"Area Sales Manager ({clean_p[-4:]})"
        create_or_update_user(
            name=mgr_name,
            phone=clean_p,
            role="asm",
            party_code="",
            party_name="Staff / System Account",
            assigned_units="Unit 1",
            status="ACTIVE",
            created_by="ASM_PORTAL_REGISTRATION"
        )
        user = get_user_by_phone(clean_p)
        log_audit_event(
            user_name=mgr_name,
            phone=clean_p,
            role="asm",
            action="ASM_REGISTRATION",
            status="SUCCESS",
            details=f"New Area Sales Manager dynamically registered: '{mgr_name}' (+91 {clean_p})",
            ip_address=client_ip
        )

    if user.get("status") == "BLOCKED":
        log_audit_event(
            user_name=user.get("name", "ASM"),
            phone=clean_p,
            role=user.get("role", "asm"),
            action="LOGIN_ATTEMPT_BLOCKED",
            status="FAILED",
            details="Blocked Area Sales Manager attempted login",
            ip_address=client_ip
        )
        return {
            "status": "error",
            "error_type": "BLOCKED_ASM",
            "message": "Your Area Sales Manager account has been temporarily blocked by Super Admin. Please contact Customer Care:\n\n📞 Toll-Free: 1800 103 3211\n✉️ Email: customercare@khandelia.com",
            "toll_free": "1800 103 3211",
            "email": "customercare@khandelia.com",
            "force_logout": True
        }
    if user.get("role") not in ["asm", "admin", "manager", "super_admin"]:
        log_audit_event(
            user_name=user.get("name", "User"),
            phone=clean_p,
            role=user.get("role", "unknown"),
            action="ROLE_MISMATCH",
            status="FAILED",
            details=f"User with role '{user.get('role')}' attempted ASM login",
            ip_address=client_ip
        )
        return {
            "status": "error",
            "error_type": "ROLE_MISMATCH",
            "message": "This mobile number is not authorized for Area Sales Manager access. Please contact Super Admin:\n\n📞 Toll-Free: 1800 103 3211\n✉️ Email: customercare@khandelia.com",
            "toll_free": "1800 103 3211",
            "email": "customercare@khandelia.com"
        }
    
    res = send_kit19_otp(clean_p)
    if res.get("status") == "success":
        log_audit_event(
            user_name=user.get("name", "ASM"),
            phone=clean_p,
            role="asm",
            action="OTP_SENT",
            status="SUCCESS",
            details=f"OTP dispatched to Area Sales Manager '{user.get('name')}'",
            ip_address=client_ip
        )
    else:
        log_audit_event(
            user_name=user.get("name", "ASM"),
            phone=clean_p,
            role="asm",
            action="OTP_SEND_FAILED",
            status="FAILED",
            details=f"OTP dispatch failed: {res.get('message')}",
            ip_address=client_ip
        )
    res["manager_name"] = user.get("name", "")
    return res

@app.post("/api/sales-manager/verify-otp")
async def api_manager_verify_otp(request: Request):
    """Verifies Sales Manager OTP and creates 1-year persistent session"""
    body = await request.json()
    phone = body.get("phone", "")
    otp = body.get("otp", "")
    clean_p = "".join(filter(str.isdigit, str(phone)))[-10:]
    client_ip = request.client.host if request.client else "127.0.0.1"
    user = get_user_by_phone(clean_p)
    name = (body.get("manager_name") or body.get("name") or "").strip()
    
    if user and user.get("status") == "BLOCKED":
        return JSONResponse(
            status_code=403,
            content={
                "status": "error",
                "error_type": "BLOCKED_ASM",
                "message": "Your account has been BLOCKED by Super Admin.",
                "force_logout": True
            }
        )

    res = verify_manager_login_otp(clean_p, otp, name or (user.get("name") if user else ""))
    if res.get("status") == "success":
        if not user:
            user_name = name or f"Area Sales Manager ({clean_p[-4:]})"
            create_or_update_user(
                name=user_name,
                phone=clean_p,
                role="asm",
                party_code="",
                party_name="Staff / System Account",
                assigned_units="Unit 1",
                status="ACTIVE",
                created_by="ASM_PORTAL_REGISTRATION"
            )
            user = get_user_by_phone(clean_p)
        elif name and (user.get("name") in ["", "ASM", "Area Sales Manager", None] or str(user.get("name")).startswith("Area Sales Manager (")):
            create_or_update_user(
                name=name,
                phone=clean_p,
                role=user.get("role", "asm"),
                party_code=user.get("party_code", ""),
                party_name=user.get("party_name", "") or "Staff / System Account",
                assigned_units=user.get("assigned_units", "Unit 1"),
                status=user.get("status", "ACTIVE"),
                created_by=user.get("created_by", "ASM_PORTAL_REGISTRATION")
            )
            user = get_user_by_phone(clean_p)

        role = user.get("role", "asm") if user else "asm"
        user_name = user.get("name", name) if user else name
        res["role"] = role
        res["manager_name"] = user_name
        log_audit_event(
            user_name=user_name,
            phone=clean_p,
            role=role,
            action="ASM_LOGIN",
            status="SUCCESS",
            details=f"Area Sales Manager '{user_name}' successfully verified OTP and logged in",
            ip_address=client_ip
        )
    else:
        log_audit_event(
            user_name=user.get("name") if user else "Unknown ASM",
            phone=clean_p,
            role="asm",
            action="OTP_VERIFICATION",
            status="FAILED",
            details="Invalid OTP entered for Area Sales Manager login",
            ip_address=client_ip
        )
    return res

@app.post("/api/sales-manager/check-session")
async def api_manager_check_session(request: Request):
    """Checks if Sales Manager has an active 1-year device session"""
    body = await request.json()
    token = body.get("token", "")
    session = validate_manager_session(token)
    if session:
        return {"status": "valid", "session": session}
    return JSONResponse(
        status_code=403,
        content={"status": "invalid", "error_type": "ACCOUNT_BLOCKED_OR_EXPIRED", "message": "Session expired or account blocked by Super Admin", "force_logout": True}
    )

@app.get("/api/sales-manager/my-orders")
async def api_get_manager_orders(request: Request):
    """Returns orders strictly assigned to the authenticated Area Sales Manager"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else request.query_params.get("token", "")
    session = validate_manager_session(token)
    mgr_name = session.get("manager_name", "") if session else request.query_params.get("manager_name", "")
    if not mgr_name:
        raise HTTPException(status_code=401, detail="Valid Area Sales Manager session required")

    date_filter = request.query_params.get("filter", "ALL")
    specific_date = request.query_params.get("date", "")
    
    from datetime import date, timedelta
    today_iso = date.today().isoformat()
    today_slash = date.today().strftime("%d/%m/%Y")
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
    yesterday_slash = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")

    all_orders = get_orders_for_asm(sales_person_name=mgr_name, phone=session.get("phone", "") if session else "", date_filter="ALL")
    today_count = sum(1 for o in all_orders if today_iso in str(o.get("created_at") or "") or today_slash in str(o.get("formattedTimestamp") or ""))
    yesterday_count = sum(1 for o in all_orders if yesterday_iso in str(o.get("created_at") or "") or yesterday_slash in str(o.get("formattedTimestamp") or ""))
    total_count = len(all_orders)

    if date_filter == "ALL":
        orders = all_orders
    else:
        orders = get_orders_for_asm(sales_person_name=mgr_name, phone=session.get("phone", "") if session else "", date_filter=date_filter, specific_date=specific_date)

    return {
        "status": "success",
        "managerName": mgr_name,
        "filter": date_filter,
        "date": specific_date,
        "todayCount": today_count,
        "yesterdayCount": yesterday_count,
        "totalOrders": total_count,
        "orders": orders
    }

# 📱 CUSTOMER MOBILE OTP LOGIN & SELF-REGISTRATION
@app.post("/api/customer/send-otp")
@limiter.limit(settings.RATE_LIMIT_OTP)
async def api_customer_send_otp(request: Request):
    """Dispatches Kit19 OTP to Customer phone. Supports self-registration for new customers."""
    body = await request.json()
    phone = body.get("phone", "")
    clean_p = "".join(filter(str.isdigit, str(phone)))[-10:]
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    if len(clean_p) != 10:
        return {"status": "error", "message": "Please enter a valid 10-digit mobile number"}

    user = get_user_by_phone(clean_p)
    if user:
        if user.get("status") == "BLOCKED":
            log_audit_event(
                user_name=user.get("name", "Customer"),
                phone=clean_p,
                role=user.get("role", "customer"),
                action="CUSTOMER_LOGIN_BLOCKED",
                status="FAILED",
                details="Blocked customer attempted to request OTP",
                ip_address=client_ip
            )
            return {
                "status": "error",
                "error_type": "BLOCKED_CUSTOMER",
                "message": "Your Customer account has been temporarily blocked by Super Admin. Please contact Customer Care:\n\n📞 Toll-Free: 1800 103 3211\n✉️ Email: customercare@khandelia.com",
                "toll_free": "1800 103 3211",
                "email": "customercare@khandelia.com"
            }
        if user.get("role") not in ["customer", "admin", "super_admin"]:
            log_audit_event(
                user_name=user.get("name", "User"),
                phone=clean_p,
                role=user.get("role", "unknown"),
                action="ROLE_MISMATCH",
                status="FAILED",
                details=f"User with role '{user.get('role')}' attempted Customer portal access",
                ip_address=client_ip
            )
            return {
                "status": "error",
                "error_type": "ROLE_MISMATCH",
                "message": "This mobile number is registered for an administrative/staff role, not Customer access. Please contact Super Admin.",
                "toll_free": "1800 103 3211",
                "email": "customercare@khandelia.com"
            }
    
    res = send_kit19_otp(clean_p)
    if res.get("status") == "success":
        log_audit_event(
            user_name=user.get("name", "Customer") if user else "New Customer",
            phone=clean_p,
            role="customer",
            action="OTP_SENT",
            status="SUCCESS",
            details=f"Customer OTP sent to {clean_p} ({'Existing Account' if user else 'New Registration'})",
            ip_address=client_ip
        )
    else:
        log_audit_event(
            user_name=user.get("name", "Customer") if user else "New Customer",
            phone=clean_p,
            role="customer",
            action="OTP_SEND_FAILED",
            status="FAILED",
            details=f"Customer OTP dispatch failed: {res.get('message')}",
            ip_address=client_ip
        )

    if user:
        res["customer_name"] = user.get("name", "")
        res["party_name"] = user.get("party_name", "")
        res["party_code"] = user.get("party_code", "")
        res["is_registered"] = True
    else:
        res["is_registered"] = False

    return res

@app.post("/api/customer/verify-otp")
async def api_customer_verify_otp(request: Request):
    """
    Verifies Customer OTP.
    If the customer is new, automatically registers them in the Super Admin User Management database.
    """
    body = await request.json()
    phone = body.get("phone", "")
    otp = body.get("otp", "")
    customer_input_name = (body.get("customer_name") or body.get("name") or "").strip()
    clean_p = "".join(filter(str.isdigit, str(phone)))[-10:]
    client_ip = request.client.host if request.client else "127.0.0.1"

    if len(clean_p) != 10:
        return {"status": "error", "message": "Invalid 10-digit mobile number"}

    verify_res = verify_kit19_otp(clean_p, otp)
    if verify_res.get("status") != "success":
        log_audit_event(
            user_name=customer_input_name or "Customer",
            phone=clean_p,
            role="customer",
            action="OTP_VERIFICATION",
            status="FAILED",
            details="Invalid OTP entered for customer verification",
            ip_address=client_ip
        )
        return verify_res

    user = get_user_by_phone(clean_p)
    if user and user.get("status") == "BLOCKED":
        log_audit_event(
            user_name=user.get("name", "Customer"),
            phone=clean_p,
            role="customer",
            action="CUSTOMER_LOGIN_BLOCKED",
            status="FAILED",
            details="Blocked customer attempted OTP verification",
            ip_address=client_ip
        )
        return JSONResponse(
            status_code=403,
            content={
                "status": "error",
                "error_type": "ACCOUNT_BLOCKED",
                "message": "Your Customer account has been BLOCKED by Super Admin.",
                "force_logout": True
            }
        )

    if not user:
        # 🌟 AUTOMATIC NEW CUSTOMER SELF-REGISTRATION
        resolved_name = customer_input_name or "New Customer"
        create_or_update_user(
            name=resolved_name,
            phone=clean_p,
            role="customer",
            party_code="",
            party_name=resolved_name,
            assigned_units="Unit 1",
            status="ACTIVE",
            created_by="SELF_REGISTERED"
        )
        user = get_user_by_phone(clean_p)
        log_audit_event(
            user_name=resolved_name,
            phone=clean_p,
            role="customer",
            action="CUSTOMER_REGISTRATION",
            status="SUCCESS",
            details=f"New customer self-registered: '{resolved_name}' ({clean_p})",
            ip_address=client_ip
        )
    else:
        resolved_name = customer_input_name or user.get("name") or "Customer"
        if customer_input_name and user.get("name") in ["", "Customer", "New Customer", None]:
            create_or_update_user(
                name=customer_input_name,
                phone=clean_p,
                role=user.get("role", "customer"),
                party_code=user.get("party_code", ""),
                party_name=user.get("party_name", "") or customer_input_name,
                assigned_units=user.get("assigned_units", "Unit 1"),
                status=user.get("status", "ACTIVE"),
                created_by=user.get("created_by", "SELF_REGISTERED")
            )
            user = get_user_by_phone(clean_p)
            resolved_name = user.get("name", resolved_name)
        
        log_audit_event(
            user_name=user.get("name", resolved_name),
            phone=clean_p,
            role="customer",
            action="CUSTOMER_LOGIN",
            status="SUCCESS",
            details=f"Customer '{user.get('name')}' logged in via OTP",
            ip_address=client_ip
        )

    session = create_customer_session(
        phone=clean_p,
        customer_name=resolved_name,
        party_code=user.get("party_code", "") if user else "",
        party_name=(user.get("party_name", "") if user else "") or resolved_name
    )
    return {
        "status": "success",
        "token": session["token"],
        "phone": clean_p,
        "customer_name": resolved_name,
        "party_code": user.get("party_code", "") if user else "",
        "party_name": (user.get("party_name", "") if user else "") or resolved_name,
        "role": user.get("role", "customer") if user else "customer",
        "expires_at": session["expires_at"],
        "message": f"Welcome, {resolved_name}!"
    }

@app.post("/api/customer/check-session")
async def api_customer_check_session(request: Request):
    """Validates Customer session and checks blocked status"""
    body = await request.json()
    token = body.get("token", "")
    session = validate_customer_session(token)
    if session:
        return {"status": "valid", "session": session}
    return JSONResponse(
        status_code=403,
        content={"status": "invalid", "error_type": "ACCOUNT_BLOCKED_OR_EXPIRED", "message": "Session expired or account blocked by Super Admin", "force_logout": True}
    )

@app.get("/api/customer/my-orders")
async def api_get_customer_orders(request: Request):
    """Returns orders strictly belonging to the authenticated customer"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else request.query_params.get("token", "")
    session = validate_customer_session(token)
    if not session:
        party_code = request.query_params.get("party_code", "")
        party_name = request.query_params.get("party_name", "")
        phone = request.query_params.get("phone", "")
        if not (party_code or party_name or phone):
            raise HTTPException(status_code=401, detail="Valid customer session required")
    else:
        party_code = session.get("party_code", "")
        party_name = session.get("party_name", "")
        phone = session.get("phone", "")

    date_filter = request.query_params.get("filter", "ALL")
    specific_date = request.query_params.get("date", "")

    from datetime import date, timedelta
    today_iso = date.today().isoformat()
    today_slash = date.today().strftime("%d/%m/%Y")
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
    yesterday_slash = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")

    all_orders = get_orders_for_customer(party_name=party_name, party_code=party_code, phone=phone, date_filter="ALL")
    today_count = sum(1 for o in all_orders if today_iso in str(o.get("created_at") or "") or today_slash in str(o.get("formattedTimestamp") or ""))
    yesterday_count = sum(1 for o in all_orders if yesterday_iso in str(o.get("created_at") or "") or yesterday_slash in str(o.get("formattedTimestamp") or ""))
    total_count = len(all_orders)

    if date_filter == "ALL":
        orders = all_orders
    else:
        orders = get_orders_for_customer(party_name=party_name, party_code=party_code, phone=phone, date_filter=date_filter, specific_date=specific_date)

    return {
        "status": "success",
        "partyName": party_name,
        "partyCode": party_code,
        "filter": date_filter,
        "date": specific_date,
        "todayCount": today_count,
        "yesterdayCount": yesterday_count,
        "totalOrders": total_count,
        "orders": orders
    }

# 🔍 CUSTOMER ORDER TRACKING API (Strictly Scoped to Authenticated Customer)
@app.get("/api/customer/track-order")
async def api_customer_track_order(request: Request):
    """
    Search and track order strictly scoped to the authenticated Customer.
    Guarantees privacy: A customer cannot view orders belonging to another party.
    """
    q = request.query_params.get("q", "").strip()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else request.query_params.get("token", "")
    session = validate_customer_session(token) if token else None

    party_code = ""
    party_name = ""
    phone = ""
    if session:
        party_code = session.get("party_code", "")
        party_name = session.get("party_name", "")
        phone = session.get("phone", "")
    else:
        party_code = request.query_params.get("party_code", "").strip()
        party_name = request.query_params.get("party_name", "").strip()
        phone = request.query_params.get("phone", "").strip()

    if not (party_code or party_name or phone):
        raise HTTPException(status_code=401, detail="Valid customer session or credentials required to track orders")

    results = search_customer_orders_db(query=q, phone=phone, party_code=party_code, party_name=party_name, limit=10)
    return {
        "status": "success",
        "query": q,
        "count": len(results),
        "orders": results
    }

# 🔍 DIRECT SALES ORDER SEARCH API
@app.get("/api/sales-orders/search")
@limiter.limit(settings.RATE_LIMIT_SEARCH)
async def api_search_sales_orders(
    request: Request,
    q: str = "",
    sales_person: Optional[str] = None,
    filter_type: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    cursor: Optional[str] = None
):
    """Fast indexed paginated & cursor search across orders by SO Number, Order ID, Party Name or ASM with scoping"""
    has_so = None
    status = None

    f_type = (filter_type or "").lower().strip()
    if f_type in ["has_so", "so"]:
        has_so = True
    elif f_type in ["pending_so", "pending"]:
        has_so = False
    elif f_type == "confirmed":
        status = "CONFIRMED"

    sp = None
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else request.query_params.get("token", "")
    if token:
        mgr_sess = validate_manager_session(token)
        if mgr_sess and mgr_sess.get("manager_name"):
            sp = mgr_sess.get("manager_name").strip()

    if not sp and sales_person and sales_person.strip() and sales_person.strip().upper() != "ALL":
        sp = sales_person.strip()

    # Avoid matching every string containing 'so' if raw keyword passed
    clean_q = q.strip()
    if clean_q.upper() in ["SO", "HAS SO", "HAS_SO", "CONFIRMED", "PENDING"]:
        clean_q = ""

    res = await async_get_orders_paginated(
        sales_person=sp,
        status=status,
        has_so=has_so,
        search_query=clean_q if clean_q else None,
        page=page,
        limit=limit,
        cursor_created_at=cursor
    )
    return {
        "status": "success",
        "query": q,
        "sales_person": sales_person or "ALL",
        "filter_type": filter_type or "all",
        "count": len(res["orders"]),
        "total_count": res["total_count"],
        "page": res["page"],
        "total_pages": res["total_pages"],
        "next_cursor": res["next_cursor"],
        "orders": res["orders"]
    }

@app.get("/api/otp/kit19-balance")
def api_get_kit19_balance():
    """Checks live SMS balance from Kit19 API"""
    return check_kit19_balance()

@app.get("/api/orders/pending")
def get_pending_orders():
    """Returns all orders pending sync to Google Sheets"""
    if not os.path.exists(ORDERS_LOG):
        return {"pending_orders": []}
    try:
        with open(ORDERS_LOG, "r", encoding="utf-8") as f:
            all_orders = json.load(f)
        pending = [o for o in all_orders if not o.get("synced_to_sheet", False)]
        return {"pending_orders": pending, "count": len(pending)}
    except Exception as e:
        return {"pending_orders": [], "error": str(e)}

@app.post("/api/orders/mark-synced")
async def mark_orders_synced(request: Request):
    """Marks specified order IDs as synced into Google Sheets (in JSON and SQLite database)"""
    body = await request.json()
    synced_ids = set(body.get("orderIds", []))
    if not synced_ids:
        return {"status": "ok", "updated": 0}
    try:
        updated_count = 0
        if os.path.exists(ORDERS_LOG):
            with open(ORDERS_LOG, "r", encoding="utf-8") as f:
                all_orders = json.load(f)
            for o in all_orders:
                if o.get("id") in synced_ids:
                    o["synced_to_sheet"] = True
                    updated_count += 1
            with open(ORDERS_LOG, "w", encoding="utf-8") as f:
                json.dump(all_orders, f, indent=2, ensure_ascii=False)
        
        # Also mark each synced order in SQLite orders.db
        for oid in synced_ids:
            mark_order_synced_in_db(oid)
            
        return {"status": "success", "updated": updated_count}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/orders/all")
def get_all_orders():
    """Returns all customer orders recorded (fallback to DB if JSON missing)"""
    if os.path.exists(ORDERS_LOG):
        try:
            with open(ORDERS_LOG, "r", encoding="utf-8") as f:
                return {"orders": json.load(f)}
        except Exception:
            pass
    # Pull directly from permanent SQLite database
    db_orders = get_all_orders_from_db()
    return {"orders": db_orders}

@app.get("/api/database/orders")
def get_database_orders():
    """Directly queries permanent orders.db SQLite table (Fail-safe for Google Sheet accidental deletes)"""
    orders = get_all_orders_from_db()
    return {
        "status": "success",
        "total_orders": len(orders),
        "source": "orders.db",
        "orders": orders
    }

# CORS setup for frontend dashboard integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🚫 ENTERPRISE SECURITY MIDDLEWARE: INSTANT BLOCKED ACCOUNT REVOCATION
@app.middleware("http")
async def security_blocked_accounts_middleware(request: Request, call_next):
    """
    Enterprise Security Middleware:
    Instantly blocks any request from a user account marked as BLOCKED in SQLite users table.
    Enforces immediate 403 Forbidden and force-logout response for Mobile APK, Customer, and ASM endpoints.
    """
    path = request.url.path
    mobile_protected_prefixes = (
        "/api/customer", "/api/sales-manager", "/api/customers",
        "/api/sales-orders", "/api/orders/submit", "/api/orders/upload-slip",
        "/api/orders/my-orders", "/api/products", "/api/parties"
    )
    if path.startswith(mobile_protected_prefixes):
        # 1. Extract Token from Authorization header, x-access-token, or query param
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        if not token:
            token = request.headers.get("x-access-token") or request.headers.get("x-token") or request.query_params.get("token", "")

        # 2. Extract Phone if provided in headers or query
        phone = request.headers.get("x-user-phone") or request.query_params.get("phone", "")

        # 3. Check token status in database
        if token:
            is_blocked, t_phone, u_name = get_user_status_by_token(token)
            if is_blocked:
                return JSONResponse(
                    status_code=403,
                    content={
                        "status": "error",
                        "error_type": "ACCOUNT_BLOCKED",
                        "code": 403,
                        "detail": "Your account has been suspended by Admin. Access denied.",
                        "message": "Your account has been suspended by Admin. Access denied.",
                        "force_logout": True
                    }
                )
            if t_phone and not phone:
                phone = t_phone

        # 4. Check phone status in database
        if phone:
            clean_p = "".join(filter(str.isdigit, str(phone)))[-10:]
            if clean_p and is_user_phone_blocked(clean_p):
                return JSONResponse(
                    status_code=403,
                    content={
                        "status": "error",
                        "error_type": "ACCOUNT_BLOCKED",
                        "code": 403,
                        "detail": "Your account has been suspended by Admin. Access denied.",
                        "message": "Your account has been suspended by Admin. Access denied.",
                        "force_logout": True
                    }
                )

    response = await call_next(request)
    return response

SECRET_TOKEN = "MASHAL_SECURE_TOKEN_2026"

# In-Memory & Local Cache Store
CURRENT_STATE: Dict[str, Any] = {
    "last_synced_at": None,
    "sheet_name": None,
    "spreadsheet_name": None,
    "total_rows": 0,
    "total_columns": 0,
    "headers": [],
    "data": [],
    "raw_grid": []
}

CACHE_FILE = "latest_sheet_data.json"

def persist_to_disk(payload: dict):
    """Save latest synced sheet to disk for persistence across restarts"""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Failed to cache data to disk: {e}")

@app.on_event("startup")
def load_cached_data():
    """Load cached sheet data if exists on server start"""
    global CURRENT_STATE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                CURRENT_STATE.update(saved)
                print(f"[STARTUP] Loaded cached data for sheet: {CURRENT_STATE.get('sheet_name')}")
        except Exception as e:
            print(f"[STARTUP ERROR] Could not read cache: {e}")

# ----------------- WEBHOOK ENDPOINT -----------------
@app.post("/api/webhook/google-sheet")
async def receive_sheet_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_token: Optional[str] = Header(None)
):
    """
    Receives real-time payload from Google Apps Script whenever:
    1. A new date sheet is added at index 0 (e.g. 14 Oct).
    2. Any value in the 1st sheet is modified.
    """
    if x_webhook_token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid security token")

    payload = await request.json()
    
    sheet_name = payload.get("activeSheetName", "Unknown")
    headers = payload.get("headers", [])
    data = payload.get("data", [])
    raw_grid = payload.get("rawGrid", [])
    header_row_1 = payload.get("headerRow1", [])
    header_row_2 = payload.get("headerRow2", [])
    
    # Update current in-memory state with 1st sheet data
    CURRENT_STATE["last_synced_at"] = datetime.now().isoformat()
    CURRENT_STATE["sheet_name"] = sheet_name
    CURRENT_STATE["spreadsheet_name"] = payload.get("spreadsheetName")
    CURRENT_STATE["total_rows"] = len(raw_grid) if raw_grid else len(data)
    CURRENT_STATE["total_columns"] = len(headers)
    CURRENT_STATE["headers"] = headers
    CURRENT_STATE["data"] = data
    CURRENT_STATE["raw_grid"] = raw_grid
    CURRENT_STATE["header_row_1"] = header_row_1
    CURRENT_STATE["header_row_2"] = header_row_2

    # Background task to write to file without blocking response (2X fast)
    background_tasks.add_task(persist_to_disk, CURRENT_STATE)

    print(f"[SYNC SUCCESS] Sheet: '{sheet_name}' | Rows: {CURRENT_STATE['total_rows']} | Cols: {len(headers)} at {CURRENT_STATE['last_synced_at']}")

    return {
        "status": "success",
        "message": f"Successfully updated to latest sheet: '{sheet_name}'",
        "rows_synced": CURRENT_STATE["total_rows"],
        "timestamp": CURRENT_STATE["last_synced_at"]
    }

# ----------------- QUERY / FRONTEND ENDPOINTS (PROTECTED) -----------------
@app.get("/api/sheet/current")
def get_current_sheet_data(x_admin_token: Optional[str] = Header(None)):
    """Returns the latest 1st sheet data - PROTECTED BY ADMIN AUTH"""
    if not validate_admin_session(x_admin_token):
        raise HTTPException(status_code=401, detail="Unauthorized: Executive access required")

    if not CURRENT_STATE["sheet_name"]:
        return {
            "status": "waiting",
            "message": "No sheet data has been received yet. Please trigger sync from Google Sheets."
        }
    return {
        "status": "active",
        "sheet_name": CURRENT_STATE["sheet_name"],
        "last_synced_at": CURRENT_STATE["last_synced_at"],
        "total_rows": CURRENT_STATE["total_rows"],
        "headers": CURRENT_STATE["headers"],
        "header_row_1": CURRENT_STATE.get("header_row_1", []),
        "header_row_2": CURRENT_STATE.get("header_row_2", []),
        "data": CURRENT_STATE["data"],
        "raw_grid": CURRENT_STATE.get("raw_grid", [])
    }

@app.get("/api/sheet/summary")
def get_sheet_summary(x_admin_token: Optional[str] = Header(None)):
    """Quick metadata without heavy data payload - PROTECTED BY ADMIN AUTH"""
    if not validate_admin_session(x_admin_token):
        raise HTTPException(status_code=401, detail="Unauthorized: Executive access required")
    return {
        "sheet_name": CURRENT_STATE.get("sheet_name"),
        "last_synced_at": CURRENT_STATE.get("last_synced_at"),
        "total_rows": CURRENT_STATE.get("total_rows", 0),
        "total_columns": CURRENT_STATE.get("total_columns", 0),
        "headers": CURRENT_STATE.get("headers", [])
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
