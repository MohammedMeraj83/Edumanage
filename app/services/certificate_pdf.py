"""Certificate PDF: A4 landscape with a border, the institute header, the wording, a signature line and a QR code
that opens the public verification page."""
import io
import os
from flask import current_app
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from xml.sax.saxutils import escape
from app.models import Institute
from app.services.certificate_service import certificate_text, type_label
from app.utils.qr import public_url, draw_qr

INK = colors.HexColor("#0f4c5c")


def _p(text):
    """Plain text the built-in PDF fonts can draw (anything non-Latin becomes ?)."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def _t(text):
    """Same, escaped for Paragraph markup."""
    return escape(_p(text))


def build_certificate_pdf(cert):
    inst, branch = Institute.query.first(), cert.branch
    title, paragraphs = certificate_text(cert)
    buf = io.BytesIO()
    W, H = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(f"{type_label(cert.cert_type)} {cert.certificate_no}")

    c.setStrokeColor(INK)
    c.setLineWidth(2.2)
    c.rect(9 * mm, 9 * mm, W - 18 * mm, H - 18 * mm)
    c.setLineWidth(0.6)
    c.rect(12.5 * mm, 12.5 * mm, W - 25 * mm, H - 25 * mm)

    top = H - 20 * mm
    if inst and inst.logo:
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], "institute", os.path.basename(inst.logo))
        if os.path.exists(path):
            try:
                from reportlab.lib.utils import ImageReader
                c.drawImage(ImageReader(path), W / 2 - 9 * mm, top - 16 * mm, 18 * mm, 18 * mm,
                            preserveAspectRatio=True, mask="auto")
                top -= 19 * mm
            except Exception:
                pass
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 21)
    c.drawCentredString(W / 2, top - 6 * mm, _p(inst.name) if inst else "Institute")
    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Helvetica", 9.5)
    line = ", ".join(p for p in [branch.name, branch.address, branch.city] if p)
    c.drawCentredString(W / 2, top - 12 * mm, _p(line)[:120])
    c.setStrokeColor(colors.HexColor("#c9d3d8"))
    c.setLineWidth(0.5)
    c.line(40 * mm, top - 16 * mm, W - 40 * mm, top - 16 * mm)

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 25)
    c.drawCentredString(W / 2, top - 30 * mm, title)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9.5)
    c.drawString(24 * mm, top - 41 * mm, f"Certificate no.: {cert.certificate_no}")
    c.drawRightString(W - 24 * mm, top - 41 * mm, f"Date: {cert.issue_date.strftime('%d %B %Y')}")

    style = ParagraphStyle("body", fontName="Helvetica", fontSize=13, leading=22, alignment=TA_JUSTIFY,
                           spaceAfter=7)
    y = top - 50 * mm
    for text in paragraphs:
        p = Paragraph(_t(text), style)
        _, h = p.wrap(W - 56 * mm, H)
        p.drawOn(c, 28 * mm, y - h)
        y -= h + 7

    base = 20 * mm
    qr = 24 * mm
    draw_qr(c, public_url("verify.certificate", token=cert.token), W / 2 - qr / 2, base + 4 * mm, qr)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawCentredString(W / 2, base, "Scan to verify this certificate")
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.6)
    c.line(W - 90 * mm, base + 10 * mm, W - 28 * mm, base + 10 * mm)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9.5)
    c.drawCentredString(W - 59 * mm, base + 5 * mm, "Authorised signatory")
    c.line(28 * mm, base + 10 * mm, 90 * mm, base + 10 * mm)
    c.drawCentredString(59 * mm, base + 5 * mm, "Date and place")

    if cert.status == "cancelled":
        c.saveState()
        c.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.22))
        c.setFont("Helvetica-Bold", 90)
        c.translate(W / 2, H / 2)
        c.rotate(28)
        c.drawCentredString(0, -30, "CANCELLED")
        c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()
