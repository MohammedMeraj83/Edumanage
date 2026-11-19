from datetime import date, datetime
from extensions import db
from sqlalchemy import func
from app.models import Expense, ExpenseCategory, DEFAULT_CATEGORIES
from app.services.audit_service import log_action
from app.services.fee_service import money, MODES
from app.utils.file_upload import save_document, delete_upload


def ensure_default_categories():
    if ExpenseCategory.query.count() == 0:
        for name in DEFAULT_CATEGORIES:
            db.session.add(ExpenseCategory(name=name))
        db.session.commit()


def save_category(name, category=None, user=None):
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ValueError("Enter a category name (up to 80 characters).")
    clash = ExpenseCategory.query.filter(func.lower(ExpenseCategory.name) == name.lower())
    if category:
        clash = clash.filter(ExpenseCategory.id != category.id)
    if clash.first():
        raise ValueError("This category already exists.")
    if category is None:
        category = ExpenseCategory(name=name)
        db.session.add(category)
    else:
        category.name = name
    db.session.flush()
    log_action("category_save", "expense_categories", category.id, name, user=user)
    db.session.commit()
    return category


def create_expense(branch_id, category_id, amount, expense_date, description, vendor, mode, reference, bill, user):
    amount = money(amount)
    if amount <= 0:
        raise ValueError("The amount must be more than zero.")
    category = db.session.get(ExpenseCategory, category_id or 0)
    if not category or not category.is_active:
        raise ValueError("Choose a category.")
    if mode not in MODES:
        raise ValueError("Choose how it was paid.")
    if expense_date > date.today():
        raise ValueError("The date cannot be in the future.")
    description = (description or "").strip()
    if not description:
        raise ValueError("Write what the money was spent on.")
    stored = original = None
    if bill is not None and getattr(bill, "filename", ""):
        stored, original, _ = save_document(bill)
    exp = Expense(branch_id=branch_id, category_id=category.id, amount=amount, expense_date=expense_date,
                  description=description[:250], vendor=(vendor or "").strip()[:120] or None, mode=mode,
                  reference=(reference or "").strip()[:80] or None, bill_file=stored, bill_name=original,
                  created_by=user.id)
    db.session.add(exp)
    db.session.flush()
    log_action("expense", "expenses", exp.id, f"{category.name}: {amount} - {description[:60]}", user=user)
    db.session.commit()
    return exp


def cancel_expense(exp, reason, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Write the reason for cancelling this expense.")
    if exp.status != "active":
        raise ValueError("This expense is already cancelled.")
    exp.status, exp.cancel_reason = "cancelled", reason[:200]
    exp.cancelled_by, exp.cancelled_at = user.id, datetime.utcnow()
    log_action("expense_cancel", "expenses", exp.id, f"{exp.category.name} {exp.amount}: {reason}", user=user)
    db.session.commit()
