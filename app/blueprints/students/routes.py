from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, login_required
from sqlalchemy import or_
from extensions import db
from app.models import (Student, StudentDocument, Admission, Branch, DOC_TYPES, STUDENT_STATUSES)
from app.services import student_service as svc
from app.services.admission_service import person_data
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import permission_required
from app.utils.file_upload import save_image, send_private
from .forms import PersonForm

bp = Blueprint("students", __name__, url_prefix="/students")


def _get(student_id):
    s = db.get_or_404(Student, student_id)
    ensure_branch_access(s.branch_id)
    return s


@bp.route("/")
@permission_required("students.view")
def list_students():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "active")
    class_name = (request.args.get("class_name") or "").strip()
    branch_id = request.args.get("branch", type=int)

    base = scope_to_branch(Student.query, Student)
    classes = [c for (c,) in scope_to_branch(db.session.query(Student.class_name), Student)
               .distinct().order_by(Student.class_name).all()]
    query = base
    if current_user.is_owner and branch_id:
        query = query.filter(Student.branch_id == branch_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Student.full_name.ilike(like), Student.student_code.ilike(like),
                                 Student.admission_no.ilike(like), Student.phone.ilike(like),
                                 Student.guardian_phone.ilike(like)))
    if status in STUDENT_STATUSES:
        query = query.filter(Student.status == status)
    if class_name:
        query = query.filter(Student.class_name == class_name)
    page = query.order_by(Student.full_name).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    branches = Branch.query.order_by(Branch.name).all() if current_user.is_owner else []
    return render_template("students/list.html", page=page, q=q, status=status, class_name=class_name,
                           classes=classes, branch_id=branch_id, branches=branches, args=args,
                           statuses=STUDENT_STATUSES)


@bp.route("/<int:student_id>")
@permission_required("students.view")
def detail(student_id):
    s = _get(student_id)
    docs = StudentDocument.query.filter_by(student_id=s.id).order_by(StudentDocument.created_at.desc()).all()
    other_branches = (Branch.query.filter(Branch.is_active.is_(True), Branch.id != s.branch_id)
                      .order_by(Branch.name).all() if current_user.is_owner else [])
    enrollments, open_batches = [], []
    if current_user.has_permission("batches.view"):
        from app.models import Batch, BatchStudent
        from app.services.academic_service import schedule_text, seats_used
        enrollments = (BatchStudent.query.filter_by(student_id=s.id, status="active").all())
        mine = {e.batch_id for e in enrollments}
        if s.status == "active":
            open_batches = [b for b in Batch.query.filter_by(branch_id=s.branch_id, status="active")
                            .order_by(Batch.name).all() if b.id not in mine and seats_used(b) < b.capacity]
    return render_template("students/detail.html", s=s, docs=docs, doc_types=DOC_TYPES,
                           other_branches=other_branches, enrollments=enrollments, open_batches=open_batches)


@bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
@permission_required("students.edit")
def edit_student(student_id):
    s = _get(student_id)
    form = PersonForm(obj=s)
    if form.validate_on_submit():
        photo = None
        f = form.photo.data
        if f is not None and getattr(f, "filename", ""):
            try:
                photo = save_image(f, "students", max_px=500)
            except ValueError as e:
                form.photo.errors.append(str(e))
        if not form.photo.errors:
            svc.update_student(s, person_data(form), photo)
            flash("Student details saved.", "success")
            return redirect(url_for("students.detail", student_id=s.id))
    return render_template("students/form.html", form=form, s=s)


@bp.route("/<int:student_id>/status", methods=["POST"])
@permission_required("students.edit")
def change_status(student_id):
    s = _get(student_id)
    try:
        svc.set_status(s, request.form.get("status"))
        flash(f"{s.full_name} is now {s.status}.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("students.detail", student_id=s.id))


@bp.route("/<int:student_id>/transfer", methods=["POST"])
@permission_required("branches.edit")        # owner only
def transfer(student_id):
    s = _get(student_id)
    to_branch = db.session.get(Branch, request.form.get("to_branch_id", type=int) or 0)
    if not to_branch:
        flash("Choose the branch to move the student to.", "danger")
    else:
        try:
            svc.transfer_student(s, to_branch, request.form.get("reason"), current_user)
            flash(f"{s.full_name} moved to {to_branch.name}. Student ID {s.student_code} is unchanged.", "success")
        except ValueError as e:
            flash(str(e), "danger")
    return redirect(url_for("students.detail", student_id=s.id))


@bp.route("/<int:student_id>/create-login", methods=["POST"])
@permission_required("students.edit")
def create_login(student_id):
    s = _get(student_id)
    try:
        user, temp = svc.create_student_login(s)
        flash("Login created. Share these details privately - the student must change the password at first "
              f"sign in. Username: {user.username} | Temporary password: {temp}", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("students.detail", student_id=s.id))


@bp.route("/<int:student_id>/reset-password", methods=["POST"])
@permission_required("students.edit")
def reset_login_password(student_id):
    from app.services.branch_service import reset_user_password
    s = _get(student_id)
    if not s.user:
        flash("This student has no login yet.", "danger")
    else:
        temp = reset_user_password(s.user)
        flash("Password reset. Share it privately - the student must change it at next sign in. "
              f"Username: {s.user.username} | Temporary password: {temp}", "success")
    return redirect(url_for("students.detail", student_id=s.id))


@bp.route("/<int:student_id>/documents", methods=["POST"])
@permission_required("students.edit")
def upload_document(student_id):
    s = _get(student_id)
    doc_type, f = request.form.get("doc_type"), request.files.get("file")
    if doc_type not in dict(DOC_TYPES) or not f or not f.filename:
        flash("Choose a document type and a file.", "danger")
    else:
        try:
            svc.add_document(f, doc_type, current_user, student=s)
            flash("Document uploaded.", "success")
        except ValueError as e:
            flash(str(e), "danger")
    return redirect(url_for("students.detail", student_id=s.id))


@bp.route("/<int:student_id>/documents/<int:doc_id>/delete", methods=["POST"])
@permission_required("students.edit")
def delete_document(student_id, doc_id):
    s = _get(student_id)
    doc = db.get_or_404(StudentDocument, doc_id)
    if doc.student_id != s.id:
        abort(404)
    svc.delete_document(doc)
    flash("Document deleted.", "success")
    return redirect(url_for("students.detail", student_id=s.id))


@bp.route("/<int:student_id>/photo")
@permission_required("students.view")
def photo(student_id):
    s = _get(student_id)
    if not s.photo:
        abort(404)
    return send_private("students", s.photo)


@bp.route("/files/<int:doc_id>")
@login_required
def document_file(doc_id):
    """Private document download. Checks permission AND branch every time."""
    doc = db.get_or_404(StudentDocument, doc_id)
    if doc.student_id:
        need, branch_id = "students.view", db.session.get(Student, doc.student_id).branch_id
    else:
        need, branch_id = "admissions.view", db.session.get(Admission, doc.admission_id).branch_id
    if not current_user.has_permission(need):
        abort(403)
    ensure_branch_access(branch_id)
    return send_private("documents", doc.filename, download_name=doc.original_name)
