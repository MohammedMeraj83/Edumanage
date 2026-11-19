import io
import os
from datetime import timedelta
from decimal import Decimal
from extensions import db
from app.models import (IdCard, Certificate, InstituteDocument, FeeDue, Staff, StudentDocument, Parent, StudentParent,
                        AcademicSession)
from app.services import idcard_service, certificate_service, library_service
from conftest import make_user, login, add_branch, flashes
from test_batches import mk_teacher, mk_student, main_branch, admin
from test_homework import user_client, parent_client


# ------------------------------------------------------------------ helpers
def pdf_file(name="notice.pdf", body=b"%PDF-1.4 test"):
    return (io.BytesIO(body), name)


def issue(client, kind, person, **extra):
    return client.post(f"/id-cards/issue/{kind}/{person.id}", data=extra)


def mk_staff_member(branch, name="Ravi Staff"):
    n = Staff.query.count() + 1
    s = Staff(employee_code=f"STF{n:06d}", branch_id=branch.id, full_name=name, gender="Male", phone=f"91000{n:05d}",
              joining_date=idcard_service.today(), designation="Accountant", status="active")
    db.session.add(s)
    db.session.commit()
    return s


def new_cert(client, student, cert_type="bonafide", **fields):
    data = {"cert_type": cert_type, "issue_date": certificate_service.today().isoformat()}
    data.update({f"f_{k}": v for k, v in fields.items()})
    return client.post(f"/certificates/issue/{student.id}", data=data)


def last_cert():
    return Certificate.query.order_by(Certificate.id.desc()).first()


def anon(client):
    return client.application.test_client()


# ------------------------------------------------------------------ ID cards
def test_issue_card_once_and_print_pdf(client):
    main = main_branch()
    s1, s2 = mk_student(main, "Asha"), mk_student(main, "Bilal")
    admin(client)
    issue(client, "student", s1)
    issue(client, "student", s1)                                       # second click: still one card
    cards = IdCard.query.filter_by(person_id=s1.id).all()
    assert len(cards) == 1 and cards[0].status == "active" and cards[0].card_no == f"{s1.student_code}-01"
    session = AcademicSession.query.filter_by(is_current=True).first()
    assert cards[0].valid_until == session.end_date or cards[0].valid_until >= idcard_service.today()
    pdf = client.get(f"/id-cards/card/{cards[0].id}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert b"Asha" in client.get("/id-cards/?kind=student").data

    sheet = client.post("/id-cards/bulk", data={"kind": "student", "ids": [s1.id, s2.id]})
    assert sheet.status_code == 200 and sheet.data.startswith(b"%PDF")
    assert IdCard.query.filter_by(person_id=s2.id, status="active").count() == 1     # bulk issued the missing card
    assert IdCard.query.filter_by(person_id=s1.id).count() == 1                      # and reused the existing one


def test_replacing_a_lost_card_stops_the_old_one_verifying(client):
    main = main_branch()
    s1 = mk_student(main, "Asha")
    admin(client)
    issue(client, "student", s1)
    old = IdCard.query.one()
    issue(client, "student", s1, replace="1", old_status="lost")
    db.session.refresh(old)
    new = IdCard.query.filter_by(status="active").one()
    assert old.status == "lost" and new.card_no == f"{s1.student_code}-02" and new.id != old.id
    assert client.get(f"/id-cards/card/{old.id}.pdf").status_code == 302          # closed cards cannot be printed
    pub = anon(client)
    assert b"no longer valid" in pub.get(f"/verify/id/{old.token}").data
    assert b"genuine" in pub.get(f"/verify/id/{new.token}").data
    client.post(f"/id-cards/card/{new.id}/close", data={"status": "cancelled"})
    db.session.refresh(new)
    assert new.status == "cancelled" and b"no longer valid" in pub.get(f"/verify/id/{new.token}").data


def test_only_active_people_get_cards(client):
    main = main_branch()
    gone = mk_student(main, "Gone")
    gone.status = "left"
    db.session.commit()
    admin(client)
    issue(client, "student", gone)
    assert IdCard.query.count() == 0 and any("Only active" in m for m in flashes(client))
    client.post("/id-cards/bulk", data={"kind": "student", "ids": [gone.id]})
    assert IdCard.query.count() == 0


def test_teacher_and_staff_cards(client):
    main = main_branch()
    t, st = mk_teacher(main), mk_staff_member(main)
    admin(client)
    issue(client, "teacher", t)
    issue(client, "staff", st)
    assert IdCard.query.filter_by(person_kind="teacher", person_id=t.id).one().card_no == f"{t.employee_code}-01"
    assert IdCard.query.filter_by(person_kind="staff", person_id=st.id).one().card_no == f"{st.employee_code}-01"
    for kind in ("teacher", "staff"):
        assert client.get(f"/id-cards/?kind={kind}").status_code == 200
    out = client.post("/id-cards/bulk", data={"kind": "teacher", "ids": [t.id]})
    assert out.status_code == 200 and out.data.startswith(b"%PDF")


def test_idcard_branch_isolation_and_roles(client):
    main = main_branch()
    city = add_branch("CITY1", "City Branch")
    other = mk_student(city, "City Student")
    admin(client)                                                       # main branch admin
    assert issue(client, "student", other).status_code == 403
    assert client.post("/id-cards/bulk", data={"kind": "student", "ids": [other.id]}).status_code == 302
    assert IdCard.query.count() == 0
    make_user("accountant", "ann")
    ac = anon(client)
    login(ac, "ann")
    for url in ("/id-cards/", "/certificates/", "/documents/"):
        assert ac.get(url).status_code == 403
    tc = user_client(client, "teacher", "tina", teacher=mk_teacher(main))
    assert tc.get("/id-cards/").status_code == 403 and tc.get("/certificates/").status_code == 403
    assert tc.get("/documents/").status_code == 200                      # teachers can read the library


def test_public_verify_shows_little_and_handles_unknown_and_expired(client):
    main = main_branch()
    s1 = mk_student(main, "Asha")
    admin(client)
    issue(client, "student", s1)
    card = IdCard.query.one()
    pub = anon(client)
    page = pub.get(f"/verify/id/{card.token}")
    assert page.status_code == 200 and b"Asha" in page.data and s1.student_code.encode() in page.data
    assert s1.guardian_phone.encode() not in page.data                   # no phone on the public page
    unknown = pub.get("/verify/id/doesnotexist")
    assert unknown.status_code == 404 and b"Not found" in unknown.data
    card.valid_until = idcard_service.today() - timedelta(days=1)
    db.session.commit()
    assert b"expired" in pub.get(f"/verify/id/{card.token}").data


# ------------------------------------------------------------------ certificates
def test_issue_certificates_numbers_text_and_pdf(client):
    main = main_branch()
    s1 = mk_student(main, "Asha", gender="Female")
    admin(client)
    new_cert(client, s1, "bonafide", purpose="a bank account")
    c1 = last_cert()
    assert c1.certificate_no.startswith("CRT-MAIN-") and c1.certificate_no.endswith("-0001") and c1.status == "issued"
    new_cert(client, s1, "character", conduct="excellent")
    c2 = last_cert()
    assert c2.certificate_no.endswith("-0002")
    title, paras = certificate_service.certificate_text(c1)
    assert title == "BONAFIDE CERTIFICATE" and "Asha" in paras[0] and "bank account" in paras[1]
    assert "her conduct" in certificate_service.certificate_text(c2)[1][1]       # pronoun follows gender
    assert b"BONAFIDE" in client.get(f"/certificates/{c1.id}").data
    pdf = client.get(f"/certificates/{c1.id}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert b"Asha" in client.get("/certificates/?q=asha").data
    assert client.get("/certificates/new?q=ash").status_code == 200


def test_certificate_field_rules(client):
    main = main_branch()
    s1 = mk_student(main, "Asha")
    admin(client)
    new_cert(client, s1, "completion", period_from="2026-01-01", period_to="2026-03-01")                 # no course
    new_cert(client, s1, "completion", course="JEE", period_from="2026-03-01", period_to="2026-01-01")   # ends before start
    new_cert(client, s1, "achievement")                                                                    # no title
    client.post(f"/certificates/issue/{s1.id}", data={"cert_type": "bonafide",
                                                       "issue_date": (certificate_service.today() + timedelta(days=2)).isoformat()})
    assert Certificate.query.count() == 0
    new_cert(client, s1, "completion", course="JEE", period_from="2024-06-01", period_to="2026-03-01", result="First class")
    new_cert(client, s1, "achievement", title="First rank", details="Scored 96 percent")
    assert Certificate.query.count() == 2
    assert b"First class" in client.get(f"/certificates/{Certificate.query.filter_by(cert_type='completion').one().id}").data


def test_transfer_certificate_is_blocked_by_pending_fees_unless_allowed(client):
    main = main_branch()
    s1 = mk_student(main, "Asha")
    admin(client)
    db.session.add(FeeDue(branch_id=main.id, student_id=s1.id, session_id=s1.session_id, kind="custom", period_key="x1",
                          label="Test fee", due_date=certificate_service.today(), amount=Decimal("1500"),
                          discount=Decimal("0"), paid=Decimal("0"), status="pending"))
    db.session.commit()
    left = certificate_service.today().isoformat()
    new_cert(client, s1, "transfer", leaving_date=left, conduct="good")
    assert Certificate.query.count() == 0 and any("pending" in m for m in flashes(client))
    client.post(f"/certificates/issue/{s1.id}", data={"cert_type": "transfer", "issue_date": left, "f_leaving_date": left,
                                                       "f_conduct": "good", "allow_dues": "1"})
    cert = last_cert()
    assert cert.fields["dues_cleared"] is False
    assert "not fully cleared" in certificate_service.certificate_text(cert)[1][-1]


def test_cancel_certificate_keeps_number_and_shows_cancelled(client):
    main = main_branch()
    s1 = mk_student(main, "Asha")
    admin(client)
    new_cert(client, s1, "bonafide")
    cert = last_cert()
    pub = anon(client)
    assert b"genuine" in pub.get(f"/verify/certificate/{cert.token}").data
    client.post(f"/certificates/{cert.id}/cancel", data={"reason": ""})              # reason is required
    db.session.refresh(cert)
    assert cert.status == "issued"
    client.post(f"/certificates/{cert.id}/cancel", data={"reason": "Wrong date of birth"})
    db.session.refresh(cert)
    assert cert.status == "cancelled" and cert.cancel_reason == "Wrong date of birth"
    assert b"no longer valid" in pub.get(f"/verify/certificate/{cert.token}").data
    assert client.get(f"/certificates/{cert.id}.pdf").data.startswith(b"%PDF")      # still printable, stamped CANCELLED
    new_cert(client, s1, "bonafide")
    assert last_cert().certificate_no.endswith("-0002")                              # the cancelled number is not reused


def test_certificate_branch_isolation(client):
    main = main_branch()
    city = add_branch("CITY1", "City Branch")
    other = mk_student(city, "City Student")
    owner = make_user("owner", "boss")
    cert = certificate_service.issue_certificate(owner, other, "bonafide", certificate_service.today(), {})
    admin(client)
    assert client.get(f"/certificates/{cert.id}").status_code == 403
    assert client.get(f"/certificates/{cert.id}.pdf").status_code == 403
    assert client.post(f"/certificates/{cert.id}/cancel", data={"reason": "test test"}).status_code == 403
    assert client.get(f"/certificates/issue/{other.id}").status_code == 403
    assert b"City Student" not in client.get("/certificates/").data


# ------------------------------------------------------------------ student and parent portals
def test_student_and_parent_see_only_their_own_documents(client):
    main = main_branch()
    s1, s2 = mk_student(main, "Asha"), mk_student(main, "Bilal")
    admin(client)
    issue(client, "student", s1)
    new_cert(client, s1, "bonafide")
    mine = last_cert()
    new_cert(client, s2, "bonafide")
    theirs = last_cert()
    new_cert(client, s1, "character", conduct="good")
    gone = last_cert()
    client.post(f"/certificates/{gone.id}/cancel", data={"reason": "Typing mistake"})

    sc = user_client(client, "student", "asha", student=s1)
    page = sc.get("/student/documents").data
    assert mine.certificate_no.encode() in page and theirs.certificate_no.encode() not in page
    assert gone.certificate_no.encode() not in page                                   # cancelled ones are hidden
    assert sc.get(f"/student/documents/certificate/{mine.id}.pdf").data.startswith(b"%PDF")
    assert sc.get(f"/student/documents/certificate/{theirs.id}.pdf").status_code == 404
    assert sc.get(f"/student/documents/certificate/{gone.id}.pdf").status_code == 404
    assert sc.get("/student/documents/id-card.pdf").data.startswith(b"%PDF")
    assert sc.get("/certificates/").status_code == 403

    bc = user_client(client, "student", "bilal", student=s2)
    assert bc.get("/student/documents/id-card.pdf").status_code == 404                # Bilal has no card

    pc = parent_client(client, "pat", s1)
    assert mine.certificate_no.encode() in pc.get(f"/parent/child/{s1.id}/documents").data
    assert pc.get(f"/parent/child/{s1.id}/documents/certificate/{mine.id}.pdf").data.startswith(b"%PDF")
    assert pc.get(f"/parent/child/{s1.id}/documents/id-card.pdf").data.startswith(b"%PDF")
    assert pc.get(f"/parent/child/{s2.id}/documents").status_code == 404              # not their child
    assert pc.get(f"/parent/child/{s1.id}/documents/certificate/{theirs.id}.pdf").status_code == 404


# ------------------------------------------------------------------ document library
def add_doc(c, title="Fee structure", audience="all", **extra):
    data = {"title": title, "category": "circular", "audience": audience, "description": "", "file": pdf_file()}
    data.update(extra)
    if data.get("file") is None:
        data.pop("file", None)
    return c.post("/documents/new", data=data, content_type="multipart/form-data")


def test_library_audience_rules(client):
    main = main_branch()
    teacher = mk_teacher(main)
    s1 = mk_student(main, "Asha")
    admin(client)
    add_doc(client, "For everyone", "all")
    add_doc(client, "Staff room rota", "teachers")
    add_doc(client, "Student rules", "students")
    docs = {d.title: d for d in InstituteDocument.query.all()}
    assert len(docs) == 3 and all(d.branch_id == main.id for d in docs.values())      # branch admin posts for own branch
    folder = os.path.join(client.application.config["UPLOAD_FOLDER"], "library")
    assert all(os.path.exists(os.path.join(folder, d.filename)) for d in docs.values())

    sc = user_client(client, "student", "asha", student=s1)
    page = sc.get("/student/documents").data
    assert b"For everyone" in page and b"Student rules" in page and b"Staff room rota" not in page
    assert sc.get(f"/documents/{docs['For everyone'].id}/file").status_code == 200
    assert sc.get(f"/documents/{docs['Student rules'].id}/file").status_code == 200
    assert sc.get(f"/documents/{docs['Staff room rota'].id}/file").status_code == 403

    tc = user_client(client, "teacher", "tina", teacher=teacher)
    tpage = tc.get("/documents/").data
    assert b"For everyone" in tpage and b"Staff room rota" in tpage and b"Student rules" not in tpage
    assert tc.get(f"/documents/{docs['Staff room rota'].id}/file").status_code == 200
    assert tc.get(f"/documents/{docs['Student rules'].id}/file").status_code == 403
    assert tc.get("/documents/new").status_code == 403                                 # teachers cannot add

    pc = parent_client(client, "pat", s1)
    assert pc.get(f"/documents/{docs['Student rules'].id}/file").status_code == 200
    assert pc.get(f"/documents/{docs['Staff room rota'].id}/file").status_code == 403
    assert anon(client).get(f"/documents/{docs['For everyone'].id}/file").status_code == 302   # must sign in


def test_library_branch_scope_owner_all_branches_and_delete(client):
    main = main_branch()
    city = add_branch("CITY1", "City Branch")
    city_student = mk_student(city, "City Student")
    make_user("owner", "boss")
    oc = anon(client)
    login(oc, "boss")
    add_doc(oc, "Everywhere", "all", branch_id="")
    add_doc(oc, "City only", "all", branch_id=str(city.id))
    docs = {d.title: d for d in InstituteDocument.query.all()}
    assert docs["Everywhere"].branch_id is None and docs["City only"].branch_id == city.id
    add_doc(oc, "Bad branch", "all", branch_id="9999")
    assert InstituteDocument.query.count() == 2

    admin(client)                                                                      # main branch admin
    page = client.get("/documents/").data
    assert b"Everywhere" in page and b"City only" not in page
    assert client.get(f"/documents/{docs['City only'].id}/file").status_code == 403
    assert client.post(f"/documents/{docs['City only'].id}/delete").status_code == 403
    assert client.post(f"/documents/{docs['Everywhere'].id}/delete").status_code == 403   # all-branch docs: owner only

    cs = user_client(client, "student", "cityk", student=city_student)
    assert b"City only" in cs.get("/student/documents").data

    path = os.path.join(client.application.config["UPLOAD_FOLDER"], "library", docs["City only"].filename)
    assert os.path.exists(path)
    oc.post(f"/documents/{docs['City only'].id}/delete")
    assert InstituteDocument.query.count() == 1 and not os.path.exists(path)


def test_library_rejects_bad_files_and_titles(client):
    main_branch()
    admin(client)
    add_doc(client, "Fake pdf", file=pdf_file("x.pdf", b"not a pdf"))
    add_doc(client, "Script", file=(io.BytesIO(b"<script>"), "x.html"))
    add_doc(client, "   ")
    add_doc(client, "No file", file=None)
    add_doc(client, "Bad audience", audience="nobody")
    assert InstituteDocument.query.count() == 0


def test_document_center_lists_uploaded_papers(client):
    main = main_branch()
    s1 = mk_student(main, "Asha")
    city = add_branch("CITY1", "City Branch")
    other = mk_student(city, "City Student")
    db.session.add_all([StudentDocument(student_id=s1.id, doc_type="id_proof", filename="a.pdf", original_name="aadhaar.pdf", size=2048),
                        StudentDocument(student_id=other.id, doc_type="id_proof", filename="b.pdf", original_name="other.pdf", size=1024)])
    db.session.commit()
    admin(client)
    page = client.get("/documents/papers").data
    assert b"aadhaar.pdf" in page and b"other.pdf" not in page                         # only own branch
    assert b"aadhaar.pdf" in client.get("/documents/papers?q=asha&kind=student").data
    assert b"aadhaar.pdf" not in client.get("/documents/papers?kind=teacher").data
    tc = user_client(client, "teacher", "tina", teacher=mk_teacher(main))
    assert tc.get("/documents/papers").status_code == 403
