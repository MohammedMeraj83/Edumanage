from app.models import Role, Branch, User
from app.utils.permissions import ALL_PERMISSIONS
from conftest import make_user, login


def test_anonymous_redirected_to_login(client):
    r = client.get("/owner/dashboard")
    assert r.status_code == 302 and "/auth/login" in r.location


def test_role_cannot_open_other_panel(client):
    make_user("teacher", "tina")
    login(client, "tina")
    assert client.get("/teacher/dashboard").status_code == 200
    assert client.get("/owner/dashboard").status_code == 403
    assert client.get("/accountant/dashboard").status_code == 403


def test_owner_has_every_permission(client):
    owner = User.query.filter_by(username="owner").first()
    assert all(owner.has_permission(c) for c in ALL_PERMISSIONS)


def test_permission_matrix(client):
    acc = make_user("accountant", "ann")
    teacher = make_user("teacher", "tina")
    admin = make_user("branch_admin", "bob")
    assert acc.has_permission("fees.create") and not acc.has_permission("students.delete")
    assert teacher.has_permission("attendance.create") and not teacher.has_permission("fees.view")
    assert admin.has_permission("students.create") and not admin.has_permission("branches.create")


def test_six_roles_exist(client):
    assert Role.query.count() == 6
