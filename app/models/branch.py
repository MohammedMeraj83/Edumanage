from extensions import db
from .mixins import TimestampMixin


class Branch(TimestampMixin, db.Model):
    __tablename__ = "branches"

    id = db.Column(db.Integer, primary_key=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institutes.id"), nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False)  # used in admission/receipt numbers
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.Text)
    city = db.Column(db.String(80))
    state = db.Column(db.String(80))
    pincode = db.Column(db.String(10))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    is_main = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    institute = db.relationship("Institute", lazy="joined")

    def __repr__(self):
        return f"<Branch {self.code}>"


class BranchSetting(db.Model):
    __tablename__ = "branch_settings"
    __table_args__ = (db.UniqueConstraint("branch_id", "key", name="uq_branch_setting"),)

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    key = db.Column(db.String(80), nullable=False)
    value = db.Column(db.Text)
