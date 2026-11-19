from functools import wraps
from flask import abort
from flask_login import current_user, login_required


def role_required(*roles):
    """Allow only users whose role is in `roles`."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.has_role(*roles):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(code):
    """Allow only users who hold permission `code` (Owner always passes)."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.has_permission(code):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def staff_permission(code, roles=("owner", "branch_admin", "accountant")):
    """Role must be institute staff AND hold the permission (students/parents never pass)."""
    def decorator(view):
        return role_required(*roles)(permission_required(code)(view))
    return decorator
