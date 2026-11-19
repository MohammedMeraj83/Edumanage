from datetime import datetime
from decimal import Decimal
from extensions import db
from .mixins import TimestampMixin

PAY_TYPES = [("fixed", "Fixed monthly salary"), ("per_lecture", "Per lecture"),
             ("mixed", "Fixed salary + per lecture")]
PAYROLL_STATUSES = ("draft", "finalized", "paid", "cancelled")


class SalaryStructure(TimestampMixin, db.Model):
    """How one teacher / staff member is paid. Payroll copies these numbers each month, so changing
    them only affects future months."""
    __tablename__ = "salary_structures"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), unique=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), unique=True)
    pay_type = db.Column(db.String(12), nullable=False)
    base_salary = db.Column(db.Numeric(10, 2), default=0, nullable=False)           # per month
    per_lecture_rate = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    missed_lecture_deduction = db.Column(db.Numeric(10, 2), default=0, nullable=False)   # per missed lecture
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    teacher = db.relationship("Teacher", lazy="joined")
    staff = db.relationship("Staff", lazy="joined")


class Payroll(TimestampMixin, db.Model):
    """One person's salary for one month."""
    __tablename__ = "payrolls"
    __table_args__ = (db.UniqueConstraint("teacher_id", "month", name="uq_payroll_teacher_month"),
                      db.UniqueConstraint("staff_id", "month", name="uq_payroll_staff_month"))

    id = db.Column(db.Integer, primary_key=True)
    slip_no = db.Column(db.String(30), unique=True, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), index=True)
    month = db.Column(db.Date, nullable=False, index=True)                           # always the 1st of the month
    pay_type = db.Column(db.String(12), nullable=False)

    base_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    lectures_taught = db.Column(db.Integer, default=0, nullable=False)
    lecture_rate = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    lecture_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    lectures_missed = db.Column(db.Integer, default=0, nullable=False)
    missed_rate = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    auto_deduction = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    allowance = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    bonus = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    deduction = db.Column(db.Numeric(10, 2), default=0, nullable=False)              # entered by hand
    adjustment_note = db.Column(db.String(250))
    net_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    paid_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)

    status = db.Column(db.String(10), default="draft", nullable=False, index=True)
    finalized_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    finalized_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", lazy="joined")
    teacher = db.relationship("Teacher", lazy="joined")
    staff = db.relationship("Staff", lazy="joined")
    payments = db.relationship("SalaryPayment", back_populates="payroll", order_by="SalaryPayment.created_at")

    @property
    def person(self):
        return self.teacher or self.staff

    @property
    def kind(self):
        return "teacher" if self.teacher_id else "staff"

    @property
    def balance(self):
        return max(Decimal(self.net_amount) - Decimal(self.paid_amount), Decimal(0))

    def compute_net(self):
        """Return net salary safely, treating unset optional amounts as zero."""
        def amount(value):
            return Decimal(str(value if value is not None else 0))

        total = (
            amount(self.base_amount)
            + amount(self.lecture_amount)
            + amount(self.allowance)
            + amount(self.bonus)
            - amount(self.auto_deduction)
            - amount(self.deduction)
        )
        return total.quantize(Decimal("0.01"))


class SalaryPayment(db.Model):
    __tablename__ = "salary_payments"

    id = db.Column(db.Integer, primary_key=True)
    payroll_id = db.Column(db.Integer, db.ForeignKey("payrolls.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    mode = db.Column(db.String(10), nullable=False)
    reference = db.Column(db.String(80))
    paid_on = db.Column(db.Date, nullable=False, index=True)
    paid_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    note = db.Column(db.String(200))
    status = db.Column(db.String(10), default="active", nullable=False)             # active | cancelled
    cancel_reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payroll = db.relationship("Payroll", back_populates="payments")
    payer = db.relationship("User", foreign_keys=[paid_by])
