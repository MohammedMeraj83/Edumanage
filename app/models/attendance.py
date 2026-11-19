from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

ATTENDANCE_STATUSES = ("present", "absent", "late", "leave")


class BranchGeo(db.Model):
    """Where the tuition physically is. Check-ins outside this circle are refused."""
    __tablename__ = "branch_geo"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), unique=True, nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    radius_m = db.Column(db.Integer, default=100, nullable=False)
    qr_token = db.Column(db.String(40), unique=True, nullable=False)     # printed QR points to this
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch", lazy="joined")


class LectureSession(TimestampMixin, db.Model):
    """One real lecture on one real date (created from a timetable slot). Times are stored in UTC."""
    __tablename__ = "lecture_sessions"
    __table_args__ = (db.UniqueConstraint("slot_id", "lecture_date", name="uq_session_slot_date"),)

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("timetable_slots.id", ondelete="SET NULL"))
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    lecture_date = db.Column(db.Date, nullable=False, index=True)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    cancelled = db.Column(db.Boolean, default=False, nullable=False)
    note = db.Column(db.String(200))

    # teacher arrival (start of class)
    checkin_at = db.Column(db.DateTime)
    checkin_lat = db.Column(db.Float)
    checkin_lng = db.Column(db.Float)
    checkin_distance_m = db.Column(db.Integer)
    ended_at = db.Column(db.DateTime)
    attendance_submitted_at = db.Column(db.DateTime)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", lazy="joined")
    batch = db.relationship("Batch", lazy="joined")
    teacher = db.relationship("Teacher", lazy="joined")
    room = db.relationship("Room", lazy="joined")
    records = db.relationship("AttendanceRecord", back_populates="session", cascade="all, delete-orphan")

    @property
    def minutes(self):
        return int((self.end_at - self.start_at).total_seconds() // 60)


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"
    __table_args__ = (db.UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),)

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("lecture_sessions.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)                    # present | absent | late | leave
    verified = db.Column(db.Boolean, default=False, nullable=False)      # student checked in from inside the branch
    verified_at = db.Column(db.DateTime)
    verified_distance_m = db.Column(db.Integer)
    marked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    marked_at = db.Column(db.DateTime)

    session = db.relationship("LectureSession", back_populates="records")
    student = db.relationship("Student", lazy="joined")
