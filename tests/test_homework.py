import io
import os
from datetime import timedelta
from extensions import db
from app.models import Homework, HomeworkCheck, StudyMaterial, BatchStudent, Parent, StudentParent
from app.services import homework_service as svc
from conftest import make_user, login, add_branch, flashes
from test_batches import mk_teacher, mk_student, mk_batch, main_branch, admin


# ------------------------------------------------------------------ helpers
def enroll_direct(batch, student, status="active"):
    db.session.add(BatchStudent(batch_id=batch.id, student_id=student.id, status=status,
                                enrolled_on=svc.today(), fee_amount=0))
    db.session.commit()


def pdf(name="sheet.pdf", body=b"%PDF-1.4 test"):
    return (io.BytesIO(body), name)


def give(client, batch, title="Chapter 1 questions", due_in=3, **extra):
    data = {"batch_id": batch.id, "title": title, "description": "Do all of them",
            "due_date": (svc.today() + timedelta(days=due_in)).isoformat()}
    data.update(extra)
    return client.post("/homework/new", data=data, content_type="multipart/form-data")


def last_hw():
    return Homework.query.order_by(Homework.id.desc()).first()


def user_client(client, role, username, **link):
    """A second logged-in client; `link` attaches the new user to a profile (teacher=, student=)."""
    u = make_user(role, username)
    if "teacher" in link:
        link["teacher"].user_id = u.id
    if "student" in link:
        link["student"].user_id = u.id
    db.session.commit()
    c = client.application.test_client()
    login(c, username)
    return c


def parent_client(client, username, child):
    u = make_user("parent", username)
    p = Parent(parent_code=f"PAR{u.id:06d}", user_id=u.id, full_name="Pat Parent", phone="9876543210",
               phone_key="9876543210")
    db.session.add(p)
    db.session.flush()
    db.session.add(StudentParent(student_id=child.id, parent_id=p.id, relation="Father"))
    db.session.commit()
    c = client.application.test_client()
    login(c, username)
    return c


def world():
    main = main_branch()
    teacher = mk_teacher(main)
    batch = mk_batch(main, teacher, subject="Physics")
    s1, s2 = mk_student(main, "Asha"), mk_student(main, "Bilal")
    enroll_direct(batch, s1)
    enroll_direct(batch, s2)
    return main, teacher, batch, s1, s2


# ------------------------------------------------------------------ giving homework
def test_admin_gives_homework_with_rules(client):
    _, _, batch, _, _ = world()
    admin(client)
    give(client, batch)
    hw = last_hw()
    assert hw.title == "Chapter 1 questions" and hw.batch_id == batch.id and hw.assigned_on == svc.today()
    assert hw.due_date == svc.today() + timedelta(days=3)
    give(client, batch, title="Late one", due_in=-1)                 # date in the past
    give(client, batch, title="   ")                                  # no title
    assert Homework.query.count() == 1
    assert any("past" in m or "required" in m for m in flashes(client))


def test_teacher_posts_only_to_own_batches(client):
    main, mine, batch, s1, _ = world()
    other = mk_teacher(main, "Other Teacher")
    other_batch = mk_batch(main, other, subject="Chemistry")
    tc = user_client(client, "teacher", "tina", teacher=mine)
    give(tc, batch)
    assert Homework.query.count() == 1
    give(tc, other_batch, title="Sneaky")                             # not in her batch list -> refused
    assert Homework.query.count() == 1
    admin(client)
    give(client, other_batch, title="Admin gives")
    theirs = last_hw()
    assert tc.get(f"/homework/{theirs.id}").status_code == 403
    assert tc.post(f"/homework/{theirs.id}/delete").status_code == 403
    assert Homework.query.count() == 2
    assert b"Admin gives" not in tc.get("/homework/").data


def test_accountant_has_no_access(client):
    make_user("accountant", "ann")
    login(client, "ann")
    assert client.get("/homework/").status_code == 403
    assert client.get("/materials/").status_code == 403


def test_branch_isolation(client):
    main, _, batch, _, _ = world()
    city = add_branch("CITY1", "City Branch")
    ct = mk_teacher(city, "City Teacher")
    cbatch = mk_batch(city, ct, course="JEE", subject="Chemistry", name="JEE City Chem")
    owner = make_user("owner", "boss")
    hw = svc.create_homework(owner, cbatch, "City work", None, svc.today() + timedelta(days=2))
    admin(client)                                                      # main branch admin
    assert client.get(f"/homework/{hw.id}").status_code == 403
    assert client.get(f"/homework/{hw.id}/file").status_code == 403
    assert b"City work" not in client.get("/homework/").data


# ------------------------------------------------------------------ attachments
def test_attachment_validation_and_download_rules(client):
    main, teacher, batch, s1, s2 = world()
    outsider = mk_student(main, "Outsider")                            # not in this batch
    admin(client)
    give(client, batch, title="Bad pdf", attachment=pdf("fake.pdf", b"not really a pdf"))
    give(client, batch, title="Bad type", attachment=(io.BytesIO(b"MZ binary"), "run.exe"))
    give(client, batch, title="Empty", attachment=pdf("empty.pdf", b""))
    assert Homework.query.count() == 0
    give(client, batch, title="With file", attachment=pdf("worksheet.pdf"))
    hw = last_hw()
    assert hw.attachment and hw.attachment_name == "worksheet.pdf"
    path = os.path.join(client.application.config["UPLOAD_FOLDER"], "homework", hw.attachment)
    assert os.path.exists(path)

    assert client.get(f"/homework/{hw.id}/file").status_code == 200
    sc = user_client(client, "student", "asha", student=s1)
    assert sc.get(f"/homework/{hw.id}/file").status_code == 200
    oc = user_client(client, "student", "outsider", student=outsider)
    assert oc.get(f"/homework/{hw.id}/file").status_code == 403
    pc = parent_client(client, "pat", s1)
    assert pc.get(f"/homework/{hw.id}/file").status_code == 200       # parent of an enrolled child
    other_parent = parent_client(client, "pam", outsider)
    assert other_parent.get(f"/homework/{hw.id}/file").status_code == 403


def test_edit_replaces_file_and_delete_removes_it(client):
    _, _, batch, _, _ = world()
    admin(client)
    give(client, batch, attachment=pdf("one.pdf"))
    hw = last_hw()
    folder = os.path.join(client.application.config["UPLOAD_FOLDER"], "homework")
    first = hw.attachment
    client.post(f"/homework/{hw.id}/edit", data={"title": "Renamed", "description": "", "due_date": hw.due_date.isoformat(),
                                                  "attachment": pdf("two.pdf")}, content_type="multipart/form-data")
    db.session.refresh(hw)
    assert hw.title == "Renamed" and hw.attachment != first and hw.attachment_name == "two.pdf"
    assert not os.path.exists(os.path.join(folder, first)) and os.path.exists(os.path.join(folder, hw.attachment))
    kept = hw.attachment
    client.post(f"/homework/{hw.id}/delete")
    assert Homework.query.count() == 0 and not os.path.exists(os.path.join(folder, kept))


# ------------------------------------------------------------------ checking sheet
def test_checking_sheet_saves_clears_and_rejects_bad_status(client):
    _, teacher, batch, s1, s2 = world()
    tc = user_client(client, "teacher", "tina", teacher=teacher)
    give(tc, batch)
    hw = last_hw()
    tc.post(f"/homework/{hw.id}/check", data={f"s_{s1.id}": "done", f"s_{s2.id}": "not_done", f"r_{s2.id}": "Copy missing"})
    got = {c.student_id: c for c in HomeworkCheck.query.all()}
    assert got[s1.id].status == "done" and got[s2.id].status == "not_done" and got[s2.id].remark == "Copy missing"
    tc.post(f"/homework/{hw.id}/check", data={f"s_{s1.id}": "excellent", f"s_{s2.id}": "done"})   # invalid -> nothing changes
    assert HomeworkCheck.query.filter_by(student_id=s2.id).one().status == "not_done"
    assert any("Choose Done" in m for m in flashes(tc))
    tc.post(f"/homework/{hw.id}/check", data={f"s_{s1.id}": "", f"s_{s2.id}": "partial"})         # blank clears
    assert HomeworkCheck.query.filter_by(student_id=s1.id).count() == 0
    assert HomeworkCheck.query.filter_by(student_id=s2.id).one().status == "partial"
    assert svc.progress([hw])[hw.id] == {"total": 2, "checked": 1, "done": 0}


def test_students_in_other_batches_cannot_be_checked(client):
    main, teacher, batch, s1, _ = world()
    stranger = mk_student(main, "Stranger")
    admin(client)
    give(client, batch)
    hw = last_hw()
    client.post(f"/homework/{hw.id}/check", data={f"s_{s1.id}": "done", f"s_{stranger.id}": "done"})
    assert [c.student_id for c in HomeworkCheck.query.all()] == [s1.id]


# ------------------------------------------------------------------ student and parent views
def test_student_sees_own_batch_homework_status_and_past_filter(client):
    main, teacher, batch, s1, s2 = world()
    other = mk_batch(main, mk_teacher(main, "Other Teacher"), subject="Chemistry")
    admin(client)
    give(client, batch, title="Physics work")
    give(client, other, title="Chemistry work")
    old = Homework.query.filter_by(title="Physics work").one()
    give(client, batch, title="Old physics")
    older = last_hw()
    older.assigned_on = svc.today() - timedelta(days=9)
    older.due_date = svc.today() - timedelta(days=2)
    db.session.commit()
    client.post(f"/homework/{old.id}/check", data={f"s_{s1.id}": "done"})

    sc = user_client(client, "student", "asha", student=s1)
    page = sc.get("/student/homework").data
    assert b"Physics work" in page and b"Chemistry work" not in page and b"Old physics" not in page
    assert b"Done" in page
    assert b"Old physics" in sc.get("/student/homework?when=past").data
    assert sc.get(f"/student/homework/{old.id}").status_code == 200
    chem = Homework.query.filter_by(title="Chemistry work").one()
    assert sc.get(f"/student/homework/{chem.id}").status_code == 404
    assert sc.get("/homework/").status_code == 403                    # no staff screen


def test_student_who_left_the_batch_stops_seeing_homework(client):
    _, _, batch, s1, _ = world()
    admin(client)
    give(client, batch, title="Physics work")
    sc = user_client(client, "student", "asha", student=s1)
    assert b"Physics work" in sc.get("/student/homework").data
    BatchStudent.query.filter_by(student_id=s1.id).one().status = "left"
    db.session.commit()
    assert b"Physics work" not in sc.get("/student/homework").data
    hw = last_hw()
    assert sc.get(f"/student/homework/{hw.id}").status_code == 404


def test_parent_sees_only_own_childs_homework(client):
    _, _, batch, s1, s2 = world()
    admin(client)
    give(client, batch, title="Physics work")
    hw = last_hw()
    client.post(f"/homework/{hw.id}/check", data={f"s_{s1.id}": "partial", f"r_{s1.id}": "Half done"})
    pc = parent_client(client, "pat", s1)
    assert b"Physics work" in pc.get(f"/parent/child/{s1.id}/homework").data
    detail = pc.get(f"/parent/child/{s1.id}/homework/{hw.id}")
    assert detail.status_code == 200 and b"Half done" in detail.data
    assert pc.get(f"/parent/child/{s2.id}/homework").status_code == 404    # not their child
    assert pc.get(f"/parent/child/{s2.id}/homework/{hw.id}").status_code == 404
    assert pc.get("/homework/").status_code == 403


# ------------------------------------------------------------------ study materials
def test_teacher_shares_file_and_link_and_student_downloads(client):
    main, teacher, batch, s1, s2 = world()
    outsider = mk_student(main, "Outsider")
    tc = user_client(client, "teacher", "tina", teacher=teacher)
    tc.post("/materials/new", data={"batch_id": batch.id, "kind": "file", "title": "Notes", "file": pdf("notes.pdf")},
            content_type="multipart/form-data")
    tc.post("/materials/new", data={"batch_id": batch.id, "kind": "link", "title": "Video",
                                    "url": "https://example.com/watch?v=1"})
    assert StudyMaterial.query.count() == 2
    f = StudyMaterial.query.filter_by(kind="file").one()
    assert f.original_name == "notes.pdf" and f.size == len(b"%PDF-1.4 test")

    sc = user_client(client, "student", "asha", student=s1)
    page = sc.get("/student/materials").data
    assert b"Notes" in page and b"Video" in page and b"https://example.com/watch?v=1" in page
    assert sc.get(f"/materials/{f.id}/file").status_code == 200
    oc = user_client(client, "student", "outsider", student=outsider)
    assert oc.get(f"/materials/{f.id}/file").status_code == 403
    assert b"Notes" not in oc.get("/student/materials").data
    pc = parent_client(client, "pat", s1)
    assert pc.get(f"/materials/{f.id}/file").status_code == 403       # parents do not get materials


def test_material_rules(client):
    _, _, batch, _, _ = world()
    admin(client)
    base = {"batch_id": batch.id, "title": "Bad"}
    client.post("/materials/new", data={**base, "kind": "link", "url": "javascript:alert(1)"})
    client.post("/materials/new", data={**base, "kind": "link", "url": "ftp://example.com/x"})
    client.post("/materials/new", data={**base, "kind": "link", "url": "https://exa mple.com"})
    client.post("/materials/new", data={**base, "kind": "file"}, content_type="multipart/form-data")     # no file
    client.post("/materials/new", data={**base, "kind": "file", "file": (io.BytesIO(b"<script>"), "x.html")},
                content_type="multipart/form-data")
    assert StudyMaterial.query.count() == 0


def test_teacher_cannot_touch_other_teachers_material_and_delete_removes_file(client):
    main, mine, batch, _, _ = world()
    other = mk_teacher(main, "Other Teacher")
    other_batch = mk_batch(main, other, subject="Chemistry")
    admin(client)
    client.post("/materials/new", data={"batch_id": other_batch.id, "kind": "file", "title": "Theirs",
                                        "file": pdf("theirs.pdf")}, content_type="multipart/form-data")
    m = StudyMaterial.query.one()
    tc = user_client(client, "teacher", "tina", teacher=mine)
    assert tc.post(f"/materials/{m.id}/delete").status_code == 403
    assert tc.get(f"/materials/{m.id}/edit").status_code == 403
    assert tc.get(f"/materials/{m.id}/file").status_code == 403
    path = os.path.join(client.application.config["UPLOAD_FOLDER"], "materials", m.filename)
    assert os.path.exists(path)
    client.post(f"/materials/{m.id}/delete")
    assert StudyMaterial.query.count() == 0 and not os.path.exists(path)


def test_attachment_content_checks(client):
    """Office files must be real zip / OLE containers, text must be UTF-8 without binary bytes."""
    from werkzeug.datastructures import FileStorage
    from app.utils.file_upload import save_attachment
    ok = [("a.docx", b"PK\x03\x04rest"), ("a.xlsx", b"PK\x03\x04rest"), ("a.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1x"),
          ("a.txt", "namaste \u0928\u092e\u0938\u094d\u0924\u0947".encode()), ("a.pdf", b"%PDF-1.7 x")]
    for name, body in ok:
        stored, original, size = save_attachment(FileStorage(io.BytesIO(body), name), "materials")
        assert original == name and size == len(body)
    for name, body in [("a.docx", b"plain text"), ("a.doc", b"PK\x03\x04"), ("a.txt", b"\x00\x01"),
                       ("a.png", b"not an image"), ("a.exe", b"MZ"), ("noext", b"x")]:
        try:
            save_attachment(FileStorage(io.BytesIO(body), name), "materials")
            raise AssertionError(f"{name} should have been refused")
        except ValueError:
            pass
