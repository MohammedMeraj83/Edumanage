from datetime import datetime
from extensions import db
from .mixins import TimestampMixin

GENDERS = ["Male", "Female", "Other"]
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
STUDENT_STATUSES = ("active", "inactive", "left")
DOC_TYPES = [
    ("id_proof", "ID proof"),
    ("birth_certificate", "Birth certificate"),
    ("marksheet", "Previous marksheet"),
    ("address_proof", "Address proof"),
    ("other", "Other"),
]


class Student(TimestampMixin, db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    # Institute-wide ID. NEVER changes, not even when the student moves branch.
    student_code = db.Column(db.String(15), unique=True, nullable=False, index=True)
    admission_no = db.Column(db.String(30), unique=True, nullable=False)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), unique=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    status = db.Column(db.String(15), default="active", nullable=False, index=True)
    admitted_on = db.Column(db.Date, nullable=False)

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

    branch = db.relationship("Branch", lazy="joined")
    session = db.relationship("AcademicSession", lazy="joined")
    user = db.relationship("User", lazy="joined")
    admission = db.relationship("Admission", backref=db.backref("student", uselist=False))
    transfers = db.relationship("StudentTransfer", order_by="StudentTransfer.created_at.desc()",
                                back_populates="student")
    documents = db.relationship("StudentDocument", order_by="StudentDocument.created_at.desc()",
                                primaryjoin="Student.id == StudentDocument.student_id", viewonly=True)

    def __repr__(self):
        return f"<Student {self.student_code}>"


class StudentTransfer(db.Model):
    """History of branch transfers (never deleted)."""
    __tablename__ = "student_transfers"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    from_branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    to_branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    reason = db.Column(db.String(255))
    transferred_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="transfers")
    from_branch = db.relationship("Branch", foreign_keys=[from_branch_id])
    to_branch = db.relationship("Branch", foreign_keys=[to_branch_id])
    by_user = db.relationship("User", foreign_keys=[transferred_by])


class StudentDocument(db.Model):
    """Uploaded paper (ID proof, birth certificate...). Belongs to an admission and,
    after approval, to the student too. Files are private (permission-checked route)."""
    __tablename__ = "student_documents"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), index=True)
    doc_type = db.Column(db.String(30), nullable=False)
    filename = db.Column(db.String(255), nullable=False)       # stored name (uuid)
    original_name = db.Column(db.String(255), nullable=False)
    size = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    uploader = db.relationship("User", foreign_keys=[uploaded_by])

    @property
    def type_label(self):
        return dict(DOC_TYPES).get(self.doc_type, self.doc_type)
