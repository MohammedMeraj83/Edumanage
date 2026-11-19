from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager
from .mixins import TimestampMixin
from .role import OWNER
from .permission import Permission

user_permissions = db.Table(
    "user_permissions",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=True, index=True)

    is_active_user = db.Column("is_active", db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)

    role = db.relationship("Role", lazy="joined")
    branch = db.relationship("Branch", lazy="joined")
    extra_permissions = db.relationship("Permission", secondary=user_permissions, lazy="selectin")

    # ---- password ----
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        try:
            return check_password_hash(self.password_hash, raw)
        except (ValueError, TypeError):  # corrupted / hand-edited hash -> just refuse login
            return False

    # ---- flask-login ----
    @property
    def is_active(self):
        return self.is_active_user

    # ---- lockout ----
    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    # ---- roles / permissions ----
    @property
    def role_name(self):
        return self.role.name

    @property
    def is_owner(self):
        return self.role.name == OWNER

    def has_role(self, *names):
        return self.role.name in names

    def has_permission(self, code):
        if self.role.is_super:
            return True
        return (any(p.code == code for p in self.role.permissions)
                or any(p.code == code for p in self.extra_permissions))

    def __repr__(self):
        return f"<User {self.username} ({self.role.name})>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
