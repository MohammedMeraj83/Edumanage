from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

PERSON_KINDS = ("student", "teacher", "staff")
ID_CARD_STATUSES = ("active", "replaced", "lost", "cancelled")

LIBRARY_CATEGORIES = [
    ("circular", "Circular / notice"), ("form", "Form"), ("syllabus", "Syllabus"), ("policy", "Rules / policy"),
    ("timetable", "Timetable / schedule"), ("other", "Other"),
]
LIBRARY_AUDIENCES = [
    ("all", "Everyone (staff, students, parents)"), ("teachers", "Teachers only"),
    ("students", "Students and parents"),
]


class IdCard(TimestampMixin, db.Model):
    """One issued ID card. A person can have many over time, only one is `active`.
    The QR on the card points to a public page that checks `token`."""
    __tablename__ = "id_cards"
    __table_args__ = (db.Index("ix_idcard_person", "person_kind", "person_id"),)

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    person_kind = db.Column(db.String(8), nullable=False)               # student | teacher | staff
    person_id = db.Column(db.Integer, nullable=False)
    card_no = db.Column(db.String(30), unique=True, nullable=False)     # e.g. STU000001-01
    token = db.Column(db.String(32), unique=True, nullable=False, index=True)
    issued_on = db.Column(db.Date, nullable=False)
    valid_until = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), default="active", nullable=False, index=True)
    reason = db.Column(db.String(120))
    issued_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    closed_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", lazy="joined")


class Certificate(TimestampMixin, db.Model):
    """A certificate issued to a student. Never deleted: a wrong one is cancelled and the number stays used."""
    __tablename__ = "certificates"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    cert_type = db.Column(db.String(20), nullable=False, index=True)
    certificate_no = db.Column(db.String(40), unique=True, nullable=False)
    token = db.Column(db.String(32), unique=True, nullable=False, index=True)
    issue_date = db.Column(db.Date, nullable=False)
    fields = db.Column(db.JSON, nullable=False, default=dict)           # the type-specific details
    status = db.Column(db.String(10), default="issued", nullable=False, index=True)   # issued | cancelled
    issued_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(200))

    branch = db.relationship("Branch", lazy="joined")
    student = db.relationship("Student", lazy="joined")


class InstituteDocument(TimestampMixin, db.Model):
    """Library file shared with an audience (circulars, forms, syllabus...). branch_id NULL = every branch."""
    __tablename__ = "institute_documents"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), index=True)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(15), default="other", nullable=False)
    audience = db.Column(db.String(10), default="all", nullable=False)
    description = db.Column(db.String(500))
    filename = db.Column(db.String(80), nullable=False)
    original_name = db.Column(db.String(150), nullable=False)
    size = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", lazy="joined")

    @property
    def category_label(self):
        return dict(LIBRARY_CATEGORIES).get(self.category, self.category)

    @property
    def audience_label(self):
        return {"all": "Everyone", "teachers": "Teachers", "students": "Students and parents"}.get(self.audience, self.audience)
