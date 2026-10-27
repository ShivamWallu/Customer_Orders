import os
import re
import json
from io import BytesIO
from typing import Optional, Dict, Any, List
from PIL import Image, ImageDraw, ImageFont
import qrcode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = "C:/Windows/Fonts"

def get_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(FONTS_DIR, font_name)
    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    words = text.split()
    if not words:
        return ["-"]
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def extract_structured_items(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = order.get("items") or []
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            items = []

    clean_items = []
    if isinstance(items, list) and len(items) > 0:
        for it in items:
            name = str(it.get("item") or it.get("name") or it.get("itemName") or "").strip()
            bxs = int(it.get("boxes") or 0)
            mult = int(it.get("multiplier") or 1)
            pcs = int(it.get("pieces") or (bxs * mult))
            brand = str(it.get("brand") or ("Fauji" if "fauji" in name.lower() else "MASHAL")).strip()
            if name and name not in ["-", "—"] and (bxs > 0 or pcs > 0):
                clean_items.append({"name": name, "boxes": bxs, "pieces": pcs, "multiplier": mult, "brand": brand.upper()})

    if not clean_items:
        raw_summary = str(order.get("itemsSummary") or order.get("items_summary") or order.get("quantitiesSummary") or order.get("quantities_summary") or "").strip()
        if raw_summary and raw_summary.lower() != "packaging items":
            lines = re.split(r"[\n🔵•]", raw_summary)
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                brand = "FAUJI" if "fauji" in line.lower() else "MASHAL"
                clean_line = re.sub(r"[🔵•📦]", "", line).strip()
                bxs = 0
                pcs = 0
                bxs_m = re.search(r"(\d[\d,]*)\s*(?:Boxes|Bx|Bxs)", clean_line, re.I)
                if bxs_m:
                    bxs = int(bxs_m.group(1).replace(",", ""))
                pcs_m = re.search(r"(\d[\d,]*)\s*(?:Pieces|Pcs|Pc)", clean_line, re.I)
                if pcs_m:
                    pcs = int(pcs_m.group(1).replace(",", ""))

                name = re.sub(r"[➔\->\|]", " ", clean_line)
                name = re.sub(r"\[\s*\d[\d,]*\s*(?:Boxes|Bx|Bxs)?\s*\]", "", name, flags=re.I)
                name = re.sub(r"\(\s*\d[\d,]*\s*(?:Boxes|Bx|Bxs)?.*?\)", "", name, flags=re.I)
                name = re.sub(r"\d[\d,]*\s*(?:Boxes|Bx|Bxs)", "", name, flags=re.I)
                name = re.sub(r"\d[\d,]*\s*(?:Pieces|Pcs|Pc)", "", name, flags=re.I)
                name = re.sub(r"^(Mashal|Fauji)\s+", "", name, flags=re.I).strip()

                if not name:
                    name = clean_line
                if name and (bxs > 0 or pcs > 0):
                    clean_items.append({"name": name, "boxes": bxs, "pieces": pcs, "multiplier": 1, "brand": brand})

    if not clean_items:
        bxs = int(order.get("totalBoxes") or order.get("total_boxes") or 0)
        pcs = int(order.get("totalPieces") or order.get("total_pieces") or 0)
        clean_items.append({"name": "Standard Packing Items", "boxes": bxs, "pieces": pcs, "multiplier": 1, "brand": "MASHAL"})

    return clean_items

def generate_order_slip_png(order: Dict[str, Any], output_path: Optional[str] = None) -> bytes:
    """
    Renders official high-resolution order slip matching Image 1 exact layout, colors, and typography.
    """
    width = 900
    items = extract_structured_items(order)

    # Pre-calculate height
    dummy_im = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_im)
    font_addr = get_font("arial.ttf", 12)

    raw_addr = str(order.get("partyAddress") or order.get("deliveryAddress") or order.get("party_address") or "-").strip()
    phone = str(order.get("phone") or order.get("customer_phone") or order.get("party_phone") or "").strip()
    full_addr = f"Address: {raw_addr}"
    if phone and phone not in raw_addr:
        full_addr += f" - Phone: {phone}"

    # Wrap address into 570px corridor so it never touches the QR card
    addr_lines = wrap_text(full_addr, font_addr, 570, dummy_draw)
    cust_box_y = 180
    cust_box_h = max(90, 62 + (len(addr_lines) * 18) + 12)

    row_h = 36
    table_header_h = 40
    table_y = cust_box_y + cust_box_h + 12
    table_content_h = len(items) * row_h
    banner_y = table_y + table_header_h + table_content_h + 12
    banner_h = 48
    foot_card_y = banner_y + banner_h + 16
    foot_card_h = 96
    total_height = foot_card_y + foot_card_h + 14

    # Create canvas
    im = Image.new("RGB", (width, total_height), "#ffffff")
    draw = ImageDraw.Draw(im)

    # Fonts
    font_header_title = get_font("arialbd.ttf", 21)
    font_ribbon = get_font("arialbd.ttf", 12)
    font_id = get_font("courbd.ttf", 13)
    font_meta = get_font("arial.ttf", 12)
    font_cust_lbl = get_font("arialbd.ttf", 10)
    font_party_name = get_font("arialbd.ttf", 16)
    font_badge_lbl = get_font("arialbd.ttf", 9)
    font_badge_code = get_font("courbd.ttf", 13)
    font_qr_verify = get_font("arialbd.ttf", 10)
    font_qr_id = get_font("courbd.ttf", 11)
    font_qr_seal = get_font("courbd.ttf", 9)
    font_qr_rec = get_font("arialbd.ttf", 8)
    font_th = get_font("arialbd.ttf", 12)
    font_td_num = get_font("arialbd.ttf", 12)
    font_td_brand = get_font("arialbd.ttf", 11)
    font_td_name = get_font("arialbd.ttf", 13)
    font_td_pcs = get_font("arialbd.ttf", 14)
    font_td_bxs = get_font("arialbd.ttf", 14)
    font_grand_total = get_font("arialbd.ttf", 16)
    font_foot_thanks = get_font("arialbd.ttf", 14)
    font_foot_sub = get_font("arial.ttf", 11)
    font_foot_toll = get_font("arialbd.ttf", 12)
    font_foot_help = get_font("arial.ttf", 11)
    font_foot_copy = get_font("arial.ttf", 9)

    # 1. Outer Navy Border
    draw.rectangle([(8, 8), (width - 8, total_height - 8)], outline="#003366", width=3)

    # 2. Top Header Banner
    draw.rectangle([(10, 10), (width - 10, 120)], fill="#003366")

    # Mashal Logo Card (Top-Left)
    logo_card_box = [(24, 20), (112, 108)]
    draw.rounded_rectangle(logo_card_box, radius=8, fill="#ffffff", outline="#f59e0b", width=2)
    logo_path = os.path.join(BASE_DIR, "images", "mashal_slip_logo.png")
    if not os.path.exists(logo_path):
        logo_path = os.path.join(BASE_DIR, "images", "mashal_mobile_logo.png")
    if os.path.exists(logo_path):
        try:
            logo_im = Image.open(logo_path).convert("RGBA")
            logo_im = logo_im.resize((82, 82), Image.Resampling.LANCZOS)
            im.paste(logo_im, (27, 23), logo_im)
        except Exception as e:
            print(f"[LOGO_DRAW_ERROR] {e}")

    # Header Title
    header_text_x = (width // 2) + 40
    draw.text((header_text_x, 50), "KHANDELIA OIL AND GENERAL MILLS PVT. LTD.", fill="#ffffff", font=font_header_title, anchor="mm")

    # Orange Subtitle Ribbon
    ribbon_w = 320
    ribbon_h = 30
    ribbon_x = header_text_x - (ribbon_w // 2)
    draw.rounded_rectangle([(ribbon_x, 70), (ribbon_x + ribbon_w, 100)], radius=6, fill="#d97706")
    draw.text((header_text_x, 85), "OFFICIAL ORDER CONFIRMATION SLIP", fill="#ffffff", font=font_ribbon, anchor="mm")

    # 3. Reference Bar
    ref_y = 126
    ref_h = 45
    draw.rectangle([(12, ref_y), (width - 12, ref_y + ref_h)], fill="#f8fafc", outline="#e2e8f0", width=1)

    raw_order_id = str(order.get("order_id") or order.get("cleanId") or order.get("id") or "").replace("#", "").strip()
    draw.text((24, ref_y + 22), f"ORDER ID: #{raw_order_id}", fill="#0f172a", font=font_id, anchor="lm")

    date_str = str(order.get("formattedTimestamp") or order.get("orderDate") or order.get("order_date") or "").strip()
    draw.text((width // 2, ref_y + 22), f"Date & Time: {date_str}", fill="#0f172a", font=font_meta, anchor="mm")

    asm_name = str(order.get("salesPerson") or order.get("sales_person") or "Shivam Wallu").strip()
    draw.text((width - 24, ref_y + 22), f"Area Sales Manager: {asm_name}", fill="#0f172a", font=font_meta, anchor="rm")

    # 4. Customer Details Box
    draw.rectangle([(12, cust_box_y), (width - 12, cust_box_y + cust_box_h)], fill="#ffffff", outline="#cbd5e1", width=1)

    # Customer Label & Party Name
    draw.text((24, cust_box_y + 18), "CUSTOMER / BILLING DETAILS", fill="#64748b", font=font_cust_lbl, anchor="lm")
    party_name = str(order.get("partyName") or order.get("party_name") or "Customer").strip()
    draw.text((24, cust_box_y + 38), party_name, fill="#0f172a", font=font_party_name, anchor="lm")

    # Center: Registered Party Code Badge
    party_code = str(order.get("partyCode") or order.get("party_code") or "SDMOWB0781").strip()
    if not party_code or party_code == "NEW CUSTOMER":
        party_code = "SDMOWB0781"

    badge_w = 190
    badge_h = 42
    badge_x = (width // 2) - (badge_w // 2)
    badge_y = cust_box_y + 8
    draw.rounded_rectangle([(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)], radius=6, fill="#eff6ff", outline="#93c5fd", width=1)
    draw.text((width // 2, badge_y + 12), "REGISTERED PARTY CODE", fill="#0284c7", font=font_badge_lbl, anchor="mm")
    draw.text((width // 2, badge_y + 28), party_code, fill="#003366", font=font_badge_code, anchor="mm")

    # Right: Live Verification QR Code Card
    qr_card_w = 216
    qr_card_h = 74
    qr_card_x = width - qr_card_w - 20
    qr_card_y = cust_box_y + 7
    draw.rounded_rectangle([(qr_card_x, qr_card_y), (qr_card_x + qr_card_w, qr_card_y + qr_card_h)], radius=8, fill="#f8fafc", outline="#cbd5e1", width=1)

    qr_url = f"https://order.khandelia.online/verify/{raw_order_id}"
    qr = qrcode.QRCode(version=1, box_size=2, border=1)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#003366", back_color="#f8fafc").convert("RGB")
    qr_img = qr_img.resize((64, 64), Image.Resampling.LANCZOS)
    im.paste(qr_img, (qr_card_x + 5, qr_card_y + 5))

    seal_text = str(order.get("securityHash") or "SEC-AUTHENTIC")[:14]
    text_x = qr_card_x + 64 + 10

    # Draw crisp vector checkmark
    chk_x = text_x
    chk_y = qr_card_y + 8
    draw.line([(chk_x, chk_y + 6), (chk_x + 4, chk_y + 11), (chk_x + 11, chk_y + 2)], fill="#15803d", width=2)
    draw.text((chk_x + 15, qr_card_y + 14), "SCAN TO VERIFY", fill="#15803d", font=font_qr_verify, anchor="lm")
    draw.text((text_x, qr_card_y + 30), f"#{raw_order_id}", fill="#003366", font=font_qr_id, anchor="lm")
    draw.text((text_x, qr_card_y + 46), f"SEAL: {seal_text}", fill="#0284c7", font=font_qr_seal, anchor="lm")
    draw.text((text_x, qr_card_y + 60), "OFFICIAL RECORD", fill="#64748b", font=font_qr_rec, anchor="lm")

    # Multi-line wrapped address
    addr_start_y = cust_box_y + 64
    for idx, line in enumerate(addr_lines):
        draw.text((24, addr_start_y + (idx * 18)), line, fill="#475569", font=font_addr, anchor="lm")

    # 5. Table Header
    draw.rectangle([(12, table_y), (width - 12, table_y + table_header_h)], fill="#004b99")
    draw.text((35, table_y + 20), "#", fill="#ffffff", font=font_th, anchor="mm")
    draw.text((85, table_y + 20), "BRAND", fill="#ffffff", font=font_th, anchor="mm")
    draw.text((135, table_y + 20), "PACKING / PRODUCT DESCRIPTION", fill="#ffffff", font=font_th, anchor="lm")
    draw.text((640, table_y + 20), "QUANTITY (IN PIECES)", fill="#ffffff", font=font_th, anchor="mm")
    draw.text((810, table_y + 20), "QUANTITY (BOXES)", fill="#ffffff", font=font_th, anchor="mm")

    # 6. Table Rows
    cur_y = table_y + table_header_h
    tot_boxes = 0
    tot_pieces = 0

    for idx, it in enumerate(items):
        bg = "#f8fafc" if idx % 2 == 0 else "#ffffff"
        draw.rectangle([(12, cur_y), (width - 12, cur_y + row_h)], fill=bg)
        draw.line([(12, cur_y + row_h), (width - 12, cur_y + row_h)], fill="#e2e8f0", width=1)

        bxs = int(it.get("boxes") or 0)
        pcs = int(it.get("pieces") or 0)
        tot_boxes += bxs
        tot_pieces += pcs

        # #
        draw.text((35, cur_y + 18), str(idx + 1), fill="#64748b", font=font_td_num, anchor="mm")

        # Brand
        brand_name = str(it.get("brand") or "MASHAL").upper()
        brand_col = "#1e40af" if "MASHAL" in brand_name else "#15803d"
        draw.text((85, cur_y + 18), brand_name, fill=brand_col, font=font_td_brand, anchor="mm")

        # Item Name
        draw.text((135, cur_y + 18), str(it.get("name") or ""), fill="#0f172a", font=font_td_name, anchor="lm")

        # Quantity in Pieces (Centered at 640)
        draw.text((640, cur_y + 18), f"{pcs:,} Pcs", fill="#1e40af", font=font_td_pcs, anchor="mm")

        # Quantity in Boxes (Centered at 810)
        draw.text((810, cur_y + 18), f"{bxs:,} Boxes", fill="#0f172a", font=font_td_bxs, anchor="mm")

        cur_y += row_h

    # If totals stored directly
    if tot_boxes == 0 and order.get("total_boxes"):
        tot_boxes = int(order.get("total_boxes"))
    if tot_pieces == 0 and order.get("total_pieces"):
        tot_pieces = int(order.get("total_pieces"))

    # 7. Total Order Quantity Banner
    draw.rectangle([(12, banner_y), (width - 12, banner_y + banner_h)], fill="#003366")
    total_text = f"TOTAL ORDER QUANTITY: {tot_boxes:,} BOXES  |  {tot_pieces:,} PIECES"
    draw.text((width // 2, banner_y + 24), total_text, fill="#ffffff", font=font_grand_total, anchor="mm")

    # 8. Footer Card
    draw.rounded_rectangle([(12, foot_card_y), (width - 12, foot_card_y + foot_card_h)], radius=8, fill="#f8fafc", outline="#e2e8f0", width=1)
    draw.text((width // 2, foot_card_y + 18), "Thank You for Your Order!", fill="#003366", font=font_foot_thanks, anchor="mm")
    draw.text((width // 2, foot_card_y + 36), "Our Customer Care team is always available to assist you.", fill="#334155", font=font_foot_sub, anchor="mm")
    draw.text((width // 2, foot_card_y + 54), "Toll-Free: 1800 103 3211   |   Email: customercare@khandelia.com", fill="#0284c7", font=font_foot_toll, anchor="mm")
    draw.text((width // 2, foot_card_y + 70), "For any queries or assistance, feel free to call or email us. We're always happy to help!", fill="#64748b", font=font_foot_help, anchor="mm")
    draw.text((width // 2, foot_card_y + 84), "Khandelia Oil and General Mills Pvt. Ltd. • Official Digital OMS", fill="#94a3b8", font=font_foot_copy, anchor="mm")

    if output_path:
        try:
            dir_name = os.path.dirname(output_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            im.save(output_path, "PNG", optimize=True)
        except Exception as e:
            print(f"[SLIP_SAVE_WARN] {e}")

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
