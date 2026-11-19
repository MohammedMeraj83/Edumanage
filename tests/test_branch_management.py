from datetime import date
from extensions import db
from app.models import Branch, User, AcademicSession, Institute
from conftest import make_user, login

BRANCH = {"name": "City Branch", "code": "city1", "phone": "9876543210", "email": "city@t.com",
          "address": "Main road", "city": "Nanded", "state": "Maharashtra", "pincode": "431601"}


def owner_client(client):
    make_user("owner", "boss")
    login(client, "boss")
    return client


def flashes(client):
    with client.session_transaction() as s:
        return [m for _, m in s.get("_flashes", [])]


def test_owner_dashboard_and_branch_list(client):
    owner_client(client)
    assert client.get("/owner/dashboard").status_code == 200
    r = client.get("/owner/branches/")
    assert r.status_code == 200 and b"Main Branch" in r.data


def test_create_branch_uppercases_code_and_blocks_duplicates(client):
    owner_client(client)
    r = client.post("/owner/branches/new", data=BRANCH)
    assert r.status_code == 302
    assert Branch.query.filter_by(code="CITY1").first() is not None
    r = client.post("/owner/branches/new", data={**BRANCH, "code": "CITY1", "name": "Other"})
    assert r.status_code == 200 and b"already used" in r.data
    assert Branch.query.filter_by(code="CITY1").count() == 1


def test_branch_admin_cannot_manage_branches(client):
    make_user("branch_admin", "bob")
    login(client, "bob")
    assert client.get("/owner/branches/").status_code == 403
    assert client.post("/owner/branches/new", data=BRANCH).status_code == 403
    assert client.get("/owner/sessions").status_code == 403


def test_edit_keeps_code_and_main_branch_cannot_be_deactivated(client):
    owner_client(client)
    main = Branch.query.filter_by(is_main=True).first()
    r = client.post(f"/owner/branches/{main.id}/edit", data={**BRANCH, "code": "HACK", "name": "Renamed"})
    assert r.status_code == 302
    db.session.refresh(main)
    assert main.name == "Renamed" and main.code == "MAIN"
    client.post(f"/owner/branches/{main.id}/toggle")
    db.session.refresh(main)
    assert main.is_active is True


def test_deactivated_branch_blocks_its_users(client):
    owner_client(client)
    client.post("/owner/branches/new", data=BRANCH)
    b = Branch.query.filter_by(code="CITY1").first()
    make_user("teacher", "tina", branch_code="CITY1")
    client.post(f"/owner/branches/{b.id}/toggle")
    db.session.refresh(b)
    assert b.is_active is False
    other = client.application.test_client()
    r = login(other, "tina")
    assert r.status_code == 200 and b"inactive" in r.data


def test_create_admin_with_temp_password_and_forced_change(client):
    owner_client(client)
    client.post("/owner/branches/new", data=BRANCH)
    b = Branch.query.filter_by(code="CITY1").first()
    r = client.post(f"/owner/branches/{b.id}/admins/new", data={
        "full_name": "Asha Patil", "username": "asha", "email": "asha@t.com", "phone": ""})
    assert r.status_code == 302
    msg = [m for m in flashes(client) if "Temporary password" in m][0]
    temp = msg.split("Temporary password: ")[1].split(" ")[0]
    user = User.query.filter_by(username="asha").first()
    assert user.role.name == "branch_admin" and user.branch_id == b.id and user.must_change_password

    admin = client.application.test_client()
    r = login(admin, "asha", temp)
    assert r.status_code == 302 and "change-password" in r.location

    # duplicate username / email rejected
    r = client.post(f"/owner/branches/{b.id}/admins/new", data={
        "full_name": "X", "username": "ASHA", "email": "asha@t.com", "phone": ""})
    assert r.status_code == 200 and b"taken" in r.data


def test_reset_password_and_disable_admin(client):
    owner_client(client)
    client.post("/owner/branches/new", data=BRANCH)
    b = Branch.query.filter_by(code="CITY1").first()
    admin = make_user("branch_admin", "bob", branch_code="CITY1")
    client.post(f"/owner/branches/{b.id}/admins/{admin.id}/reset-password")
    db.session.refresh(admin)
    assert admin.must_change_password and not admin.check_password("Passw0rd!x")
    client.post(f"/owner/branches/{b.id}/admins/{admin.id}/toggle")
    db.session.refresh(admin)
    assert admin.is_active_user is False
    # an admin id from another branch must not be reachable through this branch URL
    main = Branch.query.filter_by(is_main=True).first()
    assert client.post(f"/owner/branches/{main.id}/admins/{admin.id}/toggle").status_code == 404


def test_institute_profile_update(client):
    owner_client(client)
    r = client.post("/owner/institute", data={"name": "Bright Tuition", "tagline": "Learn well",
                                              "email": "info@bright.com", "phone": "9876543210"})
    assert r.status_code == 302
    assert Institute.query.first().name == "Bright Tuition"


def test_session_rules(client):
    owner_client(client)
    r = client.post("/owner/sessions/new", data={"name": "2027-28", "start_date": "2027-04-01",
                                                  "end_date": "2028-03-31", "is_current": "y"})
    assert r.status_code == 302
    assert AcademicSession.query.filter_by(is_current=True).count() == 1
    assert AcademicSession.query.filter_by(is_current=True).first().name == "2027-28"
    # end before start
    r = client.post("/owner/sessions/new", data={"name": "Bad", "start_date": "2028-04-01", "end_date": "2028-03-01"})
    assert r.status_code == 200 and b"after the start" in r.data
    # duplicate name
    r = client.post("/owner/sessions/new", data={"name": "2027-28", "start_date": "2027-04-01", "end_date": "2028-03-31"})
    assert r.status_code == 200 and b"already exists" in r.data
    # switch back via set-current
    old = AcademicSession.query.filter_by(is_current=False).first()
    client.post(f"/owner/sessions/{old.id}/set-current")
    db.session.refresh(old)
    assert old.is_current and AcademicSession.query.filter_by(is_current=True).count() == 1
