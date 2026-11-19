from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, Response
from flask_login import current_user
from extensions import db
from app.models import IdCard, Branch, Student
from app.services import idcard_service as svc
from app.services.idcard_pdf import build_id_cards_pdf
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import role_required, permission_required

bp = Blueprint("id_cards", __name__, url_prefix="/id-cards")
ADMIN = ("owner", "branch_admin")


def guard(code):
    def deco(view):
        return role_required(*ADMIN)(permission_required(code)(view))
    return deco


def pdf_response(data, name):
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


def card_pdf_response(card):
    """One card (front + back). Caller has already checked who may see it."""
    person = svc.get_person(card.person_kind, card.person_id)
    if person is None:
        abort(404)
    return pdf_response(build_id_cards_pdf([(svc.person_info(card.person_kind, person), card)]), f"{card.card_no}.pdf")


def _person(kind, person_id):
    if kind not in svc.KINDS:
        abort(404)
    person = svc.get_person(kind, person_id)
    if person is None:
        abort(404)
    ensure_branch_access(person.branch_id)
    return person


@bp.route("/")
@guard("id_cards.view")
def index():
    kind = request.args.get("kind", "student")
    if kind not in svc.KINDS:
        kind = "student"
    q = request.args.get("q", "").strip()
    class_name = request.args.get("class", "")
    status = request.args.get("status", "active")
    branch_id = request.args.get("branch", type=int)
    page = svc.people_page(kind, current_user, q, class_name, status, branch_id, request.args.get("page", 1, type=int))
    classes = []
    if kind == "student":
        rows = scope_to_branch(db.session.query(Student.class_name).distinct(), Student).order_by(Student.class_name).all()
        classes = [r[0] for r in rows]
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("id_cards/index.html", page=page, kind=kind, kinds=svc.KINDS, q=q, class_name=class_name,
                           status=status, classes=classes, branch_id=branch_id, args=args,
                           cards=svc.cards_map(kind, [p.id for p in page.items]), valid=svc.card_is_valid,
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [],
                           code_of=lambda p: getattr(p, svc.KINDS[kind]["code"]),
                           line_of=lambda p: p.class_name if kind == "student" else (
                               p.specialization or "Teacher" if kind == "teacher" else p.designation))


@bp.route("/issue/<kind>/<int:person_id>", methods=["POST"])
@guard("id_cards.create")
def issue(kind, person_id):
    person = _person(kind, person_id)
    replace = bool(request.form.get("replace"))
    try:
        card, created = svc.issue_card(kind, person, current_user, reason=request.form.get("reason"), replace=replace,
                                       old_status=request.form.get("old_status") or "replaced")
        flash(f"Card {card.card_no} issued." if created else "This person already has an active card.",
              "success" if created else "info")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("id_cards.index", kind=kind, q=getattr(person, svc.KINDS[kind]["code"])))


@bp.route("/card/<int:card_id>.pdf")
@guard("id_cards.view")
def card_pdf(card_id):
    card = db.get_or_404(IdCard, card_id)
    ensure_branch_access(card.branch_id)
    if card.status != "active":
        flash("This card is closed, so it cannot be printed. Issue a new card.", "warning")
        return redirect(url_for("id_cards.index", kind=card.person_kind))
    return card_pdf_response(card)


@bp.route("/card/<int:card_id>/close", methods=["POST"])
@guard("id_cards.edit")
def close(card_id):
    card = db.get_or_404(IdCard, card_id)
    ensure_branch_access(card.branch_id)
    try:
        svc.close_card(card, request.form.get("status"), current_user)
        flash("Card closed. Its QR code no longer verifies.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("id_cards.index", kind=card.person_kind))


@bp.route("/bulk", methods=["POST"])
@guard("id_cards.create")
def bulk():
    """Print the chosen people on A4 sheets (10 cards a page). Anyone without an active card gets one."""
    kind = request.form.get("kind", "student")
    if kind not in svc.KINDS:
        abort(404)
    ids = request.form.getlist("ids", type=int)[:200]
    model = svc.KINDS[kind]["model"]
    people = (scope_to_branch(model.query, model).filter(model.id.in_(ids), model.status == "active")
              .order_by(model.full_name).all()) if ids else []
    if not people:
        flash("Tick at least one active person to print.", "warning")
        return redirect(url_for("id_cards.index", kind=kind))
    items = svc.ensure_cards(kind, people, current_user)
    return pdf_response(build_id_cards_pdf(items, sheet=True), "id_cards.pdf")
