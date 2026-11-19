from extensions import db
from .mixins import TimestampMixin

course_subjects = db.Table(
    "course_subjects",
    db.Column("course_id", db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    db.Column("subject_id", db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)


class Subject(TimestampMixin, db.Model):
    __tablename__ = "subjects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class Course(TimestampMixin, db.Model):
    """Institute-wide course, e.g. 'NEET', 'Class 10'. Branches run batches of these courses."""
    __tablename__ = "courses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    subjects = db.relationship("Subject", secondary=course_subjects, order_by="Subject.name", lazy="selectin")
