import math
import secrets
from datetime import datetime, date, timedelta
from flask import current_app
from sqlalchemy import func, case, distinct
from sqlalchemy.exc import IntegrityError
from extensions import db
from app.models import (BranchGeo, LectureSession, AttendanceRecord, TimetableSlot, Batch, BatchStudent, Student,
                        LeaveRequest, ATTENDANCE_STATUSES)
from app.services.audit_service import log_action
from app.utils.date_utils import local_to_utc


def rule(key):
    return current_app.config["ATTENDANCE_RULES"][key]


def _now(now=None):
    return now or datetime.utcnow()


# ------------------------------------------------------------------ location
def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_position(lat, lng, accuracy):
    try:
        lat, lng = float(lat), float(lng)
        accuracy = float(accuracy) if accuracy not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("Location was not received. Allow location access and try again.")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Location was not received. Allow location access and try again.")
    return lat, lng, accuracy


def verify_location(branch_id, lat, lng, accuracy):
    """Returns the distance (m) from the branch, or raises ValueError. Used for teachers AND students."""
    lat, lng, accuracy = parse_position(lat, lng, accuracy)
    geo = BranchGeo.query.filter_by(branch_id=branch_id).first()
    if not geo:
        raise ValueError("This branch's location is not set yet. Ask your branch admin to set it.")
    if accuracy is None or accuracy > rule("max_accuracy_m"):
        raise ValueError(f"Your location is not accurate enough (needs {rule('max_accuracy_m')} m or better). "
                         "Turn on GPS / precise location and try again outside any basement or thick wall.")
    dist = int(round(haversine_m(lat, lng, geo.latitude, geo.longitude)))
    if dist > geo.radius_m:
        raise ValueError(f"You are about {dist} m from the tuition. You must be within {geo.radius_m} m.")
    return dist


def save_branch_geo(branch_id, lat, lng, radius, user):
    lat, lng, _ = parse_position(lat, lng, None)
    radius = int(radius)
    if not 30 <= radius <= 1000:
        raise ValueError("Radius must be between 30 and 1000 metres.")
    geo = BranchGeo.query.filter_by(branch_id=branch_id).first()
    if geo is None:
        geo = BranchGeo(branch_id=branch_id, qr_token=secrets.token_urlsafe(16))
        db.session.add(geo)
    geo.latitude, geo.longitude, geo.radius_m, geo.updated_by = lat, lng, radius, user.id
    log_action("set_location", "branch_geo", branch_id, f"Branch location set ({radius} m radius)", user=user)
    db.session.commit()
    return geo


def regenerate_qr(geo, user):
    geo.qr_token = secrets.token_urlsafe(16)
    log_action("qr_regenerate", "branch_geo", geo.branch_id, "Branch QR code replaced", user=user)
    db.session.commit()


# ------------------------------------------------------------------ sessions
def ensure_sessions(day, branch_id=None, teacher_id=None):
    """Create today's (or any day's) lecture sessions from the weekly timetable if missing."""
    q = (TimetableSlot.query.join(Batch, Batch.id == TimetableSlot.batch_id)
         .filter(TimetableSlot.weekday == day.weekday(), Batch.status == "active"))
    if branch_id:
        q = q.filter(Batch.branch_id == branch_id)
    slots = q.all()
    have = {sid for (sid,) in db.session.query(LectureSession.slot_id).filter(LectureSession.lecture_date == day)}
    created = False
    for s in slots:
        b = s.batch
        if s.id in have or (b.start_date and day < b.start_date) or (b.end_date and day > b.end_date):
            continue
        db.session.add(LectureSession(
            branch_id=b.branch_id, batch_id=b.id, slot_id=s.id, teacher_id=s.teacher_id or b.teacher_id,
            room_id=s.room_id or b.room_id, lecture_date=day,
            start_at=local_to_utc(day, s.start_time), end_at=local_to_utc(day, s.end_time)))
        created = True
    if created:
        try:
            db.session.commit()
        except IntegrityError:          # two phones opened the page at the same moment
            db.session.rollback()
    q = LectureSession.query.filter(LectureSession.lecture_date == day)
    if branch_id:
        q = q.filter(LectureSession.branch_id == branch_id)
    if teacher_id:
        q = q.filter(LectureSession.teacher_id == teacher_id)
    return q.order_by(LectureSession.start_at).all()


def on_leave(kind, person_id, day):
    col = LeaveRequest.teacher_id if kind == "teacher" else LeaveRequest.student_id
    return (LeaveRequest.query.filter(LeaveRequest.kind == kind, col == person_id, LeaveRequest.status == "approved",
                                      LeaveRequest.from_date <= day, LeaveRequest.to_date >= day).first() is not None)


def checkin_window(s):
    opens = s.start_at - timedelta(minutes=rule("teacher_checkin_opens_min"))
    ontime_until = s.start_at + timedelta(minutes=rule("ontime_grace_min"))
    return opens, ontime_until


def late_minutes(s):
    """Minutes late (0 if on time or not arrived)."""
    if not s.checkin_at:
        return 0
    _, ontime_until = checkin_window(s)
    return max(0, int((s.checkin_at - s.start_at).total_seconds() // 60)) if s.checkin_at > ontime_until else 0


def session_state(s, now=None):
    """(key, label, badge colour) for boards and dashboards."""
    now = _now(now)
    opens, ontime_until = checkin_window(s)
    if s.cancelled:
        return "cancelled", "Cancelled", "secondary"
    if s.checkin_at:
        if s.ended_at or now >= s.end_at:
            return "completed", "Completed", "success" if late_minutes(s) == 0 else "warning"
        return "running", "Running", "primary"
    if on_leave("teacher", s.teacher_id, s.lecture_date):
        return "teacher_leave", "Teacher on leave", "secondary"
    if now < opens:
        return "upcoming", "Upcoming", "light"
    if now <= ontime_until:
        return "waiting", "Waiting for teacher", "info"
    if now < s.end_at:
        return "late", "Teacher late", "danger"
    return "missed", "Missed", "danger"


def teacher_checkin(s, teacher, lat, lng, accuracy, now=None):
    now = _now(now)
    if s.teacher_id != teacher.id:
        raise PermissionError("This is not your lecture.")
    if s.cancelled:
        raise ValueError("This lecture is cancelled.")
    if s.checkin_at:
        raise ValueError("You have already started this lecture.")
    opens, _ = checkin_window(s)
    if now < opens:
        raise ValueError(f"Too early. You can start this lecture {rule('teacher_checkin_opens_min')} minutes before it begins.")
    if now > s.end_at:
        raise ValueError("This lecture has already ended. Ask your branch admin to correct it.")
    dist = verify_location(s.branch_id, lat, lng, accuracy)
    s.checkin_at, s.checkin_lat, s.checkin_lng, s.checkin_distance_m = now, float(lat), float(lng), dist
    log_action("class_start", "lecture_sessions", s.id,
               f"{teacher.employee_code} started {s.batch.name} ({late_minutes(s)} min late, {dist} m from branch)")
    db.session.commit()


def end_class(s, teacher, now=None):
    if s.teacher_id != teacher.id:
        raise PermissionError("This is not your lecture.")
    if not s.checkin_at:
        raise ValueError("Start the lecture first.")
    if s.ended_at:
        raise ValueError("The lecture is already ended.")
    s.ended_at = _now(now)
    log_action("class_end", "lecture_sessions", s.id, s.batch.name)
    db.session.commit()


# ------------------------------------------------------------------ roster + marking
def roster(s):
    """[(student, record|None, on_leave)] for the lecture's batch."""
    students = (Student.query.join(BatchStudent, BatchStudent.student_id == Student.id)
                .filter(BatchStudent.batch_id == s.batch_id, BatchStudent.status == "active",
                        BatchStudent.enrolled_on <= s.lecture_date, Student.status == "active")
                .order_by(Student.full_name).all())
    recs = {r.student_id: r for r in AttendanceRecord.query.filter_by(session_id=s.id)}
    seen = {st.id for st in students}
    students += [r.student for r in recs.values() if r.student_id not in seen]
    return [(st, recs.get(st.id), on_leave("student", st.id, s.lecture_date)) for st in students]


def marking_allowed(s, user, teacher, now=None):
    """Returns 'admin', 'teacher' or raises PermissionError/ValueError."""
    now = _now(now)
    if user.role_name in ("owner", "branch_admin"):
        if user.role_name == "branch_admin" and user.branch_id != s.branch_id:
            raise PermissionError("Not your branch.")
        return "admin"
    if user.role_name == "teacher" and teacher and teacher.id == s.teacher_id:
        if not s.checkin_at:
            raise ValueError("Start the lecture (scan the branch QR) before taking attendance.")
        if now > s.end_at + timedelta(minutes=rule("edit_window_min")):
            raise ValueError("The time to change this attendance is over. Ask your branch admin.")
        return "teacher"
    raise PermissionError("You cannot mark attendance for this lecture.")


def mark_attendance(s, statuses, user, teacher, lat=None, lng=None, accuracy=None, now=None):
    mode = marking_allowed(s, user, teacher, now)
    if mode == "teacher":
        verify_location(s.branch_id, lat, lng, accuracy)       # teacher must be at the tuition while marking
    now = _now(now)
    existing = {r.student_id: r for r in AttendanceRecord.query.filter_by(session_id=s.id)}
    changed = 0
    for st, rec, leave in roster(s):
        status = statuses.get(st.id)
        if status not in ATTENDANCE_STATUSES:
            status = rec.status if rec else ("leave" if leave else "present")
        if rec is None:
            rec = existing.get(st.id) or AttendanceRecord(session_id=s.id, student_id=st.id)
            db.session.add(rec)
        if rec.status != status:
            changed += 1
        rec.status, rec.marked_by, rec.marked_at = status, user.id, now
    first = s.attendance_submitted_at is None
    s.attendance_submitted_at, s.submitted_by = now, user.id
    log_action("attendance_mark" if first else "attendance_edit", "lecture_sessions", s.id,
               f"{s.batch.name} {s.lecture_date}: by {mode}, {changed} change(s)", user=user)
    db.session.commit()


def student_self_checkin(s, student, lat, lng, accuracy, now=None):
    now = _now(now)
    if s.cancelled:
        raise ValueError("This lecture is cancelled.")
    if now < s.start_at - timedelta(minutes=rule("student_checkin_opens_min")):
        raise ValueError("Too early. Check-in opens a few minutes before the lecture.")
    if now > s.end_at:
        raise ValueError("This lecture has ended.")
    if student.id not in {st.id for st, _, _ in roster(s)}:
        raise PermissionError("You are not in this batch.")
    dist = verify_location(s.branch_id, lat, lng, accuracy)
    rec = AttendanceRecord.query.filter_by(session_id=s.id, student_id=student.id).first()
    if rec is None:
        rec = AttendanceRecord(session_id=s.id, student_id=student.id, status="present")
        db.session.add(rec)
    rec.verified, rec.verified_at, rec.verified_distance_m = True, now, dist
    log_action("student_checkin", "lecture_sessions", s.id, f"{student.student_code} {dist} m from branch",
               user=student.user)
    db.session.commit()
    return rec


# ------------------------------------------------------------------ summaries
def student_summary(student, start, end):
    rows = (db.session.query(AttendanceRecord.status, func.count(AttendanceRecord.id))
            .join(LectureSession, LectureSession.id == AttendanceRecord.session_id)
            .filter(AttendanceRecord.student_id == student.id, LectureSession.lecture_date >= start,
                    LectureSession.lecture_date <= end).group_by(AttendanceRecord.status).all())
    c = {k: 0 for k in ATTENDANCE_STATUSES}
    c.update(dict(rows))
    counted = c["present"] + c["late"] + c["absent"]          # leave days are not held against the student
    c["percent"] = round(100 * (c["present"] + c["late"]) / counted) if counted else None
    return c


def student_recent(student, limit=30):
    return (AttendanceRecord.query.join(LectureSession, LectureSession.id == AttendanceRecord.session_id)
            .filter(AttendanceRecord.student_id == student.id)
            .order_by(LectureSession.start_at.desc()).limit(limit).all())


def todays_status_for(student, day):
    """[(session, record|None)] for the student's lectures on `day` (sessions are created if needed)."""
    ids = [bid for (bid,) in db.session.query(BatchStudent.batch_id).filter_by(student_id=student.id, status="active")]
    if not ids:
        return []
    ensure_sessions(day, branch_id=student.branch_id)
    sessions = (LectureSession.query.filter(LectureSession.lecture_date == day, LectureSession.batch_id.in_(ids))
                .order_by(LectureSession.start_at).all())
    recs = {r.session_id: r for r in AttendanceRecord.query.filter(
        AttendanceRecord.student_id == student.id, AttendanceRecord.session_id.in_([s.id for s in sessions] or [0]))}
    return [(s, recs.get(s.id)) for s in sessions]


def teacher_report(start, end, branch_id=None, now=None):
    """Punctuality per teacher between two dates (only lectures whose time has passed)."""
    now = _now(now)
    q = LectureSession.query.filter(LectureSession.lecture_date >= start, LectureSession.lecture_date <= end,
                                    LectureSession.cancelled.is_(False), LectureSession.start_at <= now)
    if branch_id:
        q = q.filter(LectureSession.branch_id == branch_id)
    out = {}
    for s in q.all():
        r = out.setdefault(s.teacher_id, {"teacher": s.teacher, "lectures": 0, "on_time": 0, "late": 0,
                                         "late_total": 0, "missed": 0, "leave": 0, "marked": 0})
        key, _, _ = session_state(s, now)
        r["lectures"] += 1
        if key == "teacher_leave":
            r["leave"] += 1
        elif key == "missed":
            r["missed"] += 1
        elif s.checkin_at:
            lm = late_minutes(s)
            r["late" if lm else "on_time"] += 1
            r["late_total"] += lm
            r["marked"] += 1 if s.attendance_submitted_at else 0
    for r in out.values():
        r["avg_late"] = round(r["late_total"] / r["late"]) if r["late"] else 0
    return sorted(out.values(), key=lambda r: r["teacher"].full_name)


def batch_report(start, end, branch_id=None):
    q = (db.session.query(Batch, func.count(distinct(LectureSession.id)),
                          func.sum(case((AttendanceRecord.status.in_(("present", "late")), 1), else_=0)),
                          func.sum(case((AttendanceRecord.status.in_(("present", "late", "absent")), 1), else_=0)))
         .join(LectureSession, LectureSession.batch_id == Batch.id)
         .outerjoin(AttendanceRecord, AttendanceRecord.session_id == LectureSession.id)
         .filter(LectureSession.lecture_date >= start, LectureSession.lecture_date <= end,
                 LectureSession.attendance_submitted_at.isnot(None)))
    if branch_id:
        q = q.filter(Batch.branch_id == branch_id)
    rows = []
    for batch, held, present, counted in q.group_by(Batch.id).order_by(Batch.name).all():
        rows.append({"batch": batch, "held": held,
                     "percent": round(100 * (present or 0) / counted) if counted else None})
    return rows


def student_checkin_open(s, now=None):
    now = _now(now)
    return (not s.cancelled and s.start_at - timedelta(minutes=rule("student_checkin_opens_min")) <= now <= s.end_at)


def teacher_checkin_open(s, now=None):
    now = _now(now)
    opens, _ = checkin_window(s)
    return (not s.cancelled and not s.checkin_at and opens <= now <= s.end_at)
