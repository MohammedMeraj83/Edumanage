from extensions import db
from app.models import (Teacher, Staff, EmployeeDocument, User, Role, EMPLOYEE_STATUSES)
from app.services.audit_service import log_action
from app.utils.file_upload import save_document, delete_upload
from app.utils.helpers import generate_temp_password
from app.utils.numbering import next_employee_code

KINDS = {
    "teacher": {"model": Teacher, "prefix": "TCH", "perm": "teachers", "label": "Teacher", "plural": "Teachers",
                "role": "teacher", "doc_fk": "teacher_id"},
    "staff": {"model": Staff, "prefix": "STF", "perm": "staff", "label": "Staff member", "plural": "Staff",
              "role": "accountant", "doc_fk": "staff_id"},
}

COMMON_FIELDS = ["full_name", "gender", "dob", "phone", "email", "address", "qualification", "joining_date", "notes"]
EXTRA_FIELDS = {"teacher": ["specialization", "experience_years"], "staff": ["designation"]}


def form_data(form, kind):
    out = {}
    for k in COMMON_FIELDS + EXTRA_FIELDS[kind]:
        v = getattr(form, k).data
        if isinstance(v, str):
            v = v.strip()
        out[k] = v if (v == 0 or v) else None
    return out


def can_have_login(kind, obj):
    """Teachers always can. Staff only when they are Accountants (the only staff role with a panel)."""
    return kind == "teacher" or obj.designation == "Accountant"


def create_employee(kind, data, branch_id, photo):
    cfg = KINDS[kind]
    obj = cfg["model"](employee_code=next_employee_code(cfg["model"], cfg["prefix"]),
                       branch_id=branch_id, photo=photo, status="active", **data)
    db.session.add(obj)
    db.session.flush()
    log_action("create", cfg["perm"], obj.id, f"Added {cfg['label'].lower()} {obj.employee_code} - {obj.full_name}")
    db.session.commit()
    return obj


def update_employee(kind, obj, data, photo=None, branch_id=None):
    for k, v in data.items():
        setattr(obj, k, v)
    if photo:
        delete_upload("employees", obj.photo)
        obj.photo = photo
    if branch_id and branch_id != obj.branch_id:
        obj.branch_id = branch_id
        if obj.user:
            obj.user.branch_id = branch_id
        log_action("branch_change", KINDS[kind]["perm"], obj.id, f"{obj.employee_code} moved to branch id {branch_id}")
    if obj.user:
        obj.user.full_name, obj.user.phone = obj.full_name, obj.phone
    log_action("update", KINDS[kind]["perm"], obj.id, f"Edited {obj.employee_code}")
    db.session.commit()


def set_status(kind, obj, status):
    if status not in EMPLOYEE_STATUSES:
        raise ValueError("Unknown status.")
    obj.status = status
    if obj.user:
        obj.user.is_active_user = (status == "active")
    log_action("status", KINDS[kind]["perm"], obj.id, f"{obj.employee_code} -> {status}")
    db.session.commit()


def create_login(kind, obj):
    """Returns (user, temp_password)."""
    if obj.user_id:
        raise ValueError("This person already has a login.")
    if not can_have_login(kind, obj):
        raise ValueError("Only teachers and accountants can sign in. Change the designation to Accountant first.")
    role = Role.query.filter_by(name=KINDS[kind]["role"]).first()
    username = obj.employee_code.lower()
    email = f"{username}@staff.edumanage.local"
    if obj.email and not User.query.filter(db.func.lower(User.email) == obj.email.lower()).first():
        email = obj.email.lower()
    temp = generate_temp_password()
    user = User(username=username, email=email, full_name=obj.full_name, phone=obj.phone, role_id=role.id,
                branch_id=obj.branch_id, must_change_password=True, is_active_user=(obj.status == "active"))
    user.set_password(temp)
    db.session.add(user)
    db.session.flush()
    obj.user_id = user.id
    log_action("create", "users", user.id, f"{role.display_name} login {username}")
    db.session.commit()
    return user, temp


def add_document(kind, obj, file_storage, doc_type, user):
    stored, original, size = save_document(file_storage)
    doc = EmployeeDocument(**{KINDS[kind]["doc_fk"]: obj.id}, doc_type=doc_type, filename=stored,
                           original_name=original, size=size, uploaded_by=user.id)
    db.session.add(doc)
    db.session.flush()
    log_action("upload", "employee_documents", doc.id, f"{doc.type_label}: {original}")
    db.session.commit()
    return doc


def delete_document(doc):
    log_action("delete", "employee_documents", doc.id, doc.original_name)
    delete_upload("documents", doc.filename)
    db.session.delete(doc)
    db.session.commit()
