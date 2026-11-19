from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user, login_required
from extensions import db
from app.models import (InstituteDocument, StudentDocument, EmployeeDocument, Student, Teacher, Staff, Branch,
                        LIBRARY_CATEGORIES, LIBRARY_AUDIENCES, DOC_TYPES, EMPLOYEE_DOC_TYPES)
from app.services import library_service as svc
from app.services import homework_service
from app.utils.branch_access import scope_to_branch
from app.utils.decorators import role_required, permission_required
from app.utils.file_upload import send_private

bp = Blueprint("documents", __name__, url_prefix="/documents")
ADMIN = ("owner", "branch_admin")
STAFF_SIDE = ("owner", "branch_admin", "teacher")


def guard(code, roles=ADMIN):
    def deco(view):
        return role_required(*roles)(permission_required(code)(view))
    return deco


def _doc(doc_id):
    doc = db.get_or_404(InstituteDocument, doc_id)
    if not svc.can_manage(current_user, doc):
        abort(403)
    return doc


@bp.route("/")
@guard("documents.view", STAFF_SIDE)
def index():
    category, audience = request.args.get("category", ""), request.args.get("audience", "")
    q = request.args.get("q", "").strip()
    query = svc.staff_query(current_user)
    if category in svc.CATEGORIES:
        query = query.filter(InstituteDocument.category == category)
    if audience in svc.AUDIENCES:
        query = query.filter(InstituteDocument.audience == audience)
    if q:
        query = query.filter(InstituteDocument.title.ilike(f"%{q}%"))
    page = query.order_by(InstituteDocument.created_at.desc(), InstituteDocument.id.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("documents/index.html", page=page, args=args, category=category, audience=audience, q=q,
                           categories=LIBRARY_CATEGORIES, audiences=LIBRARY_AUDIENCES,
                           can_manage=svc.can_manage, human_size=homework_service.human_size,
                           can_add=current_user.role_name in ADMIN and current_user.has_permission("documents.create"))


@bp.route("/new", methods=["GET", "POST"])
@guard("documents.create")
def new():
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all() if current_user.is_owner else []
    if request.method == "POST":
        try:
            svc.create_doc(current_user, request.form.get("branch_id", type=int), request.form.get("title"),
                           request.form.get("category"), request.form.get("audience"), request.form.get("description"),
                           request.files.get("file"))
            flash("Document added to the library.", "success")
            return redirect(url_for("documents.index"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("documents/form.html", doc=None, branches=branches, form=request.form,
                           categories=LIBRARY_CATEGORIES, audiences=LIBRARY_AUDIENCES)


@bp.route("/<int:doc_id>/edit", methods=["GET", "POST"])
@guard("documents.edit")
def edit(doc_id):
    doc = _doc(doc_id)
    if request.method == "POST":
        try:
            svc.update_doc(doc, current_user, request.form.get("title"), request.form.get("category"),
                           request.form.get("audience"), request.form.get("description"), request.files.get("file"))
            flash("Saved.", "success")
            return redirect(url_for("documents.index"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("documents/form.html", doc=doc, branches=[], form=request.form,
                           categories=LIBRARY_CATEGORIES, audiences=LIBRARY_AUDIENCES)


@bp.route("/<int:doc_id>/delete", methods=["POST"])
@guard("documents.delete")
def delete(doc_id):
    doc = _doc(doc_id)
    try:
        svc.delete_doc(doc, current_user)
        flash("Document removed.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("documents.index"))


@bp.route("/<int:doc_id>/file")
@login_required
def file(doc_id):
    """Download for everyone who may see it: staff in scope, teachers, students and parents of the right audience."""
    doc = db.get_or_404(InstituteDocument, doc_id)
    if not svc.can_view(current_user, doc):
        abort(403)
    if not homework_service.file_exists(svc.FOLDER, doc.filename):
        abort(404)
    return send_private(svc.FOLDER, doc.filename, download_name=doc.original_name)


# ------------------------------------------------------------------ central list of uploaded papers
@bp.route("/papers")
@guard("documents.view")
def papers():
    """Every paper uploaded on a student, teacher or staff profile, in one searchable list."""
    kind = request.args.get("kind", "")
    dtype = request.args.get("type", "")
    q = request.args.get("q", "").strip().lower()
    page_no = max(1, request.args.get("page", 1, type=int))
    rows = []
    if kind in ("", "student"):
        query = (StudentDocument.query.join(Student, Student.id == StudentDocument.student_id))
        for d in scope_to_branch(query, Student).order_by(StudentDocument.created_at.desc()).limit(600).all():
            s = d.student_id and db.session.get(Student, d.student_id)
            rows.append({"kind": "Student", "who": s.full_name, "code": s.student_code, "type": d.type_label,
                         "type_key": d.doc_type, "name": d.original_name, "size": d.size, "at": d.created_at,
                         "url": url_for("students.document_file", doc_id=d.id),
                         "profile": url_for("students.detail", student_id=s.id)})
    for label, Model, fk, bpn in (("Teacher", Teacher, "teacher_id", "teachers"), ("Staff", Staff, "staff_id", "staff")):
        if kind not in ("", label.lower()):
            continue
        query = EmployeeDocument.query.join(Model, Model.id == getattr(EmployeeDocument, fk))
        for d in scope_to_branch(query, Model).order_by(EmployeeDocument.created_at.desc()).limit(600).all():
            p = db.session.get(Model, getattr(d, fk))
            rows.append({"kind": label, "who": p.full_name, "code": p.employee_code, "type": d.type_label,
                         "type_key": d.doc_type, "name": d.original_name, "size": d.size, "at": d.created_at,
                         "url": url_for(f"{bpn}.document_file", doc_id=d.id),
                         "profile": url_for(f"{bpn}.detail", obj_id=p.id)})
    if dtype:
        rows = [r for r in rows if r["type_key"] == dtype]
    if q:
        rows = [r for r in rows if q in r["who"].lower() or q in r["code"].lower() or q in r["name"].lower()]
    rows.sort(key=lambda r: r["at"], reverse=True)
    per = 25
    pages = max(1, -(-len(rows) // per))
    page_no = min(page_no, pages)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("documents/papers.html", rows=rows[(page_no - 1) * per: page_no * per], total=len(rows),
                           page_no=page_no, pages=pages, args=args, kind=kind, dtype=dtype, q=q,
                           types=DOC_TYPES + [t for t in EMPLOYEE_DOC_TYPES if t not in DOC_TYPES],
                           human_size=homework_service.human_size)
