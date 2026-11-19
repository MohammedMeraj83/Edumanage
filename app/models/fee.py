from datetime import date, datetime
from decimal import Decimal
from extensions import db
from .mixins import TimestampMixin

PAYMENT_MODES = [("cash", "Cash"), ("upi", "UPI"), ("card", "Card"), ("bank", "Bank transfer"), ("cheque", "Cheque")]
CASHLESS = {"upi", "card", "bank", "cheque"}            # these need a reference / transaction number
PAY_STYLES = [("monthly", "Pay as we go (monthly / per period)"), ("full", "Pay the whole fee now")]


class FeeDue(TimestampMixin, db.Model):
    """One amount a student must pay: a month of a batch, a full-course fee, or a custom charge."""
    __tablename__ = "fee_dues"
    __table_args__ = (db.UniqueConstraint("enrollment_id", "period_key", name="uq_due_enrollment_period"),)

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("batch_students.id"), index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False)
    kind = db.Column(db.String(12), nullable=False)          # monthly | quarterly | yearly | one_time | full | custom
    period_key = db.Column(db.String(20))                    # 2026-07, Q1, full ... stops duplicate generation
    label = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    discount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    discount_reason = db.Column(db.String(200))
    paid = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    status = db.Column(db.String(10), default="pending", nullable=False, index=True)   # pending|partial|paid|cancelled
    cancel_reason = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    student = db.relationship("Student", lazy="joined")
    batch = db.relationship("Batch", lazy="joined")

    @property
    def net(self):
        return Decimal(self.amount) - Decimal(self.discount or 0)

    @property
    def balance(self):
        return Decimal(0) if self.status == "cancelled" else max(self.net - Decimal(self.paid or 0), Decimal(0))

    @property
    def overdue(self):
        return self.balance > 0 and self.due_date < date.today()


class Payment(TimestampMixin, db.Model):
    """Money received. Never edited or deleted: mistakes are cancelled (with a reason) or refunded."""
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    receipt_no = db.Column(db.String(30), unique=True, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    mode = db.Column(db.String(10), nullable=False)
    reference = db.Column(db.String(80))
    paid_on = db.Column(db.Date, nullable=False, index=True)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    note = db.Column(db.String(200))
    status = db.Column(db.String(10), default="active", nullable=False, index=True)    # active | cancelled
    cancel_reason = db.Column(db.String(200))
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancelled_at = db.Column(db.DateTime)
    refunded_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    client_token = db.Column(db.String(40), unique=True)            # stops a double-click from charging twice

    student = db.relationship("Student", lazy="joined")
    branch = db.relationship("Branch", lazy="joined")
    receiver = db.relationship("User", foreign_keys=[received_by], lazy="joined")
    allocations = db.relationship("PaymentAllocation", back_populates="payment", cascade="all, delete-orphan")
    refunds = db.relationship("Refund", back_populates="payment", order_by="Refund.created_at")

    @property
    def net_amount(self):
        return Decimal(self.amount) - Decimal(self.refunded_amount or 0)

    @property
    def mode_label(self):
        return dict(PAYMENT_MODES).get(self.mode, self.mode)


class PaymentAllocation(db.Model):
    __tablename__ = "payment_allocations"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False, index=True)
    due_id = db.Column(db.Integer, db.ForeignKey("fee_dues.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    refunded = db.Column(db.Numeric(10, 2), default=0, nullable=False)

    payment = db.relationship("Payment", back_populates="allocations")
    due = db.relationship("FeeDue", lazy="joined")


class Refund(db.Model):
    __tablename__ = "refunds"

    id = db.Column(db.Integer, primary_key=True)
    refund_no = db.Column(db.String(30), unique=True, nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    mode = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    refunded_on = db.Column(db.Date, nullable=False)
    processed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payment = db.relationship("Payment", back_populates="refunds")
    processor = db.relationship("User", foreign_keys=[processed_by])
