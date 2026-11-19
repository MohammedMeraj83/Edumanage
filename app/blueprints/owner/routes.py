from flask import Blueprint, render_template
from sqlalchemy import func
from extensions import db
from app.models import (Branch, User, Role, AcademicSession, AuditLog, BRANCH_ADMIN,
                        Student, Teacher, Staff, Parent, Batch)
from app.utils.decorators import role_required

bp = Blueprint("owner", __name__, url_prefix="/owner")


@bp.route("/dashboard")
@role_required("owner")
def dashboard():
    branches = Branch.query.order_by(Branch.is_main.desc(), Branch.name).all()
    rows = (db.session.query(User.branch_id, Role.name, func.count(User.id))
            .join(Role, User.role_id == Role.id)
            .filter(User.is_active_user.is_(True), User.branch_id.isnot(None))
            .group_by(User.branch_id, Role.name).all())
    admins, users = {}, {}
    for branch_id, role_name, n in rows:
        users[branch_id] = users.get(branch_id, 0) + n
        if role_name == BRANCH_ADMIN:
            admins[branch_id] = n

    # Single round-trip aggregation for dashboard stats
    counts = db.session.query(
        db.select(func.count(User.id)).filter(User.is_active_user.is_(True)).scalar_subquery(),
        db.select(func.count(Student.id)).filter(Student.status == "active").scalar_subquery(),
        db.select(func.count(Teacher.id)).filter(Teacher.status == "active").scalar_subquery(),
        db.select(func.count(Staff.id)).filter(Staff.status == "active").scalar_subquery(),
        db.select(func.count(Parent.id)).filter(Parent.status == "active").scalar_subquery(),
        db.select(func.count(Batch.id)).filter(Batch.status == "active").scalar_subquery(),
    ).first()

    stats = {
        "branches": sum(1 for b in branches if b.is_active),
        "branches_total": len(branches),
        "users": counts[0] if counts else 0,
        "admins": sum(admins.values()),
        "students": counts[1] if counts else 0,
        "teachers": counts[2] if counts else 0,
        "staff": counts[3] if counts else 0,
        "parents": counts[4] if counts else 0,
        "batches": counts[5] if counts else 0,
    }
    return render_template(
        "owner/dashboard.html", stats=stats, branches=branches, admins=admins, users=users,
        session=AcademicSession.query.filter_by(is_current=True).first(),
        activity=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all(),
    )
