from datetime import date, time
from extensions import db
from app.models import (Branch, Teacher, Student, Course, Subject, Room, Batch, BatchStudent, AcademicSession,
                        TimetableSlot)
from app.services import academic_service as svc
from conftest import make_user, login, add_branch, flashes

_n = {"s": 0, "t": 0}


def mk_teacher(branch, name="Meena Rao"):
    _n["t"] += 1
    t = Teacher(employee_code=f"TCH{_n['t']:06d}", branch_id=branch.id, full_name=name, gender="Female",
                phone=f"90000{_n['t']:05d}", joining_date=date(2026, 6, 1), status="active")
    db.session.add(t)
    db.session.commit()
    return t


def mk_student(branch, name="Rohan", gender="Male"):
    _n["s"] += 1
    s = Student(student_code=f"STU{_n['s']:06d}", admission_no=f"{branch.code}-T-{_n['s']:04d}", branch_id=branch.id,
                session_id=AcademicSession.query.first().id, status="active", admitted_on=date.today(),
                full_name=name, dob=date(2010, 1, 1), gender=gender, class_name="Class 10",
                guardian_phone="9876543210")
    db.session.add(s)
    db.session.commit()
    return s


def mk_batch(branch, teacher, course="NEET", subject="Physics", name=None, capacity=30, fee=1500, room=None):
    svc.load_starter_set()
    c, s = Course.query.filter_by(name=course).one(), Subject.query.filter_by(name=subject).one()
    b = Batch(branch_id=branch.id, session_id=AcademicSession.query.first().id, course_id=c.id, subject_id=s.id,
              teacher_id=teacher.id, name=name or f"{course} - {subject}", capacity=capacity, fee_amount=fee,
              fee_frequency="monthly", room_id=room.id if room else None)
    db.session.add(b)
    db.session.commit()
    return b


def slot(client, batch, day=0, start="09:00", end="10:00", room=0, teacher=0):
    return client.post(f"/batches/{batch.id}/slots", data={"weekday": day, "start_time": start, "end_time": end,
                                                          "room_id": room, "teacher_id": teacher})


def admin(client, code="MAIN", username="bob"):
    make_user("branch_admin", username, branch_code=code)
    login(client, username)
    return client


def main_branch():
    return Branch.query.filter_by(is_main=True).one()


def test_starter_set_is_idempotent(client):
    assert svc.load_starter_set() > 0
    assert Course.query.filter_by(name="NEET").one().subjects
    assert svc.load_starter_set() == 0


def test_only_owner_manages_courses(client):
    svc.load_starter_set()
    admin(client)
    assert client.get("/academics/courses").status_code == 200
    assert client.get("/academics/courses/new").status_code == 403
    assert client.post("/academics/courses/starter").status_code == 403
    owner = client.application.test_client()
    make_user("owner", "boss")
    login(owner, "boss")
    assert owner.post("/academics/courses/new", data={"name": "Foundation", "is_active": "y"}).status_code == 302
    assert Course.query.filter_by(name="Foundation").count() == 1
    assert owner.post("/academics/courses/new", data={"name": "foundation"}).status_code == 200  # duplicate name


def test_create_batch_rules(client):
    svc.load_starter_set()
    t = mk_teacher(main_branch())
    admin(client)
    neet, jee = Course.query.filter_by(name="NEET").one(), Course.query.filter_by(name="JEE").one()
    phys, bio = Subject.query.filter_by(name="Physics").one(), Subject.query.filter_by(name="Biology").one()
    data = {"name": "", "course_id": neet.id, "subject_id": phys.id, "teacher_id": t.id, "room_id": 0,
            "capacity": 2, "fee_amount": "1500", "fee_frequency": "monthly", "start_date": "2026-06-01", "end_date": ""}
    assert client.post("/batches/new", data=data).status_code == 302
    b = Batch.query.one()
    assert b.name == "NEET - Physics" and float(b.fee_amount) == 1500 and b.branch.code == "MAIN"
    # same name again is refused; a label makes it unique
    assert client.post("/batches/new", data=data).status_code == 200
    assert client.post("/batches/new", data={**data, "name": "NEET - Physics - Evening"}).status_code == 302
    # subject that is not part of the course is refused
    client.post("/batches/new", data={**data, "course_id": jee.id, "subject_id": bio.id, "name": "x"})
    assert Batch.query.count() == 2
    # a free batch (fee 0) is allowed
    client.post("/batches/new", data={**data, "name": "Free doubt class", "fee_amount": "0"})
    assert Batch.query.count() == 3


def test_timetable_clash_checks(client):
    main = main_branch()
    t1, t2 = mk_teacher(main, "One"), mk_teacher(main, "Two")
    room = Room(branch_id=main.id, name="Room 1")
    db.session.add(room)
    db.session.commit()
    a = mk_batch(main, t1, subject="Physics", room=room)
    b = mk_batch(main, t1, subject="Chemistry")                       # same teacher as a
    c = mk_batch(main, t2, subject="Biology", room=room)              # same room as a
    d = mk_batch(main, t2, course="JEE", subject="Mathematics")       # nothing shared
    admin(client)
    assert slot(client, a).status_code == 302
    assert TimetableSlot.query.count() == 1
    slot(client, b, start="09:30", end="10:30")
    assert TimetableSlot.query.count() == 1 and "already teaching" in flashes(client)[-1]
    slot(client, c, start="09:30", end="10:30")
    assert TimetableSlot.query.count() == 1 and "room is already used" in flashes(client)[-1]
    slot(client, d, start="09:30", end="10:30")                        # no clash
    slot(client, b, start="10:00", end="11:00")                        # back-to-back is fine
    assert TimetableSlot.query.count() == 3
    slot(client, a, start="09:30", end="09:45")                        # overlaps own batch
    assert TimetableSlot.query.count() == 3
    slot(client, a, day=1, start="11:00", end="10:00")                 # end before start
    slot(client, a, day=1, start="11:00", end="11:10")                 # shorter than 15 min
    assert TimetableSlot.query.count() == 3
    assert svc.schedule_text(a) == "Mon 9:00 AM–10:00 AM"


def test_enrollment_counts_capacity_and_fee(client):
    main = main_branch()
    b = mk_batch(main, mk_teacher(main), capacity=2, fee=1500)
    boys, girl, extra = mk_student(main, "Amit", "Male"), mk_student(main, "Sita", "Female"), mk_student(main, "Late")
    admin(client)
    client.post(f"/batches/{b.id}/enroll", data={"student_id": boys.id})
    client.post(f"/batches/{b.id}/enroll", data={"student_id": girl.id, "fee": "1000"})
    counts = svc.batch_counts([b.id])[b.id]
    assert counts == {"total": 2, "male": 1, "female": 1}
    assert [float(e.fee_amount) for e in BatchStudent.query.order_by(BatchStudent.id)] == [1500.0, 1000.0]
    client.post(f"/batches/{b.id}/enroll", data={"student_id": extra.id})
    assert "full" in flashes(client)[-1] and BatchStudent.query.count() == 2
    client.post(f"/batches/{b.id}/enroll", data={"student_id": boys.id})
    assert "already" in flashes(client)[-1]
    # remove, then the same student can join again (same row is reused)
    client.post(f"/batches/{b.id}/unenroll/{boys.id}")
    assert svc.batch_counts([b.id])[b.id]["total"] == 1
    client.post(f"/batches/{b.id}/enroll", data={"student_id": boys.id})
    assert BatchStudent.query.count() == 2 and svc.batch_counts([b.id])[b.id]["total"] == 2
    # capacity cannot drop below enrolled students
    r = client.post(f"/batches/{b.id}/edit", data={"name": b.name, "course_id": b.course_id, "subject_id": b.subject_id,
                                                   "teacher_id": b.teacher_id, "room_id": 0, "capacity": 1,
                                                   "fee_amount": "1500", "fee_frequency": "monthly"})
    assert r.status_code == 200


def test_student_cannot_join_two_overlapping_batches(client):
    main = main_branch()
    t1, t2 = mk_teacher(main, "One"), mk_teacher(main, "Two")
    a, b = mk_batch(main, t1, subject="Physics"), mk_batch(main, t2, subject="Chemistry")
    s = mk_student(main)
    admin(client)
    slot(client, a, start="09:00", end="10:00")
    slot(client, b, start="09:30", end="10:30")
    client.post(f"/batches/{a.id}/enroll", data={"student_id": s.id})
    client.post(f"/batches/{b.id}/enroll", data={"student_id": s.id})
    assert "clash" in flashes(client)[-1].lower() and BatchStudent.query.count() == 1


def test_different_fees_per_subject(client):
    main = main_branch()
    t = mk_teacher(main)
    phys, chem = mk_batch(main, t, subject="Physics", fee=2000), mk_batch(main, t, subject="Chemistry", fee=1200)
    s = mk_student(main)
    admin(client)
    client.post(f"/batches/{phys.id}/enroll", data={"student_id": s.id})
    client.post(f"/batches/{chem.id}/enroll", data={"student_id": s.id})
    fees = sorted(float(e.fee_amount) for e in BatchStudent.query.filter_by(student_id=s.id))
    assert fees == [1200.0, 2000.0]


def test_branch_transfer_ends_batch_seats(client):
    main, other = main_branch(), add_branch("CITY1")
    b = mk_batch(main, mk_teacher(main))
    s = mk_student(main)
    admin(client)
    client.post(f"/batches/{b.id}/enroll", data={"student_id": s.id})
    owner = client.application.test_client()
    make_user("owner", "boss")
    login(owner, "boss")
    owner.post(f"/students/{s.id}/transfer", data={"to_branch_id": other.id, "reason": "moved"})
    enr = BatchStudent.query.one()
    assert enr.status == "left" and enr.left_on is not None
    # a student of another branch cannot be enrolled
    s2 = mk_student(other, "Elsewhere")
    client.post(f"/batches/{b.id}/enroll", data={"student_id": s2.id})
    assert client.application.test_client() and BatchStudent.query.filter_by(student_id=s2.id).count() == 0


def test_teacher_sees_only_own_batches(client):
    main = main_branch()
    t1, t2 = mk_teacher(main, "One"), mk_teacher(main, "Two")
    mine, theirs = mk_batch(main, t1, subject="Physics"), mk_batch(main, t2, subject="Chemistry")
    user = make_user("teacher", "tina")
    t1.user_id = user.id
    db.session.commit()
    me = client.application.test_client()
    login(me, "tina")
    html = me.get("/batches/").data
    assert b"NEET - Physics" in html and b"NEET - Chemistry" not in html
    assert me.get(f"/batches/{mine.id}").status_code == 200
    assert me.get(f"/batches/{theirs.id}").status_code == 403
    assert me.get(f"/batches/{mine.id}/edit").status_code == 403
    assert me.post(f"/batches/{mine.id}/slots", data={"weekday": 0, "start_time": "09:00", "end_time": "10:00",
                                                       "room_id": 0, "teacher_id": 0}).status_code == 403
    assert me.get("/timetable/").status_code == 200
    assert me.get("/teacher/dashboard").status_code == 200


def test_branch_isolation_and_roles(client):
    main, other = main_branch(), add_branch("CITY1")
    b = mk_batch(main, mk_teacher(main))
    admin(client, code="CITY1", username="cara")
    assert client.get(f"/batches/{b.id}").status_code == 403
    assert b"NEET - Physics" not in client.get("/batches/?status=all").data
    make_user("accountant", "ann")
    acc = client.application.test_client()
    login(acc, "ann")
    assert acc.get("/batches/").status_code == 403
    assert acc.get("/timetable/").status_code == 403


def test_student_and_parent_dashboards_show_batches(client):
    from app.services.student_service import create_student_login
    from app.services.parent_service import link_from_student, create_parent_login
    main = main_branch()
    b = mk_batch(main, mk_teacher(main))
    s = mk_student(main, "Rohan")
    admin(client)
    client.post(f"/batches/{b.id}/enroll", data={"student_id": s.id})
    slot(client, b, day=0)
    user, temp = create_student_login(s)
    user.must_change_password = False
    parent, _ = link_from_student(s, "Father", None)
    puser, ptemp = create_parent_login(parent)
    puser.must_change_password = False
    db.session.commit()
    stu = client.application.test_client()
    login(stu, user.username, temp)
    page = stu.get("/student/dashboard")
    assert page.status_code == 200 and b"NEET - Physics" in page.data
    par = client.application.test_client()
    login(par, puser.username, ptemp)
    page = par.get("/parent/dashboard")
    assert page.status_code == 200 and b"Physics" in page.data
