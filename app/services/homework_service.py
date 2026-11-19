"""Homework and study materials.

Who can do what:
- Owner: every branch. Branch admin: own branch. Teacher: only the batches they teach.
- Posting homework / materials is always for ONE batch. Only active batches can receive new posts.
- Students see what was posted to batches they are actively enrolled in. Parents see homework (not materials) of
  their children's batches.
- Homework checking: the teacher marks each student Done / Partly done / Not done (blank = not checked yet).
"""
import os
from datetime import datetime
from urllib.parse import urlparse
from flask import current_app
from sqlalchemy import func
from extensions import db
from app.models import (Homework, HomeworkCheck, StudyMaterial, Batch, BatchStudent, Student, Parent,
                        CHECK_STATUSES)
from app.services import academic_service
from app.services.audit_service import log_action
from app.utils.date_utils import local_now
from app.utils.file_upload import save_attachment, delete_upload

HW_FOLDER = "homework"
MATERIAL_FOLDER = "materials"
VALID_STATUSES = {k for k, _ in CHECK_STATUSES}
STATUS_LABELS = dict(CHECK_STATUSES)
STATUS_COLORS = {"done": "success", "partial": "warning", "not_done": "danger"}


def today():
    return local_now().date()


def has_file(file_storage):
    return file_storage is not None and bool(getattr(file_storage, "filename", ""))


# ---------------------------------------------------------------- who may see / manage which batch
def _my_teacher(user):
    return academic_service.teacher_for_user(user)


def manageable_batches(user):
    """Active batches this user may post to."""
    q = Batch.query.filter(Batch.status == "active")
    role = user.role_name
    if role == "teacher":
        t = _my_teacher(user)
        q = q.filter(Batch.teacher_id == (t.id if t else 0))
    elif role == "branch_admin":
        q = q.filter(Batch.branch_id == user.branch_id)
    elif role != "owner":
        return []
    return q.order_by(Batch.name).all()


def can_manage_batch(user, batch):
    role = user.role_name
    if role == "owner":
        return True
    if role == "branch_admin":
        return batch.branch_id == user.branch_id
    if role == "teacher":
        t = _my_teacher(user)
        return bool(t and batch.teacher_id == t.id)
    return False


def my_student(user):
    return Student.query.filter_by(user_id=user.id).first()


def my_children(user):
    p = Parent.query.filter_by(user_id=user.id).first()
    return [l.student for l in p.links] if p else []


def _enrolled(student_ids, batch_id):
    if not student_ids:
        return False
    return db.session.query(BatchStudent.id).join(Student, Student.id == BatchStudent.student_id).filter(
        BatchStudent.batch_id == batch_id, BatchStudent.student_id.in_(student_ids),
        BatchStudent.status == "active", Student.status == "active").first() is not None


def student_in_batch(student, batch):
    return _enrolled([student.id], batch.id)


def can_view_batch(user, batch, allow_parent=True):
    """Everyone who may open content posted to `batch`: staff of that scope, enrolled students, their parents."""
    if can_manage_batch(user, batch):
        return True
    role = user.role_name
    if role == "student":
        me = my_student(user)
        return bool(me and _enrolled([me.id], batch.id))
    if role == "parent" and allow_parent:
        return _enrolled([c.id for c in my_children(user)], batch.id)
    return False


def batch_students(batch, extra_ids=()):
    """Active students of the batch, plus any extra ids (students who already have a note)."""
    found = {s.id: s for s in (Student.query.join(BatchStudent, BatchStudent.student_id == Student.id)
                               .filter(BatchStudent.batch_id == batch.id, BatchStudent.status == "active",
                                       Student.status == "active").all())}
    missing = [i for i in extra_ids if i not in found]
    if missing:
        for s in Student.query.filter(Student.id.in_(missing)).all():
            found[s.id] = s
    return sorted(found.values(), key=lambda s: (s.full_name or "").lower())


# ---------------------------------------------------------------- lists
def _scope(query, model, user):
    role = user.role_name
    if role == "teacher":
        t = _my_teacher(user)
        return query.join(Batch, Batch.id == model.batch_id).filter(Batch.teacher_id == (t.id if t else 0))
    if role == "branch_admin":
        return query.filter(model.branch_id == user.branch_id)
    if role == "owner":
        return query
    return query.filter(db.false())


def staff_homework_query(user):
    return _scope(Homework.query, Homework, user)


def staff_material_query(user):
    return _scope(StudyMaterial.query, StudyMaterial, user)


def _enrolled_batch_ids(student):
    rows = db.session.query(BatchStudent.batch_id).filter(BatchStudent.student_id == student.id,
                                                          BatchStudent.status == "active").all()
    return [r[0] for r in rows]


def homework_for_student(student, when="all"):
    """when: 'upcoming' (due today or later), 'past', or 'all'. Upcoming is soonest first, the rest newest first."""
    q = Homework.query.filter(Homework.batch_id.in_(_enrolled_batch_ids(student)))
    if when == "upcoming":
        return q.filter(Homework.due_date >= today()).order_by(Homework.due_date, Homework.id).all()
    if when == "past":
        q = q.filter(Homework.due_date < today())
    return q.order_by(Homework.due_date.desc(), Homework.id.desc()).all()


def materials_for_student(student):
    return (StudyMaterial.query.filter(StudyMaterial.batch_id.in_(_enrolled_batch_ids(student)))
            .order_by(StudyMaterial.created_at.desc(), StudyMaterial.id.desc()).all())


def check_map(student, homework_ids):
    """{homework_id: HomeworkCheck} for one student."""
    if not homework_ids:
        return {}
    rows = HomeworkCheck.query.filter(HomeworkCheck.student_id == student.id,
                                      HomeworkCheck.homework_id.in_(homework_ids)).all()
    return {r.homework_id: r for r in rows}


def progress(homeworks):
    """{homework_id: {'total': students in batch, 'checked': n, 'done': n}} with two queries."""
    if not homeworks:
        return {}
    totals = academic_service.batch_counts(list({h.batch_id for h in homeworks}))
    rows = (db.session.query(HomeworkCheck.homework_id, func.count(HomeworkCheck.id),
                             func.sum(db.case((HomeworkCheck.status == "done", 1), else_=0)))
            .filter(HomeworkCheck.homework_id.in_([h.id for h in homeworks])).group_by(HomeworkCheck.homework_id).all())
    got = {hid: (n, int(d or 0)) for hid, n, d in rows}
    return {h.id: {"total": totals[h.batch_id]["total"], "checked": got.get(h.id, (0, 0))[0],
                   "done": got.get(h.id, (0, 0))[1]} for h in homeworks}


def due_label(due):
    """('Due today', 'warning') style label for lists."""
    d = (due - today()).days
    if d < 0:
        return f"Was due {abs(d)} day{'s' if abs(d) != 1 else ''} ago", "secondary"
    if d == 0:
        return "Due today", "danger"
    if d == 1:
        return "Due tomorrow", "warning"
    return f"Due in {d} days", "primary"


# ---------------------------------------------------------------- homework
def _clean_text(value, limit, field, required=False):
    v = (value or "").strip()
    if required and not v:
        raise ValueError(f"{field} is required.")
    if len(v) > limit:
        raise ValueError(f"{field} is too long (maximum {limit} characters).")
    return v or None


def create_homework(user, batch, title, description, due_date, file=None):
    if not can_manage_batch(user, batch):
        raise ValueError("You cannot give homework to this batch.")
    if batch.status != "active":
        raise ValueError("This batch is closed.")
    title = _clean_text(title, 150, "Title", required=True)
    description = _clean_text(description, 5000, "Details")
    if due_date is None:
        raise ValueError("Choose the last date.")
    if due_date < today():
        raise ValueError("The last date cannot be in the past.")
    stored = original = None
    if has_file(file):
        stored, original, _ = save_attachment(file, HW_FOLDER)
    hw = Homework(branch_id=batch.branch_id, batch_id=batch.id, title=title, description=description,
                  assigned_on=today(), due_date=due_date, attachment=stored, attachment_name=original,
                  created_by=user.id)
    db.session.add(hw)
    db.session.flush()
    log_action("homework_create", "homework", hw.id, f"{title} ({batch.name})", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="New homework assigned",
                 body=f"{title} was added to {batch.name}. Due: {due_date.strftime('%d %b %Y')}.", batch=batch)
    return hw


def update_homework(hw, user, title, description, due_date, file=None, remove_file=False):
    if not can_manage_batch(user, hw.batch):
        raise ValueError("You cannot change this homework.")
    title = _clean_text(title, 150, "Title", required=True)
    description = _clean_text(description, 5000, "Details")
    if due_date is None:
        raise ValueError("Choose the last date.")
    if due_date < hw.assigned_on:
        raise ValueError("The last date cannot be before the day it was given.")
    new_stored = new_original = None
    if has_file(file):
        new_stored, new_original, _ = save_attachment(file, HW_FOLDER)
    old = hw.attachment
    hw.title, hw.description, hw.due_date = title, description, due_date
    if new_stored:
        hw.attachment, hw.attachment_name = new_stored, new_original
    elif remove_file:
        hw.attachment = hw.attachment_name = None
    log_action("homework_edit", "homework", hw.id, title, user=user)
    db.session.commit()
    if old and old != hw.attachment:
        delete_upload(HW_FOLDER, old)
    return hw


def delete_homework(hw, user):
    if not can_manage_batch(user, hw.batch):
        raise ValueError("You cannot delete this homework.")
    old = hw.attachment
    log_action("homework_delete", "homework", hw.id, f"{hw.title} ({hw.batch.name})", user=user)
    db.session.delete(hw)
    db.session.commit()
    delete_upload(HW_FOLDER, old)


def save_checks(hw, cells, user):
    """cells = {student_id: (status, remark)}. Blank status clears the note. All or nothing.
    Returns (saved, cleared)."""
    if not can_manage_batch(user, hw.batch):
        raise ValueError("You cannot check this homework.")
    existing = {c.student_id: c for c in hw.checks}
    allowed = {s.id for s in batch_students(hw.batch, existing.keys())}
    now = datetime.utcnow()
    parsed = {}
    for sid, (status, remark) in cells.items():
        if sid not in allowed:
            continue
        status = (status or "").strip()
        if status and status not in VALID_STATUSES:
            raise ValueError("Choose Done, Partly done or Not done for each student.")
        parsed[sid] = (status, (remark or "").strip()[:120] or None)
    saved = cleared = 0
    for sid, (status, remark) in parsed.items():
        row = existing.get(sid)
        if not status:
            if row is not None:
                db.session.delete(row)
                cleared += 1
            continue
        if row is None:
            db.session.add(HomeworkCheck(homework_id=hw.id, student_id=sid, status=status, remark=remark,
                                         checked_by=user.id, checked_at=now))
            saved += 1
        elif (row.status, row.remark) != (status, remark):
            row.status, row.remark, row.checked_by, row.checked_at = status, remark, user.id, now
            saved += 1
    log_action("homework_check", "homework", hw.id, f"{hw.title}: {saved} saved, {cleared} cleared", user=user)
    db.session.commit()
    return saved, cleared


# ---------------------------------------------------------------- study materials
def clean_url(value):
    v = (value or "").strip()
    if not v:
        raise ValueError("Paste the link.")
    if len(v) > 500 or any(c.isspace() for c in v):
        raise ValueError("This link is not valid.")
    p = urlparse(v)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("The link must start with http:// or https://")
    return v


def create_material(user, batch, title, description, kind, file=None, url=None):
    if not can_manage_batch(user, batch):
        raise ValueError("You cannot share material with this batch.")
    if batch.status != "active":
        raise ValueError("This batch is closed.")
    title = _clean_text(title, 150, "Title", required=True)
    description = _clean_text(description, 500, "Description")
    m = StudyMaterial(branch_id=batch.branch_id, batch_id=batch.id, title=title, description=description,
                      kind=kind, uploaded_by=user.id)
    if kind == "link":
        m.url = clean_url(url)
    elif kind == "file":
        if not has_file(file):
            raise ValueError("Choose a file to upload.")
        m.filename, m.original_name, m.size = save_attachment(file, MATERIAL_FOLDER)
    else:
        raise ValueError("Choose File or Link.")
    db.session.add(m)
    db.session.flush()
    log_action("material_create", "study_materials", m.id, f"{title} ({batch.name})", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="New study material",
                 body=f"{title} was shared in {batch.name}.", batch=batch)
    return m


def update_material(m, user, title, description, url=None, file=None):
    if not can_manage_batch(user, m.batch):
        raise ValueError("You cannot change this material.")
    title = _clean_text(title, 150, "Title", required=True)
    description = _clean_text(description, 500, "Description")
    old = None
    if m.kind == "link":
        m.url = clean_url(url)
    elif has_file(file):
        new = save_attachment(file, MATERIAL_FOLDER)
        old = m.filename
        m.filename, m.original_name, m.size = new
    m.title, m.description = title, description
    log_action("material_edit", "study_materials", m.id, title, user=user)
    db.session.commit()
    if old:
        delete_upload(MATERIAL_FOLDER, old)
    return m


def delete_material(m, user):
    if not can_manage_batch(user, m.batch):
        raise ValueError("You cannot delete this material.")
    old = m.filename
    log_action("material_delete", "study_materials", m.id, f"{m.title} ({m.batch.name})", user=user)
    db.session.delete(m)
    db.session.commit()
    delete_upload(MATERIAL_FOLDER, old)


def human_size(n):
    if not n:
        return ""
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def file_exists(folder, name):
    return bool(name) and os.path.exists(os.path.join(current_app.config["UPLOAD_FOLDER"], folder,
                                                      os.path.basename(name)))
