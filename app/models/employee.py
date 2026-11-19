from datetime import datetime
from sqlalchemy.orm import declared_attr
from extensions import db
from .mixins import TimestampMixin

EMPLOYEE_STATUSES = ("active", "inactive", "left")
STAFF_DESIGNATIONS = ["Accountant", "Receptionist", "Office assistant", "Counsellor", "Librarian",
                      "Driver", "Security", "Peon", "Cleaner", "Other"]
EMPLOYEE_DOC_TYPES = [
    ("id_proof", "ID proof"),
    ("qualification", "Qualification certificate"),
    ("experience", "Experience letter"),
    ("address_proof", "Address proof"),
    ("other", "Other"),
]


class EmployeeMixin(TimestampMixin):
    """Columns shared by Teacher and Staff. Employee codes are institute-wide unique."""
    id = db.Column(db.Integer, primary_key=True)
    employee_code = db.Column(db.String(15), unique=True, nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    status = db.Column(db.String(15), default="active", nullable=False, index=True)

    full_name = db.Column(db.String(120), nullable=False, index=True)
    gender = db.Column(db.String(10), nullable=False)
    dob = db.Column(db.Date)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    qualification = db.Column(db.String(150))
    joining_date = db.Column(db.Date, nullable=False)
    photo = db.Column(db.String(255))
    notes = db.Column(db.Text)

    @declared_attr
    def branch(cls):
        return db.relationship("Branch", lazy="joined")

    @declared_attr
    def user(cls):
        return db.relationship("User", lazy="joined")


class Teacher(EmployeeMixin, db.Model):
    __tablename__ = "teachers"
    specialization = db.Column(db.String(150))       # subjects they teach (linked to real subjects in Phase 5)
    experience_years = db.Column(db.Integer)

    @property
    def title_text(self):
        return self.specialization or "—"

    def extra_rows(self):
        return [("Specialization", self.specialization or "—"),
                ("Experience", f"{self.experience_years} years" if self.experience_years is not None else "—")]


class Staff(EmployeeMixin, db.Model):
    __tablename__ = "staff"
    designation = db.Column(db.String(60), nullable=False)

    @property
    def title_text(self):
        return self.designation

    def extra_rows(self):
        return [("Designation", self.designation)]


class EmployeeDocument(db.Model):
    __tablename__ = "employee_documents"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), index=True)
    doc_type = db.Column(db.String(30), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    size = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def type_label(self):
        return dict(EMPLOYEE_DOC_TYPES).get(self.doc_type, self.doc_type)
