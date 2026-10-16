import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_QUEUE_FILE = "whatsapp_orders_queue.json"
TARGET_WHATSAPP_NUMBER = os.environ.get("TARGET_WHATSAPP_NUMBER", "917814749816")

def enqueue_whatsapp_order(order: Dict[str, Any]):
    """
    Adds order to persistent WhatsApp queue.
    If WhatsApp bot is running (now or in the morning), it picks this up and delivers image & text.
    """
    queue: List[Dict[str, Any]] = []
    if os.path.exists(WHATSAPP_QUEUE_FILE):
        try:
            with open(WHATSAPP_QUEUE_FILE, "r", encoding="utf-8") as f:
                queue = json.load(f)
        except Exception:
            queue = []
            
    # Check if already enqueued
    order_id = order.get("id")
    for item in queue:
        if item.get("order_id") == order_id:
            return item
            
    slip_path = order.get("slipImagePath", "")
    if not slip_path:
        slip_filename = f"{order_id}.png"
        cand_path = os.path.join("order_slips", slip_filename)
        if os.path.exists(cand_path):
            slip_path = os.path.abspath(cand_path)
    else:
        slip_path = os.path.abspath(slip_path)

    queue_entry = {
        "order_id": order_id,
        "party_name": order.get("partyName", ""),
        "total_boxes": order.get("totalBoxes", 0),
        "sales_person": order.get("salesPerson", "-"),
        "delivery_address": order.get("deliveryAddress", "-"),
        "timestamp": order.get("formattedTimestamp", datetime.now().strftime("%d/%m/%Y %I:%M:%S %p")),
        "slip_image_path": slip_path,
        "items": order.get("items", []),
        "status": "PENDING",
        "created_at": datetime.now().isoformat(),
        "target_number": TARGET_WHATSAPP_NUMBER
    }
    
    queue.append(queue_entry)
    
    try:
        with open(WHATSAPP_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
        print(f"[WHATSAPP QUEUE] Enqueued order #{order_id} for {TARGET_WHATSAPP_NUMBER}")
    except Exception as e:
        print(f"[WHATSAPP QUEUE ERROR] {e}")

    return queue_entry

def get_pending_whatsapp_orders() -> List[Dict[str, Any]]:
    """Returns all orders pending delivery via WhatsApp"""
    if not os.path.exists(WHATSAPP_QUEUE_FILE):
        return []
    try:
        with open(WHATSAPP_QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
        return [item for item in queue if item.get("status") == "PENDING"]
    except Exception:
        return []

def mark_whatsapp_order_sent(order_id: str):
    """Marks order as delivered via WhatsApp in both queue and database"""
    if os.path.exists(WHATSAPP_QUEUE_FILE):
        try:
            with open(WHATSAPP_QUEUE_FILE, "r", encoding="utf-8") as f:
                queue = json.load(f)
            for item in queue:
                if item.get("order_id") == order_id:
                    item["status"] = "SENT"
                    item["sent_at"] = datetime.now().isoformat()
            with open(WHATSAPP_QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(queue, f, indent=2, ensure_ascii=False)
            print(f"[WHATSAPP SENT] Order #{order_id} marked as delivered in queue!")
        except Exception as e:
            print(f"[WHATSAPP MARK ERROR] {e}")

    try:
        from database import mark_whatsapp_sent_in_db
        mark_whatsapp_sent_in_db(order_id)
    except Exception as db_err:
        print(f"[DATABASE MARK ERROR] {db_err}")

def format_whatsapp_message(item: Dict[str, Any]) -> str:
    """Formats clean, high-priority WhatsApp caption matching executive standard"""
    order_id = item.get("order_id")
    party = item.get("party_name")
    total = item.get("total_boxes")
    rep = item.get("sales_person", "-")
    time_str = item.get("timestamp")
    delivery = item.get("delivery_address", "-")
    items_list = item.get("items", [])
    
    msg = f"📦 *KHANDELIA OIL AND GENERAL MILLS PVT. LTD.*\n"
    msg += f"🔥 *NEW ORDER CONFIRMATION* (Digital OMS)\n"
    msg += f"------------------------------------\n"
    msg += f"*Order ID:* #{order_id}\n"
    msg += f"*Time:* {time_str}\n"
    msg += f"*Party Name:* {party}\n"
    msg += f"*Sales Person:* {rep}\n"
    msg += f"*Delivery Godown:* {delivery}\n"
    msg += f"------------------------------------\n"
    msg += f"*ITEMS BREAKDOWN:*\n"
    for i, it in enumerate(items_list, 1):
        brand = it.get("brand", "Mashal")
        icon = "🔵" if brand.lower() == "mashal" else "🟢"
        msg += f"{icon} {brand} {it.get('item')} ➔ *{it.get('boxes')} bxs*\n"
    msg += f"------------------------------------\n"
    msg += f"🏆 *TOTAL QUANTITY: {total} BOXES*\n"
    msg += f"------------------------------------\n"
    msg += f"✔ _Official Order Record • Khandelia Oil & General Mills Pvt. Ltd._\n"
    msg += f"🖼 _Slip Image Attached Above_"
    return msg
