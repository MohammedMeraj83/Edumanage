from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from extensions import db
from app.models import OnlineClass, OnlineExam, OnlineExamAttempt, Batch
from app.services import online_service as svc
from app.utils.decorators import role_required, permission_required

bp = Blueprint("online", __name__, url_prefix="/online")
STAFF = ("owner", "branch_admin", "teacher")


def guard(code):
    def deco(view):
        return role_required(*STAFF)(permission_required(code)(view))
    return deco


def _class(class_id):
    item = db.get_or_404(OnlineClass, class_id)
    if not current_user.is_owner and item.branch_id != current_user.branch_id:
        abort(403)
    if current_user.role_name == "teacher" and item.batch not in svc.manageable_batches(current_user):
        abort(403)
    return item


def _exam(exam_id):
    exam = db.get_or_404(OnlineExam, exam_id)
    if not current_user.is_owner and exam.branch_id != current_user.branch_id:
        abort(403)
    if current_user.role_name == "teacher" and exam.batch not in svc.manageable_batches(current_user):
        abort(403)
    return exam


@bp.route("/classes")
@permission_required("online_classes.view")
def classes():
    if current_user.role_name in STAFF:
        q = OnlineClass.query
        if not current_user.is_owner:
            q = q.filter(OnlineClass.branch_id == current_user.branch_id)
        if current_user.role_name == "teacher":
            ids = [b.id for b in svc.manageable_batches(current_user)]
            q = q.filter(OnlineClass.batch_id.in_(ids))
        items = q.order_by(OnlineClass.starts_at.desc()).all()
    else:
        student = svc.my_student(current_user)
        ids = [e.batch_id for e in student.enrollments if e.status == "active"] if student else []
        items = OnlineClass.query.filter(OnlineClass.batch_id.in_(ids)).order_by(OnlineClass.starts_at.desc()).all() if ids else []
    return render_template("online/classes.html", items=items, now=datetime.now())


@bp.route("/classes/new", methods=["GET", "POST"])
@guard("online_classes.create")
def class_new():
    batches = svc.manageable_batches(current_user)
    if request.method == "POST":
        try:
            svc.create_class(current_user, request.form)
            flash("Online class scheduled.", "success")
            return redirect(url_for("online.classes"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("online/class_form.html", item=None, batches=batches, form=request.form)


@bp.route("/classes/<int:class_id>/edit", methods=["GET", "POST"])
@guard("online_classes.edit")
def class_edit(class_id):
    item = _class(class_id)
    if request.method == "POST":
        try:
            svc.update_class(current_user, item, request.form)
            flash("Class updated.", "success")
            return redirect(url_for("online.classes"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("online/class_form.html", item=item, batches=[], form=request.form)


@bp.route("/classes/<int:class_id>/status", methods=["POST"])
@guard("online_classes.edit")
def class_status(class_id):
    item = _class(class_id)
    status = request.form.get("status")
    if status not in ("live", "completed", "cancelled"):
        flash("Choose a valid class status.", "danger")
    else:
        item.status = status
        db.session.commit()
        from app.services.communication_service import notify_event
        notify_event(actor=current_user, title="Online class status updated",
                     body=f"{item.title} is now {status}.", batch=item.batch)
    return redirect(url_for("online.classes"))


@bp.route("/exams")
@permission_required("online_exams.view")
def exams():
    if current_user.role_name in STAFF:
        q = OnlineExam.query
        if not current_user.is_owner:
            q = q.filter(OnlineExam.branch_id == current_user.branch_id)
        if current_user.role_name == "teacher":
            ids = [b.id for b in svc.manageable_batches(current_user)]
            q = q.filter(OnlineExam.batch_id.in_(ids))
        items = q.order_by(OnlineExam.starts_at.desc()).all()
    else:
        student = svc.my_student(current_user)
        ids = [e.batch_id for e in student.enrollments if e.status == "active"] if student else []
        items = OnlineExam.query.filter(OnlineExam.batch_id.in_(ids), OnlineExam.status != "draft").order_by(OnlineExam.starts_at.desc()).all() if ids else []
    return render_template("online/exams.html", items=items, now=datetime.now())


@bp.route("/exams/new", methods=["GET", "POST"])
@guard("online_exams.create")
def exam_new():
    batches = svc.manageable_batches(current_user)
    if request.method == "POST":
        try:
            exam = svc.create_exam(current_user, request.form)
            flash("Exam created. Add questions before publishing.", "success")
            return redirect(url_for("online.exam_detail", exam_id=exam.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("online/exam_form.html", exam=None, batches=batches, form=request.form)


@bp.route("/exams/<int:exam_id>")
@guard("online_exams.view")
def exam_detail(exam_id):
    exam = _exam(exam_id)
    return render_template("online/exam_detail.html", exam=exam,
                           can_manage=current_user.role_name in ("owner", "branch_admin", "teacher") and current_user.has_permission("online_exams.edit"))


@bp.route("/exams/<int:exam_id>/questions", methods=["POST"])
@guard("online_exams.edit")
def exam_question(exam_id):
    exam = _exam(exam_id)
    try:
        svc.add_question(current_user, exam, request.form)
        flash("Question added.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("online.exam_detail", exam_id=exam.id))


@bp.route("/exams/<int:exam_id>/publish", methods=["POST"])
@guard("online_exams.edit")
def exam_publish(exam_id):
    exam = _exam(exam_id)
    if exam.status != "draft":
        flash("Exam is already published or closed.", "danger")
    elif not exam.questions:
        flash("Add at least one question before publishing.", "danger")
    else:
        exam.status = "published"
        db.session.commit()
        from app.services.communication_service import notify_event
        notify_event(actor=current_user, title="Online exam published",
                     body=f"{exam.title} is open from {exam.starts_at.strftime('%d %b %Y, %I:%M %p')}.", batch=exam.batch)
        flash("Exam published.", "success")
    return redirect(url_for("online.exam_detail", exam_id=exam.id))


@bp.route("/exams/<int:exam_id>/take", methods=["GET", "POST"])
@permission_required("online_exams.view")
def exam_take(exam_id):
    exam = db.get_or_404(OnlineExam, exam_id)
    if current_user.role_name not in ("student",):
        abort(403)
    student = svc.my_student(current_user)
    if not student or not svc.enrolled_batch(student, exam.batch):
        abort(403)
    if request.method == "POST":
        try:
            attempt = svc.submit_exam(current_user, exam, request.form)
            flash("Exam submitted successfully.", "success")
            return redirect(url_for("online.exam_result", exam_id=exam.id))
        except ValueError as e:
            flash(str(e), "danger")
    if exam.status != "published":
        abort(404)
    existing = OnlineExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id).first()
    if existing:
        return redirect(url_for("online.exam_result", exam_id=exam.id))
    now = datetime.now()
    if now < exam.starts_at:
        flash("The exam has not started yet.", "warning")
    elif now > exam.ends_at:
        flash("The exam time has ended.", "warning")
    return render_template("online/exam_take.html", exam=exam, now=now)


@bp.route("/exams/<int:exam_id>/result")
@permission_required("online_exams.view")
def exam_result(exam_id):
    exam = db.get_or_404(OnlineExam, exam_id)
    student = svc.my_student(current_user)
    if not student:
        abort(403)
    attempt = OnlineExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id).first()
    if not attempt:
        return redirect(url_for("online.exam_take", exam_id=exam.id))
    return render_template("online/exam_result.html", exam=exam, attempt=attempt)
