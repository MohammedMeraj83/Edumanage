from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from extensions import db
from app.models import (Teacher, Staff, SalaryStructure, Payroll, SalaryPayment, LectureSession, Branch)
from app.services import attendance_service as att
from app.services.audit_service import log_action
from app.services.fee_service import money, MODES
from app.models import CASHLESS
from app.utils.numbering import next_slip_no

ZERO = Decimal("0.00")


def month_start(d):
    return d.replace(day=1)


def month_end(d):
    return d.replace(day=monthrange(d.year, d.month)[1])


# ------------------------------------------------------------------ structures
def structure_for(kind, person):
    col = SalaryStructure.teacher_id if kind == "teacher" else SalaryStructure.staff_id
    return SalaryStructure.query.filter(col == person.id).first()


def save_structure(kind, person, pay_type, base, rate, missed_deduction, user):
    base, rate = money(base or 0), money(rate or 0)
    missed_deduction = money(missed_deduction or 0)
    if min(base, rate, missed_deduction) < 0:
        raise ValueError("Amounts cannot be negative.")
    if kind == "staff" and pay_type != "fixed":
        raise ValueError("Staff are paid a fixed monthly salary.")
    if pay_type == "fixed":
        if base <= 0:
            raise ValueError("Enter the monthly salary.")
        rate = ZERO
    elif pay_type == "per_lecture":
        if rate <= 0:
            raise ValueError("Enter the amount paid per lecture.")
        base = ZERO
    elif pay_type == "mixed":
        if base <= 0 or rate <= 0:
            raise ValueError("Enter both the monthly salary and the amount per lecture.")
    else:
        raise ValueError("Choose how this person is paid.")
    if kind == "staff":
        missed_deduction = ZERO
    st = structure_for(kind, person)
    if st is None:
        st = SalaryStructure(**{f"{kind}_id": person.id})
        db.session.add(st)
    st.pay_type, st.base_salary, st.per_lecture_rate = pay_type, base, rate
    st.missed_lecture_deduction, st.updated_by = missed_deduction, user.id
    db.session.flush()
    log_action("salary_structure", "salary_structures", st.id,
               f"{person.employee_code}: {pay_type} base {base} rate {rate} missed {missed_deduction}", user=user)
    db.session.commit()
    return st


# ------------------------------------------------------------------ attendance numbers
def ensure_month_sessions(month, branch_id):
    """Make sure every past day of the month has its lecture sessions (nobody may have opened the board)."""
    last = min(month_end(month), date.today())
    day = month
    while day <= last:
        att.ensure_sessions(day, branch_id=branch_id)
        day += timedelta(days=1)


def lecture_numbers(teacher, month, now=None):
    """(taught, missed) for one teacher in one month. A lecture counts as taught when the teacher started it."""
    now = now or datetime.utcnow()
    sessions = LectureSession.query.filter(
        LectureSession.teacher_id == teacher.id, LectureSession.lecture_date >= month,
        LectureSession.lecture_date <= month_end(month), LectureSession.cancelled.is_(False)).all()
    taught = missed = 0
    for s in sessions:
        if s.checkin_at:
            taught += 1
        elif att.session_state(s, now)[0] == "missed":
            missed += 1
    return taught, missed


# ------------------------------------------------------------------ building payroll
def _fill(p, st, person, month):
    p.pay_type, p.base_amount, p.lecture_rate = st.pay_type, st.base_salary, st.per_lecture_rate
    p.missed_rate = st.missed_lecture_deduction
    if p.teacher_id:
        taught, missed = lecture_numbers(person, month)
    else:
        taught = missed = 0
    p.lectures_taught, p.lectures_missed = taught, missed
    p.lecture_amount = (Decimal(st.per_lecture_rate or 0) * taught).quantize(Decimal("0.01")) if st.pay_type != "fixed" else ZERO
    p.auto_deduction = (Decimal(st.missed_lecture_deduction or 0) * missed).quantize(Decimal("0.01"))

    # SQLAlchemy column defaults are applied during INSERT, not necessarily
    # when the Payroll object is first created. Set optional amounts explicitly.
    p.allowance = p.allowance if p.allowance is not None else ZERO
    p.bonus = p.bonus if p.bonus is not None else ZERO
    p.deduction = p.deduction if p.deduction is not None else ZERO

    p.net_amount = p.compute_net()


def build_payroll(kind, person, month, user):
    st = structure_for(kind, person)
    if st is None:
        raise ValueError(f"Set the salary of {person.full_name} first.")
    month = month_start(month)
    col = Payroll.teacher_id if kind == "teacher" else Payroll.staff_id
    if Payroll.query.filter(col == person.id, Payroll.month == month).first():
        raise ValueError("Payroll for this month already exists.")
    branch = db.session.get(Branch, person.branch_id)
    for _ in range(3):
        try:
            p = Payroll(slip_no=next_slip_no(branch, month), branch_id=person.branch_id, month=month,
                        created_by=user.id, status="draft", **{f"{kind}_id": person.id})
            _fill(p, st, person, month)
            db.session.add(p)
            db.session.flush()
            log_action("payroll_create", "payrolls", p.id, f"{person.employee_code} {month:%b %Y}: net {p.net_amount}", user=user)
            db.session.commit()
            return p
        except IntegrityError:
            db.session.rollback()
    raise RuntimeError("Could not create a unique slip number. Please try again.")


def generate_month(branch_id, month, user):
    """Draft payroll for every active teacher / staff member who has a salary set and none for this month yet."""
    month = month_start(month)
    ensure_month_sessions(month, branch_id)
    created, no_structure = [], []
    people = [("teacher", t) for t in Teacher.query.filter_by(branch_id=branch_id, status="active").all()]
    people += [("staff", s) for s in Staff.query.filter_by(branch_id=branch_id, status="active").all()]
    for kind, person in people:
        if person.joining_date > month_end(month):
            continue
        col = Payroll.teacher_id if kind == "teacher" else Payroll.staff_id
        if Payroll.query.filter(col == person.id, Payroll.month == month).first():
            continue
        if structure_for(kind, person) is None:
            no_structure.append(person)
            continue
        created.append(build_payroll(kind, person, month, user))
    return created, no_structure


def recalculate(p, user):
    if p.status != "draft":
        raise ValueError("Only a draft can be recalculated.")
    st = structure_for(p.kind, p.person)
    if st is None:
        raise ValueError("This person has no salary set.")
    ensure_month_sessions(p.month, p.branch_id)
    _fill(p, st, p.person, p.month)
    log_action("payroll_recalc", "payrolls", p.id, p.slip_no, user=user)
    db.session.commit()


def update_adjustments(p, allowance, bonus, deduction, note, user):
    if p.status != "draft":
        raise ValueError("Only a draft can be changed.")
    a, b, d = money(allowance or 0), money(bonus or 0), money(deduction or 0)
    note = (note or "").strip()[:250] or None
    if min(a, b, d) < 0:
        raise ValueError("Amounts cannot be negative.")
    if d > 0 and not note:
        raise ValueError("Write the reason for the deduction in the note.")
    net = (Decimal(p.base_amount) + Decimal(p.lecture_amount) + a + b - Decimal(p.auto_deduction) - d)
    if net < 0:
        raise ValueError("The deductions are more than the salary.")
    p.allowance, p.bonus, p.deduction, p.adjustment_note, p.net_amount = a, b, d, note, net     # only after every check
    log_action("payroll_edit", "payrolls", p.id, f"{p.slip_no}: +{a + b} -{d}", user=user)
    db.session.commit()


def finalize(p, user):
    if p.status != "draft":
        raise ValueError("Only a draft can be finalized.")
    p.net_amount = p.compute_net()
    if p.net_amount <= 0:
        raise ValueError("The net salary is zero. Cancel this payroll instead.")
    p.status, p.finalized_by, p.finalized_at = "finalized", user.id, datetime.utcnow()
    log_action("payroll_finalize", "payrolls", p.id, f"{p.slip_no}: net {p.net_amount}", user=user)
    db.session.commit()


def cancel_payroll(p, reason, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Write the reason.")
    if p.status in ("cancelled",):
        raise ValueError("Already cancelled.")
    if any(sp.status == "active" for sp in p.payments):
        raise ValueError("Money was already paid. Cancel those payments first.")
    p.status, p.cancel_reason = "cancelled", reason[:200]
    log_action("payroll_cancel", "payrolls", p.id, f"{p.slip_no}: {reason}", user=user)
    db.session.commit()


def recalc_paid(p):
    total = db.session.query(db.func.coalesce(db.func.sum(SalaryPayment.amount), 0)).filter_by(
        payroll_id=p.id, status="active"
    ).scalar()
    p.paid_amount = Decimal(total)
    if p.status in ("finalized", "paid"):
        p.status = "paid" if p.paid_amount >= Decimal(p.net_amount) else "finalized"
    db.session.expire(p, ["payments"])


def pay(p, amount, mode, reference, paid_on, note, user):
    if p.status != "finalized":
        raise ValueError("Salary can be paid only after the payroll is finalized." if p.status == "draft"
                         else "This salary is not open for payment.")
    amount = money(amount)
    if amount <= 0:
        raise ValueError("The amount must be more than zero.")
    if amount > p.balance:
        raise ValueError(f"Only ₹{p.balance} is left to pay.")
    if mode not in MODES:
        raise ValueError("Choose how it was paid.")
    reference = (reference or "").strip() or None
    if mode in CASHLESS and not reference:
        raise ValueError("Enter the transaction / cheque number for this payment mode.")
    if paid_on > date.today():
        raise ValueError("The date cannot be in the future.")
    sp = SalaryPayment(payroll_id=p.id, branch_id=p.branch_id, amount=amount, mode=mode, reference=reference,
                       paid_on=paid_on, paid_by=user.id, note=(note or "").strip()[:200] or None)
    db.session.add(sp)
    db.session.flush()
    recalc_paid(p)
    log_action("salary_paid", "salary_payments", sp.id, f"{p.slip_no}: {amount} by {mode}", user=user)
    db.session.commit()
    return sp


def cancel_salary_payment(sp, reason, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Write the reason.")
    if sp.status != "active":
        raise ValueError("Already cancelled.")
    sp.status, sp.cancel_reason = "cancelled", reason[:200]
    db.session.flush()
    recalc_paid(sp.payroll)
    log_action("salary_payment_cancel", "salary_payments", sp.id, f"{sp.payroll.slip_no}: {reason}", user=user)
    db.session.commit()
