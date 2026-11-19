from datetime import date, time
from flask import (Blueprint, render_template, redirect, url_for, flash, request, abort, Response)
from flask_login import current_user
from extensions import db
from app.models import Exam, ExamPaper, Student, Batch, Branch, Institute, EXAM_TYPES
from app.services import exam_service as svc
from app.services import academic_service
from app.services.marksheet_pdf import build_marksheet_pdf
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import role_required, permission_required
from app.utils.exports import xlsx_response
from .forms import ExamForm

bp = Blueprint("exams", __name__, url_prefix="/exams")
ADMIN = ("owner", "branch_admin")
TEACHING = ("owner", "branch_admin", "teacher")


def guard(code, roles=TEACHING):
    """Role must be in `roles` AND hold the permission."""
    def deco(view):
        return role_required(*roles)(permission_required(code)(view))
    return deco


def _me_teacher():
    return academic_service.teacher_for_user(current_user)


def _teacher_owns_paper(paper):
    me = _me_teacher()
    return bool(me and paper.batch.teacher_id == me.id)


def _exam(exam_id):
    exam = db.get_or_404(Exam, exam_id)
    ensure_branch_access(exam.branch_id)
    if current_user.role_name == "teacher" and not any(_teacher_owns_paper(p) for p in exam.papers):
        abort(403)
    return exam


def _paper(paper_id):
    paper = db.get_or_404(ExamPaper, paper_id)
    ensure_branch_access(paper.exam.branch_id)
    if current_user.role_name == "teacher" and not _teacher_owns_paper(paper):
        abort(403)
    return paper


def _visible_papers(exam):
    if current_user.role_name == "teacher":
        return [p for p in exam.papers if _teacher_owns_paper(p)]
    return list(exam.papers)


def _parse_date(text):
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _parse_time(text):
    try:
        return time.fromisoformat(text) if text else None
    except ValueError:
        return None


def _int_or_none(text):
    try:
        return int(text) if (text or "").strip() else None
    except ValueError:
        raise ValueError("Duration must be a whole number of minutes.")


# ------------------------------------------------------------------ list
@bp.route("/")
@guard("exams.view")
def index():
    branch_id = request.args.get("branch", type=int)
    session_id = request.args.get("session", type=int)
    kind = request.args.get("type", "")
    state = request.args.get("state", "")
    cur = academic_service.current_session()
    if session_id is None and cur:
        session_id = cur.id
    query = scope_to_branch(Exam.query, Exam)
    if current_user.role_name == "teacher":
        me = _me_teacher()
        query = (query.join(ExamPaper, ExamPaper.exam_id == Exam.id).join(Batch, Batch.id == ExamPaper.batch_id)
                 .filter(Batch.teacher_id == (me.id if me else 0)).distinct())
    if current_user.is_owner and branch_id:
        query = query.filter(Exam.branch_id == branch_id)
    if session_id:
        query = query.filter(Exam.session_id == session_id)
    if kind in dict(EXAM_TYPES):
        query = query.filter(Exam.exam_type == kind)
    if state == "published":
        query = query.filter(Exam.results_published.is_(True))
    elif state == "pending":
        query = query.filter(Exam.results_published.is_(False))
    page = query.order_by(Exam.start_date.desc(), Exam.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    from app.models import AcademicSession
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("exams/index.html", page=page, args=args, branch_id=branch_id, session_id=session_id,
                           kind=kind, state=state, types=EXAM_TYPES,
                           sessions=AcademicSession.query.order_by(AcademicSession.start_date.desc()).all(),
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


# ------------------------------------------------------------------ create / edit / delete
@bp.route("/new", methods=["GET", "POST"])
@guard("exams.create", ADMIN)
def new():
    if current_user.is_owner:
        branch_id = request.args.get("branch", type=int)
        if not branch_id:
            return render_template("exams/choose_branch.html",
                                   branches=Branch.query.filter_by(is_active=True).order_by(Branch.name).all())
        branch = db.get_or_404(Branch, branch_id)
    else:
        branch = current_user.branch
    form = ExamForm()
    if form.validate_on_submit():
        try:
            exam = svc.create_exam(branch, academic_service.current_session(), form.data, current_user)
            flash("Exam created. Now add the papers (one per batch).", "success")
            return redirect(url_for("exams.detail", exam_id=exam.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("exams/form.html", form=form, exam=None, branch=branch)


@bp.route("/<int:exam_id>/edit", methods=["GET", "POST"])
@guard("exams.edit", ADMIN)
def edit(exam_id):
    exam = _exam(exam_id)
    form = ExamForm(obj=exam)
    if form.validate_on_submit():
        try:
            svc.update_exam(exam, form.data, current_user)
            flash("Exam saved.", "success")
            return redirect(url_for("exams.detail", exam_id=exam.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("exams/form.html", form=form, exam=exam, branch=exam.branch)


@bp.route("/<int:exam_id>/delete", methods=["POST"])
@guard("exams.delete", ADMIN)
def delete(exam_id):
    exam = _exam(exam_id)
    try:
        svc.delete_exam(exam, current_user)
        flash("Exam deleted.", "success")
        return redirect(url_for("exams.index"))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("exams.detail", exam_id=exam.id))


# ------------------------------------------------------------------ one exam
@bp.route("/<int:exam_id>")
@guard("exams.view")
def detail(exam_id):
    exam = _exam(exam_id)
    papers = _visible_papers(exam)
    can_manage = current_user.role_name in ADMIN and current_user.has_permission("exams.edit")
    free_batches = []
    if can_manage and not exam.results_published:
        used = {p.batch_id for p in exam.papers}
        free_batches = [b for b in Batch.query.filter_by(branch_id=exam.branch_id, session_id=exam.session_id,
                                                         status="active").order_by(Batch.name).all()
                        if b.id not in used]
    return render_template("exams/detail.html", exam=exam, papers=papers, progress=svc.paper_progress(papers),
                           can_manage=can_manage, free_batches=free_batches, today=date.today(),
                           can_publish=current_user.role_name in ADMIN, fmt=svc.fmt_marks)


@bp.route("/<int:exam_id>/papers", methods=["POST"])
@guard("exams.edit", ADMIN)
def add_papers(exam_id):
    exam = _exam(exam_id)
    try:
        d = _parse_date(request.form.get("exam_date"))
        if not d:
            raise ValueError("Choose the paper date.")
        made = svc.add_papers(exam, request.form.getlist("batch_id", type=int), d,
                              _parse_time(request.form.get("start_time")), _int_or_none(request.form.get("duration")),
                              request.form.get("max_marks"), request.form.get("pass_marks"), current_user)
        flash(f"{len(made)} paper(s) added.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("exams.detail", exam_id=exam.id))


@bp.route("/paper/<int:paper_id>/edit", methods=["POST"])
@guard("exams.edit", ADMIN)
def paper_edit(paper_id):
    paper = _paper(paper_id)
    try:
        d = _parse_date(request.form.get("exam_date"))
        if not d:
            raise ValueError("Choose the paper date.")
        svc.update_paper(paper, d, _parse_time(request.form.get("start_time")), _int_or_none(request.form.get("duration")),
                         request.form.get("max_marks"), request.form.get("pass_marks"), current_user)
        flash("Paper saved.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("exams.detail", exam_id=paper.exam_id))


@bp.route("/paper/<int:paper_id>/delete", methods=["POST"])
@guard("exams.edit", ADMIN)
def paper_delete(paper_id):
    paper = _paper(paper_id)
    exam_id = paper.exam_id
    try:
        svc.delete_paper(paper, current_user)
        flash("Paper removed.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("exams.detail", exam_id=exam_id))


# ------------------------------------------------------------------ marks entry
@bp.route("/paper/<int:paper_id>/marks", methods=["GET", "POST"])
@guard("results.view")
def marks(paper_id):
    paper = _paper(paper_id)
    students = svc.paper_students(paper)
    if request.method == "POST":
        if not current_user.has_permission("results.create"):
            abort(403)
        cells = {s.id: (request.form.get(f"m_{s.id}"), request.form.get(f"r_{s.id}")) for s in students}
        try:
            saved, cleared = svc.save_marks(paper, cells, current_user, lock=request.form.get("action") == "submit")
            flash("Marks submitted and locked." if paper.locked else f"Marks saved ({saved} changed).", "success")
            return redirect(url_for("exams.detail", exam_id=paper.exam_id) if paper.locked
                            else url_for("exams.marks", paper_id=paper.id))
        except ValueError as e:
            flash(str(e), "danger")
            posted = cells
            ok, why = svc.paper_editable(paper)
            return render_template("exams/marks.html", paper=paper, students=students, editable=ok, why=why,
                                   existing={}, posted=posted, fmt=svc.fmt_marks,
                                   can_unlock=current_user.role_name in ADMIN)
    existing = {m.student_id: m for m in paper.marks}
    ok, why = svc.paper_editable(paper)
    can_edit = ok and current_user.has_permission("results.edit")
    return render_template("exams/marks.html", paper=paper, students=students, editable=can_edit, why=why,
                           existing=existing, posted=None, fmt=svc.fmt_marks,
                           can_unlock=current_user.role_name in ADMIN)


@bp.route("/paper/<int:paper_id>/unlock", methods=["POST"])
@guard("results.edit", ADMIN)
def unlock(paper_id):
    paper = _paper(paper_id)
    try:
        svc.unlock_paper(paper, current_user)
        flash("Paper unlocked. The teacher can change marks again.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("exams.detail", exam_id=paper.exam_id))


# ------------------------------------------------------------------ publish
@bp.route("/<int:exam_id>/publish", methods=["POST"])
@guard("results.edit", ADMIN)
def publish(exam_id):
    exam = _exam(exam_id)
    try:
        svc.publish(exam, current_user)
        flash("Results published. Students and parents can see them now.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("exams.detail", exam_id=exam.id))


@bp.route("/<int:exam_id>/unpublish", methods=["POST"])
@guard("results.edit", ADMIN)
def unpublish(exam_id):
    exam = _exam(exam_id)
    try:
        svc.unpublish(exam, current_user)
        flash("Results are hidden from students and parents again.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("exams.detail", exam_id=exam.id))


# ------------------------------------------------------------------ results (admin)
@bp.route("/<int:exam_id>/results")
@guard("results.view", ADMIN)
def results(exam_id):
    exam = _exam(exam_id)
    rows = svc.compute_results(exam)
    return render_template("exams/results.html", exam=exam, rows=rows, stats=svc.subject_stats(rows),
                           papers=list(exam.papers), fmt=svc.fmt_marks, grade_colors=svc.GRADE_COLORS,
                           passed=sum(1 for r in rows if r["passed"]))


@bp.route("/<int:exam_id>/results.xlsx")
@guard("results.view", ADMIN)
def results_xlsx(exam_id):
    exam = _exam(exam_id)
    headers, body = svc.results_export_rows(exam, svc.compute_results(exam))
    safe = "".join(c if c.isalnum() else "_" for c in exam.name)
    return xlsx_response(f"results_{safe}.xlsx", headers, body)


def marksheet_context(exam, student, back_url, pdf_url):
    row = svc.student_result(exam, student)
    if row is None:
        abort(404)
    return dict(exam=exam, student=student, row=row, branch=exam.branch, inst=Institute.query.first(),
                back_url=back_url, pdf_url=pdf_url, fmt=svc.fmt_marks, grade_colors=svc.GRADE_COLORS)


def marksheet_pdf_response(exam, student):
    row = svc.student_result(exam, student)
    if row is None:
        abort(404)
    pdf = build_marksheet_pdf(exam, row)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="marksheet_{student.student_code}.pdf"'})


@bp.route("/<int:exam_id>/marksheet/<int:student_id>")
@guard("results.view", ADMIN)
def marksheet(exam_id, student_id):
    exam, student = _exam(exam_id), db.get_or_404(Student, student_id)
    ensure_branch_access(student.branch_id)
    return render_template("exams/marksheet.html", **marksheet_context(
        exam, student, url_for("exams.results", exam_id=exam.id),
        url_for("exams.marksheet_pdf", exam_id=exam.id, student_id=student.id)))


@bp.route("/<int:exam_id>/marksheet/<int:student_id>.pdf")
@guard("results.view", ADMIN)
def marksheet_pdf(exam_id, student_id):
    exam, student = _exam(exam_id), db.get_or_404(Student, student_id)
    ensure_branch_access(student.branch_id)
    return marksheet_pdf_response(exam, student)
