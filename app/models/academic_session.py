from extensions import db
from .mixins import TimestampMixin


class AcademicSession(TimestampMixin, db.Model):
    """e.g. 2026-27. Old sessions are kept forever (history is preserved)."""
    __tablename__ = "academic_sessions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)
