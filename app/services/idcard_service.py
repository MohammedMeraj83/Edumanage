"""ID cards for students, teachers and staff.

- A person has at most ONE active card. Re-issuing (lost / damaged) closes the old one, so a lost card stops verifying.
- The QR on a card opens a public page that confirms the card is real and still valid (it shows no phone, photo or address).
- Cards are valid until the end of the current academic session.
"""
import os
import secrets
from datetime import timedelta
from flask import current_app
from extensions import db
from app.models import IdCard, Student, Teacher, Staff
from app.services import academic_service
from app.services.audit_service import log_action
from app.utils.branch_access import scope_to_branch
from app.utils.date_utils import local_now

KINDS = {
    "student": {"model": Student, "label": "Student", "code": "student_code", "folder": "students", "perm": "students"},
    "teacher": {"model": Teacher, "label": "Teacher", "code": "employee_code", "folder": "employees", "perm": "teachers"},
    "staff": {"model": Staff, "label": "Staff", "code": "employee_code", "folder": "employees", "perm": "staff"},
}
CLOSE_REASONS = {"lost": "Lost", "cancelled": "Cancelled"}


def today():
    return local_now().date()


def get_person(kind, person_id):
    cfg = KINDS.get(kind)
    return db.session.get(cfg["model"], person_id) if cfg else None


def person_info(kind, p):
    """Everything a card or a verification page needs, in one plain dict."""
    cfg = KINDS[kind]
    if kind == "student":
        line = p.class_name
    elif kind == "teacher":
        line = p.specialization or "Teacher"
    else:
        line = p.designation
    photo = os.path.join(current_app.config["UPLOAD_FOLDER"], cfg["folder"], p.photo) if p.photo else None
    return {"kind": kind, "role": cfg["label"], "name": p.full_name, "code": getattr(p, cfg["code"]), "line": line,
            "dob": p.dob, "phone": p.phone or getattr(p, "guardian_phone", None), "blood_group": getattr(p, "blood_group", None),
            "address": p.address, "branch": p.branch, "photo_path": photo if photo and os.path.exists(photo) else None}


def active_card(kind, person_id):
    return (IdCard.query.filter_by(person_kind=kind, person_id=person_id, status="active")
            .order_by(IdCard.id.desc()).first())


def cards_map(kind, person_ids):
    """{person_id: active IdCard} in one query."""
    if not person_ids:
        return {}
    rows = IdCard.query.filter(IdCard.person_kind == kind, IdCard.person_id.in_(person_ids),
                               IdCard.status == "active").order_by(IdCard.id).all()
    return {c.person_id: c for c in rows}


def card_is_valid(card):
    return card.status == "active" and card.valid_until >= today()


def people_page(kind, user, q="", class_name="", status="active", branch_id=None, page=1, per_page=25):
    model = KINDS[kind]["model"]
    query = scope_to_branch(model.query, model)
    if branch_id and user.is_owner:
        query = query.filter(model.branch_id == branch_id)
    if status in ("active", "inactive", "left"):
        query = query.filter(model.status == status)
    if class_name and kind == "student":
        query = query.filter(Student.class_name == class_name)
    if q:
        code = getattr(model, KINDS[kind]["code"])
        query = query.filter(db.or_(model.full_name.ilike(f"%{q}%"), code.ilike(f"%{q}%")))
    return query.order_by(model.full_name).paginate(page=page, per_page=per_page, error_out=False)


def issue_card(kind, person, user, reason=None, replace=False, old_status="replaced"):
    """Issue a card. Returns (card, created). Without replace=True an existing active card is simply returned."""
    if person.status != "active":
        raise ValueError(f"Only active people can get an ID card. {person.full_name} is {person.status}.")
    existing = active_card(kind, person.id)
    if existing and not replace:
        return existing, False
    if old_status not in ("replaced", "lost", "cancelled"):
        raise ValueError("Choose why the old card is being replaced.")
    now = local_now()
    if existing:
        existing.status, existing.closed_at, existing.closed_by = old_status, now, user.id
    count = IdCard.query.filter_by(person_kind=kind, person_id=person.id).count()
    code = getattr(person, KINDS[kind]["code"])
    session = academic_service.current_session()
    valid_until = session.end_date if session and session.end_date >= today() else today() + timedelta(days=365)
    card = IdCard(branch_id=person.branch_id, person_kind=kind, person_id=person.id, card_no=f"{code}-{count + 1:02d}",
                  token=secrets.token_hex(12), issued_on=today(), valid_until=valid_until,
                  reason=(reason or "").strip()[:120] or None, issued_by=user.id)
    db.session.add(card)
    db.session.flush()
    log_action("idcard_issue", "id_cards", card.id, f"{card.card_no} ({kind})", user=user)
    db.session.commit()
    return card, True


def close_card(card, status, user):
    if status not in CLOSE_REASONS:
        raise ValueError("Choose Lost or Cancelled.")
    if card.status != "active":
        raise ValueError("This card is already closed.")
    card.status, card.closed_at, card.closed_by = status, local_now(), user.id
    log_action("idcard_close", "id_cards", card.id, f"{card.card_no}: {status}", user=user)
    db.session.commit()


def ensure_cards(kind, people, user):
    """For bulk printing: give every active person a card (reusing existing ones). Returns [(info, card)]."""
    have = cards_map(kind, [p.id for p in people])
    out = []
    for p in people:
        card = have.get(p.id)
        if card is None:
            card, _ = issue_card(kind, p, user)
        out.append((person_info(kind, p), card))
    return out


def lookup_by_token(token):
    """For the public verification page: (card, info) or (None, None)."""
    card = IdCard.query.filter_by(token=token).first()
    if not card:
        return None, None
    person = get_person(card.person_kind, card.person_id)
    return card, (person_info(card.person_kind, person) if person else None)
