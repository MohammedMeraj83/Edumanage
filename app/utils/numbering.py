"""Unique numbers. Admission no. is per branch + session; student code is institute-wide."""
from sqlalchemy import func
from extensions import db
from app.models import Admission, Student


def _last(column, prefix):
    row = (db.session.query(column).filter(column.like(prefix + "%"))
           .order_by(func.length(column).desc(), column.desc()).first())
    return row[0] if row else None


def session_tag(session):
    return f"{session.start_date.year % 100:02d}{session.end_date.year % 100:02d}"


def next_admission_no(branch, session):
    """e.g. MAIN-2627-0001"""
    prefix = f"{branch.code}-{session_tag(session)}-"
    last = _last(Admission.admission_no, prefix)
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def next_student_code():
    """e.g. STU000001 - no branch inside, so it survives branch transfers."""
    last = _last(Student.student_code, "STU")
    seq = int(last[3:]) + 1 if last else 1
    return f"STU{seq:06d}"


def next_employee_code(model, prefix):
    """TCH000001 for teachers, STF000001 for staff. Institute-wide, never reused."""
    last = _last(model.employee_code, prefix)
    return f"{prefix}{(int(last[len(prefix):]) + 1 if last else 1):06d}"


def next_parent_code():
    from app.models import Parent
    last = _last(Parent.parent_code, "PAR")
    return f"PAR{(int(last[3:]) + 1 if last else 1):06d}"


def next_receipt_no(branch, session):
    """RCT-MAIN-2627-000001 (per branch and session)."""
    from app.models import Payment
    prefix = f"RCT-{branch.code}-{session_tag(session)}-"
    last = _last(Payment.receipt_no, prefix)
    return f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):06d}"


def next_refund_no(branch, session):
    from app.models import Refund
    prefix = f"RFD-{branch.code}-{session_tag(session)}-"
    last = _last(Refund.refund_no, prefix)
    return f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):06d}"


def next_slip_no(branch, month):
    """SAL-MAIN-2607-0001 (per branch and month)."""
    from app.models import Payroll
    prefix = f"SAL-{branch.code}-{month:%y%m}-"
    last = _last(Payroll.slip_no, prefix)
    return f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):04d}"


def next_certificate_no(branch, session):
    """CRT-MAIN-2627-0001 (per branch and session). Numbers are never reused, even for cancelled certificates."""
    from app.models import Certificate
    prefix = f"CRT-{branch.code}-{session_tag(session)}-"
    last = _last(Certificate.certificate_no, prefix)
    return f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):04d}"
