import base64
import hmac
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlparse
import logging
import requests
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from flask import current_app
from sqlalchemy import or_
from extensions import db
from app.models import (
    Branch, Enquiry, ENQUIRY_STATUSES, Notice, Notification, Parent, PushSubscription, Role,
    Student, StudentParent, User,
)
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)

NOTICE_AUDIENCES = (
    ("all", "All staff, students and parents"),
    ("branch_admin", "Branch admins"),
    ("accountant", "Accountants"),
    ("teacher", "Teachers"),
    ("student", "Students"),
    ("parent", "Parents"),
)


def create_enquiry(*, branch_id, full_name, phone, email, course_interest, message, source, user=None):
    name = (full_name or "").strip()
    phone = (phone or "").strip()
    email = (email or "").strip().lower()
    course_interest = (course_interest or "").strip()
    message = (message or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Enter a name of up to 120 characters.")
    if not phone and not email:
        raise ValueError("Enter at least one contact method: phone or email.")
    if len(phone) > 20 or len(email) > 120:
        raise ValueError("Phone or email is too long.")
    if phone and (not re.fullmatch(r"[0-9+(). -]+", phone) or sum(char.isdigit() for char in phone) < 7):
        raise ValueError("Enter a valid phone number.")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address.")
    if len(course_interest) > 120 or len(message) > 2000:
        raise ValueError("Course interest or message is too long.")
    if user is not None and not user.is_owner:
        if user.branch_id is None:
            raise ValueError("Your account is not assigned to a branch.")
        branch_id = user.branch_id
    if branch_id is not None:
        branch = db.session.get(Branch, branch_id)
        if branch is None or not branch.is_active:
            raise ValueError("Choose an active branch.")

    enquiry = Enquiry(
        branch_id=branch_id,
        full_name=name,
        phone=phone or None,
        email=email or None,
        course_interest=course_interest or None,
        message=message or None,
        source=source,
        created_by=user.id if user else None,
    )
    db.session.add(enquiry)
    db.session.flush()
    log_action("create", "enquiry", enquiry.id, "Enquiry received", user=user)
    db.session.commit()
    return enquiry


def update_enquiry(enquiry, *, status, follow_up_at, staff_notes, user, branch_id=None, update_branch=False):
    allowed_statuses = {value for value, _ in ENQUIRY_STATUSES}
    if status not in allowed_statuses:
        raise ValueError("Choose a valid enquiry status.")
    notes = (staff_notes or "").strip()
    if len(notes) > 4000:
        raise ValueError("Staff notes must be 4,000 characters or fewer.")
    if update_branch and branch_id is not None:
        branch = db.session.get(Branch, branch_id)
        if branch is None or not branch.is_active:
            raise ValueError("Choose an active branch.")
    enquiry.status = status
    enquiry.follow_up_at = follow_up_at
    enquiry.staff_notes = notes or None
    if update_branch:
        enquiry.branch_id = branch_id
    log_action("update", "enquiry", enquiry.id, f"Status: {status}", user=user)
    db.session.commit()
    return enquiry


def create_notice(*, user, branch_id, title, body, audience):
    title = (title or "").strip()
    body = (body or "").strip()
    valid_audiences = {value for value, _ in NOTICE_AUDIENCES}
    if not title or len(title) > 150:
        raise ValueError("Enter a title of up to 150 characters.")
    if not body or len(body) > 10000:
        raise ValueError("Enter notice text of up to 10,000 characters.")
    if audience not in valid_audiences:
        raise ValueError("Choose a valid audience.")
    if not user.is_owner:
        if user.branch_id is None:
            raise ValueError("Your account is not assigned to a branch.")
        branch_id = user.branch_id
    if branch_id is not None:
        branch = db.session.get(Branch, branch_id)
        if branch is None or not branch.is_active:
            raise ValueError("Choose an active branch.")

    notice = Notice(
        branch_id=branch_id,
        title=title,
        body=body,
        audience=audience,
        created_by=user.id,
    )
    db.session.add(notice)
    db.session.flush()

    recipients = User.query.join(Role, User.role_id == Role.id).filter(
        User.is_active_user.is_(True),
        User.id != user.id,
    )
    if audience != "all":
        recipients = recipients.filter(Role.name == audience)
    else:
        recipients = recipients.filter(Role.name != "owner")

    if branch_id is not None:
        parent_user_ids = (
            db.session.query(Parent.user_id)
            .join(StudentParent, StudentParent.parent_id == Parent.id)
            .join(Student, Student.id == StudentParent.student_id)
            .filter(Student.branch_id == branch_id, Parent.user_id.isnot(None))
        )
        recipients = recipients.filter(
            or_(User.branch_id == branch_id, User.id.in_(parent_user_ids))
        )

    notifications = [
        Notification(notice_id=notice.id, user_id=recipient.id, created_at=datetime.utcnow())
        for recipient in recipients.all()
    ]
    db.session.add_all(notifications)
    log_action("create", "notice", notice.id, f"Audience: {audience}", user=user)
    db.session.commit()
    for notification in notifications:
        send_push_notification(notification)
    return notice


def notify_event(*, actor, title, body, branch_id=None, batch=None, recipient_ids=None):
    """Create an inbox notification and optionally a browser push for an app event.

    When batch is supplied, relevant recipients are resolved automatically: active students,
    their linked parents, the batch teacher, branch admins and owners. Other staff can still
    receive a targeted event by passing recipient_ids explicitly.
    """
    title = (title or "").strip()[:150]
    body = (body or "").strip()[:10000]
    if not title or not body:
        return None

    if recipient_ids is None:
        recipient_ids = set()
    else:
        recipient_ids = set(recipient_ids)

    owner_ids = [u.id for u in (
        db.session.query(User).join(Role, User.role_id == Role.id)
        .filter(Role.name == "owner", User.is_active_user.is_(True)).all()
    )]
    recipient_ids.update(owner_ids)

    if branch_id is not None:
        branch_admin_ids = [u.id for u in (
            db.session.query(User).join(Role, User.role_id == Role.id)
            .filter(Role.name == "branch_admin", User.is_active_user.is_(True),
                    User.branch_id == branch_id).all()
        )]
        recipient_ids.update(branch_admin_ids)

    if batch is not None:
        branch_id = batch.branch_id
        if batch.teacher and batch.teacher.user_id:
            recipient_ids.add(batch.teacher.user_id)


    if batch is not None:
        from app.models import BatchStudent, StudentParent, Parent
        active_students = (
            db.session.query(Student)
            .join(BatchStudent, BatchStudent.student_id == Student.id)
            .filter(BatchStudent.batch_id == batch.id, BatchStudent.status == "active",
                    Student.status == "active").all()
        )
        for student in active_students:
            if student.user_id:
                recipient_ids.add(student.user_id)
            parent_ids = [link.parent.user_id for link in student.parent_links
                          if link.parent.user_id]
            recipient_ids.update(parent_ids)

    if actor is not None:
        recipient_ids.discard(actor.id)

    recipient_ids = {int(uid) for uid in recipient_ids if uid}
    if not recipient_ids:
        return None

    notice = Notice(branch_id=branch_id, title=title, body=body,
                    audience="all", created_by=actor.id if actor else None)
    db.session.add(notice)
    db.session.flush()
    notifications = [Notification(notice_id=notice.id, user_id=uid,
                                  created_at=datetime.utcnow())
                     for uid in recipient_ids]
    db.session.add_all(notifications)
    db.session.commit()
    for notification in notifications:
        send_push_notification(notification)
    return notice


def _endpoint_hash(endpoint):
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def save_push_subscription(*, user, endpoint, p256dh, auth):
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError("The browser push endpoint is invalid.")
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    trusted_host = (
        host == "fcm.googleapis.com"
        or host == "updates.push.services.mozilla.com"
        or host.endswith(".push.apple.com")
        or host.endswith(".notify.windows.com")
    )
    if (parsed.scheme != "https" or not trusted_host or parsed.username or parsed.password
            or parsed.port not in (None, 443)):
        raise ValueError("This browser's push provider is not supported.")
    if not isinstance(p256dh, str) or not re.fullmatch(r"[A-Za-z0-9_-]{80,160}", p256dh):
        raise ValueError("The browser push keys are invalid.")
    if not isinstance(auth, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", auth):
        raise ValueError("The browser push keys are invalid.")

    digest = _endpoint_hash(endpoint)
    subscription = PushSubscription.query.filter_by(endpoint_hash=digest).first()
    if subscription and subscription.user_id != user.id:
        raise ValueError("This device is registered to another account. Turn off push there first.")
    if subscription is None:
        subscription = PushSubscription(user_id=user.id, endpoint=endpoint, endpoint_hash=digest,
                                        p256dh=p256dh, auth=auth)
        db.session.add(subscription)
    else:
        subscription.p256dh = p256dh
        subscription.auth = auth
    db.session.commit()
    return subscription


def remove_push_subscription(*, user, endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError("The browser push endpoint is invalid.")
    subscription = PushSubscription.query.filter_by(
        user_id=user.id, endpoint_hash=_endpoint_hash(endpoint)
    ).first()
    if subscription:
        db.session.delete(subscription)
        db.session.commit()


def configured_vapid_key():
    public_key = current_app.config["VAPID_PUBLIC_KEY"]
    private_key = current_app.config["VAPID_PRIVATE_KEY"]
    if not public_key or not private_key:
        return None, "Phone notifications are not configured on this server yet."

    from py_vapid import Vapid

    try:
        if "-----BEGIN " in private_key:
            vapid_key = Vapid.from_pem(private_key.encode("utf-8"))
        else:
            vapid_key = Vapid.from_string(private_key)
        derived_public_key = base64.urlsafe_b64encode(
            vapid_key.public_key.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        ).decode("ascii").rstrip("=")
    except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
        logger.error("Invalid VAPID private key configuration (%s).", type(exc).__name__)
        return None, "The server's VAPID private key is invalid. Regenerate the VAPID key pair and restart the app."

    if (not isinstance(public_key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{87}", public_key)
            or not hmac.compare_digest(public_key, derived_public_key)):
        logger.error("Configured VAPID public and private keys do not match.")
        return None, "The server's VAPID public and private keys do not match. Configure a matching pair."
    return vapid_key, None


def send_push_notification(notification):
    vapid_key, error = configured_vapid_key()
    if error:
        return

    from pywebpush import WebPushException, webpush

    payload = json.dumps({
        "title": notification.notice.title,
        "body": notification.notice.body[:240],
        "url": f"/notifications/{notification.id}",
        "tag": f"edumanage-notification-{notification.id}",
    })
    subscriptions = PushSubscription.query.filter_by(user_id=notification.user_id).all()
    for subscription in subscriptions:
        try:
            response = webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=payload,
                vapid_private_key=vapid_key,
                vapid_claims={"sub": current_app.config["VAPID_CLAIMS_EMAIL"]},
                timeout=5,
            )
            logger.info(
                "Web push accepted by the provider for subscription %s (HTTP %s)",
                subscription.id,
                response.status_code,
            )
        except WebPushException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in (404, 410):
                db.session.delete(subscription)
                db.session.commit()
                continue
            logger.warning("Web push failed for subscription %s (HTTP %s)", subscription.id, status_code)
        except requests.RequestException:
            logger.exception("Network error sending web push for subscription %s", subscription.id)


def update_notice(notice, *, title, body, audience, user):
    title = (title or "").strip()
    body = (body or "").strip()
    valid_audiences = {value for value, _ in NOTICE_AUDIENCES}
    if not title or len(title) > 150:
        raise ValueError("Enter a title of up to 150 characters.")
    if not body or len(body) > 10000:
        raise ValueError("Enter notice text of up to 10,000 characters.")
    if audience not in valid_audiences:
        raise ValueError("Choose a valid audience.")
    if audience != notice.audience:
        raise ValueError("A published notice's audience cannot be changed.")
    notice.title = title
    notice.body = body
    notice.audience = audience
    log_action("update", "notice", notice.id, "Notice updated", user=user)
    db.session.commit()
    return notice


def delete_notice(notice, *, user):
    log_action("delete", "notice", notice.id, "Notice withdrawn", user=user)
    db.session.delete(notice)
    db.session.commit()


def mark_notification_read(notification, *, user):
    if notification.user_id != user.id:
        raise PermissionError("This notification belongs to another account.")
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        db.session.commit()
    return notification
