from extensions import db
from app.models import Student, StudentTransfer, StudentDocument, Admission, User, Role, STUDENT_STATUSES
from app.services.audit_service import log_action
from app.utils.file_upload import save_document, delete_upload
from app.utils.helpers import generate_temp_password


def update_student(student, data, photo=None):
    for k, v in data.items():
        setattr(student, k, v)
    if photo:
        _replace_photo(student, photo)
    log_action("update", "students", student.id, f"Edited {student.student_code}")
    db.session.commit()


def _replace_photo(student, new_name):
    old = student.photo
    student.photo = new_name
    db.session.flush()
    in_use = (Admission.query.filter_by(photo=old).first() or Student.query.filter_by(photo=old).first())
    if old and not in_use:
        delete_upload("students", old)


def set_status(student, status):
    if status not in STUDENT_STATUSES:
        raise ValueError("Unknown status.")
    student.status = status
    if student.user:                       # inactive / left students cannot sign in
        student.user.is_active_user = (status == "active")
    log_action("status", "students", student.id, f"{student.student_code} -> {status}")
    db.session.commit()


def transfer_student(student, to_branch, reason, user):
    """Move to another branch. Student code stays the same; full history is kept."""
    if to_branch.id == student.branch_id:
        raise ValueError("The student is already in this branch.")
    if not to_branch.is_active:
        raise ValueError("The selected branch is inactive.")
    db.session.add(StudentTransfer(
        student_id=student.id, from_branch_id=student.branch_id, to_branch_id=to_branch.id,
        reason=(reason or "").strip()[:255] or None, transferred_by=user.id))
    old_code = student.branch.code
    from app.services.academic_service import end_all_enrollments
    ended = end_all_enrollments(student, f"Transferred to {to_branch.code}")
    student.branch_id = to_branch.id
    if student.user:
        student.user.branch_id = to_branch.id
    log_action("transfer", "students", student.id,
               f"{student.student_code}: {old_code} -> {to_branch.code} ({ended} batch seat(s) ended)")
    db.session.commit()


def create_student_login(student):
    """Create the student's sign-in account. Returns (user, temp_password)."""
    if student.user_id:
        raise ValueError("This student already has a login.")
    role = Role.query.filter_by(name="student").first()
    username = student.student_code.lower()
    placeholder = f"{username}@students.edumanage.local"
    email = placeholder
    if student.email and not User.query.filter(db.func.lower(User.email) == student.email.lower()).first():
        email = student.email.lower()
    temp = generate_temp_password()
    user = User(username=username, email=email, full_name=student.full_name, phone=student.phone,
                role_id=role.id, branch_id=student.branch_id, must_change_password=True,
                is_active_user=(student.status == "active"))
    user.set_password(temp)
    db.session.add(user)
    db.session.flush()
    student.user_id = user.id
    log_action("create", "users", user.id, f"Student login {username}")
    db.session.commit()
    return user, temp


def add_document(file_storage, doc_type, user, admission=None, student=None):
    stored, original, size = save_document(file_storage)
    doc = StudentDocument(
        admission_id=admission.id if admission else None,
        student_id=student.id if student else None,
        doc_type=doc_type, filename=stored, original_name=original, size=size, uploaded_by=user.id)
    db.session.add(doc)
    db.session.flush()
    log_action("upload", "student_documents", doc.id, f"{doc.type_label}: {original}")
    db.session.commit()
    return doc


def delete_document(doc):
    log_action("delete", "student_documents", doc.id, doc.original_name)
    delete_upload("documents", doc.filename)
    db.session.delete(doc)
    db.session.commit()
