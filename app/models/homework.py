from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

CHECK_STATUSES = [("done", "Done"), ("partial", "Partly done"), ("not_done", "Not done")]
MATERIAL_KINDS = [("file", "File"), ("link", "Link")]


class Homework(TimestampMixin, db.Model):
    """Work given to one batch. The teacher later ticks who did it (HomeworkCheck)."""
    __tablename__ = "homework"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    assigned_on = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    attachment = db.Column(db.String(80))            # stored name under uploads/homework
    attachment_name = db.Column(db.String(150))      # name shown to people
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    batch = db.relationship("Batch", lazy="joined")
    checks = db.relationship("HomeworkCheck", back_populates="homework", cascade="all, delete-orphan")


class HomeworkCheck(db.Model):
    """The teacher's note for one student on one homework. No row = not checked yet."""
    __tablename__ = "homework_checks"
    __table_args__ = (db.UniqueConstraint("homework_id", "student_id", name="uq_hw_check"),)

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey("homework.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)           # done | partial | not_done
    remark = db.Column(db.String(120))
    checked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    checked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    homework = db.relationship("Homework", back_populates="checks")
    student = db.relationship("Student", lazy="joined")


class StudyMaterial(TimestampMixin, db.Model):
    """Notes, papers or links shared with one batch."""
    __tablename__ = "study_materials"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(500))
    kind = db.Column(db.String(5), default="file", nullable=False)        # file | link
    filename = db.Column(db.String(80))
    original_name = db.Column(db.String(150))
    size = db.Column(db.Integer)
    url = db.Column(db.String(500))
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    batch = db.relationship("Batch", lazy="joined")
