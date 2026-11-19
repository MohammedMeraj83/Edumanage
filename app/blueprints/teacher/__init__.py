from flask import Blueprint, render_template
from flask_login import current_user
from app.models import Batch
from app.services import academic_service as svc
from app.services import attendance_service as att
from app.utils.date_utils import WEEKDAYS, local_now
from app.utils.decorators import role_required

bp = Blueprint("teacher", __name__, url_prefix="/teacher")


@bp.route("/dashboard")
@role_required("teacher")
def dashboard():
    me = svc.teacher_for_user(current_user)
    batches, rows, counts, pending_papers = [], [], {}, []
    day = local_now().date()
    if me:
        batches = Batch.query.filter_by(teacher_id=me.id, status="active").order_by(Batch.name).all()
        sessions = att.ensure_sessions(day, branch_id=me.branch_id, teacher_id=me.id)
        rows = [(s, *att.session_state(s), att.teacher_checkin_open(s)) for s in sessions]
        from app.services import exam_service
        pending_papers = exam_service.teacher_pending_papers(me)
        counts = svc.batch_counts([b.id for b in batches] + [s.batch_id for s in sessions])
    return render_template("teacher/dashboard.html", me=me, batches=batches, rows=rows, counts=counts, pending_papers=pending_papers,
                           today_name=WEEKDAYS[day.weekday()], schedule_text=svc.schedule_text)
