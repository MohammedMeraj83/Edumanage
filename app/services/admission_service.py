from datetime import datetime, date
from sqlalchemy.exc import IntegrityError
from extensions import db
from app.models import Admission, Student, StudentDocument, Branch
from app.services.audit_service import log_action
from app.utils.numbering import next_admission_no, next_student_code

PERSON_FIELDS = ["full_name", "dob", "gender", "blood_group", "phone", "email", "class_name",
                 "previous_school", "address", "city", "state", "pincode",
                 "father_name", "mother_name", "guardian_phone", "guardian_email", "notes"]


def person_data(form):
    """Clean values from a PersonForm: strip text, empty -> None."""
    out = {}
    for k in PERSON_FIELDS:
        v = getattr(form, k).data
        if isinstance(v, str):
            v = v.strip()
        out[k] = v or None
    return out


def create_admission(data, branch_id, session_id, photo, user):
    adm = Admission(**data, branch_id=branch_id, session_id=session_id, photo=photo,
                    status="pending", created_by=user.id)
    db.session.add(adm)
    db.session.flush()
    log_action("create", "admissions", adm.id, f"New admission application for {adm.full_name}")
    db.session.commit()
    return adm


def update_admission(adm, data, photo=None):
    for k, v in data.items():
        setattr(adm, k, v)
    if photo:
        adm.photo = photo
    log_action("update", "admissions", adm.id, f"Edited application {adm.reference}")
    db.session.commit()


def approve_admission(adm, user):
    """Pending admission -> Student with admission number and student code.
    Retries if two people approve at the same moment and the numbers collide."""
    adm_id = adm.id
    for _ in range(3):
        try:
            adm = db.session.get(Admission, adm_id)
            if adm.status != "pending":
                raise ValueError("Only pending applications can be approved.")
            branch = db.session.get(Branch, adm.branch_id)
            adm.admission_no = next_admission_no(branch, adm.session)
            student = Student(
                student_code=next_student_code(), admission_no=adm.admission_no, admission_id=adm.id,
                branch_id=adm.branch_id, session_id=adm.session_id, status="active", admitted_on=date.today(),
                photo=adm.photo,
                **{k: getattr(adm, k) for k in ["full_name", "dob", "gender", "blood_group", "phone", "email",
                                                "class_name", "previous_school", "address", "city", "state",
                                                "pincode", "father_name", "mother_name", "guardian_phone",
                                                "guardian_email", "notes"]})
            db.session.add(student)
            db.session.flush()
            adm.status, adm.decided_by, adm.decided_at = "approved", user.id, datetime.utcnow()
            StudentDocument.query.filter_by(admission_id=adm.id).update({"student_id": student.id})
            log_action("approve", "admissions", adm.id,
                       f"Approved {adm.reference} -> {student.student_code} / {adm.admission_no}")
            db.session.commit()
            return student
        except IntegrityError:
            db.session.rollback()
    raise RuntimeError("Could not generate unique numbers. Please try again.")


def reject_admission(adm, user, reason):
    if adm.status != "pending":
        raise ValueError("Only pending applications can be rejected.")
    adm.status, adm.rejection_reason = "rejected", (reason or "").strip()[:255] or None
    adm.decided_by, adm.decided_at = user.id, datetime.utcnow()
    log_action("reject", "admissions", adm.id, f"Rejected {adm.reference}: {adm.rejection_reason or '-'}")
    db.session.commit()
