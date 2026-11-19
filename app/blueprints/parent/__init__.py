from datetime import timedelta
from flask import Blueprint, render_template, abort, url_for, request
from flask_login import current_user
from extensions import db
from app.models import Parent, Student
from app.services import academic_service as svc
from app.services import attendance_service as att
from app.utils.date_utils import local_now
from app.utils.decorators import role_required

bp = Blueprint("parent", __name__, url_prefix="/parent")


def _me():
    return Parent.query.filter_by(user_id=current_user.id).first()


@bp.route("/dashboard")
@role_required("parent")
def dashboard():
    me = _me()
    children = [l.student for l in me.links] if me else []
    day = local_now().date()
    child_batches, today_rows, summaries = {}, {}, {}
    for c in children:
        child_batches[c.id] = svc.student_batches(c)
        today_rows[c.id] = [(s, rec, att.session_state(s)) for s, rec in att.todays_status_for(c, day)]
        summaries[c.id] = att.student_summary(c, day - timedelta(days=30), day)
    from app.services import fee_service
    balances = {c.id: fee_service.student_totals(c) for c in children}
    return render_template("parent/dashboard.html", me=me, children=children, child_batches=child_batches,
                           today_rows=today_rows, summaries=summaries, balances=balances, schedule_text=svc.schedule_text)


@bp.route("/child/<int:student_id>/attendance")
@role_required("parent")
def child_attendance(student_id):
    me = _me()
    if not me or student_id not in {l.student_id for l in me.links}:
        abort(404)
    student = db.get_or_404(Student, student_id)
    today = local_now().date()
    return render_template("attendance/history.html", student=student, own=False,
                           summary=att.student_summary(student, today - timedelta(days=30), today),
                           recent=att.student_recent(student))


@bp.route("/child/<int:student_id>/fees")
@role_required("parent")
def child_fees(student_id):
    from app.models import FeeDue, Payment
    from app.services import fee_service
    me = _me()
    if not me or student_id not in {l.student_id for l in me.links}:
        abort(404)
    student = db.get_or_404(Student, student_id)
    dues = FeeDue.query.filter(FeeDue.student_id == student.id, FeeDue.status != "cancelled").order_by(FeeDue.due_date).all()
    pays = Payment.query.filter_by(student_id=student.id, status="active").order_by(Payment.created_at.desc()).all()
    return render_template("fees/portal.html", student=student, dues=dues, payments=pays,
                           totals=fee_service.student_totals(student))


def _my_child(student_id):
    me = _me()
    if not me or student_id not in {l.student_id for l in me.links}:
        abort(404)
    return db.get_or_404(Student, student_id)


def _published_exam(exam_id):
    from app.models import Exam
    exam = db.get_or_404(Exam, exam_id)
    if not exam.results_published:
        abort(404)
    return exam


@bp.route("/child/<int:student_id>/results")
@role_required("parent")
def child_results(student_id):
    from app.services import exam_service
    child = _my_child(student_id)
    return render_template("exams/portal.html", student=child, items=exam_service.results_for_student(child), own=False,
                           grade_colors=exam_service.GRADE_COLORS, detail_endpoint="parent.child_result_detail",
                           fmt=exam_service.fmt_marks)


@bp.route("/child/<int:student_id>/results/<int:exam_id>")
@role_required("parent")
def child_result_detail(student_id, exam_id):
    from app.blueprints.exams.routes import marksheet_context
    child = _my_child(student_id)
    exam = _published_exam(exam_id)
    return render_template("exams/marksheet.html", **marksheet_context(
        exam, child, url_for("parent.child_results", student_id=child.id),
        url_for("parent.child_result_pdf", student_id=child.id, exam_id=exam.id)))


@bp.route("/child/<int:student_id>/results/<int:exam_id>.pdf")
@role_required("parent")
def child_result_pdf(student_id, exam_id):
    from app.blueprints.exams.routes import marksheet_pdf_response
    child = _my_child(student_id)
    return marksheet_pdf_response(_published_exam(exam_id), child)


@bp.route("/child/<int:student_id>/homework")
@role_required("parent")
def child_homework(student_id):
    from app.services import homework_service as hw_svc
    child = _my_child(student_id)
    when = request.args.get("when", "upcoming")
    when = when if when in ("upcoming", "past", "all") else "upcoming"
    items = hw_svc.homework_for_student(child, when)
    return render_template("homework/portal.html", student=child, items=items, when=when,
                           checks=hw_svc.check_map(child, [h.id for h in items]),
                           list_url=url_for("parent.child_homework", student_id=child.id),
                           detail_endpoint="parent.child_homework_detail", detail_args={"student_id": child.id},
                           due_label=hw_svc.due_label, status_labels=hw_svc.STATUS_LABELS,
                           status_colors=hw_svc.STATUS_COLORS, own=False)


@bp.route("/child/<int:student_id>/homework/<int:hw_id>")
@role_required("parent")
def child_homework_detail(student_id, hw_id):
    from app.models import Homework
    from app.services import homework_service as hw_svc
    child = _my_child(student_id)
    hw = db.get_or_404(Homework, hw_id)
    if not hw_svc.student_in_batch(child, hw.batch):
        abort(404)
    label, css = hw_svc.due_label(hw.due_date)
    return render_template("homework/portal_detail.html", student=child, hw=hw,
                           check=hw_svc.check_map(child, [hw.id]).get(hw.id), due=label, due_css=css,
                           back_url=url_for("parent.child_homework", student_id=child.id),
                           status_labels=hw_svc.STATUS_LABELS, status_colors=hw_svc.STATUS_COLORS)


@bp.route("/child/<int:student_id>/documents")
@role_required("parent")
def child_documents(student_id):
    from app.services import library_service, certificate_service, idcard_service
    child = _my_child(student_id)
    return render_template("documents/portal.html", student=child, own=False,
                           docs=library_service.docs_for_student_side({child.branch_id}),
                           certs=certificate_service.student_certificates(child),
                           card=idcard_service.active_card("student", child.id),
                           cert_pdf="parent.child_certificate_pdf", card_pdf="parent.child_id_card_pdf",
                           pdf_args={"student_id": child.id}, type_label=certificate_service.type_label)


@bp.route("/child/<int:student_id>/documents/certificate/<int:cert_id>.pdf")
@role_required("parent")
def child_certificate_pdf(student_id, cert_id):
    from app.models import Certificate
    from app.blueprints.certificates.routes import certificate_pdf_response
    child = _my_child(student_id)
    cert = db.get_or_404(Certificate, cert_id)
    if cert.student_id != child.id or cert.status != "issued":
        abort(404)
    return certificate_pdf_response(cert)


@bp.route("/child/<int:student_id>/documents/id-card.pdf")
@role_required("parent")
def child_id_card_pdf(student_id):
    from app.services import idcard_service
    from app.blueprints.id_cards.routes import card_pdf_response
    child = _my_child(student_id)
    card = idcard_service.active_card("student", child.id)
    if card is None:
        abort(404)
    return card_pdf_response(card)
