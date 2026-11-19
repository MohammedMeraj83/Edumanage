import io
from PIL import Image
from extensions import db
from app.models import Admission, Student, AcademicSession, Branch
from app.utils.numbering import session_tag
from conftest import make_user, login, add_branch


def admission_data(**over):
    d = {"full_name": "Rohan Patil", "dob": "2012-05-10", "gender": "Male", "blood_group": "",
         "phone": "", "email": "", "class_name": "Class 8", "previous_school": "", "address": "",
         "city": "", "state": "", "pincode": "", "father_name": "Suresh Patil", "mother_name": "",
         "guardian_phone": "9876543210", "guardian_email": "", "notes": "",
         "session_id": AcademicSession.query.filter_by(is_current=True).first().id}
    d.update(over)
    return d


def test_branch_admin_creates_pending_admission(client):
    make_user("branch_admin", "bob")
    login(client, "bob")
    assert client.post("/admissions/new", data=admission_data()).status_code == 302
    a = Admission.query.one()
    assert a.status == "pending" and a.admission_no is None and a.branch.code == "MAIN"


def test_approve_creates_student_with_unique_numbers(client):
    make_user("branch_admin", "bob")
    login(client, "bob")
    client.post("/admissions/new", data=admission_data())
    client.post("/admissions/new", data=admission_data(full_name="Sneha Joshi"))
    first, second = Admission.query.order_by(Admission.id).all()
    client.post(f"/admissions/{first.id}/approve")
    client.post(f"/admissions/{second.id}/approve")
    s1, s2 = Student.query.order_by(Student.id).all()
    tag = session_tag(first.session)
    assert (s1.student_code, s2.student_code) == ("STU000001", "STU000002")
    assert (s1.admission_no, s2.admission_no) == (f"MAIN-{tag}-0001", f"MAIN-{tag}-0002")
    assert s1.status == "active" and s1.guardian_phone == "9876543210"
    # approving twice is refused, nothing new is created
    client.post(f"/admissions/{first.id}/approve")
    assert Student.query.count() == 2


def test_duplicate_application_blocked(client):
    make_user("branch_admin", "bob")
    login(client, "bob")
    client.post("/admissions/new", data=admission_data())
    r = client.post("/admissions/new", data=admission_data(full_name="rohan patil"))
    assert r.status_code == 200 and b"already exists" in r.data
    assert Admission.query.count() == 1


def test_validation_errors(client):
    make_user("branch_admin", "bob")
    login(client, "bob")
    r = client.post("/admissions/new", data=admission_data(dob="2999-01-01", guardian_phone="abc"))
    assert r.status_code == 200 and Admission.query.count() == 0


def test_reject_then_cannot_approve(client):
    make_user("branch_admin", "bob")
    login(client, "bob")
    client.post("/admissions/new", data=admission_data())
    a = Admission.query.one()
    client.post(f"/admissions/{a.id}/reject", data={"reason": "No seat"})
    db.session.refresh(a)
    assert a.status == "rejected" and a.rejection_reason == "No seat"
    client.post(f"/admissions/{a.id}/approve")
    assert Student.query.count() == 0


def test_owner_walk_in_approve_now(client):
    make_user("owner", "boss")
    login(client, "boss")
    main = Branch.query.filter_by(is_main=True).first()
    r = client.post("/admissions/new", data=admission_data(branch_id=main.id, approve_now="y"))
    assert r.status_code == 302 and "/students/" in r.location
    assert Student.query.count() == 1


def test_accountant_can_view_but_not_create(client):
    make_user("accountant", "ann")
    login(client, "ann")
    assert client.get("/admissions/").status_code == 200
    assert client.get("/students/").status_code == 200
    assert client.get("/admissions/new").status_code == 403


def test_other_branch_admin_cannot_open_application(client):
    add_branch("CITY1")
    make_user("branch_admin", "bob")
    make_user("branch_admin", "cara", branch_code="CITY1")
    login(client, "bob")
    client.post("/admissions/new", data=admission_data())
    a = Admission.query.one()
    other = client.application.test_client()
    login(other, "cara")
    assert other.get(f"/admissions/{a.id}").status_code == 403
    assert other.post(f"/admissions/{a.id}/approve").status_code == 403
    assert b"Rohan" not in other.get("/admissions/?status=all").data


def test_documents_follow_admission_to_student_and_are_private(client):
    add_branch("CITY1")
    make_user("branch_admin", "bob")
    make_user("branch_admin", "cara", branch_code="CITY1")
    login(client, "bob")
    client.post("/admissions/new", data=admission_data())
    a = Admission.query.one()
    pdf = (io.BytesIO(b"%PDF-1.4 test"), "birth.pdf")
    r = client.post(f"/admissions/{a.id}/documents", data={"doc_type": "birth_certificate", "file": pdf},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    fake = (io.BytesIO(b"not a pdf"), "bad.pdf")
    client.post(f"/admissions/{a.id}/documents", data={"doc_type": "other", "file": fake},
                content_type="multipart/form-data")
    from app.models import StudentDocument
    assert StudentDocument.query.count() == 1

    client.post(f"/admissions/{a.id}/approve")
    doc = StudentDocument.query.one()
    student = Student.query.one()
    assert doc.student_id == student.id
    assert client.get(f"/students/files/{doc.id}").status_code == 200
    other = client.application.test_client()
    login(other, "cara")
    assert other.get(f"/students/files/{doc.id}").status_code == 403
    client.post(f"/students/{student.id}/documents/{doc.id}/delete")
    assert StudentDocument.query.count() == 0


def test_photo_upload_and_privacy(client):
    add_branch("CITY1")
    make_user("branch_admin", "bob")
    make_user("branch_admin", "cara", branch_code="CITY1")
    login(client, "bob")
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), "red").save(buf, "PNG")
    buf.seek(0)
    client.post("/admissions/new", data={**admission_data(), "photo": (buf, "p.png")},
                content_type="multipart/form-data")
    a = Admission.query.one()
    assert a.photo and client.get(f"/admissions/{a.id}/photo").status_code == 200
    other = client.application.test_client()
    login(other, "cara")
    assert other.get(f"/admissions/{a.id}/photo").status_code == 403
