from datetime import date
from decimal import Decimal
from sqlalchemy import func
from extensions import db
from app.models import Payment, Expense, ExpenseCategory, SalaryPayment, Branch, PAYMENT_MODES

ZERO = Decimal("0.00")


def _d(v):
    return Decimal(v or 0).quantize(Decimal("0.01"))


def summary(start, end, branch_id=None):
    """Cash-basis money in and out between two dates."""
    pq = db.session.query(Payment.mode, func.sum(Payment.amount - Payment.refunded_amount)).filter(
        Payment.status == "active", Payment.paid_on >= start, Payment.paid_on <= end)
    eq = db.session.query(ExpenseCategory.name, func.sum(Expense.amount)).join(
        Expense, Expense.category_id == ExpenseCategory.id).filter(
        Expense.status == "active", Expense.expense_date >= start, Expense.expense_date <= end)
    sq = db.session.query(func.sum(SalaryPayment.amount)).filter(
        SalaryPayment.status == "active", SalaryPayment.paid_on >= start, SalaryPayment.paid_on <= end)
    if branch_id:
        pq, eq, sq = (pq.filter(Payment.branch_id == branch_id), eq.filter(Expense.branch_id == branch_id),
                      sq.filter(SalaryPayment.branch_id == branch_id))
    by_mode = {m: _d(v) for m, v in pq.group_by(Payment.mode).all()}
    by_cat = sorted(((n, _d(v)) for n, v in eq.group_by(ExpenseCategory.name).all()), key=lambda x: -x[1])
    salary = _d(sq.scalar())
    income = sum(by_mode.values(), ZERO)
    spent = sum((v for _, v in by_cat), ZERO)
    return {"income": income, "by_mode": [(label, by_mode.get(m, ZERO)) for m, label in PAYMENT_MODES if by_mode.get(m)],
            "expenses": spent, "by_category": by_cat, "salary": salary, "total_out": spent + salary,
            "profit": income - spent - salary}


def monthly_series(end_month, count=6, branch_id=None):
    """[(label, income, expenses incl. salary)] for the last `count` months ending at end_month."""
    out = []
    y, m = end_month.year, end_month.month
    months = []
    for _ in range(count):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    for first in reversed(months):
        last = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
        from datetime import timedelta
        s = summary(first, last - timedelta(days=1), branch_id)
        out.append((first.strftime("%b %Y"), s["income"], s["total_out"]))
    return out


def branch_comparison(start, end):
    rows = []
    for b in Branch.query.order_by(Branch.name).all():
        s = summary(start, end, b.id)
        rows.append({"branch": b, **s})
    return rows
