from datetime import date
from decimal import Decimal
from sqlalchemy import func
from extensions import db
from app.models import (Batch, BatchStudent, TimetableSlot, Student, Teacher, Course, Subject, AcademicSession)
from app.services.audit_service import log_action
from app.utils.date_utils import WEEKDAYS_SHORT, fmt_time

STARTER_SUBJECTS = ["Physics", "Chemistry", "Mathematics", "Biology", "English", "Science", "Social Studies"]
STARTER_COURSES = {
    "Class 8": ["Mathematics", "Science", "English", "Social Studies"],
    "Class 9": ["Mathematics", "Science", "English", "Social Studies"],
    "Class 10": ["Mathematics", "Science", "English", "Social Studies"],
    "Class 11-12 Science": ["Physics", "Chemistry", "Mathematics", "Biology", "English"],
    "NEET": ["Physics", "Chemistry", "Biology"],
    "JEE": ["Physics", "Chemistry", "Mathematics"],
    "MHT-CET": ["Physics", "Chemistry", "Mathematics", "Biology"],
}


def teacher_for_user(user):
    return Teacher.query.filter_by(user_id=user.id).first()


# ---------------------------------------------------------------- counts
def batch_counts(batch_ids):
    """{batch_id: {'total':n, 'male':n, 'female':n}} counting active seats of active students."""
    out = {bid: {"total": 0, "male": 0, "female": 0} for bid in batch_ids}
    if not batch_ids:
        return out
    rows = (db.session.query(BatchStudent.batch_id, Student.gender, func.count(BatchStudent.id))
            .join(Student, Student.id == BatchStudent.student_id)
            .filter(BatchStudent.batch_id.in_(batch_ids), BatchStudent.status == "active", Student.status == "active")
            .group_by(BatchStudent.batch_id, Student.gender).all())
    for bid, gender, n in rows:
        out[bid]["total"] += n
        if gender == "Male":
            out[bid]["male"] += n
        elif gender == "Female":
            out[bid]["female"] += n
    return out


def seats_used(batch):
    """Seats taken = all active enrollments (so a full batch stays full)."""
    return BatchStudent.query.filter_by(batch_id=batch.id, status="active").count()


def schedule_text(batch):
    """'Mon, Wed 9:00 AM–10:00 AM' (groups days that share the same time)."""
    groups = {}
    for s in batch.slots:
        groups.setdefault((s.start_time, s.end_time), []).append(WEEKDAYS_SHORT[s.weekday])
    parts = [f"{', '.join(days)} {fmt_time(st)}–{fmt_time(en)}" for (st, en), days in groups.items()]
    return " · ".join(parts) if parts else "No timetable yet"


# ---------------------------------------------------------------- clashes
def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def slot_conflicts(batch, weekday, start, end, room_id, teacher_id, exclude_id=None):
    """Human-readable clashes inside the same branch (teacher, room, or the batch itself)."""
    eff_teacher = teacher_id or batch.teacher_id
    eff_room = room_id or batch.room_id
    others = (TimetableSlot.query.join(Batch, Batch.id == TimetableSlot.batch_id)
              .filter(Batch.branch_id == batch.branch_id, Batch.status == "active",
                      TimetableSlot.weekday == weekday).all())
    problems = []
    for o in others:
        if exclude_id and o.id == exclude_id:
            continue
        if not overlaps(start, end, o.start_time, o.end_time):
            continue
        when = f"{fmt_time(o.start_time)}–{fmt_time(o.end_time)}"
        if o.batch_id == batch.id:
            problems.append(f"This batch already has a lecture at {when} on this day.")
            continue
        if eff_teacher and (o.teacher_id or o.batch.teacher_id) == eff_teacher:
            problems.append(f"The teacher is already teaching {o.batch.name} at {when}.")
        if eff_room and (o.room_id or o.batch.room_id) == eff_room:
            problems.append(f"The room is already used by {o.batch.name} at {when}.")
    return problems


def student_conflicts(student, batch):
    """Clashes between the target batch's timetable and the student's other active batches."""
    mine = (TimetableSlot.query.join(Batch, Batch.id == TimetableSlot.batch_id)
            .join(BatchStudent, BatchStudent.batch_id == Batch.id)
            .filter(BatchStudent.student_id == student.id, BatchStudent.status == "active",
                    Batch.status == "active", Batch.id != batch.id).all())
    problems = []
    for new in batch.slots:
        for o in mine:
            if o.weekday == new.weekday and overlaps(new.start_time, new.end_time, o.start_time, o.end_time):
                problems.append(f"{WEEKDAYS_SHORT[o.weekday]} {fmt_time(o.start_time)}–{fmt_time(o.end_time)} "
                                f"clashes with {o.batch.name}.")
    return problems


# ---------------------------------------------------------------- enrollment
def enroll_student(batch, student, fee, user, pay_style="monthly", discount=None):
    if batch.status != "active":
        raise ValueError("This batch is closed.")
    if student.status != "active":
        raise ValueError("Only active students can be enrolled.")
    if student.branch_id != batch.branch_id:
        raise ValueError("The student belongs to a different branch.")
    enr = BatchStudent.query.filter_by(batch_id=batch.id, student_id=student.id).first()
    if enr and enr.status == "active":
        raise ValueError("The student is already in this batch.")
    if seats_used(batch) >= batch.capacity:
        raise ValueError(f"This batch is full ({batch.capacity} seats).")
    clashes = student_conflicts(student, batch)
    if clashes:
        raise ValueError("Timetable clash: " + " ".join(clashes))
    fee = batch.fee_amount if fee is None else Decimal(fee)
    if fee < 0:
        raise ValueError("Fee cannot be negative.")
    if enr:                                         # re-joining: reuse the row, keep history in the audit log
        enr.status, enr.left_on, enr.leave_reason = "active", None, None
        enr.enrolled_on, enr.fee_amount = date.today(), fee
    else:
        enr = BatchStudent(batch_id=batch.id, student_id=student.id, status="active",
                           enrolled_on=date.today(), fee_amount=fee)
        db.session.add(enr)
    db.session.flush()
    from app.services.fee_service import generate_dues, money
    generate_dues(enr, pay_style, user, money(discount) if discount not in (None, "") else Decimal("0.00"))
    log_action("enroll", "batches", batch.id, f"{student.student_code} joined {batch.name} (fee {fee}, {pay_style})", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="Added to a new batch",
                 body=f"You have been enrolled in {batch.name}.", batch=batch)
    return enr


def end_enrollment(enr, reason=None, user=None, commit=True):
    enr.status, enr.left_on, enr.leave_reason = "left", date.today(), (reason or None)
    from app.services.fee_service import cancel_future_dues
    cancelled = cancel_future_dues(enr)
    log_action("unenroll", "batches", enr.batch_id,
               f"{enr.student.student_code} left {enr.batch.name} ({cancelled} future due(s) cancelled)", user=user)
    if commit:
        db.session.commit()


def end_all_enrollments(student, reason):
    """Used on branch transfer: batches belong to a branch, so seats in the old branch end."""
    rows = BatchStudent.query.filter_by(student_id=student.id, status="active").all()
    from app.services.fee_service import cancel_future_dues
    for enr in rows:
        enr.status, enr.left_on, enr.leave_reason = "left", date.today(), reason
        cancel_future_dues(enr, reason)
    return len(rows)


# ---------------------------------------------------------------- batches
def current_session():
    return AcademicSession.query.filter_by(is_current=True).first()


def auto_name(course, subject, label):
    base = f"{course.name} - {subject.name}"
    return f"{base} - {label}" if label else base


def create_batch(data, branch_id, user):
    session = current_session()
    if not session:
        raise ValueError("Set a current academic session first.")
    batch = Batch(branch_id=branch_id, session_id=session.id, **data)
    db.session.add(batch)
    db.session.flush()
    log_action("create", "batches", batch.id, f"Created batch {batch.name}", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="New batch created", body=f"Batch {batch.name} is now available.", batch=batch)
    return batch


def update_batch(batch, data, user):
    for k, v in data.items():
        setattr(batch, k, v)
    log_action("update", "batches", batch.id, f"Edited batch {batch.name}", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="Batch updated", body=f"Details for {batch.name} have changed.", batch=batch)


def set_batch_status(batch, status, user):
    if status not in ("active", "closed"):
        raise ValueError("Unknown status.")
    batch.status = status
    log_action("status", "batches", batch.id, f"{batch.name} -> {status}", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="Batch status updated",
                 body=f"{batch.name} is now {status}.", batch=batch)


def add_slot(batch, weekday, start, end, room_id, teacher_id, user):
    if end <= start:
        raise ValueError("End time must be after the start time.")
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if minutes < 15 or minutes > 240:
        raise ValueError("A lecture must be between 15 minutes and 4 hours long.")
    problems = slot_conflicts(batch, weekday, start, end, room_id, teacher_id)
    if problems:
        raise ValueError(" ".join(problems))
    slot = TimetableSlot(batch_id=batch.id, weekday=weekday, start_time=start, end_time=end,
                         room_id=room_id or None, teacher_id=teacher_id or None)
    db.session.add(slot)
    db.session.flush()
    log_action("create", "timetable", slot.id, f"{batch.name}: {WEEKDAYS_SHORT[weekday]} {fmt_time(start)}-{fmt_time(end)}", user=user)
    db.session.commit()
    return slot


def delete_slot(slot, user):
    log_action("delete", "timetable", slot.id, f"{slot.batch.name}: {WEEKDAYS_SHORT[slot.weekday]}", user=user)
    db.session.delete(slot)
    db.session.commit()


# ---------------------------------------------------------------- starter data
def load_starter_set():
    """Adds common subjects/courses that are missing. Never changes existing ones."""
    added = 0
    subjects = {s.name: s for s in Subject.query.all()}
    for name in STARTER_SUBJECTS:
        if name not in subjects:
            subjects[name] = Subject(name=name)
            db.session.add(subjects[name])
            added += 1
    existing = {c.name: c for c in Course.query.all()}
    for name, subs in STARTER_COURSES.items():
        if name not in existing:
            db.session.add(Course(name=name, subjects=[subjects[n] for n in subs if n in subjects]))
            added += 1
    log_action("starter_set", "courses", None, f"Loaded starter courses/subjects ({added} new)")
    db.session.commit()
    return added


# ---------------------------------------------------------------- views for dashboards
def slots_on(weekday, teacher=None, batch_ids=None):
    q = (TimetableSlot.query.join(Batch, Batch.id == TimetableSlot.batch_id)
         .filter(TimetableSlot.weekday == weekday, Batch.status == "active"))
    if batch_ids is not None:
        q = q.filter(TimetableSlot.batch_id.in_(batch_ids))
    slots = q.order_by(TimetableSlot.start_time).all()
    if teacher is not None:
        slots = [s for s in slots if (s.teacher_id or s.batch.teacher_id) == teacher.id]
    return slots


def student_batches(student):
    return (Batch.query.join(BatchStudent, BatchStudent.batch_id == Batch.id)
            .filter(BatchStudent.student_id == student.id, BatchStudent.status == "active", Batch.status == "active")
            .order_by(Batch.name).all())
