from flask_login import login_user
from app.models import Branch
from app.utils.branch_access import current_branch_id, ensure_branch_access
from extensions import db
from conftest import make_user
import pytest
from werkzeug.exceptions import Forbidden


def test_branch_isolation_helpers(app):
    second = Branch(institute_id=1, code="B2", name="Second")
    db.session.add(second)
    db.session.commit()
    admin = make_user("branch_admin", "bob")
    owner = make_user("owner", "boss")

    with app.test_request_context():
        login_user(owner)
        assert current_branch_id() is None
        ensure_branch_access(second.id)  # owner passes everywhere

    with app.test_request_context():
        login_user(admin)
        assert current_branch_id() == admin.branch_id
        ensure_branch_access(admin.branch_id)
        with pytest.raises(Forbidden):
            ensure_branch_access(second.id)
