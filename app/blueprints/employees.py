"""One factory builds both the Teachers and the Staff management modules."""
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, login_required
from sqlalchemy import or_
from extensions import db
from app.models import Branch, EmployeeDocument, EMPLOYEE_DOC_TYPES, EMPLOYEE_STATUSES
from app.services import employee_service as svc
from app.services.branch_service import reset_user_password
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import permission_required
from app.utils.file_upload import save_image, send_private
from app.blueprints.employee_forms import TeacherForm, StaffForm

FORMS = {"teacher": TeacherForm, "staff": StaffForm}


def make_employee_blueprint(name, url_prefix, kind):
    cfg = svc.KINDS[kind]
    Model, perm, label = cfg["model"], cfg["perm"], cfg["label"]
    bp = Blueprint(name, __name__, url_prefix=url_prefix)

    def ctx(**extra):
        return dict(kind=kind, cfg=cfg, **extra)

    def _get(obj_id):
        obj = db.get_or_404(Model, obj_id)
        ensure_branch_access(obj.branch_id)
        return obj

    def _prepare(form, editing):
        if current_user.is_owner:
            form.branch_id.choices = [(b.id, f"{b.name} ({b.code})")
                                      for b in Branch.query.filter_by(is_active=True).order_by(Branch.name)]
        else:
            del form.branch_id
        if editing:
            del form.create_login

    def _photo(form):
        f = form.photo.data
        if f is not None and getattr(f, "filename", ""):
            try:
                return save_image(f, "employees", max_px=500)
            except ValueError as e:
                form.photo.errors.append(str(e))
        return None

    def _phone_taken(phone, exclude_id=None):
        q = Model.query.filter(Model.phone == phone, Model.status != "left")
        if exclude_id:
            q = q.filter(Model.id != exclude_id)
        return q.first() is not None

    @bp.route("/")
    @permission_required(f"{perm}.view")
    def index():
        q = (request.args.get("q") or "").strip()
        status = request.args.get("status", "active")
        branch_id = request.args.get("branch", type=int)
        query = scope_to_branch(Model.query, Model)
        if current_user.is_owner and branch_id:
            query = query.filter(Model.branch_id == branch_id)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Model.full_name.ilike(like), Model.employee_code.ilike(like),
                                     Model.phone.ilike(like)))
        if status in EMPLOYEE_STATUSES:
            query = query.filter(Model.status == status)
        page = query.order_by(Model.full_name).paginate(
            page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
        args = {k: v for k, v in request.args.items() if k != "page" and v}
        branches = Branch.query.order_by(Branch.name).all() if current_user.is_owner else []
        return render_template("employees/list.html", **ctx(
            page=page, q=q, status=status, branch_id=branch_id, branches=branches, args=args,
            statuses=EMPLOYEE_STATUSES))

    @bp.route("/new", methods=["GET", "POST"])
    @permission_required(f"{perm}.create")
    def new():
        form = FORMS[kind]()
        _prepare(form, editing=False)
        if form.validate_on_submit():
            branch_id = form.branch_id.data if current_user.is_owner else current_user.branch_id
            data = svc.form_data(form, kind)
            if _phone_taken(data["phone"]):
                form.phone.errors.append("This phone number is already registered.")
            else:
                photo = _photo(form)
                if not form.photo.errors:
                    obj = svc.create_employee(kind, data, branch_id, photo)
                    msg = f"{label} added. ID {obj.employee_code}."
                    if form.create_login.data:
                        try:
                            user, temp = svc.create_login(kind, obj)
                            msg += (" Share these sign-in details privately - they must change the password at "
                                    f"first sign in. Username: {user.username} | Temporary password: {temp}")
                        except ValueError as e:
                            msg += f" Login not created: {e}"
                    flash(msg, "success")
                    return redirect(url_for(f"{name}.detail", obj_id=obj.id))
        return render_template("employees/form.html", **ctx(form=form, obj=None))

    @bp.route("/<int:obj_id>")
    @permission_required(f"{perm}.view")
    def detail(obj_id):
        obj = _get(obj_id)
        docs = (EmployeeDocument.query.filter(getattr(EmployeeDocument, cfg["doc_fk"]) == obj.id)
                .order_by(EmployeeDocument.created_at.desc()).all())
        return render_template("employees/detail.html", **ctx(
            obj=obj, docs=docs, doc_types=EMPLOYEE_DOC_TYPES, login_ok=svc.can_have_login(kind, obj)))

    @bp.route("/<int:obj_id>/edit", methods=["GET", "POST"])
    @permission_required(f"{perm}.edit")
    def edit(obj_id):
        obj = _get(obj_id)
        form = FORMS[kind](obj=obj)
        _prepare(form, editing=True)
        if form.validate_on_submit():
            data = svc.form_data(form, kind)
            if _phone_taken(data["phone"], exclude_id=obj.id):
                form.phone.errors.append("This phone number is already registered.")
            else:
                photo = _photo(form)
                if not form.photo.errors:
                    new_branch = form.branch_id.data if current_user.is_owner else None
                    svc.update_employee(kind, obj, data, photo, new_branch)
                    flash("Details saved.", "success")
                    return redirect(url_for(f"{name}.detail", obj_id=obj.id))
        return render_template("employees/form.html", **ctx(form=form, obj=obj))

    @bp.route("/<int:obj_id>/status", methods=["POST"])
    @permission_required(f"{perm}.edit")
    def change_status(obj_id):
        obj = _get(obj_id)
        try:
            svc.set_status(kind, obj, request.form.get("status"))
            flash(f"{obj.full_name} is now {obj.status}.", "success")
        except ValueError as e:
            flash(str(e), "danger")
        return redirect(url_for(f"{name}.detail", obj_id=obj.id))

    @bp.route("/<int:obj_id>/create-login", methods=["POST"])
    @permission_required(f"{perm}.edit")
    def create_login(obj_id):
        obj = _get(obj_id)
        try:
            user, temp = svc.create_login(kind, obj)
            flash("Login created. Share these details privately - they must change the password at first "
                  f"sign in. Username: {user.username} | Temporary password: {temp}", "success")
        except ValueError as e:
            flash(str(e), "danger")
        return redirect(url_for(f"{name}.detail", obj_id=obj.id))

    @bp.route("/<int:obj_id>/reset-password", methods=["POST"])
    @permission_required(f"{perm}.edit")
    def reset_password(obj_id):
        obj = _get(obj_id)
        if not obj.user:
            flash("No login yet.", "danger")
        else:
            temp = reset_user_password(obj.user)
            flash("Password reset. Share it privately - they must change it at next sign in. "
                  f"Username: {obj.user.username} | Temporary password: {temp}", "success")
        return redirect(url_for(f"{name}.detail", obj_id=obj.id))

    @bp.route("/<int:obj_id>/documents", methods=["POST"])
    @permission_required(f"{perm}.edit")
    def upload_document(obj_id):
        obj = _get(obj_id)
        doc_type, f = request.form.get("doc_type"), request.files.get("file")
        if doc_type not in dict(EMPLOYEE_DOC_TYPES) or not f or not f.filename:
            flash("Choose a document type and a file.", "danger")
        else:
            try:
                svc.add_document(kind, obj, f, doc_type, current_user)
                flash("Document uploaded.", "success")
            except ValueError as e:
                flash(str(e), "danger")
        return redirect(url_for(f"{name}.detail", obj_id=obj.id))

    @bp.route("/<int:obj_id>/documents/<int:doc_id>/delete", methods=["POST"])
    @permission_required(f"{perm}.edit")
    def delete_document(obj_id, doc_id):
        obj = _get(obj_id)
        doc = db.get_or_404(EmployeeDocument, doc_id)
        if getattr(doc, cfg["doc_fk"]) != obj.id:
            abort(404)
        svc.delete_document(doc)
        flash("Document deleted.", "success")
        return redirect(url_for(f"{name}.detail", obj_id=obj.id))

    @bp.route("/<int:obj_id>/photo")
    @permission_required(f"{perm}.view")
    def photo(obj_id):
        obj = _get(obj_id)
        if not obj.photo:
            abort(404)
        return send_private("employees", obj.photo)

    @bp.route("/files/<int:doc_id>")
    @login_required
    def document_file(doc_id):
        doc = db.get_or_404(EmployeeDocument, doc_id)
        owner_id = getattr(doc, cfg["doc_fk"])
        if not owner_id:
            abort(404)
        if not current_user.has_permission(f"{perm}.view"):
            abort(403)
        ensure_branch_access(db.session.get(Model, owner_id).branch_id)
        return send_private("documents", doc.filename, download_name=doc.original_name)

    return bp
