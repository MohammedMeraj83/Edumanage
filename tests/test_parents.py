from extensions import db
from app.models import Parent, StudentParent, Student, Branch
from conftest import make_user, login, add_branch, temp_password_from
from test_admissions import admission_data


def admit(client, **over):
    main = Branch.query.filter_by(is_main=True).first()
    client.post("/admissions/new", data=admission_data(branch_id=main.id, approve_now="y", **over))
    return Student.query.order_by(Student.id.desc()).first()


def owner(client):
    make_user("owner", "boss")
    login(client, "boss")
    return client


def test_parent_created_from_student_guardian_details(client):
    owner(client)
    s = admit(client, father_name="Suresh Patil")
    client.post(f"/parents/from-student/{s.id}", data={"relation": "Father"})
    p = Parent.query.one()
    assert p.full_name == "Suresh Patil" and p.parent_code == "PAR000001" and p.phone == "9876543210"
    link = StudentParent.query.one()
    assert link.student_id == s.id and link.relation == "Father"
    # pressing again does not duplicate
    client.post(f"/parents/from-student/{s.id}", data={"relation": "Father"})
    assert Parent.query.count() == 1 and StudentParent.query.count() == 1


def test_siblings_share_one_parent_even_with_different_phone_format(client):
    owner(client)
    s1 = admit(client, full_name="Rohan Patil", guardian_phone="9876543210")
    s2 = admit(client, full_name="Sneha Patil", guardian_phone="+91 98765 43210")
    client.post(f"/parents/from-student/{s1.id}", data={"relation": "Father"})
    client.post(f"/parents/from-student/{s2.id}", data={"relation": "Father"})
    assert Parent.query.count() == 1 and StudentParent.query.count() == 2


def test_parent_login_sees_only_own_children(client):
    owner(client)
    s1 = admit(client, full_name="Rohan Patil", guardian_phone="9876543210")
    admit(client, full_name="Other Kid", guardian_phone="9000000009")
    client.post(f"/parents/from-student/{s1.id}", data={"relation": "Father"})
    p = Parent.query.one()
    client.post(f"/parents/{p.id}/create-login")
    temp = temp_password_from(client)
    me = client.application.test_client()
    login(me, "par000001", temp)
    me.post("/auth/change-password", data={"current_password": temp, "new_password": "NewPass123",
                                           "confirm_password": "NewPass123"})
    page = me.get("/parent/dashboard")
    assert page.status_code == 200 and b"Rohan Patil" in page.data and b"Other Kid" not in page.data
    assert me.get("/students/").status_code == 403 and me.get("/parents/").status_code == 403


def test_link_and_unlink_child_by_student_code(client):
    owner(client)
    s1 = admit(client, full_name="Rohan Patil", guardian_phone="9876543210")
    s2 = admit(client, full_name="Other Kid", guardian_phone="9000000009")
    client.post(f"/parents/from-student/{s1.id}", data={"relation": "Father"})
    p = Parent.query.one()
    client.post(f"/parents/{p.id}/link", data={"student_code": s2.student_code.lower(), "relation": "Guardian"})
    assert StudentParent.query.count() == 2
    client.post(f"/parents/{p.id}/link", data={"student_code": "STU999999", "relation": "Guardian"})
    assert StudentParent.query.count() == 2
    client.post(f"/parents/{p.id}/unlink/{s2.id}")
    assert StudentParent.query.count() == 1


def test_branch_admin_only_sees_parents_of_own_branch(client):
    b2 = add_branch("CITY1")
    owner(client)
    s_main = admit(client, full_name="Main Kid", guardian_phone="9876543210")
    client.post("/admissions/new", data=admission_data(full_name="City Kid", guardian_phone="9555555555",
                                                       branch_id=b2.id, approve_now="y"))
    s_city = Student.query.filter_by(full_name="City Kid").one()
    client.post(f"/parents/from-student/{s_main.id}", data={"relation": "Father"})
    client.post(f"/parents/from-student/{s_city.id}", data={"relation": "Father"})
    make_user("branch_admin", "cara", branch_code="CITY1")
    cara = client.application.test_client()
    login(cara, "cara")
    html = cara.get("/parents/").data
    assert b"PAR000002" in html and b"PAR000001" not in html
    p_main = Parent.query.filter_by(parent_code="PAR000001").one()
    assert cara.get(f"/parents/{p_main.id}").status_code == 404
    assert cara.post(f"/parents/from-student/{s_main.id}", data={"relation": "Father"}).status_code == 403


def test_edit_parent_updates_phone_key(client):
    owner(client)
    s = admit(client)
    client.post(f"/parents/from-student/{s.id}", data={"relation": "Mother"})
    p = Parent.query.one()
    r = client.post(f"/parents/{p.id}/edit", data={"full_name": "Asha Patil", "phone": "9000011111",
                                                    "email": "", "occupation": "Teacher", "address": ""})
    assert r.status_code == 302
    db.session.refresh(p)
    assert p.full_name == "Asha Patil" and p.phone_key == "9000011111"
