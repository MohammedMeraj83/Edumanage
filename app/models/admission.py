from extensions import db
from .mixins import TimestampMixin

ADMISSION_STATUSES = ("pending", "approved", "rejected")


class Admission(TimestampMixin, db.Model):
    """One admission application. Becomes a Student when approved."""
    __tablename__ = "admissions"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False, index=True)
    admission_no = db.Column(db.String(30), unique=True)          # given at approval
    status = db.Column(db.String(15), default="pending", nullable=False, index=True)

    full_name = db.Column(db.String(120), nullable=False, index=True)
    dob = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    blood_group = db.Column(db.String(5))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    class_name = db.Column(db.String(40), nullable=False)
    previous_school = db.Column(db.String(150))
    address = db.Column(db.Text)
    city = db.Column(db.String(80))
    state = db.Column(db.String(80))
    pincode = db.Column(db.String(10))

    father_name = db.Column(db.String(120))
    mother_name = db.Column(db.String(120))
    guardian_phone = db.Column(db.String(20), nullable=False)
    guardian_email = db.Column(db.String(120))

    photo = db.Column(db.String(255))
    notes = db.Column(db.Text)
    rejection_reason = db.Column(db.String(255))

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime)

    branch = db.relationship("Branch", lazy="joined")
    session = db.relationship("AcademicSession", lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
    decider = db.relationship("User", foreign_keys=[decided_by])

    @property
    def reference(self):
        return f"APP-{self.id:05d}"
