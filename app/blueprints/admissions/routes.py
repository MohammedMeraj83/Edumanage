from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, login_required
from sqlalchemy import or_, func
from extensions import db
from app.models import Admission, AcademicSession, Branch, StudentDocument, DOC_TYPES, ADMISSION_STATUSES
from app.services import admission_service as svc
from app.services import student_service
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import permission_required
from app.utils.file_upload import save_image, send_private
from .forms import AdmissionForm

bp = Blueprint("admissions", __name__, url_prefix="/admissions")


def _get(admission_id):
    adm = db.get_or_404(Admission, admission_id)
    ensure_branch_access(adm.branch_id)
    return adm


def _prepare_form(form):
    """Fill branch/session dropdowns. Non-owners are fixed to their own branch."""
    sessions = AcademicSession.query.order_by(AcademicSession.start_date.desc()).all()
    form.session_id.choices = [(s.id, s.name + (" (current)" if s.is_current else "")) for s in sessions]
    if current_user.is_owner:
        form.branch_id.choices = [(b.id, f"{b.name} ({b.code})")
                                  for b in Branch.query.filter_by(is_active=True).order_by(Branch.name)]
    else:
        del form.branch_id
    if not current_user.has_permission("admissions.edit"):
        del form.approve_now
    return sessions


def _save_photo(form):
    f = form.photo.data
    if f is not None and getattr(f, "filename", ""):
        try:
            return save_image(f, "students", max_px=500)
        except ValueError as e:
            form.photo.errors.append(str(e))
    return None


def _is_duplicate(branch_id, name, dob, exclude_id=None):
    q = Admission.query.filter(Admission.branch_id == branch_id, func.lower(Admission.full_name) == name.lower(),
                               Admission.dob == dob, Admission.status.in_(("pending", "approved")))
    if exclude_id:
        q = q.filter(Admission.id != exclude_id)
    return q.first() is not None


@bp.route("/")
@permission_required("admissions.view")
def list_admissions():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "pending")
    branch_id = request.args.get("branch", type=int)
    query = scope_to_branch(Admission.query, Admission)
    if current_user.is_owner and branch_id:
        query = query.filter(Admission.branch_id == branch_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Admission.full_name.ilike(like), Admission.admission_no.ilike(like),
                                 Admission.guardian_phone.ilike(like), Admission.phone.ilike(like)))
    if status in ADMISSION_STATUSES:
        query = query.filter(Admission.status == status)
    page = query.order_by(Admission.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    branches = Branch.query.order_by(Branch.name).all() if current_user.is_owner else []
    return render_template("admissions/list.html", page=page, q=q, status=status, branch_id=branch_id,
                           branches=branches, args=args, statuses=ADMISSION_STATUSES)


@bp.route("/new", methods=["GET", "POST"])
@permission_required("admissions.create")
def new_admission():
    form = AdmissionForm()
    sessions = _prepare_form(form)
    if request.method == "GET":
        cur = next((s for s in sessions if s.is_current), None)
        if cur:
            form.session_id.data = cur.id
    if form.validate_on_submit():
        branch_id = form.branch_id.data if current_user.is_owner else current_user.branch_id
        data = svc.person_data(form)
        if _is_duplicate(branch_id, data["full_name"], data["dob"]):
            form.full_name.errors.append("An application for this name and date of birth already exists in this branch.")
        else:
            photo = _save_photo(form)
            if not form.photo.errors:
                adm = svc.create_admission(data, branch_id, form.session_id.data, photo, current_user)
                approve = getattr(form, "approve_now", None) is not None and form.approve_now.data
                if approve and current_user.has_permission("admissions.edit"):
                    student = svc.approve_admission(adm, current_user)
                    flash(f"Admitted. Student ID {student.student_code}, admission no. {student.admission_no}.", "success")
                    return redirect(url_for("students.detail", student_id=student.id))
                flash("Application saved. It is waiting for approval.", "success")
                return redirect(url_for("admissions.detail", admission_id=adm.id))
    return render_template("admissions/form.html", form=form, adm=None)


@bp.route("/<int:admission_id>")
@permission_required("admissions.view")
def detail(admission_id):
    adm = _get(admission_id)
    docs = StudentDocument.query.filter_by(admission_id=adm.id).order_by(StudentDocument.created_at.desc()).all()
    return render_template("admissions/detail.html", adm=adm, docs=docs, doc_types=DOC_TYPES)


@bp.route("/<int:admission_id>/edit", methods=["GET", "POST"])
@permission_required("admissions.edit")
def edit_admission(admission_id):
    adm = _get(admission_id)
    if adm.status != "pending":
        flash("Only pending applications can be edited. Approved students are edited from the Students page.", "warning")
        return redirect(url_for("admissions.detail", admission_id=adm.id))
    form = AdmissionForm(obj=adm)
    for name in ("branch_id", "session_id", "approve_now"):   # not editable here
        if name in form:
            del form[name]
    if form.validate_on_submit():
        data = svc.person_data(form)
        if _is_duplicate(adm.branch_id, data["full_name"], data["dob"], exclude_id=adm.id):
            form.full_name.errors.append("Another application with this name and date of birth exists.")
        else:
            photo = _save_photo(form)
            if not form.photo.errors:
                svc.update_admission(adm, data, photo)
                flash("Application updated.", "success")
                return redirect(url_for("admissions.detail", admission_id=adm.id))
    return render_template("admissions/form.html", form=form, adm=adm)


@bp.route("/<int:admission_id>/approve", methods=["POST"])
@permission_required("admissions.edit")
def approve(admission_id):
    adm = _get(admission_id)
    try:
        student = svc.approve_admission(adm, current_user)
    except (ValueError, RuntimeError) as e:
        flash(str(e), "danger")
        return redirect(url_for("admissions.detail", admission_id=adm.id))
    flash(f"Approved. Student ID {student.student_code}, admission no. {student.admission_no}.", "success")
    return redirect(url_for("students.detail", student_id=student.id))


@bp.route("/<int:admission_id>/reject", methods=["POST"])
@permission_required("admissions.edit")
def reject(admission_id):
    adm = _get(admission_id)
    try:
        svc.reject_admission(adm, current_user, request.form.get("reason"))
        flash("Application rejected.", "warning")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("admissions.detail", admission_id=adm.id))


@bp.route("/<int:admission_id>/documents", methods=["POST"])
@permission_required("admissions.edit")
def upload_document(admission_id):
    adm = _get(admission_id)
    doc_type = request.form.get("doc_type")
    f = request.files.get("file")
    if doc_type not in dict(DOC_TYPES) or not f or not f.filename:
        flash("Choose a document type and a file.", "danger")
    else:
        try:
            student_service.add_document(f, doc_type, current_user, admission=adm)
            flash("Document uploaded.", "success")
        except ValueError as e:
            flash(str(e), "danger")
    return redirect(url_for("admissions.detail", admission_id=adm.id))


@bp.route("/<int:admission_id>/documents/<int:doc_id>/delete", methods=["POST"])
@permission_required("admissions.edit")
def delete_document(admission_id, doc_id):
    adm = _get(admission_id)
    doc = db.get_or_404(StudentDocument, doc_id)
    if doc.admission_id != adm.id:
        abort(404)
    student_service.delete_document(doc)
    flash("Document deleted.", "success")
    return redirect(url_for("admissions.detail", admission_id=adm.id))


@bp.route("/<int:admission_id>/photo")
@permission_required("admissions.view")
def photo(admission_id):
    adm = _get(admission_id)
    if not adm.photo:
        abort(404)
    return send_private("students", adm.photo)
