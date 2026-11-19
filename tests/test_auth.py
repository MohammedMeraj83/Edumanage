from extensions import db
from app.models import User, LoginLog
from conftest import make_user, login


def test_seed_creates_owner_forced_password_change(client):
    owner = User.query.filter_by(username="owner").first()
    assert owner and owner.must_change_password and owner.is_owner


def test_login_success_redirects_to_role_dashboard(client):
    make_user("teacher", "tina")
    r = login(client, "tina")
    assert r.status_code == 302 and r.location.endswith("/teacher/dashboard")


def test_login_by_email_and_wrong_password(client):
    make_user("teacher", "tina")
    assert login(client, "tina@t.com").status_code == 302
    client.post("/auth/logout")
    r = login(client, "tina", "wrong")
    assert r.status_code == 200 and b"Incorrect username or password" in r.data


def test_lockout_after_five_failures(client):
    u = make_user("student", "sam")
    for _ in range(5):
        login(client, "sam", "bad")
    assert db.session.get(User, u.id).is_locked
    r = login(client, "sam")  # correct password still refused while locked
    assert r.status_code == 200 and b"locked" in r.data
    assert LoginLog.query.filter_by(success=False).count() >= 6


def test_inactive_user_cannot_login(client):
    u = make_user("student", "sam")
    u.is_active_user = False
    db.session.commit()
    assert login(client, "sam").status_code == 200


def test_open_redirect_blocked(client):
    make_user("teacher", "tina")
    r = client.post("/auth/login?next=https://evil.com", data={"identifier": "tina", "password": "Passw0rd!x"})
    assert "evil.com" not in r.location


def test_must_change_password_gate(client):
    login(client, "owner", "ChangeMe@123")
    r = client.get("/owner/dashboard")
    assert r.status_code == 302 and "change-password" in r.location
    r = client.post("/auth/change-password", data={
        "current_password": "ChangeMe@123", "new_password": "NewPass123", "confirm_password": "NewPass123"})
    assert r.status_code == 302
    assert client.get("/owner/dashboard").status_code == 200
