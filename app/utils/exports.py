import io
from flask import Response


def xlsx_response(filename, headers, rows):
    """Plain Excel file from a header row and a list of rows."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([float(v) if hasattr(v, "quantize") else v for v in r])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 2, 45)
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
