from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from extensions import db
from app.models import StudyMaterial, MATERIAL_KINDS
from app.services import homework_service as svc
from app.utils.decorators import role_required, permission_required
from app.utils.file_upload import send_private

bp = Blueprint("materials", __name__, url_prefix="/materials")
TEACHING = ("owner", "branch_admin", "teacher")


def guard(code):
    def deco(view):
        return role_required(*TEACHING)(permission_required(code)(view))
    return deco


def _material(mid):
    m = db.get_or_404(StudyMaterial, mid)
    if not svc.can_manage_batch(current_user, m.batch):
        abort(403)
    return m


@bp.route("/")
@guard("materials.view")
def index():
    batch_id = request.args.get("batch", type=int)
    kind = request.args.get("kind", "")
    q = request.args.get("q", "").strip()
    query = svc.staff_material_query(current_user)
    if batch_id:
        query = query.filter(StudyMaterial.batch_id == batch_id)
    if kind in dict(MATERIAL_KINDS):
        query = query.filter(StudyMaterial.kind == kind)
    if q:
        query = query.filter(StudyMaterial.title.ilike(f"%{q}%"))
    page = query.order_by(StudyMaterial.created_at.desc(), StudyMaterial.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    batches = svc.manageable_batches(current_user)
    return render_template("materials/index.html", page=page, args=args, batch_id=batch_id, kind=kind, q=q,
                           batches=batches, kinds=MATERIAL_KINDS, human_size=svc.human_size, can_post=bool(batches))


@bp.route("/new", methods=["GET", "POST"])
@guard("materials.create")
def new():
    batches = svc.manageable_batches(current_user)
    chosen = request.values.get("batch", type=int)
    if request.method == "POST":
        batch = next((b for b in batches if b.id == request.form.get("batch_id", type=int)), None)
        try:
            if batch is None:
                raise ValueError("Choose one of your batches.")
            svc.create_material(current_user, batch, request.form.get("title"), request.form.get("description"),
                                request.form.get("kind", "file"), request.files.get("file"), request.form.get("url"))
            flash("Shared with the batch.", "success")
            return redirect(url_for("materials.index", batch=batch.id))
        except ValueError as e:
            flash(str(e), "danger")
            chosen = request.form.get("batch_id", type=int)
    return render_template("materials/form.html", m=None, batches=batches, chosen=chosen, form=request.form,
                           kinds=MATERIAL_KINDS)


@bp.route("/<int:mid>/edit", methods=["GET", "POST"])
@guard("materials.edit")
def edit(mid):
    m = _material(mid)
    if request.method == "POST":
        try:
            svc.update_material(m, current_user, request.form.get("title"), request.form.get("description"),
                                request.form.get("url"), request.files.get("file"))
            flash("Saved.", "success")
            return redirect(url_for("materials.index", batch=m.batch_id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("materials/form.html", m=m, batches=[], chosen=m.batch_id, form=request.form,
                           kinds=MATERIAL_KINDS)


@bp.route("/<int:mid>/delete", methods=["POST"])
@guard("materials.delete")
def delete(mid):
    m = _material(mid)
    batch_id = m.batch_id
    try:
        svc.delete_material(m, current_user)
        flash("Removed.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("materials.index", batch=batch_id))


@bp.route("/<int:mid>/file")
@permission_required("materials.view")
def file(mid):
    m = db.get_or_404(StudyMaterial, mid)
    if not svc.can_view_batch(current_user, m.batch, allow_parent=False):
        abort(403)
    if m.kind != "file" or not m.filename or not svc.file_exists(svc.MATERIAL_FOLDER, m.filename):
        abort(404)
    return send_private(svc.MATERIAL_FOLDER, m.filename, download_name=m.original_name)
