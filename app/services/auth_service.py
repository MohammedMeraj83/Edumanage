from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy import or_, func
from extensions import db
from app.models import User
from .audit_service import log_action, log_login


def find_user(identifier):
    ident = (identifier or "").strip().lower()
    return User.query.filter(
        or_(func.lower(User.username) == ident, func.lower(User.email) == ident)
    ).first()


def authenticate(identifier, password):
    """Return (user, error_message). error_message is None on success."""
    user = find_user(identifier)
    generic = "Incorrect username or password."

    if user is None:
        log_login(identifier, False, reason="unknown_user")
        db.session.commit()
        return None, generic

    if user.is_locked:
        log_login(identifier, False, user, "locked")
        db.session.commit()
        return None, "Account is temporarily locked after too many failed attempts. Try again later."

    if not user.check_password(password):
        user.failed_attempts += 1
        if user.failed_attempts >= current_app.config["MAX_FAILED_LOGINS"]:
            user.locked_until = datetime.utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
            user.failed_attempts = 0
        log_login(identifier, False, user, "bad_password")
        db.session.commit()
        return None, generic

    if not user.is_active:
        log_login(identifier, False, user, "inactive")
        db.session.commit()
        return None, "This account is disabled. Contact your administrator."

    if user.branch is not None and not user.branch.is_active:
        log_login(identifier, False, user, "branch_inactive")
        db.session.commit()
        return None, "Your branch is currently inactive. Contact the owner."

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    log_login(identifier, True, user)
    log_action("login", "users", user.id, user=user)
    db.session.commit()
    return user, None
