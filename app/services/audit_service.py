from flask import has_request_context
from flask_login import current_user
from extensions import db
from app.models import AuditLog, LoginLog
from app.utils.helpers import client_ip


def log_action(action, entity=None, entity_id=None, details=None, user=None):
    """Write an audit entry. Call BEFORE db.session.commit() of the main action
    so both are saved together, or commit separately afterwards."""
    u = user or (current_user if current_user and current_user.is_authenticated else None)
    db.session.add(AuditLog(
        user_id=u.id if u else None,
        branch_id=u.branch_id if u else None,
        action=action, entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
        ip_address=client_ip() if has_request_context() else None,
    ))


def log_login(username, success, user=None, reason=None):
    from flask import request
    db.session.add(LoginLog(
        user_id=user.id if user else None,
        username_tried=(username or "")[:120],
        success=success, reason=reason,
        ip_address=client_ip(),
        user_agent=(request.user_agent.string or "")[:255],
    ))
