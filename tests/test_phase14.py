from datetime import date, datetime, timedelta
from app.models import (Branch, AcademicSession, Course, Subject, Teacher, Batch,
                        BatchStudent, Student, OnlineClass, OnlineExam,
                        OnlineExamQuestion, OnlineExamAttempt)
from conftest import login, make_user
from extensions import db


def create_batch_pair():
    branch = Branch.query.filter_by(code="MAIN").one()
    session = AcademicSession.query.filter_by(is_current=True).one()
    course = Course(name="Science")
    subject = Subject(name="Physics")
    db.session.add_all([course, subject])
    db.session.flush()
    teacher_user = make_user("teacher", "phyteacher")
    teacher = Teacher(employee_code="T-PHY", branch_id=branch.id, user_id=teacher_user.id,
                      status="active", full_name="Physics Teacher", gender="other",
                      phone="9876543210", joining_date=date.today())
    db.session.add(teacher)
    db.session.flush()
    batch = Batch(branch_id=branch.id, session_id=session.id, course_id=course.id,
                  subject_id=subject.id, teacher_id=teacher.id, name="Physics 10",
                  fee_amount=0)
    db.session.add(batch)
    db.session.flush()
    student_user = make_user("student", "online_student")
    student = Student(student_code="STU-ONLINE", admission_no="ADM-ONLINE",
                      branch_id=branch.id, session_id=session.id, user_id=student_user.id,
                      status="active", admitted_on=date.today(), full_name="Online Student",
                      dob=date(2010, 1, 1), gender="other", class_name="Class 10",
                      guardian_phone="9876543210")
    db.session.add(student)
    db.session.flush()
    db.session.add(BatchStudent(batch_id=batch.id, student_id=student.id, status="active",
                                enrolled_on=date.today(), fee_amount=0))
    db.session.commit()
    return teacher_user, student_user, teacher, student, batch


def test_teacher_schedules_mobile_friendly_online_class(client):
    teacher_user, _, teacher, _, batch = create_batch_pair()
    login(client, "phyteacher")
    response = client.post("/online/classes/new", data={
        "batch_id": str(batch.id), "title": "Doubt clearing",
        "meeting_url": "https://meet.example.com/physics",
        "starts_at": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        "duration_min": "45", "description": "Live revision"
    })
    assert response.status_code == 302
    item = OnlineClass.query.one()
    assert item.batch_id == batch.id and item.duration_min == 45
    assert b"Join class" in client.get("/online/classes").data


def test_rejects_external_link_without_http_scheme(client):
    teacher_user, _, teacher, _, batch = create_batch_pair()
    login(client, "phyteacher")
    response = client.post("/online/classes/new", data={
        "batch_id": str(batch.id), "title": "Bad link", "meeting_url": "javascript:alert(1)",
        "starts_at": datetime.now().strftime("%Y-%m-%dT%H:%M"), "duration_min": "45"
    })
    assert response.status_code == 200 and b"https:// or http://" in response.data
    assert OnlineClass.query.count() == 0


def test_student_takes_published_mcq_exam_once(client):
    _, student_user, _, student, batch = create_batch_pair()
    login(client, "phyteacher")
    exam_response = client.post("/online/exams/new", data={
        "batch_id": str(batch.id), "title": "Chapter 1 Test",
        "starts_at": (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
        "ends_at": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        "duration_min": "30", "pass_marks": "2", "instructions": "Choose carefully"
    })
    assert exam_response.status_code == 302
    exam = OnlineExam.query.one()
    client.post(f"/online/exams/{exam.id}/questions", data={
        "text": "What is 2 + 2?", "option_a": "3", "option_b": "4",
        "option_c": "5", "option_d": "6", "correct_option": "B", "marks": "2"
    })
    client.post(f"/online/exams/{exam.id}/publish")

    own = client.application.test_client()
    login(own, "online_student")
    page = own.get(f"/online/exams/{exam.id}/take")
    assert page.status_code == 200 and b"What is 2 + 2?" in page.data
    submitted = own.post(f"/online/exams/{exam.id}/take", data={f"q_{exam.questions[0].id}": "B"})
    assert submitted.status_code == 302
    attempt = OnlineExamAttempt.query.one()
    assert attempt.student_id == student.id and attempt.obtained_marks == 2
    assert b"Pass" in own.get(f"/online/exams/{exam.id}/result").data

    duplicate = own.post(f"/online/exams/{exam.id}/take", data={f"q_{exam.questions[0].id}": "B"})
    assert duplicate.status_code == 302
    assert OnlineExamAttempt.query.count() == 1


def test_batch_and_study_event_create_in_app_notifications(client):
    make_user("branch_admin", "eventadmin")
    teacher_user, student_user, _, _, batch = create_batch_pair()

    login(client, "phyteacher")
    client.post("/online/classes/new", data={
        "batch_id": str(batch.id), "title": "Notification class",
        "meeting_url": "https://meet.example.com/class",
        "starts_at": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        "duration_min": "45"
    })

    from app.models import Notification, Notice
    title = "Online class scheduled"
    notice = Notice.query.filter_by(title=title).order_by(Notice.id.desc()).first()
    assert notice is not None
    recipient_ids = {n.user_id for n in Notification.query.filter_by(notice_id=notice.id)}
    assert student_user.id in recipient_ids
    assert teacher_user.id not in recipient_ids
    assert batch.branch_id is not None


def test_exam_cannot_publish_without_questions(client):
    _, _, _, _, batch = create_batch_pair()
    login(client, "phyteacher")
    client.post("/online/exams/new", data={
        "batch_id": str(batch.id), "title": "Empty test",
        "starts_at": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "ends_at": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        "duration_min": "30", "pass_marks": "0"
    })
    exam = OnlineExam.query.one()
    client.post(f"/online/exams/{exam.id}/publish")
    db.session.refresh(exam)
    assert exam.status == "draft"
