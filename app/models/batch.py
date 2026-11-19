from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

FEE_FREQUENCIES = [("monthly", "Per month"), ("quarterly", "Per quarter"), ("yearly", "Per year"),
                   ("one_time", "One time")]
BATCH_STATUSES = ("active", "closed")


class Room(TimestampMixin, db.Model):
    __tablename__ = "rooms"
    __table_args__ = (db.UniqueConstraint("branch_id", "name", name="uq_room_branch_name"),)
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    capacity = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    branch = db.relationship("Branch", lazy="joined")


class Batch(TimestampMixin, db.Model):
    """One subject of one course, with one teacher, in one branch. Has its own fee."""
    __tablename__ = "batches"
    __table_args__ = (db.UniqueConstraint("branch_id", "session_id", "name", name="uq_batch_name"),)

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    name = db.Column(db.String(150), nullable=False)
    capacity = db.Column(db.Integer, default=30, nullable=False)
    fee_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    fee_frequency = db.Column(db.String(15), default="monthly", nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(10), default="active", nullable=False, index=True)

    branch = db.relationship("Branch", lazy="joined")
    session = db.relationship("AcademicSession", lazy="joined")
    course = db.relationship("Course", lazy="joined")
    subject = db.relationship("Subject", lazy="joined")
    teacher = db.relationship("Teacher", lazy="joined")
    room = db.relationship("Room", lazy="joined")
    slots = db.relationship("TimetableSlot", back_populates="batch", cascade="all, delete-orphan",
                            order_by="TimetableSlot.weekday, TimetableSlot.start_time")
    enrollments = db.relationship("BatchStudent", back_populates="batch")

    @property
    def fee_label(self):
        return dict(FEE_FREQUENCIES).get(self.fee_frequency, self.fee_frequency)


class BatchStudent(db.Model):
    """A student's seat in a batch. The fee is copied here so a later batch-fee change
    does not silently change an existing student's fee."""
    __tablename__ = "batch_students"
    __table_args__ = (db.UniqueConstraint("batch_id", "student_id", name="uq_batch_student"),)

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    status = db.Column(db.String(10), default="active", nullable=False, index=True)   # active | left
    enrolled_on = db.Column(db.Date, nullable=False)
    left_on = db.Column(db.Date)
    leave_reason = db.Column(db.String(120))
    fee_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    batch = db.relationship("Batch", back_populates="enrollments")
    student = db.relationship("Student", lazy="joined", backref=db.backref("enrollments"))
