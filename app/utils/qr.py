"""QR codes drawn straight into PDFs (reportlab's own generator, no extra packages) and public link building."""
from flask import current_app, url_for


def public_url(endpoint, **values):
    """Absolute URL of a public page. Set PUBLIC_BASE_URL (e.g. https://school.example.com) if the app runs behind a
    proxy or on an internal address, so the QR codes on printed cards open the real website."""
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if base:
        return base + url_for(endpoint, _external=False, **values)
    return url_for(endpoint, _external=True, **values)


def draw_qr(c, text, x, y, size):
    """Draw a QR code of `text` with its lower-left corner at (x, y), `size` points wide and high."""
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode import qr
    from reportlab.graphics.shapes import Drawing
    widget = qr.QrCodeWidget(text, barLevel="M", barBorder=1)
    x0, y0, x1, y1 = widget.getBounds()
    w, h = x1 - x0, y1 - y0
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)
