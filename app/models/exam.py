from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

EXAM_TYPES = [
    ("unit_test", "Unit test"),
    ("monthly", "Monthly test"),
    ("midterm", "Mid-term exam"),
    ("final", "Final exam"),
    ("mock", "Mock / practice test"),
    ("other", "Other"),
]


class Exam(TimestampMixin, db.Model):
    """One exam event of one branch (e.g. 'Unit Test 1'). Its papers are one per batch (= one subject)."""
    __tablename__ = "exams"
    __table_args__ = (db.UniqueConstraint("branch_id", "session_id", "name", name="uq_exam_name"),)

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    exam_type = db.Column(db.String(20), default="unit_test", nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(255))

    # Students and parents see results only after the exam is published.
    results_published = db.Column(db.Boolean, default=False, nullable=False, index=True)
    published_at = db.Column(db.DateTime)
    published_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", lazy="joined")
    session = db.relationship("AcademicSession", lazy="joined")
    papers = db.relationship("ExamPaper", back_populates="exam", cascade="all, delete-orphan",
                             order_by="ExamPaper.exam_date, ExamPaper.id")

    @property
    def type_label(self):
        return dict(EXAM_TYPES).get(self.exam_type, self.exam_type)


class ExamPaper(TimestampMixin, db.Model):
    """The paper of one batch in an exam: date, maximum marks, passing marks."""
    __tablename__ = "exam_papers"
    __table_args__ = (db.UniqueConstraint("exam_id", "batch_id", name="uq_paper_exam_batch"),)

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    exam_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time)
    duration_min = db.Column(db.Integer)
    max_marks = db.Column(db.Numeric(6, 2), nullable=False)
    pass_marks = db.Column(db.Numeric(6, 2), nullable=False)

    # A locked paper cannot be edited (teacher submitted it). Only an admin can unlock.
    locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    locked_at = db.Column(db.DateTime)

    exam = db.relationship("Exam", back_populates="papers")
    batch = db.relationship("Batch", lazy="joined")
    marks = db.relationship("ExamMark", back_populates="paper", cascade="all, delete-orphan")

    @property
    def subject_name(self):
        return self.batch.subject.name


class ExamMark(db.Model):
    """A student's result in one paper. No row = marks not entered yet."""
    __tablename__ = "exam_marks"
    __table_args__ = (db.UniqueConstraint("paper_id", "student_id", name="uq_mark_paper_student"),)

    id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("exam_papers.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    absent = db.Column(db.Boolean, default=False, nullable=False)
    marks = db.Column(db.Numeric(6, 2))                      # NULL when absent
    remark = db.Column(db.String(120))
    entered_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    entered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    paper = db.relationship("ExamPaper", back_populates="marks")
    student = db.relationship("Student", lazy="joined")
