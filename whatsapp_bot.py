"""
Khandelia Oil and General Mills Pvt. Ltd.
WhatsApp Automatic Order & Slip Image Sender Bot
Using Persistent Chrome Profile (Linked Devices)

Key Features:
- Scan QR code ONCE via WhatsApp > Linked Devices > Link a Device.
- Session is saved permanently in 'whatsapp_chrome_profile'.
- Every morning when PC starts, WhatsApp connects automatically without re-scanning.
- Whenever any customer places an order, the slip image + item breakdown is sent to +91 7814749816.
"""

import os
import sys
import time
import urllib.parse
from datetime import datetime

# Configure Windows terminal encoding to UTF-8
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from whatsapp_service import (
    get_pending_whatsapp_orders,
    mark_whatsapp_order_sent,
    format_whatsapp_message,
    TARGET_WHATSAPP_NUMBER
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "whatsapp_chrome_profile")
os.makedirs(PROFILE_DIR, exist_ok=True)

REMOTE_SERVER_URL = os.environ.get("REMOTE_SERVER_URL", "https://order.khandelia.online").rstrip("/")

def fetch_pending_orders_hybrid():
    """
    Fetches pending orders from LIVE AWS server (https://order.khandelia.online/api/whatsapp/pending).
    Falls back to local queue if server is unreachable.
    Downloads any missing slip images to local order_slips/ directory.
    """
    import urllib.request
    import json

    # 1. Try remote live server first
    if REMOTE_SERVER_URL:
        try:
            req = urllib.request.Request(
                f"{REMOTE_SERVER_URL}/api/whatsapp/pending",
                headers={"User-Agent": "MashalWhatsAppBot/1.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    remote_orders = data.get("pending_orders", [])
                    if remote_orders:
                        for item in remote_orders:
                            order_id = item.get("order_id")
                            local_slip = os.path.join(BASE_DIR, "order_slips", f"{order_id}.png")
                            if not os.path.exists(local_slip):
                                os.makedirs(os.path.dirname(local_slip), exist_ok=True)
                                try:
                                    img_url = f"{REMOTE_SERVER_URL}/order_slips/{order_id}.png"
                                    urllib.request.urlretrieve(img_url, local_slip)
                                    item["slip_image_path"] = os.path.abspath(local_slip)
                                except Exception as dl_err:
                                    print(f"[BOT WARN] Could not download slip image for #{order_id}: {dl_err}")
                            else:
                                item["slip_image_path"] = os.path.abspath(local_slip)
                        return remote_orders
        except Exception:
            pass

    # 2. Local fallback
    return get_pending_whatsapp_orders()

def mark_order_sent_hybrid(order_id: str):
    """Marks order sent in local queue and on remote server"""
    mark_whatsapp_order_sent(order_id)
    if REMOTE_SERVER_URL:
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                f"{REMOTE_SERVER_URL}/api/whatsapp/mark-sent",
                data=json.dumps({"order_id": order_id}).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "MashalWhatsAppBot/1.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                pass
        except Exception as e:
            print(f"[BOT SYNC WARN] Could not mark sent on remote server: {e}")

def cleanup_orphaned_chrome():
    """Kills any previous orphaned Chrome process holding the profile locked"""
    try:
        import subprocess
        cmd = 'Get-CimInstance Win32_Process -Filter "Name like \'chrome%\'" | Where-Object {$_.CommandLine -like "*whatsapp_chrome_profile*"} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=5)
    except Exception:
        pass

def init_driver():
    """Initializes Chrome with persistent profile for WhatsApp Web"""
    cleanup_orphaned_chrome()
    time.sleep(1)
    print(f"[BOT] Starting Chrome with persistent profile at: {PROFILE_DIR}")
    options = Options()
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-notifications")
    options.add_argument("--remote-allow-origins=*")
    # Window size suitable for viewing and desktop layout
    options.add_argument("--window-size=1200,900")
    
    driver = webdriver.Chrome(options=options)
    return driver

def wait_for_whatsapp_login(driver):
    """Waits for user to scan QR code (if first time) or logs in automatically"""
    print("\n" + "="*60)
    print("[WHATSAPP] KHANDELIA MASHAL OMS - WHATSAPP AUTOMATION BOT")
    print(f"[TARGET] Target Alert Number: +{TARGET_WHATSAPP_NUMBER}")
    print("="*60)
    
    driver.get("https://web.whatsapp.com")
    print("[BOT] Loading WhatsApp Web...")
    
    is_logged_in = False
    dots = 0
    while not is_logged_in:
        try:
            # Check for chat pane or search bar that indicates user is logged in
            elements = driver.find_elements(By.CSS_SELECTOR, "#pane-side, div[contenteditable='true'][data-tab='3'], header[data-testid='chatlist-header']")
            if elements:
                is_logged_in = True
                print("\n[OK] WhatsApp Web is LOGGED IN & READY!")
                print("   Linked device session is active. Orders will be sent automatically.\n")
                break
        except Exception:
            pass
            
        # Check if QR code is visible
        try:
            qr = driver.find_elements(By.CSS_SELECTOR, "canvas[aria-label='Scan this QR code to link a device'], div[data-ref]")
            if qr and dots % 5 == 0:
                print("\n[FIRST-TIME LINKING REQUIRED]")
                print("   1. Open WhatsApp on your phone.")
                print("   2. Tap Settings (or 3 dots) > Linked Devices > 'Link a device'.")
                print("   3. Scan the QR code showing on your PC screen.")
                print("   (Note: You only need to do this ONCE. Tomorrow morning it connects automatically!)\n")
        except Exception:
            pass
            
        time.sleep(2)
        dots += 1
        sys.stdout.write(".")
        sys.stdout.flush()

def send_image_and_caption(driver, phone: str, image_path: str, caption_text: str) -> bool:
    """
    Sends order slip image with formatted caption to the target WhatsApp number.
    Ensures ZERO page reloads if already in the chat, so multiple orders send seamlessly.
    """
    try:
        # Check if already in the active chat with this phone
        current_url = driver.current_url or ""
        chat_ready = False
        try:
            active_inputs = driver.find_elements(By.CSS_SELECTOR, "footer, div[data-tab='10'], div[contenteditable='true']")
            if phone in current_url and active_inputs:
                chat_ready = True
        except Exception:
            chat_ready = False

        if not chat_ready:
            print(f"\n[BOT] Navigating to chat with +{phone}...")
            chat_url = f"https://web.whatsapp.com/send?phone={phone}"
            driver.get(chat_url)
            wait = WebDriverWait(driver, 25)
            wait.until(EC.presence_of_element_located((
                By.CSS_SELECTOR, "footer, div[data-tab='10'], div[contenteditable='true']"
            )))
            time.sleep(2)
        else:
            print(f"[BOT] Reusing existing open chat with +{phone} (No page refresh needed!)...")

        # If an old stuck preview exists from earlier, dismiss it cleanly first
        try:
            stuck_previews = driver.find_elements(By.CSS_SELECTOR, "span[data-icon='x'], div[aria-label='Close']")
            if stuck_previews and driver.find_elements(By.CSS_SELECTOR, "span[data-icon='send']"):
                print("[BOT] Closing previous unsent preview dialog before new order...")
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(1)
        except Exception:
            pass

        # Check if phone number is invalid dialog appears
        invalid_popups = driver.find_elements(By.XPATH, "//*[contains(text(), 'Phone number shared via url is invalid') or contains(text(), 'invalid phone number')]")
        if invalid_popups:
            print(f"[BOT ERROR] Phone number +{phone} was flagged as invalid by WhatsApp.")
            return False

        # Attempt 1: Attach image
        if image_path and os.path.exists(image_path):
            print(f"[BOT] Attaching order slip image: {image_path}")
            
            # Find attach button (plus icon / paperclip)
            attach_btn = None
            for selector in [
                "button[aria-label='Attach']",
                "footer button[aria-label='Attach']",
                "div[aria-label='Attach']",
                "button[title='Attach']",
                "div[title='Attach']",
                "span[data-icon='plus']",
                "span[data-icon='attach-menu-plus']",
                "span[data-icon='clip']"
            ]:
                matches = driver.find_elements(By.CSS_SELECTOR, selector)
                if matches:
                    attach_btn = matches[0]
                    break
                    
            if attach_btn:
                try:
                    driver.execute_script("arguments[0].click();", attach_btn)
                    time.sleep(1.5)
                except Exception as click_err:
                    print(f"[BOT] Attach button click warning: {click_err}")

            # Find file input for images after opening attach menu
            file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file'][accept*='image']")
            if not file_inputs:
                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                
            if file_inputs:
                file_inputs[0].send_keys(os.path.abspath(image_path))
                print("[BOT] Image selected. Waiting for WhatsApp preview screen...")
                time.sleep(2.5)
                
                # In image preview modal, find the caption text box
                caption_boxes = driver.find_elements(By.CSS_SELECTOR, "div[contenteditable='true'][aria-placeholder*='caption'], div[contenteditable='true'][data-tab='10'], div[contenteditable='true']")
                if caption_boxes:
                    target_box = caption_boxes[-1]
                    try:
                        driver.execute_script("arguments[0].focus();", target_box)
                        time.sleep(0.3)
                        # Type caption line by line with Shift+Enter for newlines
                        lines = caption_text.split("\n")
                        for line_idx, line in enumerate(lines):
                            target_box.send_keys(line)
                            if line_idx < len(lines) - 1:
                                target_box.send_keys(Keys.SHIFT + Keys.ENTER)
                        time.sleep(1)
                    except Exception as type_err:
                        print(f"[BOT] Caption type notice: {type_err}")

                # Trigger Send on Preview Modal
                print("[BOT] Triggering Send on Preview Modal...")
                time.sleep(1)
                
                # Try clicking via JS first, then Enter
                send_js = """
                const findAndClickSend = () => {
                    const sel = document.querySelector("span[data-icon='send']") 
                             || document.querySelector("div[aria-label='Send']") 
                             || document.querySelector("button[aria-label='Send']")
                             || document.querySelector("div[role='button'][aria-label='Send']");
                    if (sel) {
                        const clickable = sel.closest("button, div[role='button']") || sel;
                        clickable.click();
                        return true;
                    }
                    return false;
                };
                return findAndClickSend();
                """
                clicked = driver.execute_script(send_js)
                if not clicked:
                    # Fallback to Enter on active caption box
                    if caption_boxes:
                        try:
                            caption_boxes[-1].send_keys(Keys.ENTER)
                        except Exception:
                            pass

                # Confirm the image preview actually closes (meaning sent)
                is_sent = False
                for wait_sec in range(10):
                    time.sleep(1)
                    # Check if preview dialog is closed
                    previews = driver.find_elements(By.CSS_SELECTOR, "div[aria-placeholder*='caption'], div[data-animate-modal-popup='true']")
                    if not previews:
                        is_sent = True
                        print("[BOT] [OK] Confirmed: Preview closed and order slip image posted into chat!")
                        break
                    # If still open after 3 seconds, retry click
                    if wait_sec >= 3:
                        driver.execute_script(send_js)
                        if caption_boxes:
                            try:
                                caption_boxes[-1].send_keys(Keys.ENTER)
                            except Exception:
                                pass
                
                if is_sent:
                    time.sleep(2)
                    return True
                else:
                    print("[BOT WARN] Preview dialog did not close automatically. Retrying next cycle.")
                    return False

        # Fallback / Text Mode: If image attachment was not possible, send text breakdown
        print("[BOT] Sending text-based order summary breakdown...")
        text_boxes = driver.find_elements(By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='10'], footer div[contenteditable='true']")
        if text_boxes:
            target_box = text_boxes[-1]
            target_box.click()
            time.sleep(0.5)
            lines = caption_text.split("\n")
            for line_idx, line in enumerate(lines):
                target_box.send_keys(line)
                if line_idx < len(lines) - 1:
                    target_box.send_keys(Keys.SHIFT + Keys.ENTER)
            target_box.send_keys(Keys.ENTER)
            time.sleep(3)
            return True

    except Exception as e:
        print(f"[BOT SEND ERROR] {e}")
        return False
        
    return False

def run_bot_loop():
    """Main polling loop for WhatsApp Automation"""
    driver = None
    try:
        driver = init_driver()
        wait_for_whatsapp_login(driver)
        
        print("[BOT] Entering Live Order Monitoring Loop...")
        print("[TIP] Keep this window running in background. Orders will be sent instantly!\n")
        
        while True:
            try:
                pending_orders = fetch_pending_orders_hybrid()
                if pending_orders:
                    print(f"\n[BOT] Found {len(pending_orders)} pending order(s) to send!")
                    for item in pending_orders:
                        order_id = item.get("order_id")
                        image_path = item.get("slip_image_path", "")
                        caption = format_whatsapp_message(item)
                        
                        print(f"[BOT] Processing Order #{order_id} for {TARGET_WHATSAPP_NUMBER}...")
                        success = send_image_and_caption(
                            driver=driver,
                            phone=TARGET_WHATSAPP_NUMBER,
                            image_path=image_path,
                            caption_text=caption
                        )
                        
                        if success:
                            mark_order_sent_hybrid(order_id)
                            print(f"[SUCCESS] Order #{order_id} slip & details delivered on WhatsApp!")
                        else:
                            print(f"[RETRY LATER] Failed to deliver Order #{order_id}. Will retry on next cycle.")
                            
                        time.sleep(3)
                
            except Exception as loop_err:
                print(f"[BOT LOOP ERROR] {loop_err}")
                
            time.sleep(4)
            
    except KeyboardInterrupt:
        print("\n[BOT] Stopped by user.")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

if __name__ == "__main__":
    run_bot_loop()
