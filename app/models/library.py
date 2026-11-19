from datetime import date
from extensions import db
from .mixins import TimestampMixin


LIBRARY_BOOK_STATUSES = ("active", "inactive")
LIBRARY_MEMBER_KINDS = (("student", "Student"), ("teacher", "Teacher"), ("staff", "Staff"))
LIBRARY_ISSUE_STATUSES = ("issued", "returned", "overdue", "lost")


class LibraryBook(TimestampMixin, db.Model):
    __tablename__ = "library_books"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    author = db.Column(db.String(120), nullable=False)
    isbn = db.Column(db.String(30), index=True)
    category = db.Column(db.String(60), default="General", nullable=False)
    publisher = db.Column(db.String(120))
    edition = db.Column(db.String(40))
    total_copies = db.Column(db.Integer, default=1, nullable=False)
    available_copies = db.Column(db.Integer, default=1, nullable=False)
    shelf_location = db.Column(db.String(80))
    status = db.Column(db.String(10), default="active", nullable=False, index=True)

    branch = db.relationship("Branch", lazy="joined")


class LibraryIssue(TimestampMixin, db.Model):
    __tablename__ = "library_issues"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    book_id = db.Column(db.Integer, db.ForeignKey("library_books.id"), nullable=False, index=True)
    member_kind = db.Column(db.String(10), nullable=False)
    member_id = db.Column(db.Integer, nullable=False)
    member_name = db.Column(db.String(150), nullable=False)
    member_code = db.Column(db.String(30))
    issue_date = db.Column(db.Date, default=date.today, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date)
    fine_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    fine_paid = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    status = db.Column(db.String(10), default="issued", nullable=False, index=True)
    notes = db.Column(db.String(300))

    branch = db.relationship("Branch", lazy="joined")
    book = db.relationship("LibraryBook", lazy="joined")
