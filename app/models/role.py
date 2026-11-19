from extensions import db
from .permission import role_permissions

# The six management roles (fixed system roles)
OWNER = "owner"
BRANCH_ADMIN = "branch_admin"
ACCOUNTANT = "accountant"
TEACHER = "teacher"
STUDENT = "student"
PARENT = "parent"

ALL_ROLES = [OWNER, BRANCH_ADMIN, ACCOUNTANT, TEACHER, STUDENT, PARENT]

# Roles that must always belong to a branch
BRANCH_BOUND_ROLES = {BRANCH_ADMIN, ACCOUNTANT, TEACHER, STUDENT}


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)
    display_name = db.Column(db.String(60), nullable=False)
    is_super = db.Column(db.Boolean, default=False, nullable=False)  # Owner: all permissions
    permissions = db.relationship("Permission", secondary=role_permissions, lazy="selectin")

    def __repr__(self):
        return f"<Role {self.name}>"
