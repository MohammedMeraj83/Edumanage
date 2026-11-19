"""Receipt as a PDF using reportlab (pure Python - works on Windows without extra system libraries)."""
import io
import os
from decimal import Decimal
from flask import current_app
from app.models import Institute, FeeDue


def _rs(v):
    return f"Rs. {Decimal(v):,.2f}"


def build_receipt_pdf(payment, balance_after):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image

    inst, branch, st = Institute.query.first(), payment.branch, payment.student
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title=payment.receipt_no)
    ss = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=ss["Title"], fontSize=15, leading=18, spaceAfter=2)
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    norm = ParagraphStyle("n", parent=ss["Normal"], fontSize=9.5, leading=12)
    bold = ParagraphStyle("b", parent=norm, fontName="Helvetica-Bold")
    red = ParagraphStyle("r", parent=bold, textColor=colors.HexColor("#b42318"), alignment=1, fontSize=12)

    story = []
    if inst and inst.logo:
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], "institute", os.path.basename(inst.logo))
        if os.path.exists(path):
            story.append(Image(path, width=16 * mm, height=16 * mm, kind="proportional", hAlign="CENTER"))
    story.append(Paragraph(inst.name if inst else "Institute", h))
    addr = ", ".join(x for x in [branch.name, branch.address, branch.city] if x)
    story.append(Paragraph(addr, ParagraphStyle("c", parent=small, alignment=1)))
    contact = " · ".join(x for x in [branch.phone, branch.email] if x)
    if contact:
        story.append(Paragraph(contact, ParagraphStyle("c2", parent=small, alignment=1)))
    story += [Spacer(1, 4 * mm), Paragraph("FEE RECEIPT", ParagraphStyle("t", parent=bold, alignment=1, fontSize=11))]
    if payment.status == "cancelled":
        story.append(Paragraph("CANCELLED", red))
    story.append(Spacer(1, 3 * mm))

    info = [[Paragraph("<b>Receipt no.</b>", norm), Paragraph(payment.receipt_no, norm),
             Paragraph("<b>Date</b>", norm), Paragraph(payment.paid_on.strftime("%d %b %Y"), norm)],
            [Paragraph("<b>Student</b>", norm), Paragraph(f"{st.full_name}<br/>{st.student_code} · {st.class_name}", norm),
             Paragraph("<b>Paid by</b>", norm),
             Paragraph(payment.mode_label + (f"<br/>Ref: {payment.reference}" if payment.reference else ""), norm)]]
    t = Table(info, colWidths=[24 * mm, 44 * mm, 18 * mm, 32 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [t, Spacer(1, 3 * mm)]

    rows = [[Paragraph("<b>Particulars</b>", norm), Paragraph("<b>Amount</b>", ParagraphStyle("ra", parent=norm, alignment=2))]]
    for a in payment.allocations:
        rows.append([Paragraph(a.due.label, norm), Paragraph(_rs(a.amount), ParagraphStyle("ra", parent=norm, alignment=2))])
    rows.append([Paragraph("<b>Total received</b>", norm), Paragraph(f"<b>{_rs(payment.amount)}</b>", ParagraphStyle("ra", parent=norm, alignment=2))])
    if payment.refunded_amount:
        rows.append([Paragraph("Refunded", norm), Paragraph(_rs(payment.refunded_amount), ParagraphStyle("ra", parent=norm, alignment=2))])
    items = Table(rows, colWidths=[86 * mm, 32 * mm])
    items.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [items, Spacer(1, 3 * mm),
              Paragraph(f"Balance still due for this student: <b>{_rs(balance_after)}</b>", norm), Spacer(1, 2 * mm),
              Paragraph(f"Received by {payment.receiver.full_name}. This is a computer-generated receipt.", small)]
    doc.build(story)
    return buf.getvalue()


def build_salary_slip_pdf(p):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer

    inst, branch, person = Institute.query.first(), p.branch, p.person
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title=p.slip_no)
    ss = getSampleStyleSheet()
    norm = ParagraphStyle("n", parent=ss["Normal"], fontSize=9.5, leading=12)
    right = ParagraphStyle("r", parent=norm, alignment=2)
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    center = ParagraphStyle("c", parent=small, alignment=1)
    story = [Paragraph(inst.name if inst else "Institute", ParagraphStyle("h", parent=ss["Title"], fontSize=15, leading=18)),
             Paragraph(", ".join(x for x in [branch.name, branch.address, branch.city] if x), center), Spacer(1, 3 * mm),
             Paragraph(f"SALARY SLIP · {p.month:%B %Y}", ParagraphStyle("t", parent=norm, fontName="Helvetica-Bold", alignment=1, fontSize=11)),
             Spacer(1, 3 * mm)]
    info = Table([[Paragraph("<b>Name</b>", norm), Paragraph(person.full_name, norm), Paragraph("<b>Slip no.</b>", norm), Paragraph(p.slip_no, norm)],
                  [Paragraph("<b>ID</b>", norm), Paragraph(person.employee_code, norm), Paragraph("<b>Role</b>", norm),
                   Paragraph(person.title_text if p.kind == "staff" else "Teacher", norm)]],
                 colWidths=[16 * mm, 50 * mm, 20 * mm, 32 * mm])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [info, Spacer(1, 3 * mm)]
    rows = [[Paragraph("<b>Earnings</b>", norm), Paragraph("<b>Amount</b>", right)]]

    def line(label, value):
        rows.append([Paragraph(label, norm), Paragraph(_rs(value), right)])
    if Decimal(p.base_amount) > 0:
        line("Fixed monthly salary", p.base_amount)
    if p.pay_type != "fixed":
        line(f"Lectures taken: {p.lectures_taught} x {_rs(p.lecture_rate)}", p.lecture_amount)
    if Decimal(p.allowance) > 0:
        line("Allowance", p.allowance)
    if Decimal(p.bonus) > 0:
        line("Bonus", p.bonus)
    if Decimal(p.auto_deduction) > 0:
        line(f"Missed lectures: {p.lectures_missed} x {_rs(p.missed_rate)}", -Decimal(p.auto_deduction))
    if Decimal(p.deduction) > 0:
        line(f"Deduction{(' - ' + p.adjustment_note) if p.adjustment_note else ''}", -Decimal(p.deduction))
    rows.append([Paragraph("<b>Net salary</b>", norm), Paragraph(f"<b>{_rs(p.net_amount)}</b>", right)])
    t = Table(rows, colWidths=[86 * mm, 32 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [t, Spacer(1, 3 * mm)]
    paid = [sp for sp in p.payments if sp.status == "active"]
    if paid:
        story.append(Paragraph("Paid: " + "; ".join(f"{_rs(sp.amount)} on {sp.paid_on:%d %b %Y} ({sp.mode})" for sp in paid), norm))
    story += [Spacer(1, 2 * mm), Paragraph("Computer-generated salary slip.", small)]
    doc.build(story)
    return buf.getvalue()
