"""Marksheet as a PDF using reportlab (pure Python, same approach as receipt_pdf)."""
import io
import os
from flask import current_app
from app.models import Institute
from app.services.exam_service import fmt_marks


def build_marksheet_pdf(exam, row):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image

    inst, branch, st = Institute.query.first(), exam.branch, row["student"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Marksheet {st.student_code}")
    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=17, leading=20, spaceAfter=2)
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#555555"),
                           alignment=1)
    norm = ParagraphStyle("n", parent=ss["Normal"], fontSize=10, leading=13)
    bold = ParagraphStyle("b", parent=norm, fontName="Helvetica-Bold")
    right = ParagraphStyle("r", parent=norm, alignment=2)
    right_b = ParagraphStyle("rb", parent=right, fontName="Helvetica-Bold")
    center = ParagraphStyle("c", parent=norm, alignment=1)

    story = []
    if inst and inst.logo:
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], "institute", os.path.basename(inst.logo))
        if os.path.exists(path):
            story.append(Image(path, width=18 * mm, height=18 * mm, kind="proportional", hAlign="CENTER"))
    story.append(Paragraph(inst.name if inst else "Institute", title))
    addr = ", ".join(x for x in [branch.name, branch.address, branch.city] if x)
    story.append(Paragraph(addr, small))
    story += [Spacer(1, 5 * mm),
              Paragraph("MARKSHEET", ParagraphStyle("m", parent=bold, alignment=1, fontSize=13)),
              Paragraph(f"{exam.name} · {exam.type_label} · {exam.session.name}", center), Spacer(1, 4 * mm)]

    info = Table([[Paragraph("<b>Student</b>", norm), Paragraph(st.full_name, norm),
                   Paragraph("<b>Student ID</b>", norm), Paragraph(st.student_code, norm)],
                  [Paragraph("<b>Class</b>", norm), Paragraph(st.class_name or "—", norm),
                   Paragraph("<b>Branch</b>", norm), Paragraph(branch.name, norm)]],
                 colWidths=[24 * mm, 62 * mm, 28 * mm, 60 * mm])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [info, Spacer(1, 4 * mm)]

    data = [[Paragraph(h, bold) for h in ("Subject", "Date")] +
            [Paragraph(h, right_b) for h in ("Max", "Pass", "Obtained")] +
            [Paragraph(h, ParagraphStyle("cb", parent=bold, alignment=1)) for h in ("Grade", "Result")]]
    for s in row["subjects"]:
        data.append([Paragraph(s["paper"].subject_name, norm), Paragraph(s["paper"].exam_date.strftime("%d %b %Y"), norm),
                     Paragraph(fmt_marks(s["max"]), right), Paragraph(fmt_marks(s["pass_marks"]), right),
                     Paragraph("AB" if s["absent"] else fmt_marks(s["obtained"]), right),
                     Paragraph(s["grade"], center), Paragraph("Pass" if s["passed"] else "Fail", center)])
    data.append([Paragraph("<b>Total</b>", norm), "", Paragraph(f"<b>{fmt_marks(row['max'])}</b>", right), "",
                 Paragraph(f"<b>{fmt_marks(row['obtained'])}</b>", right), Paragraph(f"<b>{row['grade']}</b>", center),
                 Paragraph("<b>Pass</b>" if row["passed"] else "<b>Fail</b>", center)])
    t = Table(data, colWidths=[50 * mm, 28 * mm, 17 * mm, 17 * mm, 25 * mm, 17 * mm, 20 * mm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f6")),
                           ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f7f7f7")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [t, Spacer(1, 5 * mm)]

    summary = Table([[Paragraph("<b>Percentage</b>", norm), Paragraph(f"{row['percent']}%", norm),
                      Paragraph("<b>Grade</b>", norm), Paragraph(row["grade"], norm),
                      Paragraph("<b>Rank</b>", norm), Paragraph(str(row["rank"]), norm),
                      Paragraph("<b>Result</b>", norm), Paragraph("PASS" if row["passed"] else "FAIL", bold)]],
                    colWidths=[26 * mm, 22 * mm, 16 * mm, 14 * mm, 14 * mm, 14 * mm, 18 * mm, 18 * mm])
    summary.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
                                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [summary, Spacer(1, 4 * mm)]
    remarks = [f"{s['paper'].subject_name}: {s['remark']}" for s in row["subjects"] if s["remark"]]
    if remarks:
        story.append(Paragraph("<b>Remarks:</b> " + "; ".join(remarks), norm))
    story += [Spacer(1, 14 * mm),
              Table([[Paragraph("Class teacher / Branch admin", small), Paragraph("Principal / Owner", small)]],
                    colWidths=[91 * mm, 91 * mm])]
    doc.build(story)
    return buf.getvalue()
