from flask import Blueprint, render_template, redirect, url_for, flash, request
from sqlalchemy import func, or_
from extensions import db
from app.models import Branch, User, Role, BRANCH_ADMIN
from app.services.audit_service import log_action
from app.services.branch_service import create_branch, create_branch_admin, reset_user_password
from app.utils.decorators import permission_required
from .forms import BranchForm, BranchAdminForm

bp = Blueprint("branches", __name__, url_prefix="/owner/branches")

FIELDS = ["name", "phone", "email", "address", "city", "state", "pincode"]


def _admin_of(branch_id, user_id):
    user = db.get_or_404(User, user_id)
    if user.branch_id != branch_id or user.role.name != BRANCH_ADMIN:
        from flask import abort
        abort(404)
    return user


@bp.route("/")
@permission_required("branches.view")
def list_branches():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "all")
    query = Branch.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Branch.name.ilike(like), Branch.code.ilike(like), Branch.city.ilike(like)))
    if status == "active":
        query = query.filter(Branch.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(Branch.is_active.is_(False))
    branches = query.order_by(Branch.is_main.desc(), Branch.name).all()

    rows = (db.session.query(User.branch_id, Role.name, func.count(User.id))
            .join(Role, User.role_id == Role.id)
            .filter(User.is_active_user.is_(True), User.branch_id.isnot(None))
            .group_by(User.branch_id, Role.name).all())
    admins, users = {}, {}
    for branch_id, role_name, n in rows:
        users[branch_id] = users.get(branch_id, 0) + n
        if role_name == BRANCH_ADMIN:
            admins[branch_id] = n
    return render_template("branches/list.html", branches=branches, q=q, status=status, admins=admins, users=users)


@bp.route("/new", methods=["GET", "POST"])
@permission_required("branches.create")
def new_branch():
    form = BranchForm()
    if form.validate_on_submit():
        data = {k: (getattr(form, k).data or None) for k in FIELDS}
        data["name"] = form.name.data.strip()
        data["code"] = form.code.data.strip()
        branch = create_branch(data)
        flash(f"Branch {branch.name} created. Now add its Branch Admin.", "success")
        return redirect(url_for("branches.detail", branch_id=branch.id))
    return render_template("branches/form.html", form=form, branch=None)


@bp.route("/<int:branch_id>")
@permission_required("branches.view")
def detail(branch_id):
    branch = db.get_or_404(Branch, branch_id)
    admins = (User.query.join(Role, User.role_id == Role.id)
              .filter(User.branch_id == branch.id, Role.name == BRANCH_ADMIN)
              .order_by(User.full_name).all())
    role_counts = dict(db.session.query(Role.display_name, func.count(User.id))
                       .join(User, User.role_id == Role.id)
                       .filter(User.branch_id == branch.id, User.is_active_user.is_(True), Role.name != BRANCH_ADMIN)
                       .group_by(Role.display_name).all())
    return render_template("branches/detail.html", branch=branch, admins=admins, role_counts=role_counts)


@bp.route("/<int:branch_id>/edit", methods=["GET", "POST"])
@permission_required("branches.edit")
def edit_branch(branch_id):
    branch = db.get_or_404(Branch, branch_id)
    form = BranchForm(obj=branch)
    del form.code  # the code is used in admission/receipt numbers, so it never changes
    if form.validate_on_submit():
        for k in FIELDS:
            setattr(branch, k, (getattr(form, k).data or None))
        branch.name = form.name.data.strip()
        log_action("update", "branches", branch.id, f"Updated branch {branch.code}")
        db.session.commit()
        flash("Branch details saved.", "success")
        return redirect(url_for("branches.detail", branch_id=branch.id))
    return render_template("branches/form.html", form=form, branch=branch)


@bp.route("/<int:branch_id>/toggle", methods=["POST"])
@permission_required("branches.edit")
def toggle_branch(branch_id):
    branch = db.get_or_404(Branch, branch_id)
    if branch.is_main and branch.is_active:
        flash("The main branch cannot be deactivated.", "danger")
        return redirect(url_for("branches.detail", branch_id=branch.id))
    branch.is_active = not branch.is_active
    log_action("activate" if branch.is_active else "deactivate", "branches", branch.id, branch.code)
    db.session.commit()
    if branch.is_active:
        flash(f"{branch.name} is active again.", "success")
    else:
        flash(f"{branch.name} is deactivated. Its users can no longer sign in.", "warning")
    return redirect(url_for("branches.detail", branch_id=branch.id))


@bp.route("/<int:branch_id>/admins/new", methods=["GET", "POST"])
@permission_required("users.create")
def new_admin(branch_id):
    branch = db.get_or_404(Branch, branch_id)
    if not branch.is_active:
        flash("Activate the branch before adding an admin.", "warning")
        return redirect(url_for("branches.detail", branch_id=branch.id))
    form = BranchAdminForm()
    if form.validate_on_submit():
        user, temp = create_branch_admin(branch, {
            "full_name": form.full_name.data.strip(), "username": form.username.data.strip(),
            "email": form.email.data.strip(), "phone": form.phone.data})
        flash("Admin created. Share these details privately - they must change the password at first sign in. "
              f"Username: {user.username} | Temporary password: {temp}", "success")
        return redirect(url_for("branches.detail", branch_id=branch.id))
    return render_template("branches/admin_form.html", form=form, branch=branch)


@bp.route("/<int:branch_id>/admins/<int:user_id>/toggle", methods=["POST"])
@permission_required("users.edit")
def toggle_admin(branch_id, user_id):
    user = _admin_of(branch_id, user_id)
    user.is_active_user = not user.is_active_user
    log_action("activate" if user.is_active_user else "deactivate", "users", user.id, user.username)
    db.session.commit()
    flash(f"{user.full_name} is now {'active' if user.is_active_user else 'disabled'}.", "success")
    return redirect(url_for("branches.detail", branch_id=branch_id))


@bp.route("/<int:branch_id>/admins/<int:user_id>/reset-password", methods=["POST"])
@permission_required("users.edit")
def reset_admin_password(branch_id, user_id):
    user = _admin_of(branch_id, user_id)
    temp = reset_user_password(user)
    flash("Password reset. Share it privately - they must change it at next sign in. "
          f"Username: {user.username} | Temporary password: {temp}", "success")
    return redirect(url_for("branches.detail", branch_id=branch_id))
