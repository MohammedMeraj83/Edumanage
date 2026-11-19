from datetime import date
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_
from extensions import db, limiter
from app.models import Branch, Enquiry, ENQUIRY_STATUSES
from app.services import communication_service as svc
from app.services.audit_service import log_action
from app.utils.branch_access import ensure_branch_access, scope_to_branch
from app.utils.decorators import permission_required

bp = Blueprint("enquiries", __name__, url_prefix="/enquiries")


def _enquiry(enquiry_id):
    enquiry = db.get_or_404(Enquiry, enquiry_id)
    if enquiry.branch_id is not None:
        ensure_branch_access(enquiry.branch_id)
    elif not current_user.is_owner:
        abort(403)
    return enquiry


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter a valid follow-up date.")


def _selected_branch_id(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        branch_id = int(value)
    except ValueError:
        raise ValueError("Choose a valid branch.")
    if branch_id <= 0:
        raise ValueError("Choose a valid branch.")
    return branch_id


@bp.route("/public", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def public_form():
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    errors = []
    if request.method == "POST":
        branch_id = None
        if request.form.get("website", "").strip():
            abort(400)
        try:
            branch_id = _selected_branch_id(request.form.get("branch_id"))
        except ValueError as exc:
            errors.append(str(exc))
        if branch_id and not any(branch.id == branch_id for branch in branches):
            errors.append("Choose an active branch.")
        if not errors:
            try:
                svc.create_enquiry(
                    branch_id=branch_id,
                    full_name=request.form.get("full_name"),
                    phone=request.form.get("phone"),
                    email=request.form.get("email"),
                    course_interest=request.form.get("course_interest"),
                    message=request.form.get("message"),
                    source="public",
                )
                return redirect(url_for("enquiries.thanks"))
            except ValueError as exc:
                errors.append(str(exc))
    return render_template("enquiries/public_form.html", branches=branches, errors=errors, form=request.form)


@bp.route("/thanks")
def thanks():
    return render_template("enquiries/thanks.html")


@bp.route("/")
@permission_required("enquiries.view")
def index():
    status = request.args.get("status", "all")
    q = (request.args.get("q") or "").strip()
    query = scope_to_branch(Enquiry.query, Enquiry)
    if status in {value for value, _ in ENQUIRY_STATUSES}:
        query = query.filter(Enquiry.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Enquiry.full_name.ilike(like),
            Enquiry.phone.ilike(like),
            Enquiry.email.ilike(like),
            Enquiry.course_interest.ilike(like),
        ))
    page = query.order_by(Enquiry.created_at.desc(), Enquiry.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("enquiries/index.html", page=page, q=q, status=status,
                           statuses=ENQUIRY_STATUSES)


@bp.route("/new", methods=["GET", "POST"])
@permission_required("enquiries.create")
def new():
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all() if current_user.is_owner else []
    errors = []
    if request.method == "POST":
        try:
            branch_id = _selected_branch_id(request.form.get("branch_id")) if current_user.is_owner else current_user.branch_id
            enquiry = svc.create_enquiry(
                branch_id=branch_id,
                full_name=request.form.get("full_name"),
                phone=request.form.get("phone"),
                email=request.form.get("email"),
                course_interest=request.form.get("course_interest"),
                message=request.form.get("message"),
                source="staff",
                user=current_user,
            )
            flash("Enquiry saved.", "success")
            return redirect(url_for("enquiries.detail", enquiry_id=enquiry.id))
        except ValueError as exc:
            errors.append(str(exc))
    return render_template("enquiries/form.html", enquiry=None, branches=branches,
                           errors=errors, form=request.form)


@bp.route("/<int:enquiry_id>")
@permission_required("enquiries.view")
def detail(enquiry_id):
    enquiry = _enquiry(enquiry_id)
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all() if current_user.is_owner else []
    return render_template("enquiries/detail.html", enquiry=enquiry, statuses=ENQUIRY_STATUSES, branches=branches)


@bp.route("/<int:enquiry_id>/edit", methods=["POST"])
@permission_required("enquiries.edit")
def edit(enquiry_id):
    enquiry = _enquiry(enquiry_id)
    try:
        update_branch = current_user.is_owner and "branch_id" in request.form
        branch_id = _selected_branch_id(request.form.get("branch_id")) if update_branch else None
        svc.update_enquiry(
            enquiry,
            status=request.form.get("status"),
            follow_up_at=_parse_date(request.form.get("follow_up_at")),
            staff_notes=request.form.get("staff_notes"),
            user=current_user,
            branch_id=branch_id,
            update_branch=update_branch,
        )
        flash("Enquiry follow-up saved.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("enquiries.detail", enquiry_id=enquiry.id))


@bp.route("/<int:enquiry_id>/delete", methods=["POST"])
@permission_required("enquiries.delete")
def delete(enquiry_id):
    enquiry = _enquiry(enquiry_id)
    log_action("delete", "enquiry", enquiry.id, "Enquiry removed", user=current_user)
    db.session.delete(enquiry)
    db.session.commit()
    flash("Enquiry deleted.", "success")
    return redirect(url_for("enquiries.index"))
