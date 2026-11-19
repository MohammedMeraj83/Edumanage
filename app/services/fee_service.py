import math
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from extensions import db
from app.models import (FeeDue, Payment, PaymentAllocation, Refund, BatchStudent, InstituteSetting, AcademicSession,
                        Branch, CASHLESS, PAYMENT_MODES)
from app.services.audit_service import log_action
from app.utils.numbering import next_receipt_no, next_refund_no

MODES = {m for m, _ in PAYMENT_MODES}
ZERO = Decimal("0.00")


def money(value):
    """Parse text/number into a 2-decimal Decimal or raise ValueError."""
    try:
        d = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, AttributeError):
        raise ValueError("Enter the amount as a number.")
    if d.is_nan() or d.is_infinite():
        raise ValueError("Enter the amount as a number.")
    return d.quantize(Decimal("0.01"))


# ------------------------------------------------------------------ settings
def get_setting(key, default=None):
    row = InstituteSetting.query.filter_by(key=key).first()
    return row.value if row and row.value not in (None, "") else default


def set_setting(key, value):
    row = InstituteSetting.query.filter_by(key=key).first()
    if row is None:
        row = InstituteSetting(key=key)
        db.session.add(row)
    row.value = str(value)


def due_day():
    try:
        return min(max(int(get_setting("fee_due_day", 5)), 1), 28)
    except (TypeError, ValueError):
        return 5


def save_due_day(day, user):
    day = int(day)
    if not 1 <= day <= 28:
        raise ValueError("Choose a day between 1 and 28.")
    set_setting("fee_due_day", day)
    log_action("fee_settings", "institute_settings", None, f"Fee due day set to {day}", user=user)
    db.session.commit()


# ------------------------------------------------------------------ generating dues
def _months_between(start, end):
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _add_months(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def plan_dues(enr, style):
    """List of dicts (label, due_date, amount, kind, period_key) for an enrollment."""
    batch, fee = enr.batch, Decimal(enr.fee_amount)
    if fee <= 0:
        return []
    start = enr.enrolled_on
    end = batch.end_date or batch.session.end_date
    if end < start:
        end = start
    months = max(1, min(_months_between(start, end), 24))
    freq, day = batch.fee_frequency, due_day()
    if freq == "one_time":
        return [dict(label=f"{batch.name} · Fee", due_date=start, amount=fee, kind="one_time", period_key="one_time")]
    if freq == "yearly":
        return [dict(label=f"{batch.name} · {batch.session.name}", due_date=start, amount=fee, kind="yearly",
                     period_key="yearly")]
    if freq == "quarterly":
        periods = math.ceil(months / 3)
        if style == "full":
            return [dict(label=f"{batch.name} · Full fee ({periods} quarters)", due_date=start, amount=fee * periods,
                         kind="full", period_key="full")]
        out = []
        for i in range(periods):
            first = _add_months(start.replace(day=1), i * 3)
            last = _add_months(first, 2)
            d = max(date(first.year, first.month, day), start) if i == 0 else date(first.year, first.month, day)
            out.append(dict(label=f"{batch.name} · {first:%b}–{last:%b %Y}", due_date=d, amount=fee,
                            kind="quarterly", period_key=f"Q{i + 1}"))
        return out
    # monthly
    if style == "full":
        return [dict(label=f"{batch.name} · Full fee ({months} months)", due_date=start, amount=fee * months,
                     kind="full", period_key="full")]
    out = []
    for i in range(months):
        first = _add_months(start.replace(day=1), i)
        d = date(first.year, first.month, day)
        if i == 0:
            d = max(d, start)
        out.append(dict(label=f"{batch.name} · {first:%b %Y}", due_date=d, amount=fee, kind="monthly",
                        period_key=f"{first:%Y-%m}"))
    return out


def generate_dues(enr, style="monthly", user=None, discount=ZERO):
    """Create the dues of an enrollment. Safe to call twice: existing periods are skipped."""
    if style not in ("monthly", "full"):
        raise ValueError("Unknown payment style.")
    existing = {k for (k,) in db.session.query(FeeDue.period_key).filter_by(enrollment_id=enr.id)}
    created = []
    student = enr.student
    for item in plan_dues(enr, style):
        # a 'full' due replaces monthly ones and vice-versa, so only one style can exist per enrollment
        if item["period_key"] in existing or (existing and "full" in existing) or (item["kind"] == "full" and existing):
            continue
        due = FeeDue(branch_id=student.branch_id, student_id=student.id, enrollment_id=enr.id, batch_id=enr.batch_id,
                     session_id=enr.batch.session_id, created_by=user.id if user else None, **item)
        if item["kind"] == "full" and discount and discount > 0:
            due.discount = min(discount, due.amount)
            due.discount_reason = "Discount for paying the full fee"
        db.session.add(due)
        created.append(due)
    if created:
        log_action("fees_generated", "fee_dues", enr.id,
                   f"{student.student_code}: {len(created)} due(s) for {enr.batch.name} ({style})", user=user)
    return created


def cancel_future_dues(enr, reason="Left the batch"):
    """When a student leaves: dues that are not yet due and have no payment are cancelled."""
    n = 0
    for due in FeeDue.query.filter_by(enrollment_id=enr.id, status="pending").all():
        if due.paid == 0 and due.due_date > date.today():
            due.status, due.cancel_reason = "cancelled", reason
            n += 1
    return n


def add_charge(student, label, amount, due_date, user):
    amount = money(amount)
    if amount <= 0:
        raise ValueError("The amount must be more than zero.")
    label = (label or "").strip()
    if not label:
        raise ValueError("Write what the charge is for (for example: Late fee, Books, Test series).")
    session = AcademicSession.query.filter_by(is_current=True).first()
    if not session:
        raise ValueError("Set a current academic session first.")
    due = FeeDue(branch_id=student.branch_id, student_id=student.id, session_id=session.id, kind="custom",
                 label=label[:200], due_date=due_date, amount=amount, created_by=user.id)
    db.session.add(due)
    db.session.flush()
    log_action("charge_added", "fee_dues", due.id, f"{student.student_code}: {label} {amount}", user=user)
    db.session.commit()
    return due


# ------------------------------------------------------------------ keeping dues consistent
def recalc_due(due):
    total = (db.session.query(func.coalesce(func.sum(PaymentAllocation.amount - PaymentAllocation.refunded), 0))
             .join(Payment, Payment.id == PaymentAllocation.payment_id)
             .filter(PaymentAllocation.due_id == due.id, Payment.status == "active").scalar())
    due.paid = Decimal(total).quantize(Decimal("0.01"))
    if due.status != "cancelled":
        if due.paid <= 0:
            due.status = "pending"
        elif due.paid < due.net:
            due.status = "partial"
        else:
            due.status = "paid"


def outstanding(student):
    """Dues with something left to pay, oldest first."""
    dues = (FeeDue.query.filter(FeeDue.student_id == student.id, FeeDue.status.in_(("pending", "partial")))
            .order_by(FeeDue.due_date, FeeDue.id).all())
    return [d for d in dues if d.balance > 0]


def student_totals(student):
    dues = FeeDue.query.filter(FeeDue.student_id == student.id, FeeDue.status != "cancelled").all()
    billed = sum((d.net for d in dues), ZERO)
    paid = sum((Decimal(d.paid) for d in dues), ZERO)
    overdue = sum((d.balance for d in dues if d.overdue), ZERO)
    return {"billed": billed, "paid": paid, "balance": billed - paid, "overdue": overdue}


# ------------------------------------------------------------------ taking money
def collect_payment(student, due_ids, amount, mode, reference, paid_on, note, user, token=None):
    """Spread `amount` over the chosen dues, oldest first. Returns the Payment (an existing one if the same
    form was sent twice)."""
    token = (token or "").strip() or None
    if token:
        again = Payment.query.filter_by(client_token=token).first()
        if again:
            return again
    amount = money(amount)
    if amount <= 0:
        raise ValueError("The amount must be more than zero.")
    if mode not in MODES:
        raise ValueError("Choose how the money was paid.")
    reference = (reference or "").strip() or None
    if mode in CASHLESS and not reference:
        raise ValueError("Enter the transaction / cheque number for this payment mode.")
    today = date.today()
    if paid_on > today:
        raise ValueError("The payment date cannot be in the future.")
    if paid_on < today - timedelta(days=30) and user.role_name not in ("owner", "branch_admin"):
        raise ValueError("Only the branch admin can enter payments older than 30 days.")
    dues = [d for d in outstanding(student) if d.id in set(due_ids)]
    if not dues:
        raise ValueError("Select at least one due to pay.")
    due_total = sum((d.balance for d in dues), ZERO)
    if amount > due_total:
        raise ValueError(f"The amount is more than the selected dues (₹{due_total}). Select more dues or reduce the amount.")
    session = AcademicSession.query.filter_by(is_current=True).first()
    branch = db.session.get(Branch, student.branch_id)

    for _ in range(3):
        try:
            payment = Payment(receipt_no=next_receipt_no(branch, session), branch_id=student.branch_id,
                              student_id=student.id, session_id=session.id, amount=amount, mode=mode,
                              reference=reference, paid_on=paid_on, received_by=user.id,
                              note=(note or "").strip()[:200] or None, client_token=token)
            db.session.add(payment)
            db.session.flush()
            left = amount
            for due in dues:
                if left <= 0:
                    break
                part = min(left, due.balance)
                db.session.add(PaymentAllocation(payment_id=payment.id, due_id=due.id, amount=part))
                db.session.flush()
                recalc_due(due)
                left -= part
            log_action("payment", "payments", payment.id,
                       f"{payment.receipt_no}: {student.student_code} paid {amount} by {mode}", user=user)
            db.session.commit()
            return payment
        except IntegrityError:
            db.session.rollback()
            again = token and Payment.query.filter_by(client_token=token).first()
            if again:
                return again
            student = db.session.get(type(student), student.id)
            dues = [db.session.get(FeeDue, d.id) for d in dues]
    raise RuntimeError("Could not create a unique receipt number. Please try again.")


def cancel_payment(payment, reason, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Write the reason for cancelling this payment.")
    if payment.status != "active":
        raise ValueError("This payment is already cancelled.")
    if payment.refunded_amount > 0:
        raise ValueError("This payment has refunds. It cannot be cancelled.")
    payment.status, payment.cancel_reason = "cancelled", reason[:200]
    payment.cancelled_by, payment.cancelled_at = user.id, datetime.utcnow()
    db.session.flush()
    for alloc in payment.allocations:
        recalc_due(alloc.due)
    log_action("payment_cancel", "payments", payment.id, f"{payment.receipt_no}: {reason}", user=user)
    db.session.commit()


def refund_payment(payment, amount, mode, reason, user, refunded_on=None):
    amount = money(amount)
    reason = (reason or "").strip()
    if payment.status != "active":
        raise ValueError("A cancelled payment cannot be refunded.")
    if amount <= 0:
        raise ValueError("The refund amount must be more than zero.")
    if amount > payment.net_amount:
        raise ValueError(f"You can refund at most ₹{payment.net_amount} of this payment.")
    if mode not in MODES:
        raise ValueError("Choose how the refund is paid.")
    if not reason:
        raise ValueError("Write the reason for the refund.")
    left = amount
    for alloc in sorted(payment.allocations, key=lambda a: (a.due.due_date, a.id), reverse=True):   # latest due first
        room = Decimal(alloc.amount) - Decimal(alloc.refunded)
        take = min(room, left)
        if take > 0:
            alloc.refunded = Decimal(alloc.refunded) + take
            left -= take
        if left <= 0:
            break
    db.session.flush()
    for alloc in payment.allocations:
        recalc_due(alloc.due)
    payment.refunded_amount = Decimal(payment.refunded_amount) + amount
    branch = db.session.get(Branch, payment.branch_id)
    session = db.session.get(AcademicSession, payment.session_id)
    for _ in range(3):
        try:
            refund = Refund(refund_no=next_refund_no(branch, session), payment_id=payment.id,
                            student_id=payment.student_id, branch_id=payment.branch_id, amount=amount, mode=mode,
                            reason=reason[:200], refunded_on=refunded_on or date.today(), processed_by=user.id)
            db.session.add(refund)
            db.session.flush()
            log_action("refund", "refunds", refund.id, f"{refund.refund_no}: {payment.receipt_no} {amount}", user=user)
            db.session.commit()
            return refund
        except IntegrityError:
            db.session.rollback()
    raise RuntimeError("Could not create a unique refund number. Please try again.")


def apply_discount(due, discount, reason, user):
    discount = money(discount)
    if discount < 0 or discount > Decimal(due.amount):
        raise ValueError("The discount must be between zero and the full amount of the due.")
    if Decimal(due.amount) - discount < Decimal(due.paid):
        raise ValueError(f"₹{due.paid} is already paid on this due. The discount cannot be that large.")
    if discount > 0 and not (reason or "").strip():
        raise ValueError("Write the reason for the discount.")
    due.discount, due.discount_reason = discount, (reason or "").strip()[:200] or None
    recalc_due(due)
    log_action("discount", "fee_dues", due.id, f"{due.student.student_code}: {due.label} discount {discount}", user=user)
    db.session.commit()


def cancel_due(due, reason, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Write the reason.")
    if due.paid > 0:
        raise ValueError("Money is already paid on this due. Refund it first.")
    due.status, due.cancel_reason = "cancelled", reason[:200]
    log_action("due_cancel", "fee_dues", due.id, f"{due.student.student_code}: {due.label}: {reason}", user=user)
    db.session.commit()


# ------------------------------------------------------------------ dashboards
def collection_between(start, end, branch_id=None):
    q = db.session.query(func.coalesce(func.sum(Payment.amount - Payment.refunded_amount), 0)).filter(
        Payment.status == "active", Payment.paid_on >= start, Payment.paid_on <= end)
    if branch_id:
        q = q.filter(Payment.branch_id == branch_id)
    return Decimal(q.scalar()).quantize(Decimal("0.01"))


def outstanding_total(branch_id=None):
    q = FeeDue.query.filter(FeeDue.status.in_(("pending", "partial")))
    if branch_id:
        q = q.filter(FeeDue.branch_id == branch_id)
    dues = q.all()
    total = sum((d.balance for d in dues), ZERO)
    overdue = [d for d in dues if d.overdue]
    return total, sum((d.balance for d in overdue), ZERO), len({d.student_id for d in overdue})


def generate_missing_dues(branch_id=None, user=None):
    """For enrollments that existed before fees were switched on (or whose dues were never made)."""
    q = BatchStudent.query.filter_by(status="active")
    n = 0
    for enr in q.all():
        if branch_id and enr.student.branch_id != branch_id:
            continue
        if FeeDue.query.filter_by(enrollment_id=enr.id).first():
            continue
        n += len(generate_dues(enr, "monthly", user))
    db.session.commit()
    return n
