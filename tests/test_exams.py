from datetime import date
from decimal import Decimal
from extensions import db
from app.models import (Exam, ExamPaper, ExamMark, BatchStudent, Parent, StudentParent)
from app.services import exam_service as svc
from app.services import academic_service
from conftest import make_user, login, add_branch, flashes
from test_batches import mk_teacher, mk_student, mk_batch, main_branch, admin

TODAY = date.today()


# ------------------------------------------------------------------ helpers
def enroll_direct(batch, student):
    db.session.add(BatchStudent(batch_id=batch.id, student_id=student.id, status="active",
                                enrolled_on=TODAY, fee_amount=0))
    db.session.commit()


def new_exam(client, name="Unit Test 1", **over):
    data = {"name": name, "exam_type": "unit_test", "start_date": TODAY.isoformat(),
            "end_date": TODAY.isoformat(), "note": ""}
    return client.post("/exams/new", data={**data, **over})


def add_papers(client, exam, batches, max_marks="100", pass_marks="35", exam_date=None):
    return client.post(f"/exams/{exam.id}/papers", data={
        "batch_id": [b.id for b in batches], "exam_date": (exam_date or TODAY).isoformat(),
        "max_marks": max_marks, "pass_marks": pass_marks})


def enter(client, paper, values, action="save"):
    """values = {student: '80' | 'AB' | ''}"""
    data = {f"m_{s.id}": v for s, v in values.items()}
    data["action"] = action
    return client.post(f"/exams/paper/{paper.id}/marks", data=data)


def world(subjects=("Physics", "Chemistry")):
    """Main branch, one teacher, one batch per subject, two enrolled students."""
    main = main_branch()
    teacher = mk_teacher(main)
    batches = [mk_batch(main, teacher, subject=s) for s in subjects]
    s1, s2 = mk_student(main, "Asha"), mk_student(main, "Bilal")
    for b in batches:
        enroll_direct(b, s1)
        enroll_direct(b, s2)
    return main, teacher, batches, s1, s2


def exam_with_papers(client, batches, **kw):
    admin(client)
    new_exam(client)
    exam = Exam.query.one()
    add_papers(client, exam, batches, **kw)
    return exam


def submit_all(client, exam, marks_by_student):
    """marks_by_student = {student: [mark in Chemistry, mark in Physics]} (papers in subject-name order)
    -> saves and submits every paper."""
    for i, paper in enumerate(sorted(exam.papers, key=lambda p: p.batch.subject.name)):
        enter(client, paper, {s: v[i] for s, v in marks_by_student.items()}, action="submit")


# ------------------------------------------------------------------ creating exams and papers
def test_admin_creates_exam_and_papers_once_per_batch(client):
    _, _, batches, _, _ = world()
    exam = exam_with_papers(client, batches)
    assert exam.name == "Unit Test 1" and len(exam.papers) == 2
    assert all(p.max_marks == Decimal("100") and p.pass_marks == Decimal("35") for p in exam.papers)
    add_papers(client, exam, batches)                         # same batches again: nothing duplicated
    assert ExamPaper.query.count() == 2


def test_exam_and_paper_rules(client):
    _, _, batches, _, _ = world()
    admin(client)
    new_exam(client)
    new_exam(client)                                          # duplicate name in same branch + session
    assert Exam.query.count() == 1
    new_exam(client, name="Bad dates", start_date="2030-02-02", end_date="2030-02-01")
    assert Exam.query.count() == 1
    exam = Exam.query.one()
    add_papers(client, exam, batches, pass_marks="120")        # pass marks above maximum
    add_papers(client, exam, batches, exam_date=date(2031, 1, 1))   # outside the exam dates
    assert ExamPaper.query.count() == 0


def test_teacher_cannot_create_exams(client):
    world()
    make_user("teacher", "tina")
    login(client, "tina")
    assert client.get("/exams/new").status_code == 403
    assert client.post("/exams/new", data={"name": "X", "exam_type": "unit_test", "start_date": TODAY.isoformat(),
                                           "end_date": TODAY.isoformat()}).status_code == 403


def test_accountant_has_no_exam_access(client):
    make_user("accountant", "ann")
    login(client, "ann")
    assert client.get("/exams/").status_code == 403


# ------------------------------------------------------------------ marks entry
def test_marks_are_all_or_nothing_and_ab_means_absent(client):
    _, _, batches, s1, s2 = world(("Physics",))
    exam = exam_with_papers(client, batches)
    paper = exam.papers[0]
    enter(client, paper, {s1: "82.5", s2: "abc"})              # one bad cell -> nothing saved
    assert ExamMark.query.count() == 0
    assert any("Nothing was saved" in m for m in flashes(client))
    enter(client, paper, {s1: "101", s2: "40"})                # above maximum is refused too
    assert ExamMark.query.count() == 0
    enter(client, paper, {s1: "82.5", s2: "AB"})
    m1 = ExamMark.query.filter_by(student_id=s1.id).one()
    m2 = ExamMark.query.filter_by(student_id=s2.id).one()
    assert m1.marks == Decimal("82.50") and not m1.absent
    assert m2.absent and m2.marks is None
    enter(client, paper, {s1: "", s2: "AB"})                   # blank removes the earlier entry
    assert ExamMark.query.filter_by(student_id=s1.id).count() == 0


def test_teacher_enters_only_own_batches_and_lock_blocks_edits(client):
    main, mine, batches, s1, s2 = world(("Physics",))
    other = mk_teacher(main, "Other Teacher")
    other_batch = mk_batch(main, other, subject="Chemistry")
    enroll_direct(other_batch, s1)
    exam = exam_with_papers(client, batches + [other_batch])
    mine_paper = next(p for p in exam.papers if p.batch_id == batches[0].id)
    other_paper = next(p for p in exam.papers if p.batch_id == other_batch.id)

    tuser = make_user("teacher", "tina")
    mine.user_id = tuser.id
    db.session.commit()
    tc = client.application.test_client()
    login(tc, "tina")
    assert tc.get(f"/exams/paper/{mine_paper.id}/marks").status_code == 200
    assert tc.get(f"/exams/paper/{other_paper.id}/marks").status_code == 403
    assert tc.post(f"/exams/paper/{other_paper.id}/marks", data={f"m_{s1.id}": "50"}).status_code == 403

    enter(tc, mine_paper, {s1: "70", s2: "60"}, action="submit")
    db.session.refresh(mine_paper)
    assert mine_paper.locked and ExamMark.query.filter_by(paper_id=mine_paper.id).count() == 2

    enter(tc, mine_paper, {s1: "99", s2: "60"})               # locked: change refused
    assert ExamMark.query.filter_by(paper_id=mine_paper.id, student_id=s1.id).one().marks == Decimal("70.00")
    assert tc.post(f"/exams/paper/{mine_paper.id}/unlock").status_code == 403    # only admin unlocks

    client.post(f"/exams/paper/{mine_paper.id}/unlock")        # `client` is the branch admin
    db.session.refresh(mine_paper)
    assert not mine_paper.locked
    enter(tc, mine_paper, {s1: "99", s2: "60"})
    assert ExamMark.query.filter_by(paper_id=mine_paper.id, student_id=s1.id).one().marks == Decimal("99.00")


def test_submit_needs_every_student_filled(client):
    _, _, batches, s1, s2 = world(("Physics",))
    exam = exam_with_papers(client, batches)
    paper = exam.papers[0]
    enter(client, paper, {s1: "70", s2: ""}, action="submit")
    db.session.refresh(paper)
    assert not paper.locked
    assert any("still have no marks" in m for m in flashes(client))
    enter(client, paper, {s1: "70", s2: "AB"}, action="submit")
    db.session.refresh(paper)
    assert paper.locked


def test_paper_cannot_be_removed_or_exam_deleted_after_marks(client):
    _, _, batches, s1, s2 = world(("Physics",))
    exam = exam_with_papers(client, batches)
    paper = exam.papers[0]
    enter(client, paper, {s1: "70", s2: "60"})
    client.post(f"/exams/paper/{paper.id}/delete")
    client.post(f"/exams/{exam.id}/delete")
    assert ExamPaper.query.count() == 1 and Exam.query.count() == 1
    # max marks cannot drop below an entered mark
    client.post(f"/exams/paper/{paper.id}/edit", data={"exam_date": TODAY.isoformat(), "max_marks": "50",
                                                        "pass_marks": "20"})
    db.session.refresh(paper)
    assert paper.max_marks == Decimal("100.00")


# ------------------------------------------------------------------ results maths
def test_results_totals_percentage_grade_rank_and_fail(client):
    main, _, batches, s1, s2 = world(("Physics", "Chemistry"))
    s3 = mk_student(main, "Chetan")
    for b in batches:
        enroll_direct(b, s3)
    exam = exam_with_papers(client, batches)
    # Asha 90+80 = 85%, Bilal 90+80 = 85% (tie), Chetan 30 in Chemistry (below pass 35) + AB in Physics
    submit_all(client, exam, {s1: ["90", "80"], s2: ["90", "80"], s3: ["30", "AB"]})
    rows = svc.compute_results(db.session.get(Exam, exam.id))
    by_name = {r["student"].full_name: r for r in rows}
    assert by_name["Asha"]["obtained"] == Decimal("170") and by_name["Asha"]["max"] == Decimal("200")
    assert by_name["Asha"]["percent"] == Decimal("85.00") and by_name["Asha"]["grade"] == "A"
    assert by_name["Asha"]["rank"] == by_name["Bilal"]["rank"] == 1          # tie shares rank 1
    assert by_name["Chetan"]["rank"] == 3 and not by_name["Chetan"]["passed"]
    assert by_name["Chetan"]["percent"] == Decimal("15.00") and by_name["Chetan"]["grade"] == "F"
    phys = next(s for s in by_name["Chetan"]["subjects"] if s["paper"].subject_name == "Physics")
    assert phys["absent"] and phys["grade"] == "AB" and not phys["passed"]
    assert by_name["Asha"]["passed"]


def test_student_who_failed_one_subject_fails_overall(client):
    _, _, batches, s1, s2 = world(("Physics", "Chemistry"))
    exam = exam_with_papers(client, batches)
    submit_all(client, exam, {s1: ["95", "20"], s2: ["60", "60"]})
    rows = {r["student"].full_name: r for r in svc.compute_results(db.session.get(Exam, exam.id))}
    assert not rows["Asha"]["passed"] and rows["Bilal"]["passed"]
    assert rows["Bilal"]["rank"] == 1                          # 60% beats 57.5%
    assert rows["Asha"]["rank"] == 2


# ------------------------------------------------------------------ publishing and portals
def test_publish_needs_all_papers_submitted(client):
    _, _, batches, s1, s2 = world(("Physics", "Chemistry"))
    exam = exam_with_papers(client, batches)
    enter(client, exam.papers[0], {s1: "70", s2: "60"}, action="submit")     # second paper still open
    client.post(f"/exams/{exam.id}/publish")
    db.session.refresh(exam)
    assert not exam.results_published
    enter(client, exam.papers[1], {s1: "70", s2: "60"}, action="submit")
    client.post(f"/exams/{exam.id}/publish")
    db.session.refresh(exam)
    assert exam.results_published and exam.published_at is not None


def test_published_exam_is_frozen_until_unpublished(client):
    _, _, batches, s1, s2 = world(("Physics",))
    exam = exam_with_papers(client, batches)
    paper = exam.papers[0]
    enter(client, paper, {s1: "70", s2: "60"}, action="submit")
    client.post(f"/exams/{exam.id}/publish")
    client.post(f"/exams/paper/{paper.id}/unlock")             # refused while published
    db.session.refresh(paper)
    assert paper.locked
    client.post(f"/exams/{exam.id}/unpublish")
    client.post(f"/exams/paper/{paper.id}/unlock")
    db.session.refresh(paper)
    assert not paper.locked


def test_student_sees_only_own_published_result(client):
    main, _, batches, s1, s2 = world(("Physics",))
    outsider = mk_student(main, "Outsider")                    # not enrolled, has no entry
    exam = exam_with_papers(client, batches)
    u1, u3 = make_user("student", "asha"), make_user("student", "outsider")
    s1.user_id, outsider.user_id = u1.id, u3.id
    db.session.commit()

    sc = client.application.test_client()
    login(sc, "asha")
    assert sc.get(f"/student/results/{exam.id}").status_code == 404      # nothing entered yet
    enter(client, exam.papers[0], {s1: "88", s2: "60"}, action="submit")
    assert sc.get(f"/student/results/{exam.id}").status_code == 404      # entered but not published
    assert b"No results yet" in sc.get("/student/results").data
    client.post(f"/exams/{exam.id}/publish")
    assert sc.get(f"/student/results/{exam.id}").status_code == 200
    assert b"88" in sc.get(f"/student/results/{exam.id}").data
    pdf = sc.get(f"/student/results/{exam.id}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")

    oc = client.application.test_client()
    login(oc, "outsider")
    assert oc.get(f"/student/results/{exam.id}").status_code == 404      # published, but not their exam


def test_parent_sees_only_own_childs_result(client):
    main, _, batches, s1, s2 = world(("Physics",))
    exam = exam_with_papers(client, batches)
    enter(client, exam.papers[0], {s1: "88", s2: "60"}, action="submit")
    client.post(f"/exams/{exam.id}/publish")
    pu = make_user("parent", "pat")
    p = Parent(parent_code="PAR000001", user_id=pu.id, full_name="Pat Parent", phone="9876543210",
               phone_key="9876543210")
    db.session.add(p)
    db.session.flush()
    db.session.add(StudentParent(student_id=s1.id, parent_id=p.id, relation="Father"))
    db.session.commit()

    pc = client.application.test_client()
    login(pc, "pat")
    assert pc.get(f"/parent/child/{s1.id}/results").status_code == 200
    assert pc.get(f"/parent/child/{s1.id}/results/{exam.id}").status_code == 200
    assert pc.get(f"/parent/child/{s2.id}/results").status_code == 404     # not their child
    assert pc.get(f"/parent/child/{s2.id}/results/{exam.id}").status_code == 404
    assert pc.get("/exams/").status_code == 403                              # no staff screens


# ------------------------------------------------------------------ admin views, exports, isolation
def test_admin_results_page_marksheet_pdf_and_excel(client):
    _, _, batches, s1, s2 = world(("Physics",))
    exam = exam_with_papers(client, batches)
    enter(client, exam.papers[0], {s1: "88", s2: "60"}, action="submit")
    assert client.get(f"/exams/{exam.id}/results").status_code == 200
    assert client.get(f"/exams/{exam.id}/marksheet/{s1.id}").status_code == 200
    pdf = client.get(f"/exams/{exam.id}/marksheet/{s1.id}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    xl = client.get(f"/exams/{exam.id}/results.xlsx")
    assert xl.status_code == 200 and xl.data[:2] == b"PK"


def test_branch_isolation_for_exams(client):
    main, _, batches, _, _ = world(("Physics",))
    city = add_branch("CITY1", "City Branch")
    owner = make_user("owner", "boss")
    exam = svc.create_exam(city, academic_service.current_session(),
                           {"name": "City Test", "exam_type": "unit_test", "start_date": TODAY, "end_date": TODAY,
                            "note": ""}, owner)
    admin(client)                                              # main branch admin
    assert client.get(f"/exams/{exam.id}").status_code == 403
    assert client.get(f"/exams/{exam.id}/results").status_code == 403
    assert b"City Test" not in client.get("/exams/").data
