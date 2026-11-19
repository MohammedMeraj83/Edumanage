from extensions import db
from .mixins import TimestampMixin


class Institute(TimestampMixin, db.Model):
    """Single institute record (only one row is ever allowed)."""
    __tablename__ = "institutes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    tagline = db.Column(db.String(200))
    logo = db.Column(db.String(255))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    website = db.Column(db.String(200))
    address = db.Column(db.Text)
    registration_no = db.Column(db.String(80))


class InstituteSetting(db.Model):
    __tablename__ = "institute_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text)
