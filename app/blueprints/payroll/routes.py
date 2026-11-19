from datetime import date
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, Response
from flask_login import current_user, login_required
from extensions import db
from app.models import (Payroll, SalaryPayment, SalaryStructure, Teacher, Staff, Branch, PAY_TYPES, PAYMENT_MODES)
from app.services import payroll_service as svc
from app.services.receipt_pdf import build_salary_slip_pdf
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import staff_permission, role_required
from app.utils.exports import xlsx_response

bp = Blueprint("payroll", __name__, url_prefix="/payroll")
ADMIN = ("owner", "branch_admin")


def _month(text):
    try:
        y, m = (text or "").split("-")
        return date(int(y), int(m), 1)
    except (ValueError, TypeError):
        return date.today().replace(day=1)


def _payroll(payroll_id):
    p = db.get_or_404(Payroll, payroll_id)
    ensure_branch_access(p.branch_id)
    return p


def _back(p):
    return redirect(url_for("payroll.detail", payroll_id=p.id))


def _guard(fn, p, ok_msg):
    try:
        fn()
        flash(ok_msg, "success")
    except (ValueError, RuntimeError) as e:
        flash(str(e), "danger")
    return _back(p)


# ------------------------------------------------------------------ month view
@bp.route("/")
@staff_permission("salary.view")
def index():
    month = _month(request.args.get("m"))
    branch_id = request.args.get("branch", type=int) if current_user.is_owner else current_user.branch_id
    q = scope_to_branch(Payroll.query, Payroll).filter(Payroll.month == month, Payroll.status != "cancelled")
    if current_user.is_owner and branch_id:
        q = q.filter(Payroll.branch_id == branch_id)
    rows = q.order_by(Payroll.slip_no).all()
    total = sum((p.net_amount for p in rows), Decimal(0))
    paid = sum((p.paid_amount for p in rows), Decimal(0))
    return render_template("payroll/index.html", rows=rows, month=month, branch_id=branch_id, total=total, paid=paid,
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


@bp.route("/month.xlsx")
@staff_permission("salary.view")
def month_xlsx():
    month = _month(request.args.get("m"))
    q = scope_to_branch(Payroll.query, Payroll).filter(Payroll.month == month, Payroll.status != "cancelled")
    rows = [(p.slip_no, p.person.employee_code, p.person.full_name, p.branch.name, p.pay_type, p.base_amount,
             p.lectures_taught, p.lecture_amount, p.allowance + p.bonus, p.auto_deduction + p.deduction, p.net_amount,
             p.paid_amount, p.status) for p in q.order_by(Payroll.slip_no).all()]
    return xlsx_response(f"payroll-{month:%Y-%m}.xlsx", ["Slip", "ID", "Name", "Branch", "Type", "Fixed", "Lectures",
                                                        "Lecture pay", "Allowance+Bonus", "Deductions", "Net", "Paid",
                                                        "Status"], rows)


@bp.route("/generate", methods=["POST"])
@staff_permission("salary.create")
def generate():
    month = _month(request.form.get("m"))
    branch_id = request.form.get("branch_id", type=int) if current_user.is_owner else current_user.branch_id
    if not branch_id or not db.session.get(Branch, branch_id):
        flash("Choose a branch first.", "danger")
        return redirect(url_for("payroll.index", m=f"{month:%Y-%m}"))
    ensure_branch_access(branch_id)
    created, missing = svc.generate_month(branch_id, month, current_user)
    msg = f"{len(created)} salary draft(s) created for {month:%B %Y}."
    if missing:
        msg += " Salary is not set for: " + ", ".join(p.full_name for p in missing) + "."
    flash(msg, "success" if created else "warning")
    return redirect(url_for("payroll.index", m=f"{month:%Y-%m}", branch=branch_id if current_user.is_owner else None))


# ------------------------------------------------------------------ one payroll
@bp.route("/<int:payroll_id>")
@staff_permission("salary.view")
def detail(payroll_id):
    p = _payroll(payroll_id)
    return render_template("payroll/detail.html", p=p, modes=PAYMENT_MODES, today=date.today())


@bp.route("/<int:payroll_id>/adjust", methods=["POST"])
@staff_permission("salary.edit")
def adjust(payroll_id):
    p = _payroll(payroll_id)
    return _guard(lambda: svc.update_adjustments(p, request.form.get("allowance"), request.form.get("bonus"),
                                                 request.form.get("deduction"), request.form.get("note"), current_user),
                  p, "Saved.")


@bp.route("/<int:payroll_id>/recalculate", methods=["POST"])
@staff_permission("salary.edit")
def recalculate(payroll_id):
    p = _payroll(payroll_id)
    return _guard(lambda: svc.recalculate(p, current_user), p, "Recalculated from the latest salary and attendance.")


@bp.route("/<int:payroll_id>/finalize", methods=["POST"])
@role_required(*ADMIN)
def finalize(payroll_id):
    p = _payroll(payroll_id)
    return _guard(lambda: svc.finalize(p, current_user), p, "Finalized. The salary can now be paid.")


@bp.route("/<int:payroll_id>/cancel", methods=["POST"])
@role_required(*ADMIN)
def cancel(payroll_id):
    p = _payroll(payroll_id)
    return _guard(lambda: svc.cancel_payroll(p, request.form.get("reason"), current_user), p, "Payroll cancelled.")


@bp.route("/<int:payroll_id>/pay", methods=["POST"])
@staff_permission("salary.edit")
def pay(payroll_id):
    p = _payroll(payroll_id)
    try:
        paid_on = date.fromisoformat(request.form.get("paid_on") or date.today().isoformat())
    except ValueError:
        paid_on = date.today()
    return _guard(lambda: svc.pay(p, request.form.get("amount"), request.form.get("mode"), request.form.get("reference"),
                                  paid_on, request.form.get("note"), current_user), p, "Salary payment saved.")


@bp.route("/payment/<int:payment_id>/cancel", methods=["POST"])
@role_required(*ADMIN)
def cancel_payment(payment_id):
    sp = db.get_or_404(SalaryPayment, payment_id)
    ensure_branch_access(sp.branch_id)
    return _guard(lambda: svc.cancel_salary_payment(sp, request.form.get("reason"), current_user), sp.payroll,
                  "Salary payment cancelled.")


# ------------------------------------------------------------------ slips
def _own_person_ids():
    t = Teacher.query.filter_by(user_id=current_user.id).first()
    s = Staff.query.filter_by(user_id=current_user.id).first()
    return (t.id if t else 0), (s.id if s else 0)


def _can_see_slip(p):
    if current_user.role_name in ("owner", "branch_admin", "accountant"):
        if current_user.has_permission("salary.view") and (current_user.is_owner or current_user.branch_id == p.branch_id):
            return True
    tid, sid = _own_person_ids()
    return p.status in ("finalized", "paid") and ((p.teacher_id and p.teacher_id == tid) or (p.staff_id and p.staff_id == sid))


def _slip(payroll_id):
    p = db.get_or_404(Payroll, payroll_id)
    if not _can_see_slip(p):
        abort(403)
    return p


@bp.route("/<int:payroll_id>/slip")
@login_required
def slip(payroll_id):
    return render_template("payroll/slip.html", p=_slip(payroll_id))


@bp.route("/<int:payroll_id>/slip.pdf")
@login_required
def slip_pdf(payroll_id):
    p = _slip(payroll_id)
    return Response(build_salary_slip_pdf(p), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{p.slip_no}.pdf"'})


@bp.route("/my")
@role_required("teacher", "accountant")
def my():
    tid, sid = _own_person_ids()
    items = (Payroll.query.filter(Payroll.status.in_(("finalized", "paid")))
             .filter((Payroll.teacher_id == tid) if tid else (Payroll.staff_id == sid))
             .order_by(Payroll.month.desc()).all())
    return render_template("payroll/my.html", items=items)


# ------------------------------------------------------------------ salary setup
@bp.route("/structures")
@staff_permission("salary.view")
def structures():
    branch_id = request.args.get("branch", type=int) if current_user.is_owner else current_user.branch_id
    tq = scope_to_branch(Teacher.query.filter_by(status="active"), Teacher)
    sq = scope_to_branch(Staff.query.filter_by(status="active"), Staff)
    if current_user.is_owner and branch_id:
        tq, sq = tq.filter(Teacher.branch_id == branch_id), sq.filter(Staff.branch_id == branch_id)
    rows = []
    for kind, people in (("teacher", tq.order_by(Teacher.full_name).all()), ("staff", sq.order_by(Staff.full_name).all())):
        for person in people:
            rows.append({"kind": kind, "person": person, "st": svc.structure_for(kind, person)})
    return render_template("payroll/structures.html", rows=rows, branch_id=branch_id,
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [],
                           pay_types=dict(PAY_TYPES))


@bp.route("/structures/<kind>/<int:person_id>", methods=["GET", "POST"])
@role_required(*ADMIN)
def structure_edit(kind, person_id):
    if kind not in ("teacher", "staff"):
        abort(404)
    person = db.get_or_404(Teacher if kind == "teacher" else Staff, person_id)
    ensure_branch_access(person.branch_id)
    st = svc.structure_for(kind, person)
    if request.method == "POST":
        try:
            svc.save_structure(kind, person, request.form.get("pay_type"), request.form.get("base_salary"),
                               request.form.get("per_lecture_rate"), request.form.get("missed_deduction"), current_user)
            flash("Salary saved. It applies to payroll created from now on.", "success")
            return redirect(url_for("payroll.structures"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("payroll/structure_form.html", kind=kind, person=person, st=st,
                           pay_types=PAY_TYPES if kind == "teacher" else [PAY_TYPES[0]])
