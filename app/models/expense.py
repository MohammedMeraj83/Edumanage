from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

DEFAULT_CATEGORIES = ["Rent", "Electricity", "Internet & phone", "Stationery & printing", "Repairs & maintenance",
                      "Marketing", "Cleaning & supplies", "Travel", "Other"]


class ExpenseCategory(db.Model):
    __tablename__ = "expense_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class Expense(TimestampMixin, db.Model):
    """Money the branch spent (not salary - salary is paid through payroll). Never deleted, only cancelled."""
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("expense_categories.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(250), nullable=False)
    vendor = db.Column(db.String(120))
    mode = db.Column(db.String(10), nullable=False)
    reference = db.Column(db.String(80))
    bill_file = db.Column(db.String(255))
    bill_name = db.Column(db.String(255))
    status = db.Column(db.String(10), default="active", nullable=False, index=True)     # active | cancelled
    cancel_reason = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancelled_at = db.Column(db.DateTime)

    branch = db.relationship("Branch", lazy="joined")
    category = db.relationship("ExpenseCategory", lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
