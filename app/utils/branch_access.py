"""Branch-level data isolation.

Owner  -> sees every branch.
Others -> restricted to their own branch_id.
"""
from flask import abort
from flask_login import current_user


def current_branch_id():
    """None means 'all branches' (Owner)."""
    if current_user.is_owner:
        return None
    return current_user.branch_id


def scope_to_branch(query, model):
    """Filter a SQLAlchemy query on a model having `branch_id`."""
    branch_id = current_branch_id()
    if branch_id is not None:
        query = query.filter(model.branch_id == branch_id)
    return query


def ensure_branch_access(branch_id):
    """Abort 403 if the user may not touch records of `branch_id`."""
    allowed = current_branch_id()
    if allowed is not None and allowed != branch_id:
        abort(403)
