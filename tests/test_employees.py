import io
from extensions import db
from app.models import Teacher, Staff, User, EmployeeDocument
from conftest import make_user, login, add_branch, temp_password_from


def person(**over):
    d = {"full_name": "Meena Kulkarni", "gender": "Female", "dob": "1990-03-12", "phone": "9123456780",
         "email": "", "qualification": "M.Sc", "joining_date": "2026-06-01", "address": "", "notes": "",
         "specialization": "Maths, Science", "experience_years": "5"}
    d.update(over)
    return d


def staff_person(**over):
    d = person(designation="Accountant")
    d.pop("specialization"); d.pop("experience_years")
    d.update(over)
    return d


def admin_client(client):
    make_user("branch_admin", "bob")
    login(client, "bob")
    return client


def test_branch_admin_adds_teacher_with_unique_code(client):
    admin_client(client)
    assert client.post("/teachers/new", data=person()).status_code == 302
    assert client.post("/teachers/new", data=person(full_name="Ravi Shah", phone="9000000001")).status_code == 302
    t1, t2 = Teacher.query.order_by(Teacher.id).all()
    assert (t1.employee_code, t2.employee_code) == ("TCH000001", "TCH000002")
    assert t1.branch.code == "MAIN"


def test_duplicate_phone_blocked_and_search(client):
    admin_client(client)
    client.post("/teachers/new", data=person())
    r = client.post("/teachers/new", data=person(full_name="Other"))
    assert r.status_code == 200 and b"already registered" in r.data
    assert Teacher.query.count() == 1
    assert b"Meena" in client.get("/teachers/?q=meena").data
    assert b"Meena" not in client.get("/teachers/?q=nobody").data


def test_teacher_login_and_dashboard(client):
    admin_client(client)
    client.post("/teachers/new", data=person(create_login="y"))
    temp = temp_password_from(client)
    t = Teacher.query.one()
    assert t.user and t.user.role.name == "teacher" and t.user.username == "tch000001"
    me = client.application.test_client()
    r = login(me, "tch000001", temp)
    assert r.status_code == 302 and "change-password" in r.location
    me.post("/auth/change-password", data={"current_password": temp, "new_password": "NewPass123",
                                           "confirm_password": "NewPass123"})
    page = me.get("/teacher/dashboard")
    assert page.status_code == 200 and b"TCH000001" in page.data
    assert me.get("/teachers/").status_code == 403


def test_inactive_teacher_cannot_sign_in(client):
    admin_client(client)
    client.post("/teachers/new", data=person(create_login="y"))
    temp = temp_password_from(client)
    t = Teacher.query.one()
    client.post(f"/teachers/{t.id}/status", data={"status": "left"})
    assert login(client.application.test_client(), "tch000001", temp).status_code == 200


def test_staff_login_only_for_accountants(client):
    admin_client(client)
    client.post("/staff/new", data=staff_person(designation="Peon", phone="9111111111"))
    peon = Staff.query.one()
    client.post(f"/staff/{peon.id}/create-login")
    db.session.refresh(peon)
    assert peon.user_id is None
    client.post("/staff/new", data=staff_person(phone="9222222222", create_login="y"))
    acc = Staff.query.filter_by(designation="Accountant").one()
    assert acc.employee_code == "STF000002" and acc.user.role.name == "accountant"
    temp = temp_password_from(client)
    other = client.application.test_client()
    assert login(other, acc.user.username, temp).status_code == 302


def test_branch_isolation(client):
    add_branch("CITY1")
    admin_client(client)
    client.post("/teachers/new", data=person())
    t = Teacher.query.one()
    make_user("branch_admin", "cara", branch_code="CITY1")
    other = client.application.test_client()
    login(other, "cara")
    assert other.get(f"/teachers/{t.id}").status_code == 403
    assert other.post(f"/teachers/{t.id}/status", data={"status": "left"}).status_code == 403
    assert b"Meena" not in other.get("/teachers/?status=all").data


def test_owner_chooses_branch_and_accountant_has_no_access(client):
    b2 = add_branch("CITY1")
    make_user("owner", "boss")
    login(client, "boss")
    client.post("/teachers/new", data=person(branch_id=b2.id))
    assert Teacher.query.one().branch_id == b2.id
    make_user("accountant", "ann")
    acc = client.application.test_client()
    login(acc, "ann")
    assert acc.get("/teachers/").status_code == 403
    assert acc.get("/staff/").status_code == 403


def test_documents_private_per_branch(client):
    add_branch("CITY1")
    admin_client(client)
    client.post("/teachers/new", data=person())
    t = Teacher.query.one()
    r = client.post(f"/teachers/{t.id}/documents", content_type="multipart/form-data",
                    data={"doc_type": "id_proof", "file": (io.BytesIO(b"%PDF-1.4 x"), "id.pdf")})
    assert r.status_code == 302
    doc = EmployeeDocument.query.one()
    assert client.get(f"/teachers/files/{doc.id}").status_code == 200
    make_user("branch_admin", "cara", branch_code="CITY1")
    other = client.application.test_client()
    login(other, "cara")
    assert other.get(f"/teachers/files/{doc.id}").status_code == 403
    # a teacher's document cannot be fetched through the staff module
    assert client.get(f"/staff/files/{doc.id}").status_code == 404


def test_branch_admin_dashboard_counts(client):
    admin_client(client)
    client.post("/teachers/new", data=person())
    page = client.get("/branch-admin/dashboard")
    assert page.status_code == 200 and b"Active students" in page.data
