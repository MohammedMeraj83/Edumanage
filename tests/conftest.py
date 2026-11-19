import pytest
from app import create_app
from extensions import db
from app.models import Branch, User, Role
from app.services.seed_service import seed_all


from flask import message_flashed, session, has_request_context

@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNER_PASSWORD", "ChangeMe@123")
    monkeypatch.setenv("OWNER_USERNAME", "owner")
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path)

    def _record_flash(sender, message, category, **extra):
        if has_request_context():
            session.setdefault("_all_flashes", []).append((category, message))

    message_flashed.connect(_record_flash, app)

    def _fresh_login_state():
        # The tests keep one app context open, so Flask's `g` would carry the previous request's user
        # into the next request (other test client). Clear it so every request starts anonymous.
        from flask import g
        g.pop("_login_user", None)
        if has_request_context():
            session.pop("_all_flashes", None)
    app.before_request_funcs.setdefault(None, []).insert(0, _fresh_login_state)
    with app.app_context():
        db.create_all()
        seed_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(role, username, branch_code="MAIN", password="Passw0rd!x"):
    branch = Branch.query.filter_by(code=branch_code).first()
    u = User(username=username, email=f"{username}@t.com", full_name=username.title(),
             role_id=Role.query.filter_by(name=role).first().id,
             branch_id=None if role == "owner" else branch.id)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


def login(client, ident, pw="Passw0rd!x"):
    return client.post("/auth/login", data={"identifier": ident, "password": pw}, follow_redirects=False)


def add_branch(code="CITY1", name="City Branch"):
    from app.models import Institute
    b = Branch(institute_id=Institute.query.first().id, code=code, name=name)
    db.session.add(b)
    db.session.commit()
    return b


def flashes(client):
    with client.session_transaction() as s:
        raw = s.get("_flashes") or s.get("_all_flashes") or []
        return [m for _, m in raw]


def temp_password_from(client):
    msg = [m for m in flashes(client) if "Temporary password: " in m][-1]
    return msg.split("Temporary password: ")[1].strip()
