from flask import Blueprint, render_template
from flask_login import current_user
from app.models import Student, Teacher, Staff, Admission, Batch, BranchGeo
from app.services import attendance_service as att
from app.utils.date_utils import local_now
from app.utils.decorators import role_required

bp = Blueprint("branch_admin", __name__, url_prefix="/branch-admin")


@bp.route("/dashboard")
@role_required("branch_admin")
def dashboard():
    bid = current_user.branch_id
    sessions = att.ensure_sessions(local_now().date(), branch_id=bid)
    tally = {}
    for s in sessions:
        key = att.session_state(s)[0]
        tally[key] = tally.get(key, 0) + 1
    stats = {
        "students": Student.query.filter_by(branch_id=bid, status="active").count(),
        "teachers": Teacher.query.filter_by(branch_id=bid, status="active").count(),
        "staff": Staff.query.filter_by(branch_id=bid, status="active").count(),
        "pending": Admission.query.filter_by(branch_id=bid, status="pending").count(),
        "batches": Batch.query.filter_by(branch_id=bid, status="active").count(),
        "today": len(sessions),
        "running": tally.get("running", 0),
        "problems": tally.get("late", 0) + tally.get("missed", 0),
    }
    return render_template("branch_admin/dashboard.html", stats=stats,
                           geo_missing=BranchGeo.query.filter_by(branch_id=bid).first() is None)
