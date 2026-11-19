from extensions import db
from .mixins import TimestampMixin


class WebsitePage(TimestampMixin, db.Model):
    __tablename__ = "website_pages"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    subtitle = db.Column(db.String(300))
    content = db.Column(db.Text)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)


class WebsiteSetting(db.Model):
    __tablename__ = "website_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text)
