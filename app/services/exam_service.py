"""Exams, marks and results.

Rules in one place:
- An exam belongs to one branch + session. It has one paper per batch (= one subject of one course).
- Marks are entered per paper. Blank = not entered, `AB` = absent (counts as 0 but the paper still counts in the total).
- A teacher can enter marks for their own batches until the paper is locked (submitted). Only an admin unlocks.
- Results are visible to students / parents only after an admin publishes the exam, and only when every paper is locked.
- Percentage = obtained / maximum of the papers the student was entered in. Rank is by percentage (ties share a rank).
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from sqlalchemy import func
from extensions import db
from app.models import Exam, ExamPaper, ExamMark, Batch, BatchStudent, Student
from app.services.audit_service import log_action

ZERO = Decimal("0")
HUNDRED = Decimal("100")

# (minimum percentage, grade). Change here if the institute uses a different scale.
GRADE_SCALE = [(90, "A+"), (80, "A"), (70, "B+"), (60, "B"), (50, "C"), (40, "D"), (0, "F")]
GRADE_COLORS = {"A+": "success", "A": "success", "B+": "primary", "B": "primary", "C": "warning", "D": "warning",
                "F": "danger"}


# ---------------------------------------------------------------- small helpers
def q2(value):
    return Decimal(value).quantize(Decimal("0.01"))


def to_decimal(value, field="Value"):
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise ValueError(f"{field} must be a number.")
    if not d.is_finite():
        raise ValueError(f"{field} must be a number.")
    return q2(d)


def grade_for(percent):
    p = Decimal(percent or 0)
    for minimum, letter in GRADE_SCALE:
        if p >= minimum:
            return letter
    return GRADE_SCALE[-1][1]


def percent_of(obtained, maximum):
    if not maximum:
        return ZERO
    return q2(Decimal(obtained) * HUNDRED / Decimal(maximum))


def fmt_marks(v):
    """Decimal('45.00') -> '45', Decimal('45.50') -> '45.5'."""
    if v is None:
        return "—"
    s = f"{Decimal(v):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def parse_mark_cell(text, max_marks):
    """'' -> None (not entered), 'AB' -> 'AB', '42.5' -> Decimal. Raises ValueError with a friendly message."""
    t = (text or "").strip()
    if not t:
        return None
    if t.upper() in ("AB", "A", "ABSENT"):
        return "AB"
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"“{t[:10]}” is not a number (write AB if absent)")
    if not d.is_finite():
        raise ValueError("not a valid number")
    if d < 0:
        raise ValueError("marks cannot be negative")
    d = q2(d)
    if d > Decimal(max_marks):
        raise ValueError(f"more than the maximum {fmt_marks(max_marks)}")
    return d


# ---------------------------------------------------------------- exams
def _check_dates(start, end):
    if end < start:
        raise ValueError("The last date cannot be before the first date.")


def create_exam(branch, session, data, user):
    if session is None:
        raise ValueError("Set a current academic session first (Owner > Academic sessions).")
    name = (data["name"] or "").strip()
    if not name:
        raise ValueError("Give the exam a name.")
    _check_dates(data["start_date"], data["end_date"])
    if Exam.query.filter_by(branch_id=branch.id, session_id=session.id, name=name).first():
        raise ValueError(f"An exam named “{name}” already exists in this branch for {session.name}.")
    exam = Exam(branch_id=branch.id, session_id=session.id, name=name, exam_type=data["exam_type"],
                start_date=data["start_date"], end_date=data["end_date"],
                note=(data.get("note") or "").strip() or None, created_by=user.id)
    db.session.add(exam)
    db.session.flush()
    log_action("exam_create", "exams", exam.id, f"{exam.name} ({branch.name})", user=user)
    db.session.commit()
    return exam


def update_exam(exam, data, user):
    if exam.results_published:
        raise ValueError("Results are published. Unpublish them before changing the exam.")
    name = (data["name"] or "").strip()
    if not name:
        raise ValueError("Give the exam a name.")
    _check_dates(data["start_date"], data["end_date"])
    clash = Exam.query.filter(Exam.branch_id == exam.branch_id, Exam.session_id == exam.session_id,
                              Exam.name == name, Exam.id != exam.id).first()
    if clash:
        raise ValueError(f"An exam named “{name}” already exists in this branch for this session.")
    outside = [p for p in exam.papers if not (data["start_date"] <= p.exam_date <= data["end_date"])]
    if outside:
        raise ValueError(f"{len(outside)} paper(s) fall outside the new dates. Change those papers first.")
    exam.name, exam.exam_type = name, data["exam_type"]
    exam.start_date, exam.end_date = data["start_date"], data["end_date"]
    exam.note = (data.get("note") or "").strip() or None
    log_action("exam_edit", "exams", exam.id, exam.name, user=user)
    db.session.commit()
    return exam


def delete_exam(exam, user):
    if exam.results_published:
        raise ValueError("Results are published. Unpublish them first.")
    if any(p.marks for p in exam.papers):
        raise ValueError("Marks are already entered, so this exam cannot be deleted.")
    log_action("exam_delete", "exams", exam.id, exam.name, user=user)
    db.session.delete(exam)
    db.session.commit()


# ---------------------------------------------------------------- papers
def _paper_numbers(max_marks, pass_marks):
    mx, pm = to_decimal(max_marks, "Maximum marks"), to_decimal(pass_marks, "Passing marks")
    if mx <= 0 or mx > 1000:
        raise ValueError("Maximum marks must be between 1 and 1000.")
    if pm < 0 or pm > mx:
        raise ValueError("Passing marks must be between 0 and the maximum marks.")
    return mx, pm


def add_papers(exam, batch_ids, exam_date, start_time, duration_min, max_marks, pass_marks, user):
    """Add the same paper settings for several batches at once. Returns the new papers."""
    if exam.results_published:
        raise ValueError("Results are published. Unpublish them before adding papers.")
    if not batch_ids:
        raise ValueError("Choose at least one batch.")
    if not (exam.start_date <= exam_date <= exam.end_date):
        raise ValueError(f"The paper date must be between {exam.start_date:%d %b} and {exam.end_date:%d %b %Y}.")
    mx, pm = _paper_numbers(max_marks, pass_marks)
    if duration_min is not None and not (1 <= duration_min <= 600):
        raise ValueError("Duration must be between 1 and 600 minutes.")
    batches = Batch.query.filter(Batch.id.in_(batch_ids), Batch.branch_id == exam.branch_id,
                                 Batch.session_id == exam.session_id).all()
    if len(batches) != len(set(batch_ids)):
        raise ValueError("Some batches do not belong to this branch and session.")
    have = {p.batch_id for p in exam.papers}
    made = []
    for b in sorted(batches, key=lambda x: x.name):
        if b.id in have:
            continue
        if b.status != "active":
            raise ValueError(f"{b.name} is closed. Choose active batches.")
        p = ExamPaper(exam_id=exam.id, batch_id=b.id, exam_date=exam_date, start_time=start_time,
                      duration_min=duration_min, max_marks=mx, pass_marks=pm)
        db.session.add(p)
        made.append(p)
    if not made:
        raise ValueError("Those batches already have a paper in this exam.")
    db.session.flush()
    log_action("exam_papers_add", "exams", exam.id, f"{len(made)} paper(s) added to {exam.name}", user=user)
    db.session.commit()
    return made


def update_paper(paper, exam_date, start_time, duration_min, max_marks, pass_marks, user):
    exam = paper.exam
    if exam.results_published:
        raise ValueError("Results are published. Unpublish them before changing a paper.")
    if paper.locked:
        raise ValueError("This paper is locked. Unlock it first.")
    if not (exam.start_date <= exam_date <= exam.end_date):
        raise ValueError(f"The paper date must be between {exam.start_date:%d %b} and {exam.end_date:%d %b %Y}.")
    mx, pm = _paper_numbers(max_marks, pass_marks)
    if duration_min is not None and not (1 <= duration_min <= 600):
        raise ValueError("Duration must be between 1 and 600 minutes.")
    top = max((m.marks for m in paper.marks if m.marks is not None), default=None)
    if top is not None and mx < top:
        raise ValueError(f"A student already has {fmt_marks(top)} marks. Maximum cannot be lower than that.")
    paper.exam_date, paper.start_time, paper.duration_min = exam_date, start_time, duration_min
    paper.max_marks, paper.pass_marks = mx, pm
    log_action("exam_paper_edit", "exam_papers", paper.id, f"{exam.name} / {paper.batch.name}", user=user)
    db.session.commit()


def delete_paper(paper, user):
    if paper.exam.results_published:
        raise ValueError("Results are published. Unpublish them first.")
    if paper.marks:
        raise ValueError("Marks are already entered for this paper, so it cannot be removed.")
    log_action("exam_paper_delete", "exam_papers", paper.id, f"{paper.exam.name} / {paper.batch.name}", user=user)
    db.session.delete(paper)
    db.session.commit()


# ---------------------------------------------------------------- marks entry
def paper_students(paper):
    """Students who sit this paper: active students in the batch, plus anyone who already has a mark row."""
    found = {s.id: s for s in (Student.query.join(BatchStudent, BatchStudent.student_id == Student.id)
                               .filter(BatchStudent.batch_id == paper.batch_id, BatchStudent.status == "active",
                                       Student.status == "active").all())}
    for m in paper.marks:
        found.setdefault(m.student_id, m.student)
    return sorted(found.values(), key=lambda s: (s.full_name or "").lower())


def paper_editable(paper):
    """(ok, reason) - can marks of this paper be changed right now?"""
    if paper.exam.results_published:
        return False, "Results are published. An admin must unpublish them before marks can change."
    if paper.locked:
        return False, "This paper is submitted (locked). An admin can unlock it."
    return True, ""


def save_marks(paper, cells, user, lock=False):
    """cells = {student_id: (marks_text, remark_text)}. All or nothing: one bad cell saves nothing.

    Returns (saved, cleared). With lock=True the paper is submitted too, which needs every student filled in."""
    ok, why = paper_editable(paper)
    if not ok:
        raise ValueError(why)
    students = {s.id: s for s in paper_students(paper)}
    existing = {m.student_id: m for m in paper.marks}
    parsed, problems = {}, []
    for sid, (text, remark) in cells.items():
        if sid not in students:
            continue                                   # ignore ids that are not in this batch
        try:
            parsed[sid] = (parse_mark_cell(text, paper.max_marks), (remark or "").strip()[:120] or None)
        except ValueError as e:
            problems.append(f"{students[sid].full_name}: {e}")
    if problems:
        extra = f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""
        raise ValueError("Nothing was saved. " + "; ".join(problems[:3]) + extra + ".")

    now = datetime.utcnow()
    saved = cleared = 0
    for sid, (value, remark) in parsed.items():
        row = existing.get(sid)
        if value is None:                              # blank -> remove any earlier entry
            if row is not None:
                db.session.delete(row)
                cleared += 1
            continue
        absent = value == "AB"
        marks = None if absent else value
        if row is None:
            db.session.add(ExamMark(paper_id=paper.id, student_id=sid, absent=absent, marks=marks, remark=remark,
                                    entered_by=user.id, entered_at=now))
            saved += 1
        elif (row.absent, row.marks, row.remark) != (absent, marks, remark):
            row.absent, row.marks, row.remark, row.entered_by, row.entered_at = absent, marks, remark, user.id, now
            saved += 1
    db.session.flush()

    if lock:
        db.session.expire(paper, ["marks"])
        filled = {m.student_id for m in paper.marks}
        missing = [s.full_name for sid, s in students.items() if sid not in filled]
        if missing:                                    # keep what was typed, but do not lock yet
            log_action("marks_save", "exam_papers", paper.id,
                       f"{paper.exam.name} / {paper.batch.name}: {saved} saved, {cleared} cleared", user=user)
            db.session.commit()
            names = ", ".join(sorted(missing)[:3]) + (f" and {len(missing) - 3} more" if len(missing) > 3 else "")
            raise ValueError(f"Marks saved, but not submitted: {len(missing)} student(s) still have no marks "
                             f"({names}). Enter marks or AB, then submit.")
        paper.locked, paper.locked_by, paper.locked_at = True, user.id, now
    log_action("marks_submit" if lock else "marks_save", "exam_papers", paper.id,
               f"{paper.exam.name} / {paper.batch.name}: {saved} saved, {cleared} cleared", user=user)
    db.session.commit()
    return saved, cleared


def unlock_paper(paper, user):
    if paper.exam.results_published:
        raise ValueError("Results are published. Unpublish them before unlocking a paper.")
    if not paper.locked:
        raise ValueError("This paper is not locked.")
    paper.locked, paper.locked_by, paper.locked_at = False, None, None
    log_action("marks_unlock", "exam_papers", paper.id, f"{paper.exam.name} / {paper.batch.name}", user=user)
    db.session.commit()


# ---------------------------------------------------------------- publishing
def publish(exam, user):
    if exam.results_published:
        raise ValueError("Results are already published.")
    if not exam.papers:
        raise ValueError("This exam has no papers yet.")
    open_papers = [p.batch.name for p in exam.papers if not p.locked]
    if open_papers:
        shown = ", ".join(open_papers[:3]) + (f" and {len(open_papers) - 3} more" if len(open_papers) > 3 else "")
        raise ValueError(f"Marks are not submitted yet for: {shown}. Every paper must be submitted (locked) first.")
    exam.results_published, exam.published_at, exam.published_by = True, datetime.utcnow(), user.id
    log_action("results_publish", "exams", exam.id, exam.name, user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    for paper in exam.papers:
        notify_event(actor=user, title="Exam results published",
                     body=f"Results for {exam.name} ({paper.batch.name}) are now available.", batch=paper.batch)


def unpublish(exam, user):
    if not exam.results_published:
        raise ValueError("Results are not published.")
    exam.results_published, exam.published_at, exam.published_by = False, None, None
    log_action("results_unpublish", "exams", exam.id, exam.name, user=user)
    db.session.commit()


# ---------------------------------------------------------------- progress
def paper_progress(papers):
    """{paper_id: {'total': students in batch, 'entered': marks rows, 'absent': n}} with two queries."""
    from app.services.academic_service import batch_counts
    if not papers:
        return {}
    totals = batch_counts([p.batch_id for p in papers])
    rows = (db.session.query(ExamMark.paper_id, func.count(ExamMark.id), func.sum(db.case((ExamMark.absent.is_(True), 1), else_=0)))
            .filter(ExamMark.paper_id.in_([p.id for p in papers])).group_by(ExamMark.paper_id).all())
    got = {pid: (n, int(a or 0)) for pid, n, a in rows}
    return {p.id: {"total": totals[p.batch_id]["total"], "entered": got.get(p.id, (0, 0))[0],
                   "absent": got.get(p.id, (0, 0))[1]} for p in papers}


def teacher_pending_papers(teacher, limit=8):
    """Papers of this teacher's batches whose date has come and that are not submitted yet."""
    if not teacher:
        return []
    return (ExamPaper.query.join(Exam, Exam.id == ExamPaper.exam_id).join(Batch, Batch.id == ExamPaper.batch_id)
            .filter(Batch.teacher_id == teacher.id, ExamPaper.locked.is_(False), Exam.results_published.is_(False),
                    ExamPaper.exam_date <= date.today())
            .order_by(ExamPaper.exam_date, ExamPaper.id).limit(limit).all())


# ---------------------------------------------------------------- results
def compute_results(exam):
    """One row per student who has at least one entry. Sorted by rank.

    row = {student, subjects:[{paper, absent, obtained, max, pass_marks, percent, grade, passed, remark}],
           obtained, max, percent, grade, passed, rank}"""
    papers = {p.id: p for p in exam.papers}
    if not papers:
        return []
    marks = ExamMark.query.filter(ExamMark.paper_id.in_(list(papers))).all()
    by_student = {}
    for m in marks:
        paper = papers[m.paper_id]
        mx, pm = Decimal(paper.max_marks), Decimal(paper.pass_marks)
        obtained = None if m.absent else Decimal(m.marks or 0)
        sub_pct = percent_of(obtained or ZERO, mx)
        by_student.setdefault(m.student_id, {"student": m.student, "subjects": []})["subjects"].append({
            "paper": paper, "absent": m.absent, "obtained": obtained, "max": mx, "pass_marks": pm,
            "percent": sub_pct, "grade": "AB" if m.absent else grade_for(sub_pct),
            "passed": (not m.absent) and obtained >= pm, "remark": m.remark})
    rows = []
    for data in by_student.values():
        subs = sorted(data["subjects"], key=lambda s: (s["paper"].exam_date, s["paper"].subject_name))
        got = sum((s["obtained"] or ZERO for s in subs), ZERO)
        total = sum((s["max"] for s in subs), ZERO)
        pct = percent_of(got, total)
        rows.append({"student": data["student"], "subjects": subs, "obtained": got, "max": total, "percent": pct,
                     "grade": grade_for(pct), "passed": all(s["passed"] for s in subs), "rank": None})
    rows.sort(key=lambda r: (-r["percent"], r["student"].full_name.lower()))
    last_pct, last_rank = None, 0
    for i, r in enumerate(rows, start=1):               # ties share a rank: 1, 1, 3
        if r["percent"] != last_pct:
            last_pct, last_rank = r["percent"], i
        r["rank"] = last_rank
    return rows


def student_result(exam, student):
    for r in compute_results(exam):
        if r["student"].id == student.id:
            return r
    return None


def subject_stats(rows):
    """{paper_id: {'appeared', 'average', 'highest', 'passed'}} from compute_results rows."""
    acc = {}
    for r in rows:
        for s in r["subjects"]:
            a = acc.setdefault(s["paper"].id, {"appeared": 0, "sum": ZERO, "highest": None, "passed": 0, "entries": 0})
            a["entries"] += 1
            if s["absent"]:
                continue
            a["appeared"] += 1
            a["sum"] += s["obtained"]
            a["highest"] = s["obtained"] if a["highest"] is None else max(a["highest"], s["obtained"])
            a["passed"] += 1 if s["passed"] else 0
    return {pid: {"appeared": a["appeared"], "entries": a["entries"], "passed": a["passed"], "highest": a["highest"],
                  "average": q2(a["sum"] / a["appeared"]) if a["appeared"] else None} for pid, a in acc.items()}


def published_exams_for(student):
    """Published exams in which this student has an entry, newest first."""
    ids = [r[0] for r in (db.session.query(ExamPaper.exam_id).join(ExamMark, ExamMark.paper_id == ExamPaper.id)
                          .filter(ExamMark.student_id == student.id).distinct().all())]
    return (Exam.query.filter(Exam.id.in_(ids), Exam.results_published.is_(True))
            .order_by(Exam.end_date.desc(), Exam.id.desc()).all())


def results_for_student(student):
    """[(exam, result row)] for the student/parent portal."""
    out = []
    for exam in published_exams_for(student):
        row = student_result(exam, student)
        if row:
            out.append((exam, row))
    return out


def results_export_rows(exam, rows):
    """Header + rows for an Excel export of the whole exam."""
    papers = list(exam.papers)
    headers = ["Rank", "Student ID", "Name", "Class"] + [f"{p.subject_name} ({fmt_marks(p.max_marks)})" for p in papers] \
        + ["Total", "Out of", "Percentage", "Grade", "Result"]
    body = []
    for r in rows:
        by_paper = {s["paper"].id: s for s in r["subjects"]}
        cells = []
        for p in papers:
            s = by_paper.get(p.id)
            cells.append("" if s is None else ("AB" if s["absent"] else float(s["obtained"])))
        body.append([r["rank"], r["student"].student_code, r["student"].full_name, r["student"].class_name, *cells,
                     float(r["obtained"]), float(r["max"]), float(r["percent"]), r["grade"],
                     "Pass" if r["passed"] else "Fail"])
    return headers, body
