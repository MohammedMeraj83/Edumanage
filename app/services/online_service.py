from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from extensions import db
from app.models import (OnlineClass, OnlineExam, OnlineExamQuestion, OnlineExamAttempt,
                        OnlineExamAnswer, Batch, BatchStudent, Student)
from app.services.audit_service import log_action


def parse_dt(value):
    value = (value or "").strip()
    if not value:
        raise ValueError("Date and time are required.")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter a valid date and time.")


def valid_meeting_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("Meeting URL is required.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Meeting URL must begin with https:// or http://")
    return url[:500]


def manageable_batches(user):
    q = Batch.query.filter_by(status="active")
    if not user.is_owner:
        q = q.filter(Batch.branch_id == user.branch_id)
    if user.role_name == "teacher":
        from app.services.academic_service import teacher_for_user
        teacher = teacher_for_user(user)
        q = q.filter(Batch.teacher_id == (teacher.id if teacher else 0))
    return q.order_by(Batch.name).all()


def create_class(user, form):
    batch = db.session.get(Batch, form.get("batch_id", type=int))
    if not batch or batch not in manageable_batches(user):
        raise ValueError("Choose a batch you may manage.")
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("Class title is required.")
    starts = parse_dt(form.get("starts_at"))
    try:
        duration = int(form.get("duration_min") or 60)
    except ValueError:
        raise ValueError("Duration must be a whole number.")
    if not 15 <= duration <= 600:
        raise ValueError("Duration must be between 15 and 600 minutes.")
    item = OnlineClass(branch_id=batch.branch_id, batch_id=batch.id, title=title[:150],
                       description=(form.get("description") or "").strip()[:500] or None,
                       meeting_url=valid_meeting_url(form.get("meeting_url")), starts_at=starts,
                       duration_min=duration, created_by=user.id)
    db.session.add(item)
    db.session.flush()
    log_action("online_class_create", "online_classes", item.id, title, user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="Online class scheduled",
                 body=f"{item.title} is scheduled for {item.starts_at.strftime('%d %b %Y, %I:%M %p')}.", batch=item.batch)
    return item


def update_class(user, item, form):
    if item.status == "cancelled":
        raise ValueError("Cancelled classes cannot be changed.")
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("Class title is required.")
    starts = parse_dt(form.get("starts_at"))
    try:
        duration = int(form.get("duration_min") or item.duration_min)
    except ValueError:
        raise ValueError("Duration must be a whole number.")
    if not 15 <= duration <= 600:
        raise ValueError("Duration must be between 15 and 600 minutes.")
    item.title, item.starts_at, item.duration_min = title[:150], starts, duration
    item.description = (form.get("description") or "").strip()[:500] or None
    item.meeting_url = valid_meeting_url(form.get("meeting_url"))
    log_action("online_class_edit", "online_classes", item.id, title, user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="Online class scheduled",
                 body=f"{item.title} is scheduled for {item.starts_at.strftime('%d %b %Y, %I:%M %p')}.", batch=item.batch)
    return item


def decimal(value, label):
    try:
        d = Decimal(str(value).strip())
        if not d.is_finite() or d < 0:
            raise ValueError
        return d.quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError, ValueError):
        raise ValueError(f"{label} must be a valid non-negative number.")


def create_exam(user, form):
    batch = db.session.get(Batch, form.get("batch_id", type=int))
    if not batch or batch not in manageable_batches(user):
        raise ValueError("Choose a batch you may manage.")
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("Exam title is required.")
    starts, ends = parse_dt(form.get("starts_at")), parse_dt(form.get("ends_at"))
    if ends <= starts:
        raise ValueError("End time must be after start time.")
    try:
        duration = int(form.get("duration_min") or 30)
    except ValueError:
        raise ValueError("Duration must be a whole number.")
    if not 5 <= duration <= 360:
        raise ValueError("Duration must be between 5 and 360 minutes.")
    exam = OnlineExam(branch_id=batch.branch_id, batch_id=batch.id, title=title[:150],
                      instructions=(form.get("instructions") or "").strip()[:1000] or None,
                      starts_at=starts, ends_at=ends, duration_min=duration,
                      pass_marks=decimal(form.get("pass_marks") or 0, "Passing marks"),
                      created_by=user.id)
    db.session.add(exam)
    db.session.flush()
    log_action("online_exam_create", "online_exams", exam.id, title, user=user)
    db.session.commit()
    return exam


def add_question(user, exam, form):
    if exam.status != "draft":
        raise ValueError("Questions cannot be changed after publishing.")
    text = (form.get("text") or "").strip()
    options = [(form.get("option_a") or "").strip(), (form.get("option_b") or "").strip(),
               (form.get("option_c") or "").strip(), (form.get("option_d") or "").strip()]
    if not text or any(not option for option in options):
        raise ValueError("Question text and all four options are required.")
    correct = (form.get("correct_option") or "").strip().upper()
    if correct not in "ABCD":
        raise ValueError("Choose the correct option.")
    marks = decimal(form.get("marks") or 1, "Question marks")
    if marks <= 0:
        raise ValueError("Question marks must be greater than zero.")
    position = len(exam.questions) + 1
    question = OnlineExamQuestion(exam_id=exam.id, position=position, text=text[:1000],
                                  option_a=options[0][:300], option_b=options[1][:300],
                                  option_c=options[2][:300], option_d=options[3][:300],
                                  correct_option=correct, marks=marks)
    db.session.add(question)
    db.session.flush()
    log_action("online_exam_question_add", "online_exam_questions", question.id, text, user=user)
    db.session.commit()
    return question


def enrolled_batch(student, batch):
    return BatchStudent.query.filter_by(batch_id=batch.id, student_id=student.id, status="active").first() is not None


def my_student(user):
    return Student.query.filter_by(user_id=user.id).first()


def submit_exam(user, exam, form):
    student = my_student(user)
    if not student or not enrolled_batch(student, exam.batch):
        raise ValueError("You are not enrolled in this exam's batch.")
    now = datetime.now()
    if exam.status != "published":
        raise ValueError("This exam is not available.")
    if now < exam.starts_at:
        raise ValueError("The exam has not started yet.")
    if now > exam.ends_at:
        raise ValueError("The exam time has ended.")
    attempt = OnlineExamAttempt.query.filter_by(exam_id=exam.id, student_id=student.id).first()
    if attempt:
        raise ValueError("You have already submitted this exam.")
    elapsed = (now - attempt.started_at).total_seconds() if attempt else 0
    attempt = OnlineExamAttempt(exam_id=exam.id, student_id=student.id, started_at=now,
                                submitted_at=now)
    db.session.add(attempt)
    db.session.flush()
    total = Decimal("0")
    obtained = Decimal("0")
    for question in exam.questions:
        total += question.marks
        selected = (form.get(f"q_{question.id}") or "").strip().upper()
        if selected not in "ABCD":
            raise ValueError("Answer every question before submitting.")
        correct = selected == question.correct_option
        if correct:
            obtained += question.marks
        db.session.add(OnlineExamAnswer(attempt_id=attempt.id, question_id=question.id,
                                        selected_option=selected, is_correct=correct))
    attempt.total_marks, attempt.obtained_marks = total, obtained
    db.session.flush()
    log_action("online_exam_submit", "online_exam_attempts", attempt.id,
               f"{exam.title}: {obtained}/{total}", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    notify_event(actor=user, title="Online exam submitted",
                 body=f"{exam.title} submitted with {obtained}/{total} marks.", batch=exam.batch)
    return attempt
