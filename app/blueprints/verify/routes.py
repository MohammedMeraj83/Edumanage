"""Public pages behind the QR codes. No sign-in. They confirm that a card or certificate is real and still valid,
and show only the minimum (name, number, status) - never photo, phone, address or date of birth."""
from flask import Blueprint, render_template
from extensions import limiter
from app.services import idcard_service, certificate_service
from app.services.homework_service import today

bp = Blueprint("verify", __name__, url_prefix="/verify")


def _page(**ctx):
    return render_template("verify/result.html", **ctx), (404 if ctx.get("state") == "unknown" else 200)


@bp.route("/id/<token>")
@limiter.limit("60 per minute")
def id_card(token):
    card, info = idcard_service.lookup_by_token(token[:40])
    if card is None or info is None:
        return _page(state="unknown", what="ID card")
    if card.status != "active":
        state = {"lost": "closed", "cancelled": "closed", "replaced": "replaced"}.get(card.status, "closed")
    elif card.valid_until < today():
        state = "expired"
    else:
        state = "valid"
    rows = [("Name", info["name"]), ("Role", info["role"]), ("ID", info["code"]), ("Branch", info["branch"].name),
            ("Card no.", card.card_no), ("Valid till", card.valid_until.strftime("%d %b %Y"))]
    return _page(state=state, what="ID card", rows=rows, institute=info["branch"].institute.name)


@bp.route("/certificate/<token>")
@limiter.limit("60 per minute")
def certificate(token):
    cert = certificate_service.lookup_by_token(token[:40])
    if cert is None:
        return _page(state="unknown", what="certificate")
    state = "valid" if cert.status == "issued" else "cancelled"
    rows = [("Certificate", certificate_service.type_label(cert.cert_type)), ("Number", cert.certificate_no),
            ("Issued to", cert.student.full_name), ("Issued on", cert.issue_date.strftime("%d %B %Y")),
            ("Branch", cert.branch.name)]
    return _page(state=state, what="certificate", rows=rows, institute=cert.branch.institute.name)
