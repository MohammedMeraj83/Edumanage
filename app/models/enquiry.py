from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

ENQUIRY_STATUSES = (
    ("new", "New"),
    ("contacted", "Contacted"),
    ("admitted", "Admitted"),
    ("closed", "Closed"),
)


class Enquiry(TimestampMixin, db.Model):
    __tablename__ = "enquiries"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), index=True)
    full_name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    course_interest = db.Column(db.String(120))
    message = db.Column(db.Text)
    status = db.Column(db.String(15), default="new", nullable=False, index=True)
    follow_up_at = db.Column(db.Date)
    staff_notes = db.Column(db.Text)
    source = db.Column(db.String(20), default="staff", nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")


class Notice(TimestampMixin, db.Model):
    __tablename__ = "notices"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), index=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(20), default="all", nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
    notifications = db.relationship(
        "Notification",
        back_populates="notice",
        cascade="all, delete-orphan",
    )


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (
        db.UniqueConstraint("notice_id", "user_id", name="uq_notification_notice_user"),
        db.Index("ix_notification_user_read", "user_id", "read_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    notice_id = db.Column(
        db.Integer, db.ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    read_at = db.Column(db.DateTime)

    notice = db.relationship("Notice", back_populates="notifications")
    user = db.relationship("User", lazy="joined")


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    endpoint = db.Column(db.Text, nullable=False)
    endpoint_hash = db.Column(db.String(64), unique=True, nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User")
