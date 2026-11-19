from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, Response
from flask_login import current_user
from extensions import db
from app.models import Certificate, Student, Branch
from app.services import certificate_service as svc
from app.services.certificate_pdf import build_certificate_pdf
from app.utils.branch_access import ensure_branch_access
from app.utils.decorators import role_required, permission_required

bp = Blueprint("certificates", __name__, url_prefix="/certificates")
ADMIN = ("owner", "branch_admin")


def guard(code):
    def deco(view):
        return role_required(*ADMIN)(permission_required(code)(view))
    return deco


def certificate_pdf_response(cert):
    return Response(build_certificate_pdf(cert), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{cert.certificate_no}.pdf"'})


def _cert(cert_id):
    cert = db.get_or_404(Certificate, cert_id)
    ensure_branch_access(cert.branch_id)
    return cert


def _parse_date(text):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


@bp.route("/")
@guard("certificates.view")
def index():
    cert_type, status = request.args.get("type", ""), request.args.get("status", "")
    q, branch_id = request.args.get("q", "").strip(), request.args.get("branch", type=int)
    page = svc.certificates_page(current_user, cert_type, status, q, branch_id, request.args.get("page", 1, type=int))
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("certificates/index.html", page=page, args=args, cert_type=cert_type, status=status, q=q,
                           branch_id=branch_id, types=svc.TYPE_CHOICES, type_label=svc.type_label,
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


@bp.route("/new")
@guard("certificates.create")
def new():
    q = request.args.get("q", "").strip()
    return render_template("certificates/new.html", q=q, students=svc.find_students(current_user, q))


@bp.route("/issue/<int:student_id>", methods=["GET", "POST"])
@guard("certificates.create")
def issue(student_id):
    student = db.get_or_404(Student, student_id)
    ensure_branch_access(student.branch_id)
    cert_type = (request.values.get("type") or request.form.get("cert_type") or "bonafide")
    if cert_type not in svc.CERT_TYPES:
        cert_type = "bonafide"
    if request.method == "POST":
        raw = {f["key"]: request.form.get(f"f_{f['key']}") for f in svc.CERT_TYPES[cert_type]["fields"]}
        try:
            cert = svc.issue_certificate(current_user, student, cert_type, _parse_date(request.form.get("issue_date")),
                                         raw, allow_dues=bool(request.form.get("allow_dues")))
            flash(f"Certificate {cert.certificate_no} issued.", "success")
            return redirect(url_for("certificates.detail", cert_id=cert.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("certificates/issue.html", student=student, cert_type=cert_type, spec=svc.CERT_TYPES[cert_type],
                           types=svc.CERT_TYPES, form=request.form if request.method == "POST" else {},
                           today=svc.today())


@bp.route("/<int:cert_id>")
@guard("certificates.view")
def detail(cert_id):
    cert = _cert(cert_id)
    title, paragraphs = svc.certificate_text(cert)
    return render_template("certificates/detail.html", cert=cert, title=title, paragraphs=paragraphs,
                           type_label=svc.type_label)


@bp.route("/<int:cert_id>.pdf")
@guard("certificates.view")
def pdf(cert_id):
    return certificate_pdf_response(_cert(cert_id))


@bp.route("/<int:cert_id>/cancel", methods=["POST"])
@guard("certificates.delete")
def cancel(cert_id):
    cert = _cert(cert_id)
    try:
        svc.cancel_certificate(cert, request.form.get("reason"), current_user)
        flash("Certificate cancelled. Its QR code now shows as cancelled.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("certificates.detail", cert_id=cert.id))
