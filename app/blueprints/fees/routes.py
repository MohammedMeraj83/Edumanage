import uuid
from datetime import date, timedelta
from decimal import Decimal
from flask import (Blueprint, render_template, redirect, url_for, flash, request, abort, Response)
from flask_login import current_user, login_required
from sqlalchemy import or_
from extensions import db
from app.models import (FeeDue, Payment, Refund, Student, BatchStudent, Branch, Parent, PAYMENT_MODES, PAY_STYLES)
from app.services import fee_service as svc
from app.services.receipt_pdf import build_receipt_pdf
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import permission_required, role_required
from app.utils.exports import xlsx_response

bp = Blueprint("fees", __name__, url_prefix="/fees")
ADMIN = ("owner", "branch_admin")
STAFF = ("owner", "branch_admin", "accountant")


def staff_perm(code):
    """Fee screens are for institute staff only (students/parents use their own pages)."""
    def deco(view):
        return role_required(*STAFF)(permission_required(code)(view))
    return deco


def _student(student_id):
    s = db.get_or_404(Student, student_id)
    ensure_branch_access(s.branch_id)
    return s


def _parse_date(text, default=None):
    try:
        return date.fromisoformat(text) if text else default
    except ValueError:
        return default


def _back(student_id):
    return redirect(url_for("fees.student", student_id=student_id))


# ------------------------------------------------------------------ dashboard
@bp.route("/")
@staff_perm("fees.view")
def index():
    branch_id = request.args.get("branch", type=int) if current_user.is_owner else current_user.branch_id
    today = date.today()
    total, overdue_amt, overdue_students = svc.outstanding_total(branch_id)
    q = (request.args.get("q") or "").strip()
    found = []
    if q:
        like = f"%{q}%"
        sq = scope_to_branch(Student.query, Student).filter(Student.status == "active")
        if current_user.is_owner and branch_id:
            sq = sq.filter(Student.branch_id == branch_id)
        found = (sq.filter(or_(Student.full_name.ilike(like), Student.student_code.ilike(like),
                               Student.phone.ilike(like), Student.guardian_phone.ilike(like)))
                 .order_by(Student.full_name).limit(15).all())
    pq = scope_to_branch(Payment.query, Payment)
    if current_user.is_owner and branch_id:
        pq = pq.filter(Payment.branch_id == branch_id)
    recent = pq.order_by(Payment.created_at.desc()).limit(8).all()
    return render_template(
        "fees/index.html", q=q, found=found, recent=recent, branch_id=branch_id,
        today_total=svc.collection_between(today, today, branch_id),
        month_total=svc.collection_between(today.replace(day=1), today, branch_id),
        outstanding=total, overdue=overdue_amt, overdue_students=overdue_students,
        branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


# ------------------------------------------------------------------ one student
@bp.route("/student/<int:student_id>")
@staff_perm("fees.view")
def student(student_id):
    s = _student(student_id)
    dues = FeeDue.query.filter_by(student_id=s.id).order_by(FeeDue.due_date.desc(), FeeDue.id.desc()).all()
    payments = Payment.query.filter_by(student_id=s.id).order_by(Payment.created_at.desc()).all()
    no_dues = [e for e in BatchStudent.query.filter_by(student_id=s.id, status="active").all()
               if not FeeDue.query.filter_by(enrollment_id=e.id).first()]
    return render_template("fees/student.html", s=s, dues=dues, payments=payments, totals=svc.student_totals(s),
                           no_dues=no_dues, pay_styles=PAY_STYLES, today=date.today())


@bp.route("/collect/<int:student_id>", methods=["GET", "POST"])
@staff_perm("payments.create")
def collect(student_id):
    s = _student(student_id)
    dues = svc.outstanding(s)
    if request.method == "POST":
        try:
            ids = [int(x) for x in request.form.getlist("due_id") if x.isdigit()]
            payment = svc.collect_payment(
                s, ids, request.form.get("amount"), request.form.get("mode"), request.form.get("reference"),
                _parse_date(request.form.get("paid_on"), date.today()), request.form.get("note"), current_user,
                token=request.form.get("token"))
            flash(f"Payment received. Receipt {payment.receipt_no}.", "success")
            return redirect(url_for("fees.receipt", payment_id=payment.id))
        except (ValueError, RuntimeError) as e:
            flash(str(e), "danger")
    return render_template("fees/collect.html", s=s, dues=dues, modes=PAYMENT_MODES, token=uuid.uuid4().hex,
                           totals=svc.student_totals(s), today=date.today(),
                           sel=set(request.form.getlist("due_id", type=int)) if request.method == "POST" else None)


@bp.route("/student/<int:student_id>/generate/<int:enrollment_id>", methods=["POST"])
@staff_perm("fees.create")
def generate(student_id, enrollment_id):
    s = _student(student_id)
    enr = BatchStudent.query.filter_by(id=enrollment_id, student_id=s.id, status="active").first_or_404()
    style = request.form.get("pay_style") if request.form.get("pay_style") in ("monthly", "full") else "monthly"
    try:
        made = svc.generate_dues(enr, style, current_user, svc.money(request.form.get("discount") or 0))
        db.session.commit()
        flash(f"{len(made)} fee due(s) created." if made else "Nothing to create - fees already exist.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return _back(s.id)


@bp.route("/student/<int:student_id>/charge", methods=["POST"])
@staff_perm("fees.create")
def charge(student_id):
    s = _student(student_id)
    try:
        svc.add_charge(s, request.form.get("label"), request.form.get("amount"),
                       _parse_date(request.form.get("due_date"), date.today()), current_user)
        flash("Charge added.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return _back(s.id)


@bp.route("/due/<int:due_id>/discount", methods=["POST"])
@role_required(*ADMIN)
def discount(due_id):
    due = db.get_or_404(FeeDue, due_id)
    ensure_branch_access(due.branch_id)
    try:
        svc.apply_discount(due, request.form.get("discount"), request.form.get("reason"), current_user)
        flash("Discount saved.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return _back(due.student_id)


@bp.route("/due/<int:due_id>/cancel", methods=["POST"])
@role_required(*ADMIN)
def cancel_due(due_id):
    due = db.get_or_404(FeeDue, due_id)
    ensure_branch_access(due.branch_id)
    try:
        svc.cancel_due(due, request.form.get("reason"), current_user)
        flash("Due cancelled.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return _back(due.student_id)


# ------------------------------------------------------------------ pending list
def _pending_query():
    branch_id = request.args.get("branch", type=int)
    only_overdue = request.args.get("overdue", "1") == "1"
    q = (request.args.get("q") or "").strip()
    query = scope_to_branch(FeeDue.query.filter(FeeDue.status.in_(("pending", "partial"))), FeeDue)
    if current_user.is_owner and branch_id:
        query = query.filter(FeeDue.branch_id == branch_id)
    if only_overdue:
        query = query.filter(FeeDue.due_date < date.today())
    if q:
        like = f"%{q}%"
        query = query.join(Student, Student.id == FeeDue.student_id).filter(
            or_(Student.full_name.ilike(like), Student.student_code.ilike(like), Student.guardian_phone.ilike(like)))
    return query.order_by(FeeDue.due_date, FeeDue.id).all(), branch_id, only_overdue, q


@bp.route("/pending")
@staff_perm("fees.view")
def pending():
    dues, branch_id, only_overdue, q = _pending_query()
    dues = [d for d in dues if d.balance > 0]
    # one row per student with the sum of what is pending
    people = {}
    for d in dues:
        row = people.setdefault(d.student_id, {"student": d.student, "balance": Decimal(0), "oldest": d.due_date, "count": 0})
        row["balance"] += d.balance
        row["count"] += 1
    rows = sorted(people.values(), key=lambda r: r["oldest"])
    return render_template("fees/pending.html", rows=rows, total=sum((r["balance"] for r in rows), Decimal(0)),
                           branch_id=branch_id, only_overdue=only_overdue, q=q, today=date.today(),
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


@bp.route("/pending.xlsx")
@staff_perm("fees.view")
def pending_xlsx():
    dues, *_ = _pending_query()
    rows = [(d.student.student_code, d.student.full_name, d.student.class_name, d.student.guardian_phone, d.label,
             d.due_date.strftime("%d-%m-%Y"), d.net, d.paid, d.balance, (date.today() - d.due_date).days if d.overdue else 0)
            for d in dues if d.balance > 0]
    return xlsx_response("pending-fees.xlsx", ["Student ID", "Name", "Class", "Parent phone", "Fee", "Due date",
                                               "Amount", "Paid", "Balance", "Days overdue"], rows)


# ------------------------------------------------------------------ payment history
def _payments_query():
    branch_id = request.args.get("branch", type=int)
    start = _parse_date(request.args.get("from"), date.today().replace(day=1))
    end = _parse_date(request.args.get("to"), date.today())
    mode, q = request.args.get("mode"), (request.args.get("q") or "").strip()
    query = scope_to_branch(Payment.query, Payment).filter(Payment.paid_on >= start, Payment.paid_on <= end)
    if current_user.is_owner and branch_id:
        query = query.filter(Payment.branch_id == branch_id)
    if mode in dict(PAYMENT_MODES):
        query = query.filter(Payment.mode == mode)
    if q:
        like = f"%{q}%"
        query = query.join(Student, Student.id == Payment.student_id).filter(
            or_(Student.full_name.ilike(like), Student.student_code.ilike(like), Payment.receipt_no.ilike(like),
                Payment.reference.ilike(like)))
    return query.order_by(Payment.paid_on.desc(), Payment.id.desc()), start, end, mode, q, branch_id


@bp.route("/payments")
@staff_perm("payments.view")
def payments():
    query, start, end, mode, q, branch_id = _payments_query()
    page = query.paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    active = [p for p in query.all() if p.status == "active"]
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("fees/payments.html", page=page, args=args, start=start, end=end, mode=mode, q=q,
                           branch_id=branch_id, modes=PAYMENT_MODES,
                           total=sum((p.net_amount for p in active), Decimal(0)),
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


@bp.route("/payments.xlsx")
@staff_perm("payments.view")
def payments_xlsx():
    query, *_ = _payments_query()
    rows = [(p.receipt_no, p.paid_on.strftime("%d-%m-%Y"), p.student.student_code, p.student.full_name,
             p.student.class_name, p.branch.name, p.mode_label, p.reference or "", p.amount, p.refunded_amount,
             p.status, p.receiver.full_name) for p in query.all()]
    return xlsx_response("payments.xlsx", ["Receipt", "Date", "Student ID", "Name", "Class", "Branch", "Mode",
                                           "Reference", "Amount", "Refunded", "Status", "Received by"], rows)


# ------------------------------------------------------------------ receipts (staff, the student, the parent)
def _can_see_payment(p):
    role = current_user.role_name
    if role in ("owner", "branch_admin", "accountant"):
        if not current_user.has_permission("payments.view"):
            return False
        return current_user.is_owner or current_user.branch_id == p.branch_id
    if role == "student":
        return p.student.user_id == current_user.id
    if role == "parent":
        me = Parent.query.filter_by(user_id=current_user.id).first()
        return bool(me and p.student_id in {l.student_id for l in me.links})
    return False


def _payment(payment_id):
    p = db.get_or_404(Payment, payment_id)
    if not _can_see_payment(p):
        abort(403)
    return p


@bp.route("/receipt/<int:payment_id>")
@login_required
def receipt(payment_id):
    p = _payment(payment_id)
    return render_template("fees/receipt.html", p=p, balance=svc.student_totals(p.student)["balance"],
                           staff=current_user.role_name in ("owner", "branch_admin", "accountant"))


@bp.route("/receipt/<int:payment_id>.pdf")
@login_required
def receipt_pdf(payment_id):
    p = _payment(payment_id)
    pdf = build_receipt_pdf(p, svc.student_totals(p.student)["balance"])
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{p.receipt_no}.pdf"'})


@bp.route("/payment/<int:payment_id>/cancel", methods=["POST"])
@role_required(*ADMIN)
def cancel_payment(payment_id):
    p = _payment(payment_id)
    try:
        svc.cancel_payment(p, request.form.get("reason"), current_user)
        flash("Payment cancelled. The dues are open again.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("fees.receipt", payment_id=p.id))


@bp.route("/payment/<int:payment_id>/refund", methods=["POST"])
@role_required(*ADMIN)
def refund(payment_id):
    p = _payment(payment_id)
    try:
        r = svc.refund_payment(p, request.form.get("amount"), request.form.get("mode"), request.form.get("reason"),
                               current_user)
        flash(f"Refund {r.refund_no} recorded.", "success")
    except (ValueError, RuntimeError) as e:
        flash(str(e), "danger")
    return redirect(url_for("fees.receipt", payment_id=p.id))


# ------------------------------------------------------------------ settings
@bp.route("/settings", methods=["GET", "POST"])
@role_required(*ADMIN)
def settings():
    if request.method == "POST":
        try:
            svc.save_due_day(request.form.get("due_day", type=int) or 0, current_user)
            flash("Saved. It applies to fee dues created from now on.", "success")
        except ValueError as e:
            flash(str(e), "danger")
        return redirect(url_for("fees.settings"))
    return render_template("fees/settings.html", due_day=svc.due_day())
