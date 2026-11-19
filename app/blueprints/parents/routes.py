from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from sqlalchemy import or_
from extensions import db
from app.models import Parent, StudentParent, Student, RELATIONS
from app.services import parent_service as svc
from app.services.branch_service import reset_user_password
from app.utils.branch_access import current_branch_id, ensure_branch_access
from app.utils.decorators import permission_required
from .forms import ParentForm

bp = Blueprint("parents", __name__, url_prefix="/parents")


def _visible(query):
    """Owner: every parent. Others: only parents having a child in their own branch."""
    bid = current_branch_id()
    if bid is None:
        return query
    ids = (db.session.query(StudentParent.parent_id).join(Student, Student.id == StudentParent.student_id)
           .filter(Student.branch_id == bid))
    return query.filter(Parent.id.in_(ids))


def _get(parent_id):
    parent = _visible(Parent.query).filter(Parent.id == parent_id).first()
    if parent is None:
        abort(404)
    return parent


def _children(parent):
    bid = current_branch_id()
    return [l for l in parent.links if bid is None or l.student.branch_id == bid]


@bp.route("/")
@permission_required("parents.view")
def index():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "active")
    query = _visible(Parent.query)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Parent.full_name.ilike(like), Parent.parent_code.ilike(like),
                                 Parent.phone.ilike(like)))
    if status in ("active", "inactive"):
        query = query.filter(Parent.status == status)
    page = query.order_by(Parent.full_name).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("parents/list.html", page=page, q=q, status=status, args=args)


@bp.route("/<int:parent_id>")
@permission_required("parents.view")
def detail(parent_id):
    parent = _get(parent_id)
    return render_template("parents/detail.html", parent=parent, children=_children(parent), relations=RELATIONS)


@bp.route("/<int:parent_id>/edit", methods=["GET", "POST"])
@permission_required("parents.edit")
def edit(parent_id):
    parent = _get(parent_id)
    form = ParentForm(obj=parent)
    if form.validate_on_submit():
        data = {k: ((getattr(form, k).data or "").strip() or None) for k in
                ("full_name", "phone", "email", "occupation", "address")}
        svc.update_parent(parent, data)
        flash("Parent details saved.", "success")
        return redirect(url_for("parents.detail", parent_id=parent.id))
    return render_template("parents/form.html", form=form, parent=parent)


@bp.route("/from-student/<int:student_id>", methods=["POST"])
@permission_required("parents.create")
def from_student(student_id):
    student = db.get_or_404(Student, student_id)
    ensure_branch_access(student.branch_id)
    try:
        parent, status = svc.link_from_student(student, request.form.get("relation"), current_user)
        if status == "created":
            flash(f"Parent {parent.full_name} ({parent.parent_code}) created and linked.", "success")
        elif status == "existing":
            flash(f"Linked to existing parent {parent.full_name} ({parent.parent_code}) - same phone number, "
                  "so siblings share one parent account.", "success")
        else:
            flash("This parent is already linked to the student.", "warning")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("students.detail", student_id=student.id))


@bp.route("/<int:parent_id>/link", methods=["POST"])
@permission_required("parents.edit")
def link(parent_id):
    parent = _get(parent_id)
    code = (request.form.get("student_code") or "").strip().upper()
    student = Student.query.filter_by(student_code=code).first()
    bid = current_branch_id()
    if not student or (bid is not None and student.branch_id != bid):
        flash("No student found with this Student ID in your branch.", "danger")
    else:
        try:
            svc.link_student(parent, student, request.form.get("relation"))
            flash(f"{student.full_name} linked.", "success")
        except ValueError as e:
            flash(str(e), "danger")
    return redirect(url_for("parents.detail", parent_id=parent.id))


@bp.route("/<int:parent_id>/unlink/<int:student_id>", methods=["POST"])
@permission_required("parents.edit")
def unlink(parent_id, student_id):
    parent = _get(parent_id)
    student = db.get_or_404(Student, student_id)
    ensure_branch_access(student.branch_id)
    svc.unlink_student(parent, student)
    flash(f"{student.full_name} unlinked.", "success")
    return redirect(url_for("parents.detail", parent_id=parent.id))


@bp.route("/<int:parent_id>/create-login", methods=["POST"])
@permission_required("parents.edit")
def create_login(parent_id):
    parent = _get(parent_id)
    try:
        user, temp = svc.create_parent_login(parent)
        flash("Login created. Share these details privately - they must change the password at first "
              f"sign in. Username: {user.username} | Temporary password: {temp}", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("parents.detail", parent_id=parent.id))


@bp.route("/<int:parent_id>/reset-password", methods=["POST"])
@permission_required("parents.edit")
def reset_password(parent_id):
    parent = _get(parent_id)
    if not parent.user:
        flash("No login yet.", "danger")
    else:
        temp = reset_user_password(parent.user)
        flash("Password reset. Share it privately - they must change it at next sign in. "
              f"Username: {parent.user.username} | Temporary password: {temp}", "success")
    return redirect(url_for("parents.detail", parent_id=parent.id))


@bp.route("/<int:parent_id>/status", methods=["POST"])
@permission_required("parents.edit")
def change_status(parent_id):
    parent = _get(parent_id)
    try:
        svc.set_status(parent, request.form.get("status"))
        flash(f"{parent.full_name} is now {parent.status}.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("parents.detail", parent_id=parent.id))
