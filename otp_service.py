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

load_dotenv()

KIT19_API_URL = os.environ.get("KIT19_API_URL", "https://www.kit19.com/ComposeSMS.aspx")
KIT19_USERNAME = os.environ.get("KIT19_USERNAME", "khandelia348774")
KIT19_PASSWORD = os.environ.get("KIT19_PASSWORD", "")
KIT19_SENDER_ID = os.environ.get("KIT19_SENDER_ID", "KHANDL")
KIT19_DLT_TEMPLATE_ID = os.environ.get("KIT19_DLT_TEMPLATE_ID", "")

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
    if not (KIT19_USERNAME and KIT19_PASSWORD):
        return {"status": "error", "message": "KIT19_USERNAME or KIT19_PASSWORD not configured in .env"}
    try:
        url = f"https://www.kit19.com/BalanceCheck.aspx?username={urllib.parse.quote(KIT19_USERNAME)}&password={urllib.parse.quote(KIT19_PASSWORD)}"
        req = urllib.request.Request(url, headers={"User-Agent": "KhandeliaOMS/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8").strip()
            return {"status": "success", "balance_response": content}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def send_kit19_otp(phone: str) -> Dict[str, Any]:
    """
    Generates and dispatches a 6-digit OTP to the recipient's phone number using Kit19 HTTP API.
    URL Format (from Kit19 Dashboard):
    https://www.kit19.com/ComposeSMS.aspx?username=username&password=password&sender=senderid&to=MobileNo&message=Message&priority=1&dnd=1&unicode=0&dlttemplateid=dlttemplateid
    """
    phone_clean = clean_phone(phone)
    if len(phone_clean) != 10:
        return {"status": "error", "message": "Please enter a valid 10-digit mobile number."}

    # Anti-flood check: if last OTP was generated < 25s ago, reuse or reject
    now = time.time()
    existing = _ACTIVE_OTPS.get(phone_clean)
    if existing and (now - existing.get("created_at", 0)) < 25:
        remaining = int(25 - (now - existing.get("created_at", 0)))
        return {
            "status": "error",
            "message": f"Please wait {remaining} seconds before requesting a new OTP."
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

    message_text = f"Your verification OTP for Khandelia Order Management is {otp}. Valid for 5 minutes. Do not share with anyone."

    # If Kit19 credentials are provided in .env, send live HTTP request
    if KIT19_USERNAME and KIT19_PASSWORD:
        try:
            # Prepare query parameters matching exact Kit19 dashboard spec
            params = {
                "username": KIT19_USERNAME,
                "password": KIT19_PASSWORD,
                "sender": KIT19_SENDER_ID,
                "to": phone_clean,
                "message": message_text,
                "priority": "1",
                "dnd": "1",
                "unicode": "0"
            }
            if KIT19_DLT_TEMPLATE_ID:
                params["dlttemplateid"] = KIT19_DLT_TEMPLATE_ID

            query_str = urllib.parse.urlencode(params)
            # Kit19 specific requirement: '%26' for '&' and '%2B' for '+'
            query_str = query_str.replace("+", "%20")
            full_url = f"{KIT19_API_URL}?{query_str}"
            
            req = urllib.request.Request(full_url, headers={"User-Agent": "KhandeliaOMS/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_text = resp.read().decode("utf-8").strip()
                print(f"[KIT19 HTTP API] OTP sent to {phone_clean} | Response: {resp_text}")
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
        "manager_name": manager_name,
        "expires_at": session["expires_at"],
        "validity_days": 365,
        "message": "Sales Manager verified successfully! Valid for 1 Year."
    }
