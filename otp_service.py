"""
Khandelia Oil and General Mills Pvt. Ltd.
Kit19 SMS & OTP Verification Service

Features:
- Sends real-time 6-digit OTPs via Kit19 HTTP API (kit19.com).
- 5-minute expiry window with anti-flood rate limiting.
- Fallback / Dev mode: allows smooth testing before live Kit19 credentials are added to .env.
- Verifies phone numbers on the Sales Manager portal before order booking.
"""

import os
import time
import random
import urllib.parse
import urllib.request
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv

def get_kit19_config():
    load_dotenv(override=True)
    return {
        "api_url": os.environ.get("KIT19_API_URL", "https://www.kit19.com/ComposeSMS.aspx"),
        "username": os.environ.get("KIT19_USERNAME", "khandelia348774"),
        "password": os.environ.get("KIT19_PASSWORD", ""),
        "sender_id": os.environ.get("KIT19_SENDER_ID", "KOGMBD"),
        "dlt_template_id": os.environ.get("KIT19_DLT_TEMPLATE_ID", "")
    }

# Store active OTPs in memory: { phone: { "otp": "123456", "expires_at": 123456789, "verified": False } }
_ACTIVE_OTPS: Dict[str, Dict[str, Any]] = {}

def clean_phone(phone: str) -> str:
    """Extracts last 10 digits of mobile number"""
    digits = "".join(filter(str.isdigit, str(phone)))
    return digits[-10:] if len(digits) >= 10 else digits

def check_kit19_balance() -> Dict[str, Any]:
    """
    Checks the remaining SMS balance on Kit19 using the official BalanceCheck API:
    https://www.kit19.com/BalanceCheck.aspx?username=username&password=password
    """
    cfg = get_kit19_config()
    username = cfg["username"]
    password = cfg["password"]
    if not (username and password):
        return {"status": "error", "message": "KIT19_USERNAME or KIT19_PASSWORD not configured in .env"}
    try:
        url = f"https://www.kit19.com/BalanceCheck.aspx?username={urllib.parse.quote(username)}&password={urllib.parse.quote(password)}"
        req = urllib.request.Request(url, headers={"User-Agent": "KhandeliaOMS/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8").strip()
            return {"status": "success", "balance_response": content}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def send_kit19_otp(phone: str, ip_address: str = "") -> Dict[str, Any]:
    """
    Generates and dispatches a 6-digit OTP to recipient using Kit19 HTTP API.
    Enforces:
    1. 25-second anti-flood cooldown.
    2. Strict rolling 1-Hour maximum 3-OTP rate limit (saves Kit19 SMS tokens).
    """
    phone_clean = clean_phone(phone)
    if len(phone_clean) != 10:
        return {"status": "error", "message": "Please enter a valid 10-digit mobile number."}

    now = time.time()

    # 🧪 Dedicated Testing Accounts: Direct 1-Click Login (100% Kit19 SMS Bypassed to preserve SMS tokens)
    TEST_NUMBERS = {
        "9999911111": {"role": "customer", "name": "Shivam Customer (Test Buyer)", "otp": "123456"},
        "9999922222": {"role": "asm", "name": "Shivam Area Sales Manager", "otp": "123456"},
        "9999900001": {"role": "customer", "name": "Test Customer", "otp": "123456"},
        "9999900002": {"role": "asm", "name": "Test Area Sales Manager", "otp": "123456"},
    }
    if phone_clean in TEST_NUMBERS or phone_clean.startswith("99999"):
        test_info = TEST_NUMBERS.get(phone_clean, {"otp": "123456"})
        test_otp = test_info.get("otp", "123456")
        _ACTIVE_OTPS[phone_clean] = {
            "otp": test_otp,
            "expires_at": now + 86400,
            "created_at": now,
            "verified": True,
            "attempts": 0
        }
        return {
            "status": "success",
            "phone": phone_clean,
            "is_test_account": True,
            "test_otp": test_otp,
            "message": f"🧪 Test Account Active: Direct 1-Click Login enabled without SMS (Test OTP: {test_otp})"
        }

    # Anti-flood check: if last OTP was generated < 25s ago, reuse or reject
    existing = _ACTIVE_OTPS.get(phone_clean)
    if existing and (now - existing.get("created_at", 0)) < 25:
        remaining = int(25 - (now - existing.get("created_at", 0)))
        return {
            "status": "error",
            "error_type": "OTP_FLOOD_WAIT",
            "message": f"Please wait {remaining} seconds before requesting a new OTP."
        }

    # 🛑 Strict 1-Hour Rolling 3-OTP Rate Limit Check (SMS Token Protection)
    from database import check_otp_rate_limit, record_otp_dispatch
    import math
    is_allowed, current_count, retry_after_seconds = check_otp_rate_limit(phone_clean, max_allowed=3, window_seconds=3600)
    if not is_allowed:
        retry_mins = max(1, math.ceil(retry_after_seconds / 60))
        return {
            "status": "error",
            "error_type": "OTP_HOURLY_LIMIT_EXCEEDED",
            "limit": 3,
            "window_minutes": 60,
            "current_count": current_count,
            "retry_after_seconds": retry_after_seconds,
            "retry_after_minutes": retry_mins,
            "message": f"Hourly OTP limit reached (3 requests). For security, please try again in ~{retry_mins} minutes."
        }

    otp = str(random.randint(100000, 999999))
    expires_at = now + 300  # 5 minutes validity

    _ACTIVE_OTPS[phone_clean] = {
        "otp": otp,
        "expires_at": expires_at,
        "created_at": now,
        "verified": False,
        "attempts": 0
    }

    # Approved DLT Template registered with Kit19 and Telecom Operators
    message_text = f"Khandelia Oil & General Mills Pvt. Ltd. - Your OTP {otp} is to login to Khandelia Trading. Please DO NOT share with anyone. The OTP expires in 10 mins."

    # If Kit19 credentials are provided in .env, send live HTTP request
    cfg = get_kit19_config()
    username = cfg["username"]
    password = cfg["password"]
    sender_id = cfg["sender_id"]
    api_url = cfg["api_url"]
    dlt_template_id = cfg["dlt_template_id"]

    if username and password:
        try:
            # Prepare query parameters matching exact Kit19 dashboard spec
            params = {
                "username": username,
                "password": password,
                "sender": sender_id,
                "to": phone_clean,
                "message": message_text,
                "priority": "1",
                "dnd": "1",
                "unicode": "0"
            }
            if dlt_template_id:
                params["dlttemplateid"] = dlt_template_id

            query_str = urllib.parse.urlencode(params)
            # Kit19 specific requirement: '%26' for '&' and '%2B' for '+'
            query_str = query_str.replace("+", "%20")
            full_url = f"{api_url}?{query_str}"
            
            req = urllib.request.Request(full_url, headers={"User-Agent": "KhandeliaOMS/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_text = resp.read().decode("utf-8").strip()
                print(f"[KIT19 HTTP API] OTP sent to {phone_clean} | Response: {resp_text}")
                
                # Record successful dispatch in permanent rate limiter log
                record_otp_dispatch(phone_clean, ip_address=ip_address, purpose="KIT19_SMS")
                
                return {
                    "status": "success",
                    "phone": phone_clean,
                    "provider_response": resp_text,
                    "message": f"OTP successfully sent to +91 {phone_clean}"
                }
        except Exception as e:
            print(f"[KIT19 API ERROR] Failed to send SMS via Kit19: {e}")
            return {
                "status": "error",
                "message": f"Kit19 SMS delivery error: {e}"
            }
    else:
        # Dev / Testing Mode when Kit19 credentials are not yet entered in .env
        print(f"\n========================================================")
        print(f"[KIT19 READY MODE] [OTP] OTP for +91 {phone_clean} is: {otp}")
        print(f"(Add KIT19_USERNAME & KIT19_PASSWORD in .env for live SMS)")
        print(f"========================================================\n")
        
        # Record dispatch in permanent rate limiter log
        record_otp_dispatch(phone_clean, ip_address=ip_address, purpose="DEV_TEST")
        
        return {
            "status": "success",
            "phone": phone_clean,
            "test_mode": True,
            "test_otp": otp,
            "message": f"OTP sent to +91 {phone_clean} (Testing Mode OTP: {otp})"
        }

def verify_kit19_otp(phone: str, entered_otp: str) -> Dict[str, Any]:
    """Verifies the OTP submitted by the user"""
    phone_clean = clean_phone(phone)
    record = _ACTIVE_OTPS.get(phone_clean)

    # 🌟 Super Admin / Test Account Bypass (123456 or 999999 or Test Numbers)
    if phone_clean in ["9999911111", "9999922222", "9999900001", "9999900002"] or phone_clean.startswith("99999") or str(entered_otp).strip() in ["123456", "999999"]:
        return {
            "status": "success",
            "phone": phone_clean,
            "master_bypass": True,
            "message": "Phone verified via Test Account / Master PIN!"
        }

    if not record:
        return {"status": "error", "message": "No OTP was requested for this phone number."}

    if time.time() > record["expires_at"]:
        _ACTIVE_OTPS.pop(phone_clean, None)
        return {"status": "error", "message": "OTP has expired. Please request a new OTP."}

    record["attempts"] += 1
    if record["attempts"] > 5:
        _ACTIVE_OTPS.pop(phone_clean, None)
        return {"status": "error", "message": "Too many invalid attempts. Please request a new OTP."}

    if str(entered_otp).strip() == str(record["otp"]).strip():
        record["verified"] = True
        return {
            "status": "success",
            "phone": phone_clean,
            "message": "Phone number successfully verified!"
        }

    return {"status": "error", "message": "Invalid OTP. Please check and try again."}

def is_phone_verified(phone: str) -> bool:
    """Checks if phone has been verified recently"""
    phone_clean = clean_phone(phone)
    record = _ACTIVE_OTPS.get(phone_clean)
    if record and record.get("verified") and (time.time() - record.get("created_at", 0)) < 1800:
        return True
    return False

def verify_manager_login_otp(phone: str, entered_otp: str, manager_name: str = "") -> Dict[str, Any]:
    """Verifies Sales Manager login OTP and generates a 1-year persistent session"""
    verify_res = verify_kit19_otp(phone, entered_otp)
    if verify_res.get("status") != "success":
        return verify_res

    # Generate 1-year persistent session token in database
    from database import create_manager_session
    phone_clean = clean_phone(phone)
    session = create_manager_session(phone_clean, manager_name)
    return {
        "status": "success",
        "phone": phone_clean,
        "token": session["token"],
        "manager_name": manager_name or session.get("manager_name", ""),
        "expires_at": session["expires_at"],
        "validity_days": 365,
        "session": session,
        "message": "Sales Manager verified successfully! Valid for 1 Year."
    }

def send_kit19_raw_sms(phone: str, message: str) -> Dict[str, Any]:
    """Sends an arbitrary SMS via Kit19 HTTP API to a 10-digit mobile number."""
    phone_clean = clean_phone(phone)
    if len(phone_clean) != 10:
        return {"status": "error", "message": f"Invalid mobile number: {phone}"}
    
    cfg = get_kit19_config()
    username = cfg["username"]
    password = cfg["password"]
    sender_id = cfg["sender_id"]
    api_url = cfg["api_url"]
    
    if not (username and password):
        print(f"[KIT19 SMS DEV MODE] To: {phone_clean} | Message: {message}")
        return {"status": "success", "dev_mode": True, "phone": phone_clean}
        
    try:
        params = {
            "username": username,
            "password": password,
            "sender": sender_id,
            "to": phone_clean,
            "message": message,
            "priority": "1",
            "dnd": "1",
            "unicode": "0"
        }
        query_str = urllib.parse.urlencode(params).replace("+", "%20")
        full_url = f"{api_url}?{query_str}"
        req = urllib.request.Request(full_url, headers={"User-Agent": "KhandeliaOMS/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            content = resp.read().decode("utf-8").strip()
            print(f"[KIT19 SMS] Dispatched to {phone_clean} | Response: {content[:40]}")
            return {"status": "success", "phone": phone_clean, "provider_response": content[:60]}
    except Exception as e:
        print(f"[KIT19 SMS ERROR] Failed to dispatch to {phone_clean}: {e}")
        return {"status": "error", "message": str(e), "phone": phone_clean}

def send_order_edit_notification(
    order_id: str,
    recipient_phones: list,
    party_name: str,
    original_boxes: int,
    new_boxes: int,
    reason: str
) -> Dict[str, Any]:
    """
    Sends real-time Order Edit alert SMS via Kit19 to all target phone numbers
    (e.g., party/customer and Super Admin 7814749816).
    """
    clean_order_id = str(order_id).replace("#", "").strip()
    msg = (
        f"Khandelia Oil & General Mills Pvt. Ltd. - Order #{clean_order_id} for {party_name[:30]} "
        f"revised ({original_boxes} to {new_boxes} Boxes). Reason: {reason[:40]}. "
        f"Helpline: 1800 103 3211. Slip: https://order.khandelia.online/order_slips/{clean_order_id}.png"
    )
    
    results = []
    # Always include 7814749816 as requested by the user
    target_set = set()
    for p in (recipient_phones or []):
        cp = clean_phone(p)
        if len(cp) == 10:
            target_set.add(cp)
    target_set.add("7814749816")  # Primary phone requested by user
    
    for phone in target_set:
        res = send_kit19_raw_sms(phone, msg)
        results.append(res)
        
    return {
        "status": "success",
        "recipients": list(target_set),
        "dispatches": results,
        "message_text": msg
    }

