"""ID card PDFs (reportlab). One card = 2 pages (front, back) at credit-card size. A sheet = A4 with 10 cards a page:
all fronts, then the matching backs with the columns mirrored, so printing double sided lines every back up behind its front."""
import io
import os
from datetime import date
from flask import current_app
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from app.models import Institute
from app.utils.qr import public_url, draw_qr

CARD_W, CARD_H = 85.6 * mm, 54 * mm
BAND = {"student": colors.HexColor("#0f766e"), "teacher": colors.HexColor("#3730a3"), "staff": colors.HexColor("#475569")}
GREY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#d0d5dd")


def _t(text):
    """The built-in PDF fonts only know Latin letters; anything else would print as black boxes."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def fit(c, text, font, size, width, min_size=5.0):
    text = _t(text)
    while size > min_size and stringWidth(text, font, size) > width:
        size -= 0.25
    return text, size


def wrap(text, font, size, width, max_lines):
    words, lines, cur = _t(text).split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if stringWidth(trial, font, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(". ") + "..."
    return lines


def _image(path):
    from reportlab.lib.utils import ImageReader
    return ImageReader(path)


def _photo(c, path, x, y, w, h, name, color):
    """Photo cropped to fill the box (or initials on grey when there is no photo)."""
    if path:
        try:
            from PIL import Image
            im = Image.open(path).convert("RGB")
            iw, ih = im.size
            want = w / h
            if iw / ih > want:                                    # too wide -> trim the sides
                nw = int(ih * want)
                im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))
            else:                                                 # too tall -> trim, keeping the face area (top)
                nh = int(iw / want)
                top = int((ih - nh) * 0.25)
                im = im.crop((0, top, iw, top + nh))
            im.thumbnail((400, 500))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=88)
            buf.seek(0)
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(buf), x, y, w, h)
            c.setStrokeColor(LIGHT)
            c.rect(x, y, w, h, stroke=1, fill=0)
            return
        except Exception:
            pass
    c.setFillColor(colors.HexColor("#e5e7eb"))
    c.rect(x, y, w, h, stroke=0, fill=1)
    initials = "".join(p[0] for p in _t(name).split()[:2]).upper() or "?"
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(x + w / 2, y + h / 2 - 5, initials)


def _logo_path(inst):
    if inst and inst.logo:
        p = os.path.join(current_app.config["UPLOAD_FOLDER"], "institute", os.path.basename(inst.logo))
        if os.path.exists(p):
            return p
    return None


def draw_front(c, x, y, info, card, inst):
    color = BAND[info["kind"]]
    c.setFillColor(colors.white)
    c.setStrokeColor(LIGHT)
    c.roundRect(x, y, CARD_W, CARD_H, 2.5 * mm, stroke=1, fill=1)
    c.setFillColor(color)
    c.rect(x + 0.3, y + CARD_H - 12 * mm, CARD_W - 0.6, 11.7 * mm, stroke=0, fill=1)
    left = x + 3 * mm
    logo = _logo_path(inst)
    if logo:
        try:
            c.drawImage(_image(logo), x + 2.5 * mm, y + CARD_H - 10.5 * mm, 9 * mm, 9 * mm, preserveAspectRatio=True,
                        mask="auto")
            left = x + 13 * mm
        except Exception:
            pass
    c.setFillColor(colors.white)
    name, size = fit(c, inst.name if inst else "Institute", "Helvetica-Bold", 8.5, x + CARD_W - 3 * mm - left)
    c.setFont("Helvetica-Bold", size)
    c.drawString(left, y + CARD_H - 6 * mm, name)
    branch, size = fit(c, info["branch"].name, "Helvetica", 6, x + CARD_W - 3 * mm - left)
    c.setFont("Helvetica", size)
    c.drawString(left, y + CARD_H - 9.6 * mm, branch)

    _photo(c, info["photo_path"], x + 3 * mm, y + CARD_H - 12 * mm - 3 * mm - 27 * mm, 21 * mm, 27 * mm, info["name"], color)

    tx, tw = x + 27 * mm, CARD_W - 30 * mm
    ty = y + CARD_H - 17.5 * mm
    c.setFillColor(colors.black)
    font, size, lines = "Helvetica-Bold", 9.5, []
    for size in (9.5, 8.5, 7.5):
        lines = wrap(info["name"], font, size, tw, 2)
        if len(lines) <= 2 and all(stringWidth(l, font, size) <= tw for l in lines):
            break
    c.setFont(font, size)
    for ln in lines:
        c.drawString(tx, ty, ln)
        ty -= size + 1.5
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 6.3)
    c.drawString(tx, ty - 1, info["role"].upper())
    ty -= 9
    rows = [("ID", info["code"])]
    if info["kind"] == "student":
        rows.append(("Class", info["line"]))
    else:
        rows.append(("Role", info["line"]))
    if info["dob"]:
        rows.append(("DOB", info["dob"].strftime("%d %b %Y")))
    if info["blood_group"]:
        rows.append(("Blood", info["blood_group"]))
    if info["phone"]:
        rows.append(("Phone", info["phone"]))
    for label, value in rows[:5]:
        c.setFillColor(GREY)
        c.setFont("Helvetica", 6)
        c.drawString(tx, ty, label)
        text, size = fit(c, value, "Helvetica-Bold", 6.6, tw - 11 * mm, 5)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", size)
        c.drawString(tx + 11 * mm, ty, text)
        ty -= 7.4
    c.setFillColor(color)
    c.rect(x + 0.3, y + 0.3, CARD_W - 0.6, 4.2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 5.6)
    c.drawString(x + 3 * mm, y + 1.6 * mm, f"Valid till {card.valid_until.strftime('%d %b %Y')}")
    c.drawRightString(x + CARD_W - 3 * mm, y + 1.6 * mm, card.card_no)


def draw_back(c, x, y, info, card, inst):
    color = BAND[info["kind"]]
    branch = info["branch"]
    c.setFillColor(colors.white)
    c.setStrokeColor(LIGHT)
    c.roundRect(x, y, CARD_W, CARD_H, 2.5 * mm, stroke=1, fill=1)
    c.setFillColor(color)
    c.rect(x + 0.3, y + CARD_H - 4.2 * mm, CARD_W - 0.6, 3.9 * mm, stroke=0, fill=1)
    left, width = x + 4 * mm, CARD_W - 33 * mm
    ty = y + CARD_H - 9.5 * mm
    c.setFillColor(GREY)
    c.setFont("Helvetica-Bold", 6)
    c.drawString(left, ty, "IF FOUND, PLEASE RETURN TO")
    ty -= 7
    c.setFillColor(colors.black)
    name, size = fit(c, inst.name if inst else "Institute", "Helvetica-Bold", 8, width)
    c.setFont("Helvetica-Bold", size)
    c.drawString(left, ty, name)
    ty -= 6.5
    c.setFont("Helvetica", 6)
    address = ", ".join(p for p in [branch.name, branch.address, branch.city, branch.pincode] if p)
    for ln in wrap(address, "Helvetica", 6, width, 3):
        c.drawString(left, ty, ln)
        ty -= 7
    for text in [branch.phone or (inst.phone if inst else None), branch.email or (inst.email if inst else None)]:
        if text:
            c.drawString(left, ty, _t(text))
            ty -= 7
    qr_size = 20 * mm
    qx, qy = x + CARD_W - qr_size - 4 * mm, y + 12 * mm
    draw_qr(c, public_url("verify.id_card", token=card.token), qx, qy, qr_size)
    c.setFillColor(GREY)
    c.setFont("Helvetica", 4.8)
    c.drawCentredString(qx + qr_size / 2, qy - 5, "Scan to verify this card")
    c.setStrokeColor(GREY)
    c.line(left, y + 11 * mm, left + 24 * mm, y + 11 * mm)
    c.setFont("Helvetica", 5)
    c.drawString(left, y + 8.3 * mm, "Authorised signatory")
    c.setFont("Helvetica", 4.6)
    c.drawString(left, y + 4.2 * mm, "This card belongs to the institute and is not transferable.")
    c.setFillColor(color)
    c.rect(x + 0.3, y + 0.3, CARD_W - 0.6, 2 * mm, stroke=0, fill=1)


def build_id_cards_pdf(items, sheet=False):
    """items = [(info, card), ...]. Returns PDF bytes."""
    inst = Institute.query.first()
    buf = io.BytesIO()
    if not sheet:
        c = canvas.Canvas(buf, pagesize=(CARD_W, CARD_H))
        c.setTitle("ID card")
        for info, card in items:
            draw_front(c, 0, 0, info, card, inst)
            c.showPage()
            draw_back(c, 0, 0, info, card, inst)
            c.showPage()
        c.save()
        return buf.getvalue()

    from reportlab.lib.pagesizes import A4
    page_w, page_h = A4
    cols, rows_n, gap_x, gap_y = 2, 5, 5 * mm, 1.5 * mm
    x0 = (page_w - (cols * CARD_W + gap_x)) / 2
    y_top = page_h - (page_h - (rows_n * CARD_H + (rows_n - 1) * gap_y)) / 2
    per_page = cols * rows_n
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("ID cards")
    for start in range(0, len(items), per_page):
        chunk = items[start:start + per_page]
        for side in ("front", "back"):
            for i, (info, card) in enumerate(chunk):
                row, col = divmod(i, cols)
                if side == "back":
                    col = cols - 1 - col                        # mirror so double-sided printing matches
                x = x0 + col * (CARD_W + gap_x)
                y = y_top - (row + 1) * CARD_H - row * gap_y
                (draw_front if side == "front" else draw_back)(c, x, y, info, card, inst)
            c.showPage()
    c.save()
    return buf.getvalue()
