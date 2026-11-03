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
            brand = str(it.get("brand") or ("FAUJI" if "fauji" in name.lower() else "MASHAL")).strip()
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

def generate_order_slip_png(order: Dict[str, Any], output_path: Optional[str] = None, hide_pieces: bool = False, is_old_slip: bool = False) -> bytes:
    """
    Renders official high-definition order slip matching industry best practices (2x Retina Clarity).
    - 100% Overlap-free 2-column customer information layout
    - Crisp vector typography and FreeType anti-aliasing
    - High-density QR verification badge and official seals
    - In-memory generation with zero disk clutter
    """
    slip_order = dict(order)
    if is_old_slip:
        orig_items = slip_order.get("originalItems") or slip_order.get("original_items_json")
        if orig_items:
            if isinstance(orig_items, str):
                try:
                    orig_items = json.loads(orig_items)
                except Exception:
                    orig_items = []
            slip_order["items"] = orig_items
        if slip_order.get("originalTotalBoxes") or slip_order.get("original_total_boxes"):
            slip_order["total_boxes"] = slip_order.get("originalTotalBoxes") or slip_order.get("original_total_boxes")
            slip_order["totalBoxes"] = slip_order["total_boxes"]
        if slip_order.get("originalTotalPieces") or slip_order.get("original_total_pieces"):
            slip_order["total_pieces"] = slip_order.get("originalTotalPieces") or slip_order.get("original_total_pieces")
            slip_order["totalPieces"] = slip_order["total_pieces"]

    width = 1400
    items = extract_structured_items(slip_order)

    # Pre-calculate height with dummy canvas
    dummy_im = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_im)
    font_addr = get_font("arial.ttf", 16)
    font_party_name = get_font("arialbd.ttf", 22)

    party_name = str(slip_order.get("partyName") or slip_order.get("party_name") or "Customer").strip()
    raw_addr = str(slip_order.get("partyAddress") or slip_order.get("deliveryAddress") or slip_order.get("party_address") or "-").strip()
    phone = str(slip_order.get("phone") or slip_order.get("customer_phone") or slip_order.get("party_phone") or slip_order.get("contactNumber") or "").strip()

    # Wrap party name into 840px max width so it never touches the right badge column
    party_lines = wrap_text(party_name, font_party_name, 840, dummy_draw)
    addr_lines = wrap_text(f"Address: {raw_addr}", font_addr, 840, dummy_draw)
    
    # Calculate customer box height dynamically based on content
    left_content_height = 24 + (len(party_lines) * 28) + 8 + (len(addr_lines) * 22) + 28 + 20
    cust_box_h = max(180, left_content_height)
    cust_box_y = 250

    row_h = 52
    table_header_h = 54
    table_y = cust_box_y + cust_box_h + 18
    table_content_h = len(items) * row_h
    banner_y = table_y + table_header_h + table_content_h + 18
    banner_h = 64
    foot_card_y = banner_y + banner_h + 20
    foot_card_h = 130
    total_height = foot_card_y + foot_card_h + 20

    # Create canvas with 100% white background
    im = Image.new("RGB", (width, total_height), "#ffffff")
    draw = ImageDraw.Draw(im)

    # High-Definition Typography Tokens (2x Crisp Scale)
    font_header_title = get_font("arialbd.ttf", 30)
    font_ribbon = get_font("arialbd.ttf", 15)
    font_id = get_font("courbd.ttf", 17)
    font_meta = get_font("arialbd.ttf", 15)
    font_cust_lbl = get_font("arialbd.ttf", 13)
    font_badge_lbl = get_font("arialbd.ttf", 12)
    font_badge_code = get_font("courbd.ttf", 19)
    font_qr_verify = get_font("arialbd.ttf", 13)
    font_qr_id = get_font("courbd.ttf", 15)
    font_qr_seal = get_font("courbd.ttf", 12)
    font_qr_rec = get_font("arialbd.ttf", 11)
    font_th = get_font("arialbd.ttf", 16)
    font_td_num = get_font("arialbd.ttf", 16)
    font_td_brand = get_font("arialbd.ttf", 15)
    font_td_name = get_font("arialbd.ttf", 17)
    font_td_pcs = get_font("arialbd.ttf", 18)
    font_td_bxs = get_font("arialbd.ttf", 18)
    font_grand_total = get_font("arialbd.ttf", 22)
    font_foot_thanks = get_font("arialbd.ttf", 19)
    font_foot_sub = get_font("arial.ttf", 14)
    font_foot_toll = get_font("arialbd.ttf", 16)
    font_foot_help = get_font("arial.ttf", 13)
    font_foot_copy = get_font("arial.ttf", 12)

    # 1. Outer Border
    border_color = "#475569" if is_old_slip else "#003366"
    draw.rectangle([(10, 10), (width - 10, total_height - 10)], outline=border_color, width=4)

    # 2. Top Header Banner
    draw.rectangle([(14, 14), (width - 14, 160)], fill="#003366")

    # Brand Logo Card (Top-Left)
    logo_card_box = [(28, 22), (180, 152)]
    draw.rounded_rectangle(logo_card_box, radius=12, fill="#ffffff", outline="#f59e0b", width=3)
    logo_path = os.path.join(BASE_DIR, "images", "NEW_PNG_MASHAL_LOGO.png")
    if not os.path.exists(logo_path):
        logo_path = os.path.join(BASE_DIR, "images", "mashal_slip_logo.png")
    if os.path.exists(logo_path):
        try:
            logo_im = Image.open(logo_path).convert("RGBA")
            logo_im.thumbnail((144, 114), Image.Resampling.LANCZOS)
            offset_x = 28 + (152 - logo_im.width) // 2
            offset_y = 22 + (130 - logo_im.height) // 2
            im.paste(logo_im, (offset_x, offset_y), logo_im)
        except Exception as e:
            print(f"[LOGO_DRAW_ERROR] {e}")

    # Header Title
    header_text_x = (width // 2) + 70
    draw.text((header_text_x, 62), "KHANDELIA OIL AND GENERAL MILLS PVT. LTD.", fill="#ffffff", font=font_header_title, anchor="mm")

    # Subtitle Ribbon (Clearly shows ORIGINAL vs REVISED vs STANDARD)
    is_revised = not is_old_slip and bool(slip_order.get("is_edited") or slip_order.get("isEdited"))
    if is_old_slip:
        ribbon_text = "ORIGINAL PRE-EDIT ORDER SLIP (ARCHIVED)"
        ribbon_color = "#64748b"
        ribbon_w = 460
    elif is_revised:
        ribbon_text = "REVISED ORDER SLIP (STOCK ADJUSTED)"
        ribbon_color = "#b45309"
        ribbon_w = 450
    else:
        ribbon_text = "OFFICIAL ORDER CONFIRMATION SLIP"
        ribbon_color = "#d97706"
        ribbon_w = 420

    ribbon_h = 38
    ribbon_x = header_text_x - (ribbon_w // 2)
    draw.rounded_rectangle([(ribbon_x, 96), (ribbon_x + ribbon_w, 96 + ribbon_h)], radius=8, fill=ribbon_color)
    draw.text((header_text_x, 115), ribbon_text, fill="#ffffff", font=font_ribbon, anchor="mm")

    # 3. Reference Bar
    ref_y = 172
    ref_h = 58
    draw.rectangle([(14, ref_y), (width - 14, ref_y + ref_h)], fill="#f8fafc", outline="#cbd5e1", width=1)

    raw_order_id = str(slip_order.get("order_id") or slip_order.get("cleanId") or slip_order.get("id") or "").replace("#", "").strip()
    if is_old_slip:
        id_label = f"ORDER ID: #{raw_order_id} (ORIGINAL PRE-EDIT)"
    elif is_revised:
        id_label = f"ORDER ID: #{raw_order_id} (REVISED)"
    else:
        id_label = f"ORDER ID: #{raw_order_id}"
    draw.text((36, ref_y + 29), id_label, fill="#0f172a", font=font_id, anchor="lm")

    date_str = str(slip_order.get("formattedTimestamp") or slip_order.get("orderDate") or slip_order.get("order_date") or "").strip()
    draw.text((width // 2, ref_y + 29), f"Date & Time: {date_str}", fill="#0f172a", font=font_meta, anchor="mm")

    asm_name = str(slip_order.get("salesPerson") or slip_order.get("sales_person") or "Shivam Wallu").strip()
    draw.text((width - 36, ref_y + 29), f"Area Sales Manager: {asm_name}", fill="#0f172a", font=font_meta, anchor="rm")

    # 4. Customer Details Box (Zero Overlap 2-Column Grid)
    draw.rectangle([(14, cust_box_y), (width - 14, cust_box_y + cust_box_h)], fill="#ffffff", outline="#cbd5e1", width=2)

    # Left Column (Customer Information: x=36 to x=900)
    draw.text((36, cust_box_y + 22), "CUSTOMER / BILLING DETAILS", fill="#64748b", font=font_cust_lbl, anchor="lm")
    
    party_y = cust_box_y + 46
    for p_line in party_lines:
        draw.text((36, party_y), p_line, fill="#0f172a", font=font_party_name, anchor="lm")
        party_y += 28

    addr_y = party_y + 4
    for line in addr_lines:
        draw.text((36, addr_y), line, fill="#475569", font=font_addr, anchor="lm")
        addr_y += 22

    if phone:
        draw.text((36, addr_y + 4), f"Contact: +91 {phone}", fill="#003366", font=font_addr, anchor="lm")

    # Right Column: Stacked Badges (x=940 to width-36 = 1364)
    right_col_x = 940
    right_col_w = width - 36 - right_col_x

    # Top Right: Registered Party Code Badge
    party_code = str(slip_order.get("partyCode") or slip_order.get("party_code") or "SDMOWB0781").strip()
    if not party_code or party_code == "NEW CUSTOMER":
        party_code = "SDMOWB0781"

    badge_h = 56
    badge_y = cust_box_y + 16
    draw.rounded_rectangle([(right_col_x, badge_y), (right_col_x + right_col_w, badge_y + badge_h)], radius=8, fill="#eff6ff", outline="#93c5fd", width=2)
    draw.text((right_col_x + (right_col_w // 2), badge_y + 16), "REGISTERED PARTY CODE", fill="#0284c7", font=font_badge_lbl, anchor="mm")
    draw.text((right_col_x + (right_col_w // 2), badge_y + 38), party_code, fill="#003366", font=font_badge_code, anchor="mm")

    # Bottom Right: QR Verification & Security Card
    qr_card_y = badge_y + badge_h + 12
    qr_card_h = 94
    draw.rounded_rectangle([(right_col_x, qr_card_y), (right_col_x + right_col_w, qr_card_y + qr_card_h)], radius=8, fill="#f8fafc", outline="#cbd5e1", width=2)

    clean_uid = str(raw_order_id).replace("#", "").strip()
    qr_url = slip_order.get("verifyUrl")
    if not qr_url:
        default_base = os.getenv("APP_BASE_URL") or os.getenv("BACKEND_BASE_URL", "https://order.khandelia.online")
        qr_url = f"{default_base}/verify/{clean_uid}"
    qr = qrcode.QRCode(version=1, box_size=3, border=1)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#003366", back_color="#f8fafc").convert("RGB")
    qr_size = 78
    qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
    im.paste(qr_img, (right_col_x + 10, qr_card_y + 8))

    seal_text = str(slip_order.get("securityHash") or "SEC-AUTHENTIC")[:14]
    txt_x = right_col_x + qr_size + 22

    # Draw crisp green vector checkmark
    chk_x = txt_x
    chk_y = qr_card_y + 14
    draw.line([(chk_x, chk_y + 7), (chk_x + 5, chk_y + 13), (chk_x + 14, chk_y + 2)], fill="#15803d", width=3)
    draw.text((chk_x + 20, qr_card_y + 18), "SCAN TO VERIFY", fill="#15803d", font=font_qr_verify, anchor="lm")
    draw.text((txt_x, qr_card_y + 39), f"#{raw_order_id}", fill="#003366", font=font_qr_id, anchor="lm")
    draw.text((txt_x, qr_card_y + 58), f"SEAL: {seal_text}", fill="#0284c7", font=font_qr_seal, anchor="lm")
    draw.text((txt_x, qr_card_y + 76), "OFFICIAL FACTORY RECORD", fill="#64748b", font=font_qr_rec, anchor="lm")

    # 5. Table Header
    header_bg = "#334155" if is_old_slip else "#004b99"
    draw.rectangle([(14, table_y), (width - 14, table_y + table_header_h)], fill=header_bg)

    if hide_pieces:
        draw.text((50, table_y + 27), "#", fill="#ffffff", font=font_th, anchor="mm")
        draw.text((140, table_y + 27), "BRAND", fill="#ffffff", font=font_th, anchor="mm")
        draw.text((230, table_y + 27), "PACKING / PRODUCT DESCRIPTION", fill="#ffffff", font=font_th, anchor="lm")
        draw.text((1220, table_y + 27), "QUANTITY (BOXES / PETIS)", fill="#ffffff", font=font_th, anchor="mm")
    else:
        draw.text((50, table_y + 27), "#", fill="#ffffff", font=font_th, anchor="mm")
        draw.text((130, table_y + 27), "BRAND", fill="#ffffff", font=font_th, anchor="mm")
        draw.text((210, table_y + 27), "PACKING / PRODUCT DESCRIPTION", fill="#ffffff", font=font_th, anchor="lm")
        draw.text((1000, table_y + 27), "QUANTITY (IN PIECES)", fill="#ffffff", font=font_th, anchor="mm")
        draw.text((1260, table_y + 27), "QUANTITY (BOXES)", fill="#ffffff", font=font_th, anchor="mm")

    # 6. Table Rows
    cur_y = table_y + table_header_h
    tot_boxes = 0
    tot_pieces = 0

    for idx, it in enumerate(items):
        bg = "#f8fafc" if idx % 2 == 0 else "#ffffff"
        draw.rectangle([(14, cur_y), (width - 14, cur_y + row_h)], fill=bg)
        draw.line([(14, cur_y + row_h), (width - 14, cur_y + row_h)], fill="#e2e8f0", width=2)

        bxs = int(it.get("boxes") or 0)
        pcs = int(it.get("pieces") or 0)
        tot_boxes += bxs
        tot_pieces += pcs

        brand_name = str(it.get("brand") or "MASHAL").upper()
        brand_col = "#1e40af" if "MASHAL" in brand_name else "#15803d"

        # Center Y anchor for row text
        mid_y = cur_y + (row_h // 2)

        if hide_pieces:
            draw.text((50, mid_y), str(idx + 1), fill="#64748b", font=font_td_num, anchor="mm")
            draw.text((140, mid_y), brand_name, fill=brand_col, font=font_td_brand, anchor="mm")
            draw.text((230, mid_y), str(it.get("name") or ""), fill="#0f172a", font=font_td_name, anchor="lm")
            draw.text((1220, mid_y), f"{bxs:,} Boxes", fill="#0f172a", font=font_td_bxs, anchor="mm")
        else:
            draw.text((50, mid_y), str(idx + 1), fill="#64748b", font=font_td_num, anchor="mm")
            draw.text((130, mid_y), brand_name, fill=brand_col, font=font_td_brand, anchor="mm")
            draw.text((210, mid_y), str(it.get("name") or ""), fill="#0f172a", font=font_td_name, anchor="lm")
            draw.text((1000, mid_y), f"{pcs:,} Pcs", fill="#1e40af", font=font_td_pcs, anchor="mm")
            draw.text((1260, mid_y), f"{bxs:,} Boxes", fill="#0f172a", font=font_td_bxs, anchor="mm")

        cur_y += row_h

    # If totals stored directly in root order
    if tot_boxes == 0 and slip_order.get("total_boxes"):
        tot_boxes = int(slip_order.get("total_boxes"))
    if tot_pieces == 0 and slip_order.get("total_pieces"):
        tot_pieces = int(slip_order.get("total_pieces"))

    # 7. Total Order Quantity Banner
    banner_bg = "#334155" if is_old_slip else "#003366"
    draw.rectangle([(14, banner_y), (width - 14, banner_y + banner_h)], fill=banner_bg)

    if hide_pieces:
        total_text = f"TOTAL ORDER QUANTITY: {tot_boxes:,} BOXES"
    else:
        total_text = f"TOTAL ORDER QUANTITY: {tot_boxes:,} BOXES   |   {tot_pieces:,} PIECES"
    draw.text((width // 2, banner_y + (banner_h // 2)), total_text, fill="#ffffff", font=font_grand_total, anchor="mm")

    # 8. Footer Card
    draw.rounded_rectangle([(14, foot_card_y), (width - 14, foot_card_y + foot_card_h)], radius=12, fill="#f8fafc", outline="#cbd5e1", width=2)
    mid_foot = foot_card_y
    draw.text((width // 2, mid_foot + 26), "Thank You for Your Order!", fill="#003366", font=font_foot_thanks, anchor="mm")
    draw.text((width // 2, mid_foot + 50), "Our Customer Care team is always available to assist you.", fill="#334155", font=font_foot_sub, anchor="mm")
    draw.text((width // 2, mid_foot + 74), "Toll-Free Helpline: 1800 103 3211   |   Email: customercare@khandelia.com", fill="#0284c7", font=font_foot_toll, anchor="mm")
    draw.text((width // 2, mid_foot + 96), "For any queries or assistance, feel free to call or email us. We are always happy to help!", fill="#64748b", font=font_foot_help, anchor="mm")
    draw.text((width // 2, mid_foot + 115), "Khandelia Oil and General Mills Pvt. Ltd. • Official Digital OMS Record", fill="#94a3b8", font=font_foot_copy, anchor="mm")

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
