from extensions import db
from app.models import Branch, Institute, Role, User, BRANCH_ADMIN
from app.services.audit_service import log_action
from app.utils.helpers import generate_temp_password


def create_branch(data):
    inst = Institute.query.first()
    branch = Branch(institute_id=inst.id, **data)
    branch.code = branch.code.upper()
    db.session.add(branch)
    db.session.flush()
    log_action("create", "branches", branch.id, f"Created branch {branch.code} - {branch.name}")
    db.session.commit()
    return branch


def create_branch_admin(branch, data):
    """Create a branch-admin login with a temporary password. Returns (user, temp_password)."""
    role = Role.query.filter_by(name=BRANCH_ADMIN).first()
    temp = generate_temp_password()
    user = User(
        username=data["username"].lower(), email=data["email"].lower(),
        full_name=data["full_name"], phone=data.get("phone") or None,
        role_id=role.id, branch_id=branch.id, must_change_password=True,
    )
    user.set_password(temp)
    db.session.add(user)
    db.session.flush()
    log_action("create", "users", user.id, f"Created branch admin {user.username} for {branch.code}")
    db.session.commit()
    return user, temp


def reset_user_password(user):
    temp = generate_temp_password()
    user.set_password(temp)
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    log_action("password_reset", "users", user.id, f"Password reset for {user.username}")
    db.session.commit()
    return temp
