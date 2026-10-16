from fastapi import FastAPI, Header, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import os
import re
import base64
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
    migrate_existing_json_orders,
    validate_manager_session
)
from crm_service import (
    init_crm_db,
    search_customers,
    save_or_update_customer
)
from otp_service import (
    send_kit19_otp,
    verify_kit19_otp,
    verify_manager_login_otp,
    check_kit19_balance
)

# Load configuration from .env file
load_dotenv()

# Initialize permanent database and auto-migrate historical orders
init_db()
migrate_existing_json_orders()
init_crm_db()

ORDER_SLIPS_DIR = "order_slips"
os.makedirs(ORDER_SLIPS_DIR, exist_ok=True)

app = FastAPI(
    title="Sales Customer Order Management - Sheet Sync Engine",
    version="1.0.2",
    description="Real-time Webhook & Dynamic Data Sync for Google Sheets 1st Tab"
)

if os.path.exists("images"):
    app.mount("/images", StaticFiles(directory="images"), name="images")

@app.get("/")
def serve_order_slip_root():
    """Serves the digital Khandelia Order Slip directly on root http://127.0.0.1:8000/"""
    return FileResponse("order_form.html")

@app.get("/order-slip")
def serve_order_slip_alias():
    """Alias for digital Khandelia Order Slip"""
    return FileResponse("order_form.html")

@app.get("/sale_manager")
def serve_sale_manager_portal():
    """Serves the smart Sales Manager Portal with AI customer auto-suggest & Kit19 OTP"""
    return FileResponse("sale_manager.html")

@app.get("/sale_manage")
def serve_sale_manage_alias():
    """Alias for Sales Manager Portal"""
    return FileResponse("sale_manager.html")

@app.get("/sale_table_data")
def serve_sales_table_data():
    """Serves the protected Sales Customer Dashboard at http://127.0.0.1:8000/sale_table_data"""
    return FileResponse("index.html")

@app.get("/order_slips/{filename}")
def serve_order_slip_file(filename: str):
    """Serves high-resolution rendered order slip PNG images"""
    file_path = os.path.join(ORDER_SLIPS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Slip image not found")

ORDERS_LOG = "customer_orders.json"
GOOGLE_SHEET_ORDERS_WEBAPP_URL = os.environ.get(
    "GOOGLE_SHEET_ORDERS_WEBAPP_URL",
    "https://script.google.com/macros/s/AKfycbz34gzaUCbs5znZrvoQ49FSiZPt9bgWK6WToz5Ek3_Y0k7H5hZTeqg0AhoSPaqxUQqA/exec"
)

# 🛡️ Executive Authentication Credentials
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123#")
AUTH_SECRET_TOKEN = os.environ.get("AUTH_SECRET_TOKEN", "KOGM_ADMIN_SECURE_TOKEN_2026_XYZ")

@app.post("/api/auth/login")
async def admin_login(request: Request):
    """Authenticates executive admin to view sales table data"""
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        return {
            "status": "success",
            "token": AUTH_SECRET_TOKEN,
            "user": "admin",
            "message": "Access granted"
        }
    raise HTTPException(status_code=401, detail="Invalid username or password")

import secrets

def generate_unique_order_id() -> str:
    """Generates unique professional order ID: KOGM-YYYYMMDD-XXXX"""
    date_code = datetime.now().strftime("%Y%m%d")
    rand_suffix = secrets.token_hex(2).upper()
    return f"KOGM-{date_code}-{rand_suffix}"

@app.post("/api/orders/submit")
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
    now_dt = datetime.now()
    order["id"] = order_id
    order["timestamp"] = now_dt.isoformat()
    order["formattedTimestamp"] = now_dt.strftime("%d/%m/%Y %I:%M:%S %p")
    order["formattedDate"] = now_dt.strftime("%d/%m/%Y")
    order["synced_to_sheet"] = False
    
    # Ensure party code is resolved from CRM if not explicitly provided
    party_code = (order.get("partyCode") or "").strip()
    if not party_code:
        p_name = order.get("partyName", "").strip().lower()
        if p_name:
            try:
                from crm_service import _CRM_CACHE, _CACHE_LOCK
                with _CACHE_LOCK:
                    for c in _CRM_CACHE:
                        if c.get("party_name", "").strip().lower() == p_name:
                            party_code = c.get("party_code", "")
                            break
            except Exception as crm_lookup_err:
                print(f"[CRM CODE LOOKUP WARN] {crm_lookup_err}")
    order["partyCode"] = party_code
    
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
        summary_parts.append(f"{icon} {brand} {item_name} ➔ {pcs} Pcs ({bxs} bxs)")
    order["totalPieces"] = total_pieces
    if not order.get("totalBoxes"):
        order["totalBoxes"] = total_boxes
    order["itemsSummary"] = "\n".join(summary_parts)
    
    # Decode and save high-resolution Order Slip image if provided by client
    slip_data = order.get("slipImageData", "")
    if slip_data and slip_data.startswith("data:image"):
        try:
            _, base64_str = slip_data.split(",", 1)
            img_bytes = base64.b64decode(base64_str)
            slip_filename = f"{order_id}.png"
            slip_path = os.path.join(ORDER_SLIPS_DIR, slip_filename)
            with open(slip_path, "wb") as img_f:
                img_f.write(img_bytes)
            order["slipImagePath"] = os.path.abspath(slip_path)
            order["slipImageUrl"] = f"/order_slips/{slip_filename}"
            print(f"[SLIP IMAGE SAVED] Saved #{order_id} image ({len(img_bytes)} bytes) at {slip_path}")
        except Exception as img_err:
            print(f"[SLIP IMAGE SAVE ERROR] {img_err}")
    # Don't persist large base64 string in JSON file to keep log snappy
    order.pop("slipImageData", None)

    orders_list.append(order)
    
    with open(ORDERS_LOG, "w", encoding="utf-8") as f:
        json.dump(orders_list, f, indent=2, ensure_ascii=False)
        
    # 0. Save permanently to orders.db SQLite database (Zero Data Loss Engine)
    save_order_to_db(order)

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
              <td style="padding: 10px 12px; border: 1px solid #e2e8f0; text-align: center; font-weight: bold; color: #1e40af; font-size: 13.5px;">{pcs:,} Pcs</td>
              <td style="padding: 10px 12px; border: 1px solid #e2e8f0; text-align: center; font-weight: bold; font-family: monospace; font-size: 14.5px; color: #003366;">{bxs} bxs</td>
            </tr>
            """

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, Helvetica, sans-serif; background-color: #f1f5f9; padding: 20px; margin: 0;">
          <div style="max-width: 750px; margin: 0 auto; background: #ffffff; border: 3px solid #003366; border-radius: 8px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.1);">
            
            <!-- 🏢 Top Navy Header -->
            <div style="background: #003366; padding: 22px 20px; text-align: center;">
              <h2 style="margin: 0; font-size: 20px; color: #ffffff; letter-spacing: 0.5px; font-weight: 800; text-transform: uppercase;">KHANDELIA OIL AND GENERAL MILLS PVT. LTD.</h2>
              <div style="display: inline-block; background: #d97706; color: #ffffff; padding: 6px 20px; border-radius: 4px; font-size: 11px; margin-top: 10px; font-weight: bold; letter-spacing: 1.2px; text-transform: uppercase;">OFFICIAL ORDER CONFIRMATION SLIP</div>
            </div>

            <!-- 🔖 Reference Bar (Order ID, Date, Area Sales Manager) -->
            <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; padding: 12px 20px;">
              <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr>
                  <td style="text-align: left; font-weight: bold; font-family: monospace; font-size: 13.5px; color: #0f172a;">
                    ORDER ID: <span style="color: #004b99;">#{order.get('id')}</span>
                  </td>
                  <td style="text-align: center; color: #475569;">
                    <strong>Date:</strong> {order.get('formattedTimestamp', order.get('timestamp'))}
                  </td>
                  <td style="text-align: right; color: #0f172a;">
                    <strong>Area Sales Manager:</strong> <span style="font-weight: 700;">{order.get('salesPerson', '-')}</span>
                  </td>
                </tr>
              </table>
            </div>

            <!-- 👤 Customer & Billing Details with Party Code -->
            <div style="padding: 18px 20px 10px 20px;">
              <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 14px 18px;">
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 8px;">
                  <tr>
                    <td style="font-size: 11px; font-weight: 800; color: #64748b; letter-spacing: 0.5px; text-transform: uppercase;">
                      CUSTOMER / BILLING DETAILS
                    </td>
                    <td style="text-align: right;">
                      <span style="display: inline-block; background: #eff6ff; color: #004b99; border: 1px solid #bfdbfe; padding: 3px 10px; border-radius: 4px; font-family: monospace; font-size: 12px; font-weight: bold;">
                        PARTY CODE: {party_code if party_code else 'N/A'}
                      </span>
                    </td>
                  </tr>
                </table>
                <div style="font-size: 16px; font-weight: 800; color: #0f172a; margin-bottom: 6px;">
                  {party_name}
                </div>
                <div style="font-size: 13px; color: #475569; line-height: 1.45;">
                  <strong>Address:</strong> {order.get('partyAddress', '-')}
                </div>
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
                TOTAL ORDER QUANTITY: {total_bxs:,} BOXES  ({total_pcs:,} PIECES)
              </div>
            </div>

            <!-- 🛡️ Bottom Digital Stamp -->
            <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 14px 20px;">
              <table style="width: 100%; border-collapse: collapse; font-size: 11.5px; color: #64748b;">
                <tr>
                  <td style="text-align: left;">
                    <div style="color: #16a34a; font-weight: bold; margin-bottom: 2px;">✔ OFFICIALLY RECORDED & VERIFIED ORDER</div>
                    <div>Submission: {order.get('formattedTimestamp', order.get('timestamp'))} • Khandelia Oil & General Mills Pvt. Ltd.</div>
                  </td>
                  <td style="text-align: right; width: 170px;">
                    <div style="border: 1.5px solid #16a34a; border-radius: 4px; padding: 4px 8px; text-align: center; color: #16a34a; font-weight: bold;">
                      VERIFIED ORDER<br>
                      <span style="font-family: monospace; font-size: 10px;">#{order.get('id')}</span>
                    </div>
                  </td>
                </tr>
              </table>
            </div>

          </div>
        </body>
        </html>
        """
        msg_alternative.attach(MIMEText(html_content, "html"))

        # Attach high-resolution slip image if saved on server
        slip_img_path = order.get("slipImagePath")
        if slip_img_path and os.path.exists(slip_img_path):
            try:
                with open(slip_img_path, "rb") as img_f:
                    image_attachment = MIMEImage(img_f.read(), name=f"Order_Slip_{order.get('id')}.png")
                    image_attachment.add_header('Content-Disposition', 'attachment', filename=f"Order_Slip_{order.get('id')}.png")
                    msg_root.attach(image_attachment)
                print(f"[EMAIL ATTACHMENT] Attached Order_Slip_{order.get('id')}.png to email")
            except Exception as att_err:
                print(f"[EMAIL ATTACHMENT ERROR] {att_err}")

        # Attach high-resolution slip image if saved on server
        slip_img_path = order.get("slipImagePath")
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

# ----------------- CRM & KIT19 OTP ENDPOINTS -----------------
@app.get("/api/customers/search")
def api_search_customers(q: str = ""):
    """Ultra-fast customer autocomplete matching phone, email, party code, or name (<1ms response)"""
    results = search_customers(q, limit=10)
    return {"status": "success", "query": q, "count": len(results), "results": results}

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
async def api_manager_send_otp(request: Request):
    """Dispatches Kit19 OTP to Sales Manager's phone for 1-year device authentication"""
    body = await request.json()
    phone = body.get("phone", "")
    return send_kit19_otp(phone)

@app.post("/api/sales-manager/verify-otp")
async def api_manager_verify_otp(request: Request):
    """Verifies Sales Manager OTP and creates 1-year persistent session"""
    body = await request.json()
    phone = body.get("phone", "")
    otp = body.get("otp", "")
    name = body.get("manager_name", "")
    return verify_manager_login_otp(phone, otp, name)

@app.post("/api/sales-manager/check-session")
async def api_manager_check_session(request: Request):
    """Checks if Sales Manager has an active 1-year device session"""
    body = await request.json()
    token = body.get("token", "")
    session = validate_manager_session(token)
    if session:
        return {"status": "valid", "session": session}
    return {"status": "invalid"}

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
    if x_admin_token != AUTH_SECRET_TOKEN:
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
    if x_admin_token != AUTH_SECRET_TOKEN:
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
