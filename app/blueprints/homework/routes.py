from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from extensions import db
from app.models import Homework, CHECK_STATUSES
from app.services import homework_service as svc
from app.utils.decorators import role_required, permission_required
from app.utils.file_upload import send_private

bp = Blueprint("homework", __name__, url_prefix="/homework")
TEACHING = ("owner", "branch_admin", "teacher")


def guard(code):
    def deco(view):
        return role_required(*TEACHING)(permission_required(code)(view))
    return deco


def _hw(hw_id):
    hw = db.get_or_404(Homework, hw_id)
    if not svc.can_manage_batch(current_user, hw.batch):
        abort(403)
    return hw


def _parse_date(text):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


# ------------------------------------------------------------------ list
@bp.route("/")
@guard("homework.view")
def index():
    batch_id = request.args.get("batch", type=int)
    when = request.args.get("when", "")
    query = svc.staff_homework_query(current_user)
    if batch_id:
        query = query.filter(Homework.batch_id == batch_id)
    if when == "upcoming":
        query = query.filter(Homework.due_date >= svc.today())
    elif when == "past":
        query = query.filter(Homework.due_date < svc.today())
    page = query.order_by(Homework.due_date.desc(), Homework.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("homework/index.html", page=page, args=args, batch_id=batch_id, when=when,
                           batches=svc.manageable_batches(current_user), progress=svc.progress(page.items),
                           due_label=svc.due_label, can_post=bool(svc.manageable_batches(current_user)))


# ------------------------------------------------------------------ create / edit / delete
@bp.route("/new", methods=["GET", "POST"])
@guard("homework.create")
def new():
    batches = svc.manageable_batches(current_user)
    chosen = request.values.get("batch", type=int)
    if request.method == "POST":
        batch = next((b for b in batches if b.id == request.form.get("batch_id", type=int)), None)
        try:
            if batch is None:
                raise ValueError("Choose one of your batches.")
            hw = svc.create_homework(current_user, batch, request.form.get("title"), request.form.get("description"),
                                     _parse_date(request.form.get("due_date")), request.files.get("attachment"))
            flash("Homework given to the batch.", "success")
            return redirect(url_for("homework.detail", hw_id=hw.id))
        except ValueError as e:
            flash(str(e), "danger")
            chosen = request.form.get("batch_id", type=int)
    return render_template("homework/form.html", hw=None, batches=batches, chosen=chosen, form=request.form,
                           today=svc.today())


@bp.route("/<int:hw_id>/edit", methods=["GET", "POST"])
@guard("homework.edit")
def edit(hw_id):
    hw = _hw(hw_id)
    if request.method == "POST":
        try:
            svc.update_homework(hw, current_user, request.form.get("title"), request.form.get("description"),
                                _parse_date(request.form.get("due_date")), request.files.get("attachment"),
                                remove_file=bool(request.form.get("remove_attachment")))
            flash("Homework saved.", "success")
            return redirect(url_for("homework.detail", hw_id=hw.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("homework/form.html", hw=hw, batches=[], chosen=hw.batch_id, form=request.form,
                           today=svc.today())


@bp.route("/<int:hw_id>/delete", methods=["POST"])
@guard("homework.delete")
def delete(hw_id):
    hw = _hw(hw_id)
    try:
        svc.delete_homework(hw, current_user)
        flash("Homework deleted.", "success")
        return redirect(url_for("homework.index"))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("homework.detail", hw_id=hw.id))


# ------------------------------------------------------------------ one homework + checking sheet
@bp.route("/<int:hw_id>")
@guard("homework.view")
def detail(hw_id):
    hw = _hw(hw_id)
    checks = {c.student_id: c for c in hw.checks}
    students = svc.batch_students(hw.batch, checks.keys())
    label, css = svc.due_label(hw.due_date)
    return render_template("homework/detail.html", hw=hw, students=students, checks=checks, statuses=CHECK_STATUSES,
                           due=label, due_css=css, status_colors=svc.STATUS_COLORS,
                           can_check=current_user.has_permission("homework.edit"))


@bp.route("/<int:hw_id>/check", methods=["POST"])
@guard("homework.edit")
def check(hw_id):
    hw = _hw(hw_id)
    students = svc.batch_students(hw.batch, [c.student_id for c in hw.checks])
    cells = {s.id: (request.form.get(f"s_{s.id}"), request.form.get(f"r_{s.id}")) for s in students}
    try:
        saved, cleared = svc.save_checks(hw, cells, current_user)
        flash(f"Saved ({saved} changed).", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("homework.detail", hw_id=hw.id))


# ------------------------------------------------------------------ attachment (staff, enrolled students, parents)
@bp.route("/<int:hw_id>/file")
@permission_required("homework.view")
def file(hw_id):
    hw = db.get_or_404(Homework, hw_id)
    if not svc.can_view_batch(current_user, hw.batch, allow_parent=True):
        abort(403)
    if not hw.attachment or not svc.file_exists(svc.HW_FOLDER, hw.attachment):
        abort(404)
    return send_private(svc.HW_FOLDER, hw.attachment, download_name=hw.attachment_name)
