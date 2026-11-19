from datetime import datetime
from extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), index=True)
    action = db.Column(db.String(60), nullable=False, index=True)   # create / update / delete / login ...
    entity = db.Column(db.String(60))                               # table / module name
    entity_id = db.Column(db.String(40))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("User", lazy="joined")


class LoginLog(db.Model):
    __tablename__ = "login_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    username_tried = db.Column(db.String(120))
    success = db.Column(db.Boolean, nullable=False)
    reason = db.Column(db.String(60))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
