import re
from sqlalchemy import func
from extensions import db
from app.models import Parent, StudentParent, User, Role, RELATIONS
from app.services.audit_service import log_action
from app.utils.helpers import generate_temp_password
from app.utils.numbering import next_parent_code


def phone_key(phone):
    """Last 10 digits - so '98765 43210' and '+91 9876543210' match."""
    return re.sub(r"\D", "", phone or "")[-10:]


def _display_name(student, relation):
    pick = {"Father": student.father_name, "Mother": student.mother_name}.get(relation)
    return pick or student.father_name or student.mother_name or f"Guardian of {student.full_name}"


def link_from_student(student, relation, user):
    """Create (or reuse by phone number) the parent from the student's guardian details and link them.
    Returns (parent, status) where status is 'created', 'existing' or 'already'."""
    if relation not in RELATIONS:
        raise ValueError("Choose Father, Mother or Guardian.")
    key = phone_key(student.guardian_phone)
    parent = Parent.query.filter_by(phone_key=key).first()
    status = "existing"
    if parent is None:
        parent = Parent(parent_code=next_parent_code(), full_name=_display_name(student, relation),
                        phone=student.guardian_phone, phone_key=key, email=student.guardian_email,
                        address=student.address)
        db.session.add(parent)
        db.session.flush()
        status = "created"
        log_action("create", "parents", parent.id, f"Parent {parent.parent_code} from {student.student_code}")
    if StudentParent.query.filter_by(student_id=student.id, parent_id=parent.id).first():
        return parent, "already"
    db.session.add(StudentParent(student_id=student.id, parent_id=parent.id, relation=relation))
    log_action("link", "parents", parent.id, f"{parent.parent_code} <-> {student.student_code} ({relation})")
    db.session.commit()
    return parent, status


def link_student(parent, student, relation):
    if relation not in RELATIONS:
        raise ValueError("Choose Father, Mother or Guardian.")
    if StudentParent.query.filter_by(student_id=student.id, parent_id=parent.id).first():
        raise ValueError("This child is already linked.")
    db.session.add(StudentParent(student_id=student.id, parent_id=parent.id, relation=relation))
    log_action("link", "parents", parent.id, f"{parent.parent_code} <-> {student.student_code} ({relation})")
    db.session.commit()


def unlink_student(parent, student):
    StudentParent.query.filter_by(student_id=student.id, parent_id=parent.id).delete()
    log_action("unlink", "parents", parent.id, f"{parent.parent_code} -/- {student.student_code}")
    db.session.commit()


def update_parent(parent, data):
    for k, v in data.items():
        setattr(parent, k, v)
    parent.phone_key = phone_key(parent.phone)
    if parent.user:
        parent.user.full_name, parent.user.phone = parent.full_name, parent.phone
    log_action("update", "parents", parent.id, f"Edited {parent.parent_code}")
    db.session.commit()


def set_status(parent, status):
    if status not in ("active", "inactive"):
        raise ValueError("Unknown status.")
    parent.status = status
    if parent.user:
        parent.user.is_active_user = (status == "active")
    log_action("status", "parents", parent.id, f"{parent.parent_code} -> {status}")
    db.session.commit()


def create_parent_login(parent):
    if parent.user_id:
        raise ValueError("This parent already has a login.")
    role = Role.query.filter_by(name="parent").first()
    username = parent.parent_code.lower()
    email = f"{username}@parents.edumanage.local"
    if parent.email and not User.query.filter(func.lower(User.email) == parent.email.lower()).first():
        email = parent.email.lower()
    temp = generate_temp_password()
    user = User(username=username, email=email, full_name=parent.full_name, phone=parent.phone,
                role_id=role.id, branch_id=None, must_change_password=True,
                is_active_user=(parent.status == "active"))
    user.set_password(temp)
    db.session.add(user)
    db.session.flush()
    parent.user_id = user.id
    log_action("create", "users", user.id, f"Parent login {username}")
    db.session.commit()
    return user, temp
