from flask import Blueprint, render_template, request, abort
from flask_login import current_user
from extensions import db
from app.models import TimetableSlot, Batch, Teacher, Room, Branch
from app.services import academic_service as svc
from app.utils.branch_access import scope_to_branch
from app.utils.date_utils import WEEKDAYS, local_now
from app.utils.decorators import permission_required

bp = Blueprint("timetable", __name__, url_prefix="/timetable")


@bp.route("/")
@permission_required("timetable.view")
def index():
    if current_user.role_name in ("student", "parent"):
        abort(403)
    branch_id = request.args.get("branch", type=int)
    teacher_id = request.args.get("teacher", type=int)
    room_id = request.args.get("room", type=int)
    day = request.args.get("day", type=int)

    q = (TimetableSlot.query.join(Batch, Batch.id == TimetableSlot.batch_id).filter(Batch.status == "active"))
    q = scope_to_branch(q, Batch)
    if current_user.is_owner and branch_id:
        q = q.filter(Batch.branch_id == branch_id)
    if current_user.role_name == "teacher":
        me = svc.teacher_for_user(current_user)
        teacher_id = me.id if me else 0
    if day is not None and 0 <= day <= 6:
        q = q.filter(TimetableSlot.weekday == day)
    slots = q.order_by(TimetableSlot.weekday, TimetableSlot.start_time).all()
    if teacher_id is not None:
        slots = [s for s in slots if (s.teacher_id or s.batch.teacher_id) == teacher_id]
    if room_id:
        slots = [s for s in slots if (s.room_id or s.batch.room_id) == room_id]

    by_day = {d: [] for d in range(7)}
    for s in slots:
        by_day[s.weekday].append(s)
    counts = svc.batch_counts(list({s.batch_id for s in slots}))

    scope = Branch.query.filter_by(id=branch_id).first() if branch_id else None
    teachers_q = scope_to_branch(Teacher.query.filter_by(status="active"), Teacher)
    rooms_q = scope_to_branch(Room.query.filter_by(is_active=True), Room)
    if current_user.is_owner and branch_id:
        teachers_q = teachers_q.filter(Teacher.branch_id == branch_id)
        rooms_q = rooms_q.filter(Room.branch_id == branch_id)
    return render_template(
        "timetable/index.html", by_day=by_day, counts=counts, weekdays=WEEKDAYS, today=local_now().weekday(),
        teachers=teachers_q.order_by(Teacher.full_name).all(), rooms=rooms_q.order_by(Room.name).all(),
        branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [],
        sel={"branch": branch_id, "teacher": teacher_id, "room": room_id, "day": day},
        is_teacher=current_user.role_name == "teacher", total=len(slots))
