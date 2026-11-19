from extensions import db
from app.models import Admission, Student, StudentTransfer, User
from conftest import make_user, login, add_branch, temp_password_from
from test_admissions import admission_data


def make_student(client, **over):
    """Owner walk-in admission -> returns the Student."""
    from app.models import Branch
    make_user("owner", "boss")
    login(client, "boss")
    main = Branch.query.filter_by(is_main=True).first()
    client.post("/admissions/new", data=admission_data(branch_id=main.id, approve_now="y", **over))
    return Student.query.order_by(Student.id.desc()).first()


def test_search_and_filters(client):
    make_student(client)
    assert b"Rohan Patil" in client.get("/students/?q=rohan").data
    assert b"Rohan Patil" not in client.get("/students/?q=zzz").data
    assert b"Rohan Patil" in client.get("/students/?q=STU000001").data
    assert b"Rohan Patil" not in client.get("/students/?status=inactive").data


def test_edit_student(client):
    s = make_student(client)
    data = admission_data(full_name="Rohan P. Patil", class_name="Class 9")
    data.pop("session_id")
    r = client.post(f"/students/{s.id}/edit", data=data)
    assert r.status_code == 302
    db.session.refresh(s)
    assert s.full_name == "Rohan P. Patil" and s.class_name == "Class 9"
    assert s.student_code == "STU000001"


def test_transfer_keeps_student_id_and_history(client):
    other_branch = add_branch("CITY1")
    s = make_student(client)
    code = s.student_code
    make_user("branch_admin", "bob")
    # branch admin may not transfer
    bob = client.application.test_client()
    login(bob, "bob")
    assert bob.post(f"/students/{s.id}/transfer", data={"to_branch_id": other_branch.id}).status_code == 403

    r = client.post(f"/students/{s.id}/transfer", data={"to_branch_id": other_branch.id, "reason": "Moved house"})
    assert r.status_code == 302
    db.session.refresh(s)
    assert s.branch_id == other_branch.id and s.student_code == code
    t = StudentTransfer.query.one()
    assert t.reason == "Moved house" and t.from_branch.code == "MAIN" and t.to_branch.code == "CITY1"
    # the old branch admin loses access, the new branch admin gains it
    assert bob.get(f"/students/{s.id}").status_code == 403
    make_user("branch_admin", "cara", branch_code="CITY1")
    cara = client.application.test_client()
    login(cara, "cara")
    assert cara.get(f"/students/{s.id}").status_code == 200
    # same branch / unknown branch refused
    client.post(f"/students/{s.id}/transfer", data={"to_branch_id": other_branch.id})
    assert StudentTransfer.query.count() == 1


def test_student_login_lifecycle(client):
    s = make_student(client)
    client.post(f"/students/{s.id}/create-login")
    temp = temp_password_from(client)
    db.session.refresh(s)
    assert s.user and s.user.role.name == "student" and s.user.branch_id == s.branch_id
    assert s.user.username == "stu000001"

    stu = client.application.test_client()
    r = login(stu, "stu000001", temp)
    assert r.status_code == 302 and "change-password" in r.location
    # second create is refused
    client.post(f"/students/{s.id}/create-login")
    assert User.query.filter_by(username="stu000001").count() == 1

    # inactive students cannot sign in
    client.post(f"/students/{s.id}/status", data={"status": "inactive"})
    other = client.application.test_client()
    assert login(other, "stu000001", temp).status_code == 200
    client.post(f"/students/{s.id}/status", data={"status": "active"})
    assert login(client.application.test_client(), "stu000001", temp).status_code == 302


def test_student_cannot_open_staff_pages(client):
    s = make_student(client)
    client.post(f"/students/{s.id}/create-login")
    temp = temp_password_from(client)
    stu = client.application.test_client()
    login(stu, "stu000001", temp)
    stu.post("/auth/change-password", data={"current_password": temp, "new_password": "NewPass123",
                                            "confirm_password": "NewPass123"})
    assert stu.get("/students/").status_code == 403
    assert stu.get("/admissions/").status_code == 403
    assert stu.get("/student/dashboard").status_code == 200
