from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, login_required
from extensions import db
from app.models import LeaveRequest, Student, Parent, Branch
from app.services import leave_service as svc
from app.services.academic_service import teacher_for_user
from app.utils.branch_access import ensure_branch_access
from app.utils.decorators import role_required

bp = Blueprint("leave", __name__, url_prefix="/leave")
ADMIN_ROLES = ("owner", "branch_admin")


def _my_children():
    me = Parent.query.filter_by(user_id=current_user.id).first()
    return [l.student for l in me.links] if me else []


@bp.route("/")
@login_required
def index():
    role = current_user.role_name
    q = LeaveRequest.query
    children = []
    if role in ADMIN_ROLES:
        if role == "branch_admin":
            q = q.filter(LeaveRequest.branch_id == current_user.branch_id)
        elif request.args.get("branch", type=int):
            q = q.filter(LeaveRequest.branch_id == request.args.get("branch", type=int))
    elif role == "teacher":
        me = teacher_for_user(current_user)
        q = q.filter(LeaveRequest.teacher_id == (me.id if me else 0))
    elif role == "student":
        me = Student.query.filter_by(user_id=current_user.id).first()
        q = q.filter(LeaveRequest.student_id == (me.id if me else 0))
    elif role == "parent":
        children = _my_children()
        q = q.filter(LeaveRequest.student_id.in_([c.id for c in children] or [0]))
    else:
        abort(403)
    items = q.order_by(LeaveRequest.created_at.desc()).limit(100).all()
    items.sort(key=lambda r: r.status != "pending")            # pending first; newest first inside each group
    return render_template("leave/index.html", items=items, children=children, role=role, today=date.today(),
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [],
                           branch_id=request.args.get("branch", type=int))


@bp.route("/new", methods=["POST"])
@role_required("teacher", "student", "parent")
def new():
    role = current_user.role_name
    try:
        start, end = date.fromisoformat(request.form.get("from_date", "")), date.fromisoformat(request.form.get("to_date", ""))
        reason = (request.form.get("reason") or "").strip()
        if not reason:
            raise ValueError("Please write the reason.")
        if role == "teacher":
            person, kind = teacher_for_user(current_user), "teacher"
        elif role == "student":
            person, kind = Student.query.filter_by(user_id=current_user.id).first(), "student"
        else:
            kids = {c.id: c for c in _my_children()}
            person, kind = kids.get(request.form.get("student_id", type=int)), "student"
            if person is None:
                raise ValueError("Choose which child the leave is for.")
        if person is None:
            raise ValueError("Your profile is not linked yet. Ask your branch admin.")
        svc.apply_leave(kind, person, current_user, start, end, reason)
        flash("Leave request sent. You will see the decision here.", "success")
    except ValueError as e:
        flash(str(e) or "Check the dates.", "danger")
    return redirect(url_for("leave.index"))


@bp.route("/<int:leave_id>/decide", methods=["POST"])
@role_required(*ADMIN_ROLES)
def decide(leave_id):
    req = db.get_or_404(LeaveRequest, leave_id)
    ensure_branch_access(req.branch_id)
    try:
        svc.decide(req, request.form.get("action") == "approve", request.form.get("note"), current_user)
        flash(f"Leave {req.status}.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("leave.index"))


@bp.route("/<int:leave_id>/cancel", methods=["POST"])
@login_required
def cancel(leave_id):
    req = db.get_or_404(LeaveRequest, leave_id)
    try:
        svc.cancel(req, current_user)
        flash("Request withdrawn.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("leave.index"))
