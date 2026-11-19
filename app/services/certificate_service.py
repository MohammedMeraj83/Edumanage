"""Certificates for students.

Five kinds (bonafide, character, course completion, transfer / leaving, achievement). Each has its own small set of
fields. The wording lives in `certificate_text` so the on-screen preview and the PDF can never differ.
Certificates are never deleted: a wrong one is cancelled (its number stays used) and a new one is issued.
The QR code on the certificate opens a public page that shows whether it is genuine and not cancelled.
"""
import secrets
from datetime import date
from decimal import Decimal
from extensions import db
from app.models import Certificate, Student
from app.services import academic_service, fee_service
from app.services.audit_service import log_action
from app.utils.branch_access import scope_to_branch
from app.utils.date_utils import local_now
from app.utils.numbering import next_certificate_no

TEXT, AREA, DATE = "text", "textarea", "date"


def _f(key, label, kind=TEXT, required=False, default="", hint=""):
    return {"key": key, "label": label, "kind": kind, "required": required, "default": default, "hint": hint}


CERT_TYPES = {
    "bonafide": {"label": "Bonafide certificate", "title": "BONAFIDE CERTIFICATE",
                 "help": "Proves the student studies here. Used for bank, scholarship, passport and similar.",
                 "fields": [_f("purpose", "Purpose (optional)", hint="e.g. opening a bank account")]},
    "character": {"label": "Character certificate", "title": "CHARACTER CERTIFICATE",
                  "help": "Confirms the student's conduct while studying here.",
                  "fields": [_f("conduct", "Conduct", required=True, default="good")]},
    "completion": {"label": "Course completion certificate", "title": "CERTIFICATE OF COMPLETION",
                   "help": "For a student who has finished a course.",
                   "fields": [_f("course", "Course", required=True, hint="e.g. JEE Main and Advanced (2 year)"),
                              _f("period_from", "From", DATE, True), _f("period_to", "To", DATE, True),
                              _f("result", "Result / grade (optional)", hint="e.g. First class")]},
    "transfer": {"label": "Transfer / leaving certificate", "title": "TRANSFER CERTIFICATE",
                 "help": "For a student who is leaving the institute. Pending fees block it unless you allow it.",
                 "fields": [_f("leaving_date", "Last day at the institute", DATE, True),
                            _f("reason", "Reason for leaving (optional)"),
                            _f("conduct", "Conduct", required=True, default="good")]},
    "achievement": {"label": "Achievement certificate", "title": "CERTIFICATE OF ACHIEVEMENT",
                    "help": "Rewards a result or an effort, such as a rank or full attendance.",
                    "fields": [_f("title", "Achievement", required=True, hint="e.g. First rank in Unit Test 2"),
                               _f("details", "More details (optional)", AREA)]},
}
TYPE_CHOICES = [(k, v["label"]) for k, v in CERT_TYPES.items()]


def today():
    return local_now().date()


def type_label(cert_type):
    return CERT_TYPES.get(cert_type, {}).get("label", cert_type)


# ---------------------------------------------------------------- issuing
def _clean_fields(spec, raw):
    out = {}
    for f in spec["fields"]:
        value = (raw.get(f["key"]) or "").strip()
        if not value:
            value = f["default"] if f["kind"] != DATE else ""
        if f["required"] and not value:
            raise ValueError(f"{f['label']} is required.")
        if f["kind"] == DATE and value:
            try:
                value = date.fromisoformat(value).isoformat()
            except ValueError:
                raise ValueError(f"{f['label']} is not a valid date.")
        limit = 500 if f["kind"] == AREA else 200
        if len(value) > limit:
            raise ValueError(f"{f['label']} is too long (maximum {limit} characters).")
        if value:
            out[f["key"]] = value
    return out


def issue_certificate(user, student, cert_type, issue_date, raw_fields, allow_dues=False):
    spec = CERT_TYPES.get(cert_type)
    if spec is None:
        raise ValueError("Choose the kind of certificate.")
    if issue_date is None:
        raise ValueError("Choose the issue date.")
    if issue_date > today():
        raise ValueError("The issue date cannot be in the future.")
    fields = _clean_fields(spec, raw_fields)
    if cert_type == "completion" and fields["period_to"] < fields["period_from"]:
        raise ValueError("The course cannot end before it starts.")
    if cert_type == "transfer":
        left = date.fromisoformat(fields["leaving_date"])
        if left < student.admitted_on:
            raise ValueError("The last day cannot be before the admission date.")
        owed = sum((d.balance for d in fee_service.outstanding(student)), Decimal("0"))
        if owed > 0 and not allow_dues:
            raise ValueError(f"₹{owed:,.2f} of fees is still pending. Collect it, or tick “Issue even with pending fees”.")
        fields["dues_cleared"] = owed <= 0
    session = academic_service.current_session() or student.session
    cert = Certificate(branch_id=student.branch_id, student_id=student.id, cert_type=cert_type,
                       certificate_no=next_certificate_no(student.branch, session), token=secrets.token_hex(12),
                       issue_date=issue_date, fields=fields, issued_by=user.id)
    db.session.add(cert)
    db.session.flush()
    log_action("certificate_issue", "certificates", cert.id, f"{cert.certificate_no} {cert_type} -> {student.student_code}",
               user=user)
    db.session.commit()
    return cert


def cancel_certificate(cert, reason, user):
    reason = (reason or "").strip()
    if cert.status != "issued":
        raise ValueError("This certificate is already cancelled.")
    if len(reason) < 3:
        raise ValueError("Write the reason for cancelling.")
    cert.status, cert.cancel_reason = "cancelled", reason[:200]
    cert.cancelled_by, cert.cancelled_at = user.id, local_now()
    log_action("certificate_cancel", "certificates", cert.id, f"{cert.certificate_no}: {reason[:80]}", user=user)
    db.session.commit()


# ---------------------------------------------------------------- lists and lookups
def certificates_page(user, cert_type="", status="", q="", branch_id=None, page=1, per_page=20):
    query = scope_to_branch(Certificate.query, Certificate)
    if branch_id and user.is_owner:
        query = query.filter(Certificate.branch_id == branch_id)
    if cert_type in CERT_TYPES:
        query = query.filter(Certificate.cert_type == cert_type)
    if status in ("issued", "cancelled"):
        query = query.filter(Certificate.status == status)
    if q:
        query = (query.join(Student, Student.id == Certificate.student_id)
                 .filter(db.or_(Student.full_name.ilike(f"%{q}%"), Student.student_code.ilike(f"%{q}%"),
                                Certificate.certificate_no.ilike(f"%{q}%"))))
    return query.order_by(Certificate.id.desc()).paginate(page=page, per_page=per_page, error_out=False)


def student_certificates(student, issued_only=True):
    q = Certificate.query.filter_by(student_id=student.id)
    if issued_only:
        q = q.filter_by(status="issued")
    return q.order_by(Certificate.issue_date.desc(), Certificate.id.desc()).all()


def lookup_by_token(token):
    return Certificate.query.filter_by(token=token).first()


def find_students(user, q, limit=20):
    """Student search for the first step of issuing (by name or student ID)."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    query = scope_to_branch(Student.query, Student).filter(
        db.or_(Student.full_name.ilike(f"%{q}%"), Student.student_code.ilike(f"%{q}%")))
    return query.order_by(Student.full_name).limit(limit).all()


# ---------------------------------------------------------------- wording
def _d(value):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d %B %Y")


def _words(student):
    g = (student.gender or "").lower()
    if g == "male":
        return "son", "his", "him"
    if g == "female":
        return "daughter", "her", "her"
    return "ward", "their", "them"


def certificate_text(cert):
    """(title, [paragraph, ...]) in plain text. Used by both the HTML preview and the PDF."""
    st, f, branch = cert.student, cert.fields or {}, cert.branch
    spec = CERT_TYPES[cert.cert_type]
    child, his, him = _words(st)
    parent = st.father_name or st.mother_name
    who = f"{st.full_name}, {child} of {parent}" if parent else st.full_name
    where = f"{branch.institute.name}, {branch.name}"
    ident = f"(Student ID {st.student_code})"

    if cert.cert_type == "bonafide":
        paras = [f"This is to certify that {who} {ident}, born on {_d(st.dob)}, is a bonafide student of {where}, "
                 f"currently studying in {st.class_name} in the academic session {st.session.name}."]
        if f.get("purpose"):
            paras.append(f"This certificate is issued on request for the purpose of {f['purpose']}.")
    elif cert.cert_type == "character":
        paras = [f"This is to certify that {who} {ident}, has been a student of {where} since {_d(st.admitted_on)} "
                 f"and is studying in {st.class_name}.",
                 f"During this time {his} conduct and character have been found to be {f.get('conduct', 'good')}. "
                 f"We wish {him} every success."]
    elif cert.cert_type == "completion":
        paras = [f"This is to certify that {who} {ident}, has successfully completed the course “{f['course']}” at "
                 f"{where}, from {_d(f['period_from'])} to {_d(f['period_to'])}."]
        if f.get("result"):
            paras.append(f"Result / grade: {f['result']}.")
        paras.append(f"We congratulate {st.full_name} and wish {him} all the best for the future.")
    elif cert.cert_type == "transfer":
        paras = [f"This is to certify that {who} {ident}, born on {_d(st.dob)}, was admitted to {where} on "
                 f"{_d(st.admitted_on)} and studied in {st.class_name} until {_d(f['leaving_date'])}."]
        if f.get("reason"):
            paras.append(f"Reason for leaving: {f['reason']}.")
        paras.append(f"{his.capitalize()} conduct was {f.get('conduct', 'good')}. "
                     + ("All fees due to the institute have been cleared."
                        if f.get("dues_cleared", True) else "Fees were not fully cleared at the time of issue."))
    else:  # achievement
        paras = [f"This certificate is proudly awarded to {who} {ident}, of {where}, for {f['title']}."]
        if f.get("details"):
            paras.append(f["details"])
        paras.append("Keep up the excellent work.")
    return spec["title"], paras
