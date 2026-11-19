from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from sqlalchemy import or_
from extensions import db
from app.models import (Batch, BatchStudent, TimetableSlot, Student, Teacher, Room, Course, Subject, Branch,
                        BATCH_STATUSES)
from app.services import academic_service as svc
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import permission_required
from .forms import BatchForm, SlotForm

bp = Blueprint("batches", __name__, url_prefix="/batches")


# ---------------------------------------------------------------- helpers
def _get(batch_id):
    batch = db.get_or_404(Batch, batch_id)
    ensure_branch_access(batch.branch_id)
    if current_user.role_name == "teacher":          # teachers see only their own batches
        me = svc.teacher_for_user(current_user)
        if not me or me.id != batch.teacher_id:
            abort(403)
    return batch


def _branch_teachers(branch_id):
    return Teacher.query.filter_by(branch_id=branch_id, status="active").order_by(Teacher.full_name).all()


def _branch_rooms(branch_id):
    return Room.query.filter_by(branch_id=branch_id, is_active=True).order_by(Room.name).all()


def _fill_choices(form, branch_id):
    form.course_id.choices = [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name)]
    form.subject_id.choices = [(s.id, s.name) for s in Subject.query.filter_by(is_active=True).order_by(Subject.name)]
    form.teacher_id.choices = [(t.id, f"{t.full_name} ({t.employee_code})") for t in _branch_teachers(branch_id)]
    form.room_id.choices = [(0, "No default room")] + [(r.id, r.name) for r in _branch_rooms(branch_id)]


def _course_subject_map():
    return {c.id: [s.id for s in c.subjects] for c in Course.query.filter_by(is_active=True)}


def _batch_data(form, branch_id, exclude_id=None):
    """Validate cross-field rules. Returns (data, error)."""
    course, subject = db.session.get(Course, form.course_id.data), db.session.get(Subject, form.subject_id.data)
    if subject not in course.subjects:
        return None, f"{subject.name} is not part of {course.name}. Add it to the course first."
    teacher = db.session.get(Teacher, form.teacher_id.data)
    if teacher.branch_id != branch_id:
        return None, "The teacher belongs to a different branch."
    room = db.session.get(Room, form.room_id.data) if form.room_id.data else None
    if room and room.branch_id != branch_id:
        return None, "The room belongs to a different branch."
    session = svc.current_session()
    name = (form.name.data or "").strip() or svc.auto_name(course, subject, "")
    q = Batch.query.filter_by(branch_id=branch_id, session_id=session.id if session else 0, name=name)
    if exclude_id:
        q = q.filter(Batch.id != exclude_id)
    if q.first():
        return None, f"A batch named “{name}” already exists in this branch. Add a label such as Morning or Evening."
    return {"name": name, "course_id": course.id, "subject_id": subject.id, "teacher_id": teacher.id,
            "room_id": room.id if room else None, "capacity": form.capacity.data, "fee_amount": form.fee_amount.data,
            "fee_frequency": form.fee_frequency.data, "start_date": form.start_date.data,
            "end_date": form.end_date.data}, None


def _back(default_batch_id):
    if request.form.get("back") == "student" and request.form.get("student_id", type=int):
        return redirect(url_for("students.detail", student_id=request.form.get("student_id", type=int)))
    return redirect(url_for("batches.detail", batch_id=default_batch_id))


# ---------------------------------------------------------------- list
@bp.route("/")
@permission_required("batches.view")
def index():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "active")
    course_id = request.args.get("course", type=int)
    branch_id = request.args.get("branch", type=int)
    query = scope_to_branch(Batch.query, Batch)
    if current_user.role_name == "teacher":
        me = svc.teacher_for_user(current_user)
        query = query.filter(Batch.teacher_id == (me.id if me else 0))
    if current_user.is_owner and branch_id:
        query = query.filter(Batch.branch_id == branch_id)
    if course_id:
        query = query.filter(Batch.course_id == course_id)
    if q:
        like = f"%{q}%"
        query = query.filter(Batch.name.ilike(like))
    if status in BATCH_STATUSES:
        query = query.filter(Batch.status == status)
    page = query.order_by(Batch.name).paginate(page=request.args.get("page", 1, type=int), per_page=20,
                                               error_out=False)
    counts = svc.batch_counts([b.id for b in page.items])
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("batches/list.html", page=page, counts=counts, q=q, status=status, course_id=course_id,
                           branch_id=branch_id, courses=Course.query.order_by(Course.name).all(),
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [],
                           args=args, statuses=BATCH_STATUSES, schedule_text=svc.schedule_text)


# ---------------------------------------------------------------- create / edit
@bp.route("/new", methods=["GET", "POST"])
@permission_required("batches.create")
def new():
    if current_user.is_owner:
        branch_id = request.args.get("branch", type=int)
        if not branch_id:
            return render_template("batches/choose_branch.html",
                                   branches=Branch.query.filter_by(is_active=True).order_by(Branch.name).all())
        branch = db.get_or_404(Branch, branch_id)
    else:
        branch = current_user.branch
    form = BatchForm()
    _fill_choices(form, branch.id)
    if form.validate_on_submit():
        data, error = _batch_data(form, branch.id)
        if error:
            flash(error, "danger")
        else:
            try:
                batch = svc.create_batch(data, branch.id, current_user)
                flash("Batch created. Now add its weekly timetable.", "success")
                return redirect(url_for("batches.detail", batch_id=batch.id))
            except ValueError as e:
                flash(str(e), "danger")
    return render_template("batches/form.html", form=form, batch=None, branch=branch,
                           subject_map=_course_subject_map())


@bp.route("/<int:batch_id>/edit", methods=["GET", "POST"])
@permission_required("batches.edit")
def edit(batch_id):
    batch = _get(batch_id)
    form = BatchForm(obj=batch)
    _fill_choices(form, batch.branch_id)
    if form.validate_on_submit():
        data, error = _batch_data(form, batch.branch_id, exclude_id=batch.id)
        if error:
            flash(error, "danger")
        elif data["capacity"] < svc.seats_used(batch):
            flash(f"{svc.seats_used(batch)} students are already enrolled. Seats cannot be fewer than that.", "danger")
        else:
            svc.update_batch(batch, data, current_user)
            flash("Batch saved. Existing students keep the fee they joined with.", "success")
            return redirect(url_for("batches.detail", batch_id=batch.id))
    return render_template("batches/form.html", form=form, batch=batch, branch=batch.branch,
                           subject_map=_course_subject_map())


@bp.route("/<int:batch_id>/status", methods=["POST"])
@permission_required("batches.edit")
def change_status(batch_id):
    batch = _get(batch_id)
    try:
        svc.set_batch_status(batch, request.form.get("status"), current_user)
        flash(f"Batch is now {batch.status}.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("batches.detail", batch_id=batch.id))


# ---------------------------------------------------------------- detail
@bp.route("/<int:batch_id>")
@permission_required("batches.view")
def detail(batch_id):
    batch = _get(batch_id)
    can_edit = current_user.has_permission("batches.edit")
    enrolled = (BatchStudent.query.join(Student, Student.id == BatchStudent.student_id)
                .filter(BatchStudent.batch_id == batch.id, BatchStudent.status == "active")
                .order_by(Student.full_name).all())
    history = (BatchStudent.query.filter_by(batch_id=batch.id, status="left")
               .order_by(BatchStudent.left_on.desc()).limit(20).all())
    find = (request.args.get("find") or "").strip()
    found = []
    if find and can_edit:
        like = f"%{find}%"
        in_batch = db.session.query(BatchStudent.student_id).filter_by(batch_id=batch.id, status="active")
        found = (Student.query.filter(Student.branch_id == batch.branch_id, Student.status == "active",
                                      Student.id.notin_(in_batch),
                                      or_(Student.full_name.ilike(like), Student.student_code.ilike(like),
                                          Student.phone.ilike(like), Student.guardian_phone.ilike(like)))
                 .order_by(Student.full_name).limit(10).all())
    slot_form = SlotForm()
    slot_form.room_id.choices = [(0, "Batch room")] + [(r.id, r.name) for r in _branch_rooms(batch.branch_id)]
    slot_form.teacher_id.choices = [(0, "Batch teacher")] + [(t.id, t.full_name) for t in _branch_teachers(batch.branch_id)]
    return render_template("batches/detail.html", batch=batch, can_edit=can_edit, enrolled=enrolled, history=history,
                           counts=svc.batch_counts([batch.id])[batch.id], seats_used=svc.seats_used(batch),
                           find=find, found=found, slot_form=slot_form, schedule_text=svc.schedule_text(batch))


# ---------------------------------------------------------------- enrollment
@bp.route("/<int:batch_id>/enroll", methods=["POST"])
@permission_required("batches.edit")
def enroll(batch_id):
    batch = _get(batch_id)
    student = db.get_or_404(Student, request.form.get("student_id", type=int) or 0)
    ensure_branch_access(student.branch_id)
    raw = (request.form.get("fee") or "").strip()
    try:
        fee = Decimal(raw) if raw else None
        style = request.form.get("pay_style") if request.form.get("pay_style") in ("monthly", "full") else "monthly"
        svc.enroll_student(batch, student, fee, current_user, pay_style=style, discount=request.form.get("discount"))
        flash(f"{student.full_name} added to {batch.name}.", "success")
    except InvalidOperation:
        flash("Enter the fee as a number.", "danger")
    except ValueError as e:
        flash(str(e), "danger")
    return _back(batch.id)


@bp.route("/<int:batch_id>/unenroll/<int:student_id>", methods=["POST"])
@permission_required("batches.edit")
def unenroll(batch_id, student_id):
    batch = _get(batch_id)
    enr = BatchStudent.query.filter_by(batch_id=batch.id, student_id=student_id, status="active").first_or_404()
    svc.end_enrollment(enr, request.form.get("reason"), current_user)
    flash(f"{enr.student.full_name} removed from {batch.name}.", "success")
    return _back(batch.id)


# ---------------------------------------------------------------- timetable slots
@bp.route("/<int:batch_id>/slots", methods=["POST"])
@permission_required("timetable.create")
def add_slot(batch_id):
    batch = _get(batch_id)
    form = SlotForm()
    form.room_id.choices = [(0, "")] + [(r.id, r.name) for r in _branch_rooms(batch.branch_id)]
    form.teacher_id.choices = [(0, "")] + [(t.id, t.full_name) for t in _branch_teachers(batch.branch_id)]
    if batch.status != "active":
        flash("Reopen the batch before changing its timetable.", "warning")
    elif form.validate_on_submit():
        try:
            svc.add_slot(batch, form.weekday.data, form.start_time.data, form.end_time.data,
                         form.room_id.data, form.teacher_id.data, current_user)
            flash("Lecture added to the timetable.", "success")
        except ValueError as e:
            flash(str(e), "danger")
    else:
        flash("Choose the day, start time and end time.", "danger")
    return redirect(url_for("batches.detail", batch_id=batch.id))


@bp.route("/<int:batch_id>/slots/<int:slot_id>/delete", methods=["POST"])
@permission_required("timetable.delete")
def delete_slot(batch_id, slot_id):
    batch = _get(batch_id)
    slot = db.get_or_404(TimetableSlot, slot_id)
    if slot.batch_id != batch.id:
        abort(404)
    svc.delete_slot(slot, current_user)
    flash("Lecture removed from the timetable.", "success")
    return redirect(url_for("batches.detail", batch_id=batch.id))
