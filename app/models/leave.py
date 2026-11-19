from datetime import datetime
from extensions import db

LEAVE_STATUSES = ("pending", "approved", "rejected")


class LeaveRequest(db.Model):
    """Leave for a teacher (applied by the teacher) or a student (applied by the student or a parent)."""
    __tablename__ = "leave_requests"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)                      # teacher | student
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(10), default="pending", nullable=False, index=True)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime)
    decision_note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch", lazy="joined")
    teacher = db.relationship("Teacher", lazy="joined")
    student = db.relationship("Student", lazy="joined")
    requester = db.relationship("User", foreign_keys=[requested_by], lazy="joined")
