from datetime import timedelta
from flask import Blueprint, render_template, abort, url_for, request
from flask_login import current_user
from app.models import Student
from app.services import academic_service as svc
from app.services import attendance_service as att
from app.utils.date_utils import WEEKDAYS, local_now
from app.utils.decorators import role_required

bp = Blueprint("student", __name__, url_prefix="/student")


@bp.route("/dashboard")
@role_required("student")
def dashboard():
    me = Student.query.filter_by(user_id=current_user.id).first()
    batches, today_rows = [], []
    day = local_now().date()
    if me:
        batches = svc.student_batches(me)
        for s, rec in att.todays_status_for(me, day):
            key, label, css = att.session_state(s)
            today_rows.append({"s": s, "rec": rec, "label": label, "css": css, "open": att.student_checkin_open(s)})
    return render_template("student/dashboard.html", me=me, batches=batches, today_rows=today_rows,
                           today_name=WEEKDAYS[day.weekday()], schedule_text=svc.schedule_text)


@bp.route("/attendance")
@role_required("student")
def attendance():
    me = Student.query.filter_by(user_id=current_user.id).first()
    today = local_now().date()
    summary = att.student_summary(me, today - timedelta(days=30), today) if me else None
    return render_template("attendance/history.html", student=me, summary=summary,
                           recent=att.student_recent(me) if me else [], own=True)


@bp.route("/fees")
@role_required("student")
def fees():
    from app.models import FeeDue, Payment
    from app.services import fee_service
    me = Student.query.filter_by(user_id=current_user.id).first()
    dues = FeeDue.query.filter(FeeDue.student_id == (me.id if me else 0), FeeDue.status != "cancelled").order_by(FeeDue.due_date).all()
    pays = Payment.query.filter_by(student_id=me.id if me else 0).order_by(Payment.created_at.desc()).all()
    return render_template("fees/portal.html", student=me, dues=dues, payments=[p for p in pays if p.status == "active"],
                           totals=fee_service.student_totals(me) if me else None)


def _published_exam(exam_id, student):
    from extensions import db
    from app.models import Exam
    exam = db.get_or_404(Exam, exam_id)
    if not exam.results_published or student is None:
        abort(404)
    return exam


@bp.route("/results")
@role_required("student")
def results():
    from app.services import exam_service
    me = Student.query.filter_by(user_id=current_user.id).first()
    items = exam_service.results_for_student(me) if me else []
    return render_template("exams/portal.html", student=me, items=items, own=True, grade_colors=exam_service.GRADE_COLORS,
                           detail_endpoint="student.result_detail", fmt=exam_service.fmt_marks)


@bp.route("/results/<int:exam_id>")
@role_required("student")
def result_detail(exam_id):
    from app.blueprints.exams.routes import marksheet_context
    me = Student.query.filter_by(user_id=current_user.id).first()
    exam = _published_exam(exam_id, me)
    return render_template("exams/marksheet.html", **marksheet_context(
        exam, me, url_for("student.results"), url_for("student.result_pdf", exam_id=exam.id)))


@bp.route("/results/<int:exam_id>.pdf")
@role_required("student")
def result_pdf(exam_id):
    from app.blueprints.exams.routes import marksheet_pdf_response
    me = Student.query.filter_by(user_id=current_user.id).first()
    return marksheet_pdf_response(_published_exam(exam_id, me), me)


@bp.route("/homework")
@role_required("student")
def homework():
    from app.services import homework_service as hw_svc
    me = Student.query.filter_by(user_id=current_user.id).first()
    when = request.args.get("when", "upcoming")
    when = when if when in ("upcoming", "past", "all") else "upcoming"
    items = hw_svc.homework_for_student(me, when) if me else []
    return render_template("homework/portal.html", student=me, items=items, when=when,
                           checks=hw_svc.check_map(me, [h.id for h in items]) if me else {},
                           list_url=url_for("student.homework"), detail_endpoint="student.homework_detail",
                           detail_args={}, due_label=hw_svc.due_label, status_labels=hw_svc.STATUS_LABELS,
                           status_colors=hw_svc.STATUS_COLORS, own=True)


@bp.route("/homework/<int:hw_id>")
@role_required("student")
def homework_detail(hw_id):
    from extensions import db
    from app.models import Homework
    from app.services import homework_service as hw_svc
    me = Student.query.filter_by(user_id=current_user.id).first()
    hw = db.get_or_404(Homework, hw_id)
    if not me or not hw_svc.student_in_batch(me, hw.batch):
        abort(404)
    label, css = hw_svc.due_label(hw.due_date)
    return render_template("homework/portal_detail.html", student=me, hw=hw, check=hw_svc.check_map(me, [hw.id]).get(hw.id),
                           due=label, due_css=css, back_url=url_for("student.homework"),
                           status_labels=hw_svc.STATUS_LABELS, status_colors=hw_svc.STATUS_COLORS)


@bp.route("/materials")
@role_required("student")
def materials():
    from app.services import homework_service as hw_svc
    me = Student.query.filter_by(user_id=current_user.id).first()
    q = request.args.get("q", "").strip().lower()
    items = hw_svc.materials_for_student(me) if me else []
    if q:
        items = [m for m in items if q in m.title.lower() or q in m.batch.subject.name.lower()]
    return render_template("materials/portal.html", student=me, items=items, q=q, human_size=hw_svc.human_size)


@bp.route("/documents")
@role_required("student")
def documents():
    from app.services import library_service, certificate_service, idcard_service
    me = Student.query.filter_by(user_id=current_user.id).first()
    return render_template("documents/portal.html", student=me, own=True,
                           docs=library_service.docs_for_student_side({me.branch_id}) if me else [],
                           certs=certificate_service.student_certificates(me) if me else [],
                           card=idcard_service.active_card("student", me.id) if me else None,
                           cert_pdf="student.certificate_pdf", card_pdf="student.id_card_pdf", pdf_args={},
                           type_label=certificate_service.type_label)


@bp.route("/documents/certificate/<int:cert_id>.pdf")
@role_required("student")
def certificate_pdf(cert_id):
    from extensions import db
    from app.models import Certificate
    from app.blueprints.certificates.routes import certificate_pdf_response
    me = Student.query.filter_by(user_id=current_user.id).first()
    cert = db.get_or_404(Certificate, cert_id)
    if not me or cert.student_id != me.id or cert.status != "issued":
        abort(404)
    return certificate_pdf_response(cert)


@bp.route("/documents/id-card.pdf")
@role_required("student")
def id_card_pdf():
    from app.services import idcard_service
    from app.blueprints.id_cards.routes import card_pdf_response
    me = Student.query.filter_by(user_id=current_user.id).first()
    card = idcard_service.active_card("student", me.id) if me else None
    if card is None:
        abort(404)
    return card_pdf_response(card)
