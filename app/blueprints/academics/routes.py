from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user
from extensions import db
from app.models import Course, Subject, Room, Branch
from app.services import academic_service as svc
from app.services.audit_service import log_action
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import permission_required, role_required
from .forms import CourseForm, SubjectForm, RoomForm

bp = Blueprint("academics", __name__, url_prefix="/academics")


# ------------------------------------------------------------------ courses
@bp.route("/courses")
@permission_required("courses.view")
def courses():
    return render_template("academics/courses.html", items=Course.query.order_by(Course.name).all())


@bp.route("/courses/new", methods=["GET", "POST"])
@role_required("owner")
def course_new():
    form = CourseForm()
    if form.validate_on_submit():
        c = Course(name=form.name.data.strip(), description=(form.description.data or "").strip() or None,
                   is_active=form.is_active.data,
                   subjects=Subject.query.filter(Subject.id.in_(form.subjects.data or [])).all())
        db.session.add(c)
        db.session.flush()
        log_action("create", "courses", c.id, c.name)
        db.session.commit()
        flash(f"Course {c.name} created.", "success")
        return redirect(url_for("academics.courses"))
    return render_template("academics/course_form.html", form=form, item=None)


@bp.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@role_required("owner")
def course_edit(course_id):
    c = db.get_or_404(Course, course_id)
    form = CourseForm(obj=c, obj_id=c.id)
    if request.method == "GET":
        form.subjects.data = [s.id for s in c.subjects]
    if form.validate_on_submit():
        c.name = form.name.data.strip()
        c.description = (form.description.data or "").strip() or None
        c.is_active = form.is_active.data
        c.subjects = Subject.query.filter(Subject.id.in_(form.subjects.data or [])).all()
        log_action("update", "courses", c.id, c.name)
        db.session.commit()
        flash("Course saved.", "success")
        return redirect(url_for("academics.courses"))
    return render_template("academics/course_form.html", form=form, item=c)


@bp.route("/courses/starter", methods=["POST"])
@role_required("owner")
def starter_set():
    n = svc.load_starter_set()
    flash(f"{n} new course/subject entries added." if n else "Everything from the starter set already exists.", "success")
    return redirect(url_for("academics.courses"))


# ------------------------------------------------------------------ subjects
@bp.route("/subjects")
@permission_required("subjects.view")
def subjects():
    return render_template("academics/subjects.html", items=Subject.query.order_by(Subject.name).all())


@bp.route("/subjects/new", methods=["GET", "POST"])
@role_required("owner")
def subject_new():
    form = SubjectForm()
    if form.validate_on_submit():
        s = Subject(name=form.name.data.strip(), is_active=form.is_active.data)
        db.session.add(s)
        db.session.flush()
        log_action("create", "subjects", s.id, s.name)
        db.session.commit()
        flash(f"Subject {s.name} added.", "success")
        return redirect(url_for("academics.subjects"))
    return render_template("academics/subject_form.html", form=form, item=None)


@bp.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@role_required("owner")
def subject_edit(subject_id):
    s = db.get_or_404(Subject, subject_id)
    form = SubjectForm(obj=s, obj_id=s.id)
    if form.validate_on_submit():
        s.name, s.is_active = form.name.data.strip(), form.is_active.data
        log_action("update", "subjects", s.id, s.name)
        db.session.commit()
        flash("Subject saved.", "success")
        return redirect(url_for("academics.subjects"))
    return render_template("academics/subject_form.html", form=form, item=s)


# ------------------------------------------------------------------ rooms
def _room_form(obj=None):
    form = RoomForm(obj=obj, obj_id=obj.id if obj else None,
                    branch_id=obj.branch_id if obj else current_user.branch_id)
    if current_user.is_owner and not obj:
        form.branch_id.choices = [(b.id, f"{b.name} ({b.code})")
                                  for b in Branch.query.filter_by(is_active=True).order_by(Branch.name)]
    else:
        del form.branch_id
    return form


@bp.route("/rooms")
@permission_required("batches.edit")
def rooms():
    items = scope_to_branch(Room.query, Room).order_by(Room.branch_id, Room.name).all()
    return render_template("academics/rooms.html", items=items)


@bp.route("/rooms/new", methods=["GET", "POST"])
@permission_required("batches.edit")
def room_new():
    form = _room_form()
    if form.validate_on_submit():
        bid = form.branch_id.data if current_user.is_owner else current_user.branch_id
        r = Room(branch_id=bid, name=form.name.data.strip(), capacity=form.capacity.data, is_active=form.is_active.data)
        db.session.add(r)
        db.session.flush()
        log_action("create", "rooms", r.id, r.name)
        db.session.commit()
        flash(f"Room {r.name} added.", "success")
        return redirect(url_for("academics.rooms"))
    return render_template("academics/room_form.html", form=form, item=None)


@bp.route("/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@permission_required("batches.edit")
def room_edit(room_id):
    r = db.get_or_404(Room, room_id)
    ensure_branch_access(r.branch_id)
    form = _room_form(r)
    if form.validate_on_submit():
        r.name, r.capacity, r.is_active = form.name.data.strip(), form.capacity.data, form.is_active.data
        log_action("update", "rooms", r.id, r.name)
        db.session.commit()
        flash("Room saved.", "success")
        return redirect(url_for("academics.rooms"))
    return render_template("academics/room_form.html", form=form, item=r)
