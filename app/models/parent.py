from extensions import db
from .mixins import TimestampMixin

RELATIONS = ["Father", "Mother", "Guardian"]


class Parent(TimestampMixin, db.Model):
    """A parent/guardian. Not tied to one branch: one parent can have children in several."""
    __tablename__ = "parents"

    id = db.Column(db.Integer, primary_key=True)
    parent_code = db.Column(db.String(15), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    status = db.Column(db.String(15), default="active", nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=False)
    phone_key = db.Column(db.String(15), nullable=False, index=True)    # last 10 digits, used to match siblings
    email = db.Column(db.String(120))
    occupation = db.Column(db.String(100))
    address = db.Column(db.Text)

    user = db.relationship("User", lazy="joined")
    links = db.relationship("StudentParent", back_populates="parent", cascade="all, delete-orphan")


class StudentParent(db.Model):
    __tablename__ = "student_parents"
    __table_args__ = (db.UniqueConstraint("student_id", "parent_id", name="uq_student_parent"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("parents.id"), nullable=False, index=True)
    relation = db.Column(db.String(15), nullable=False)

    student = db.relationship("Student", backref=db.backref("parent_links", cascade="all, delete-orphan"))
    parent = db.relationship("Parent", back_populates="links")
