from datetime import datetime, timedelta, date
from extensions import db
from app.models import (BranchGeo, LectureSession, AttendanceRecord, LeaveRequest, BatchStudent, Student)
from app.services import attendance_service as svc
from conftest import make_user, login, add_branch, flashes
from test_batches import mk_teacher, mk_student, mk_batch, main_branch, admin

LAT, LNG = 19.138300, 77.321000          # the "tuition"
NEAR = {"lat": LAT + 0.0003, "lng": LNG, "accuracy": 20}      # about 33 m away
FAR = {"lat": LAT + 0.01, "lng": LNG, "accuracy": 20}         # about 1.1 km away
FUZZY = {"lat": LAT, "lng": LNG, "accuracy": 500}


def set_geo(branch, radius=100):
    g = BranchGeo(branch_id=branch.id, latitude=LAT, longitude=LNG, radius_m=radius, qr_token="tok" + str(branch.id))
    db.session.add(g)
    db.session.commit()
    return g


def mk_session(batch, teacher, start_in_min=5, minutes=60, day=None):
    start = datetime.utcnow() + timedelta(minutes=start_in_min)
    s = LectureSession(branch_id=batch.branch_id, batch_id=batch.id, teacher_id=teacher.id,
                       lecture_date=day or date.today(), start_at=start, end_at=start + timedelta(minutes=minutes))
    db.session.add(s)
    db.session.commit()
    return s


def teacher_login(client, teacher, username="tina"):
    user = make_user("teacher", username, branch_code=teacher.branch.code)
    teacher.user_id = user.id
    db.session.commit()
    c = client.application.test_client()
    login(c, username)
    return c


def enroll(batch, student):
    db.session.add(BatchStudent(batch_id=batch.id, student_id=student.id, status="active",
                                enrolled_on=date.today() - timedelta(days=1), fee_amount=0))
    db.session.commit()


def make_world(client, start_in_min=5):
    main = main_branch()
    set_geo(main)
    t = mk_teacher(main)
    b = mk_batch(main, t)
    s = mk_session(b, t, start_in_min)
    return main, t, b, s


# ------------------------------------------------------------------ location maths
def test_haversine_and_location_rules(client):
    main = main_branch()
    set_geo(main, radius=100)
    assert svc.haversine_m(LAT, LNG, LAT, LNG) == 0
    assert 30 < svc.haversine_m(LAT, LNG, LAT + 0.0003, LNG) < 40
    assert svc.verify_location(main.id, LAT + 0.0003, LNG, 20) < 100
    for bad, text in [((LAT + 0.01, LNG, 20), "from the tuition"), ((LAT, LNG, 500), "not accurate"),
                      (("x", "y", 5), "not received"), ((LAT, LNG, None), "not accurate")]:
        try:
            svc.verify_location(main.id, *bad)
            raise AssertionError("should have failed")
        except ValueError as e:
            assert text in str(e)
    other = add_branch("CITY1")
    try:
        svc.verify_location(other.id, LAT, LNG, 10)
        raise AssertionError("branch without location must refuse")
    except ValueError as e:
        assert "not set" in str(e)


# ------------------------------------------------------------------ teacher check-in
def test_teacher_checkin_window_location_and_ownership(client):
    main, t, b, s = make_world(client, start_in_min=5)
    me = teacher_login(client, t)
    me.post(f"/attendance/session/{s.id}/checkin", data=FAR)
    db.session.refresh(s)
    assert s.checkin_at is None and "from the tuition" in flashes(me)[-1]
    me.post(f"/attendance/session/{s.id}/checkin", data=FUZZY)
    assert s.checkin_at is None
    me.post(f"/attendance/session/{s.id}/checkin", data=NEAR)
    db.session.refresh(s)
    assert s.checkin_at is not None and s.checkin_distance_m < 100 and svc.late_minutes(s) == 0
    assert svc.session_state(s)[0] == "running"
    me.post(f"/attendance/session/{s.id}/checkin", data=NEAR)
    assert "already" in flashes(me)[-1]


def test_too_early_and_late_arrival(client):
    main, t, b, early = make_world(client, start_in_min=40)        # window opens 15 min before -> not yet
    other_batch = mk_batch(main, t, subject="Chemistry")
    late = mk_session(other_batch, t, start_in_min=-20, minutes=60)   # started 20 min ago
    me = teacher_login(client, t)
    me.post(f"/attendance/session/{early.id}/checkin", data=NEAR)
    db.session.refresh(early)
    assert early.checkin_at is None and "Too early" in flashes(me)[-1]
    me.post(f"/attendance/session/{late.id}/checkin", data=NEAR)
    db.session.refresh(late)
    assert late.checkin_at is not None and 15 <= svc.late_minutes(late) <= 25
    assert svc.session_state(late)[0] == "running"


def test_early_checkin_opens_15_minutes_before(client):
    main, t, b, s = make_world(client, start_in_min=14)
    me = teacher_login(client, t)
    me.post(f"/attendance/session/{s.id}/checkin", data=NEAR)
    db.session.refresh(s)
    assert s.checkin_at is not None


def test_other_teacher_cannot_use_my_lecture(client):
    main, t, b, s = make_world(client)
    t2 = mk_teacher(main, "Other")
    intruder = teacher_login(client, t2, "ravi")
    assert intruder.post(f"/attendance/session/{s.id}/checkin", data=NEAR).status_code == 403
    assert intruder.get(f"/attendance/session/{s.id}").status_code == 403


# ------------------------------------------------------------------ marking attendance
def test_teacher_marks_attendance_only_after_checkin_and_inside_branch(client):
    main, t, b, s = make_world(client)
    a, c = mk_student(main, "Amit"), mk_student(main, "Sita", "Female")
    enroll(b, a); enroll(b, c)
    me = teacher_login(client, t)
    form = {f"status_{a.id}": "present", f"status_{c.id}": "absent", **NEAR}
    me.post(f"/attendance/session/{s.id}/mark", data=form)
    assert AttendanceRecord.query.count() == 0 and "Start the lecture" in flashes(me)[-1]
    me.post(f"/attendance/session/{s.id}/checkin", data=NEAR)
    me.post(f"/attendance/session/{s.id}/mark", data={**form, **FAR})
    assert AttendanceRecord.query.count() == 0 and "from the tuition" in flashes(me)[-1]
    me.post(f"/attendance/session/{s.id}/mark", data=form)
    recs = {r.student_id: r.status for r in AttendanceRecord.query}
    assert recs == {a.id: "present", c.id: "absent"}
    db.session.refresh(s)
    assert s.attendance_submitted_at is not None
    # change one student
    me.post(f"/attendance/session/{s.id}/mark", data={**form, f"status_{c.id}": "late"})
    assert AttendanceRecord.query.filter_by(student_id=c.id).one().status == "late"
    assert AttendanceRecord.query.count() == 2


def test_attendance_edit_window_closes_for_teacher_but_not_admin(client):
    main, t, b, s = make_world(client)
    a = mk_student(main, "Amit")
    enroll(b, a)
    me = teacher_login(client, t)
    me.post(f"/attendance/session/{s.id}/checkin", data=NEAR)
    me.post(f"/attendance/session/{s.id}/mark", data={f"status_{a.id}": "present", **NEAR})
    s.start_at -= timedelta(hours=5)
    s.end_at -= timedelta(hours=5)
    db.session.commit()
    me.post(f"/attendance/session/{s.id}/mark", data={f"status_{a.id}": "absent", **NEAR})
    assert "time to change" in flashes(me)[-1]
    assert AttendanceRecord.query.one().status == "present"
    boss = admin(client)
    boss.post(f"/attendance/session/{s.id}/mark", data={f"status_{a.id}": "absent"})       # no location needed
    assert AttendanceRecord.query.one().status == "absent"


def test_roster_respects_enrollment_date_and_approved_leave(client):
    main, t, b, s = make_world(client)
    old, new, away = mk_student(main, "Old"), mk_student(main, "New"), mk_student(main, "Away")
    enroll(b, old); enroll(b, away)
    db.session.add(BatchStudent(batch_id=b.id, student_id=new.id, status="active", enrolled_on=date.today() + timedelta(days=3),
                                fee_amount=0))
    db.session.add(LeaveRequest(branch_id=main.id, kind="student", student_id=away.id, requested_by=1, from_date=date.today(),
                                to_date=date.today(), reason="fever", status="approved"))
    db.session.commit()
    rows = {st.full_name: leave for st, rec, leave in svc.roster(s)}
    assert set(rows) == {"Old", "Away"} and rows["Away"] is True and rows["Old"] is False


# ------------------------------------------------------------------ student check-in
def test_student_self_checkin_needs_location_and_batch(client):
    main, t, b, s = make_world(client)
    a, outsider = mk_student(main, "Amit"), mk_student(main, "Outsider")
    enroll(b, a)
    for st in (a, outsider):
        from app.services.student_service import create_student_login
        u, pw = create_student_login(st)
        u.must_change_password = False
        db.session.commit()
        st._pw = pw
    me = client.application.test_client()
    login(me, a.student_code.lower(), a._pw)
    me.post(f"/attendance/session/{s.id}/self-checkin", data=FAR)
    assert AttendanceRecord.query.count() == 0 and "from the tuition" in flashes(me)[-1]
    me.post(f"/attendance/session/{s.id}/self-checkin", data=NEAR)
    rec = AttendanceRecord.query.one()
    assert rec.verified and rec.verified_distance_m < 100
    # not in the batch -> refused
    other = client.application.test_client()
    login(other, outsider.student_code.lower(), outsider._pw)
    other.post(f"/attendance/session/{s.id}/self-checkin", data=NEAR)
    assert AttendanceRecord.query.count() == 1
    # students cannot mark attendance or open the teacher page
    assert me.post(f"/attendance/session/{s.id}/mark", data={}).status_code == 403
    assert me.get(f"/attendance/session/{s.id}").status_code == 403


def test_student_checkin_too_early(client):
    main, t, b, s = make_world(client, start_in_min=45)
    a = mk_student(main, "Amit")
    enroll(b, a)
    from app.services.student_service import create_student_login
    u, pw = create_student_login(a)
    u.must_change_password = False
    db.session.commit()
    me = client.application.test_client()
    login(me, a.student_code.lower(), pw)
    me.post(f"/attendance/session/{s.id}/self-checkin", data=NEAR)
    assert AttendanceRecord.query.count() == 0 and "Too early" in flashes(me)[-1]


# ------------------------------------------------------------------ states, board, reports
def test_session_states(client):
    main, t, b, _ = make_world(client)
    now = datetime.utcnow()
    s = mk_session(b, t, start_in_min=60)
    assert svc.session_state(s, now)[0] == "upcoming"
    s2 = mk_session(mk_batch(main, t, subject="Chemistry"), t, start_in_min=3)
    assert svc.session_state(s2, now)[0] == "waiting"
    s3 = mk_session(mk_batch(main, t, subject="Biology"), t, start_in_min=-10)
    assert svc.session_state(s3, now)[0] == "late"
    s4 = mk_session(mk_batch(main, t, course="JEE", subject="Mathematics"), t, start_in_min=-90)
    assert svc.session_state(s4, now)[0] == "missed"
    db.session.add(LeaveRequest(branch_id=main.id, kind="teacher", teacher_id=t.id, requested_by=1, from_date=date.today(),
                                to_date=date.today(), reason="x", status="approved"))
    db.session.commit()
    assert svc.session_state(s4, now)[0] == "teacher_leave"


def test_live_board_access_and_report(client):
    main, t, b, s = make_world(client)
    boss = admin(client)
    page = boss.get("/attendance/live")
    assert page.status_code == 200
    assert boss.get("/attendance/reports").status_code == 200
    me = teacher_login(client, t)
    assert me.get("/attendance/live").status_code == 403
    assert me.get("/attendance/reports").status_code == 403
    assert me.get("/attendance/my").status_code == 200
    # punctuality numbers
    me.post(f"/attendance/session/{s.id}/checkin", data=NEAR)
    s.start_at -= timedelta(hours=2)
    s.end_at -= timedelta(hours=2)
    s.checkin_at = s.start_at + timedelta(minutes=12)
    db.session.commit()
    rows = svc.teacher_report(date.today() - timedelta(days=1), date.today())
    assert rows and rows[0]["late"] == 1 and rows[0]["avg_late"] == 12


def test_branch_isolation_for_sessions(client):
    main, t, b, s = make_world(client)
    add_branch("CITY1")
    cara = admin(client, code="CITY1", username="cara")
    assert cara.get(f"/attendance/session/{s.id}").status_code == 403
    assert cara.post(f"/attendance/session/{s.id}/mark", data={}).status_code == 403


def test_ensure_sessions_creates_from_timetable_once(client):
    main = main_branch()
    t = mk_teacher(main)
    b = mk_batch(main, t)
    from app.models import TimetableSlot
    from datetime import time
    today = date.today()
    db.session.add(TimetableSlot(batch_id=b.id, weekday=today.weekday(), start_time=time(9, 0), end_time=time(10, 0)))
    db.session.commit()
    first = svc.ensure_sessions(today, branch_id=main.id)
    again = svc.ensure_sessions(today, branch_id=main.id)
    assert len(first) == 1 and len(again) == 1 and first[0].id == again[0].id
    assert first[0].teacher_id == t.id and first[0].minutes == 60


# ------------------------------------------------------------------ location setup + QR + scan page
def test_location_setup_qr_and_scan(client):
    main = main_branch()
    t = mk_teacher(main)
    boss = admin(client)
    assert boss.get("/attendance/location").status_code == 200
    boss.post("/attendance/location", data={"lat": "abc", "lng": "1", "radius": "100"})
    assert BranchGeo.query.count() == 0
    boss.post("/attendance/location", data={"lat": LAT, "lng": LNG, "radius": "20"})
    assert BranchGeo.query.count() == 0                       # radius too small
    boss.post("/attendance/location", data={"lat": LAT, "lng": LNG, "radius": "120"})
    geo = BranchGeo.query.one()
    assert geo.radius_m == 120 and len(geo.qr_token) >= 16
    r = boss.get("/attendance/qr.png")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data[:4] == b"\x89PNG"
    old = geo.qr_token
    boss.post("/attendance/qr/regenerate")
    db.session.refresh(geo)
    assert geo.qr_token != old
    me = teacher_login(client, t)
    assert me.get(f"/attendance/scan/{old}").status_code == 404
    assert me.get(f"/attendance/scan/{geo.qr_token}").status_code == 200
    assert me.get("/attendance/qr.png").status_code == 403    # teachers cannot download the QR
    anon = client.application.test_client()
    assert anon.get(f"/attendance/scan/{geo.qr_token}").status_code == 302       # must sign in first


# ------------------------------------------------------------------ leave
def test_leave_flow(client):
    main = main_branch()
    t = mk_teacher(main)
    me = teacher_login(client, t)
    soon = (date.today() + timedelta(days=1)).isoformat()
    me.post("/leave/new", data={"from_date": soon, "to_date": soon, "reason": "wedding"})
    req = LeaveRequest.query.one()
    assert req.kind == "teacher" and req.status == "pending" and req.branch_id == main.id
    me.post("/leave/new", data={"from_date": soon, "to_date": soon, "reason": "again"})
    assert LeaveRequest.query.count() == 1 and "already" in flashes(me)[-1]
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    me.post("/leave/new", data={"from_date": yesterday, "to_date": yesterday, "reason": "late"})
    assert LeaveRequest.query.count() == 1
    assert me.post(f"/leave/{req.id}/decide", data={"action": "approve"}).status_code == 403
    boss = admin(client)
    boss.post(f"/leave/{req.id}/decide", data={"action": "approve", "note": "ok"})
    db.session.refresh(req)
    assert req.status == "approved"
    assert svc.on_leave("teacher", t.id, date.today() + timedelta(days=1)) is True
    boss.post(f"/leave/{req.id}/decide", data={"action": "reject"})
    assert "already" in flashes(boss)[-1]


def test_parent_applies_leave_for_own_child_only(client):
    from app.services.student_service import create_student_login
    from app.services.parent_service import link_from_student, create_parent_login
    main = main_branch()
    mine, theirs = mk_student(main, "Mine"), mk_student(main, "Theirs")
    theirs.guardian_phone = "9000000099"
    db.session.commit()
    parent, _ = link_from_student(mine, "Father", None)
    pu, pw = create_parent_login(parent)
    pu.must_change_password = False
    db.session.commit()
    par = client.application.test_client()
    login(par, pu.username, pw)
    day = (date.today() + timedelta(days=1)).isoformat()
    par.post("/leave/new", data={"student_id": theirs.id, "from_date": day, "to_date": day, "reason": "x"})
    assert LeaveRequest.query.count() == 0
    par.post("/leave/new", data={"student_id": mine.id, "from_date": day, "to_date": day, "reason": "fever"})
    assert LeaveRequest.query.one().student_id == mine.id
    assert par.get(f"/parent/child/{mine.id}/attendance").status_code == 200
    assert par.get(f"/parent/child/{theirs.id}/attendance").status_code == 404
    assert par.get("/parent/dashboard").status_code == 200


def test_summary_percent_ignores_leave(client):
    main, t, b, s = make_world(client)
    a = mk_student(main, "Amit")
    enroll(b, a)
    for i, status in enumerate(["present", "present", "late", "absent", "leave"]):
        sess = mk_session(b, t, start_in_min=-(i + 1) * 1440, day=date.today() - timedelta(days=i + 1))
        db.session.add(AttendanceRecord(session_id=sess.id, student_id=a.id, status=status))
    db.session.commit()
    summ = svc.student_summary(a, date.today() - timedelta(days=30), date.today())
    assert summ["present"] == 2 and summ["late"] == 1 and summ["absent"] == 1 and summ["leave"] == 1
    assert summ["percent"] == 75
