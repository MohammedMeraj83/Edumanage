from datetime import datetime, date
from extensions import db
from app.models import LeaveRequest
from app.services.audit_service import log_action


def apply_leave(kind, person, requester, from_date, to_date, reason):
    if to_date < from_date:
        raise ValueError("The last day cannot be before the first day.")
    if to_date < date.today():
        raise ValueError("Leave cannot be applied for days that are already over.")
    if (to_date - from_date).days > 60:
        raise ValueError("Leave longer than 60 days needs to be split.")
    col = {"teacher": LeaveRequest.teacher_id, "student": LeaveRequest.student_id}[kind]
    clash = LeaveRequest.query.filter(LeaveRequest.kind == kind, col == person.id, LeaveRequest.status != "rejected",
                                      LeaveRequest.from_date <= to_date, LeaveRequest.to_date >= from_date).first()
    if clash:
        raise ValueError("There is already a leave request for some of these days.")
    req = LeaveRequest(branch_id=person.branch_id, kind=kind, requested_by=requester.id, from_date=from_date,
                       to_date=to_date, reason=reason.strip()[:255], status="pending",
                       **{f"{kind}_id": person.id})
    db.session.add(req)
    db.session.flush()
    log_action("leave_apply", "leave_requests", req.id, f"{kind} {person.full_name}: {from_date} to {to_date}",
               user=requester)
    db.session.commit()
    return req


def decide(req, approve, note, user):
    if req.status != "pending":
        raise ValueError("This request was already decided.")
    req.status = "approved" if approve else "rejected"
    req.decided_by, req.decided_at = user.id, datetime.utcnow()
    req.decision_note = (note or "").strip()[:255] or None
    log_action("leave_" + req.status, "leave_requests", req.id, f"{req.kind} request {req.id}", user=user)
    db.session.commit()


def cancel(req, user):
    if req.status != "pending" or req.requested_by != user.id:
        raise ValueError("Only your own pending request can be withdrawn.")
    log_action("leave_cancel", "leave_requests", req.id, f"{req.kind} request {req.id}", user=user)
    db.session.delete(req)
    db.session.commit()
