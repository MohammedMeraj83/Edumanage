from datetime import datetime
from extensions import db
from .mixins import TimestampMixin


ONLINE_CLASS_STATUSES = ("scheduled", "live", "completed", "cancelled")
ONLINE_EXAM_STATUSES = ("draft", "published", "closed")


class OnlineClass(TimestampMixin, db.Model):
    __tablename__ = "online_classes"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(500))
    meeting_url = db.Column(db.String(500), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_min = db.Column(db.Integer, nullable=False, default=60)
    status = db.Column(db.String(10), default="scheduled", nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    branch = db.relationship("Branch", lazy="joined")
    batch = db.relationship("Batch", lazy="joined")


class OnlineExam(TimestampMixin, db.Model):
    __tablename__ = "online_exams"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    instructions = db.Column(db.String(1000))
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_min = db.Column(db.Integer, nullable=False, default=30)
    pass_marks = db.Column(db.Numeric(7, 2), nullable=False, default=0)
    status = db.Column(db.String(10), default="draft", nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    branch = db.relationship("Branch", lazy="joined")
    batch = db.relationship("Batch", lazy="joined")
    questions = db.relationship("OnlineExamQuestion", back_populates="exam", cascade="all, delete-orphan",
                                order_by="OnlineExamQuestion.position")
    attempts = db.relationship("OnlineExamAttempt", back_populates="exam", cascade="all, delete-orphan")


class OnlineExamQuestion(TimestampMixin, db.Model):
    __tablename__ = "online_exam_questions"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("online_exams.id"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=1)
    text = db.Column(db.String(1000), nullable=False)
    option_a = db.Column(db.String(300), nullable=False)
    option_b = db.Column(db.String(300), nullable=False)
    option_c = db.Column(db.String(300), nullable=False)
    option_d = db.Column(db.String(300), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    marks = db.Column(db.Numeric(7, 2), nullable=False, default=1)

    exam = db.relationship("OnlineExam", back_populates="questions")


class OnlineExamAttempt(TimestampMixin, db.Model):
    __tablename__ = "online_exam_attempts"
    __table_args__ = (db.UniqueConstraint("exam_id", "student_id", name="uq_online_exam_attempt"),)

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("online_exams.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime)
    obtained_marks = db.Column(db.Numeric(7, 2), default=0, nullable=False)
    total_marks = db.Column(db.Numeric(7, 2), default=0, nullable=False)

    exam = db.relationship("OnlineExam", back_populates="attempts")
    student = db.relationship("Student", lazy="joined")
    answers = db.relationship("OnlineExamAnswer", back_populates="attempt", cascade="all, delete-orphan")


class OnlineExamAnswer(db.Model):
    __tablename__ = "online_exam_answers"
    __table_args__ = (db.UniqueConstraint("attempt_id", "question_id", name="uq_online_answer_question"),)

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("online_exam_attempts.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("online_exam_questions.id"), nullable=False, index=True)
    selected_option = db.Column(db.String(1), nullable=False)
    is_correct = db.Column(db.Boolean, default=False, nullable=False)

    attempt = db.relationship("OnlineExamAttempt", back_populates="answers")
    question = db.relationship("OnlineExamQuestion", lazy="joined")
