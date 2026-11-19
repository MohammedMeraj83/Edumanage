from datetime import date, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from extensions import db
from app.models import (LibraryBook, LibraryIssue, Branch, Student, Teacher, Staff,
                        LIBRARY_MEMBER_KINDS)
from app.services import library_service as svc
from app.services import homework_service
from app.utils.decorators import role_required, permission_required

bp = Blueprint("library", __name__, url_prefix="/library")
STAFF = ("owner", "branch_admin")


def guard(code):
    def deco(view):
        return role_required(*STAFF)(permission_required(code)(view))
    return deco


def _book(book_id):
    book = db.get_or_404(LibraryBook, book_id)
    if not current_user.is_owner and book.branch_id != current_user.branch_id:
        abort(403)
    return book


@bp.route("/")
@guard("library.view")
def index():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status", "")
    query = LibraryBook.query
    query = svc.lending_scope(current_user, query, LibraryBook)
    if q:
        query = query.filter(db.or_(LibraryBook.title.ilike(f"%{q}%"),
                                    LibraryBook.author.ilike(f"%{q}%"),
                                    LibraryBook.isbn.ilike(f"%{q}%")))
    if status in ("active", "inactive"):
        query = query.filter(LibraryBook.status == status)
    page = query.order_by(LibraryBook.title).paginate(page=request.args.get("page", 1, type=int),
                                                     per_page=20, error_out=False)
    return render_template("library/index.html", page=page, q=q, status=status,
                           can_create=current_user.has_permission("library.create"))


@bp.route("/new", methods=["GET", "POST"])
@guard("library.create")
def new():
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all() if current_user.is_owner else []
    if request.method == "POST":
        try:
            svc.create_book(current_user, request.form)
            flash("Book added to the catalogue.", "success")
            return redirect(url_for("library.index"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("library/form.html", book=None, branches=branches, form=request.form)


@bp.route("/<int:book_id>/edit", methods=["GET", "POST"])
@guard("library.edit")
def edit(book_id):
    book = _book(book_id)
    if request.method == "POST":
        try:
            svc.update_book(current_user, book, request.form)
            flash("Book details saved.", "success")
            return redirect(url_for("library.index"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("library/form.html", book=book, branches=[], form=request.form)


@bp.route("/<int:book_id>/issue", methods=["GET", "POST"])
@guard("library.create")
def issue(book_id):
    book = _book(book_id)
    kind = request.values.get("member_kind") or "student"
    if kind == "student":
        members = svc.lending_scope(current_user, Student.query.filter_by(status="active"), Student).order_by(Student.full_name).all()
    elif kind == "teacher":
        members = svc.lending_scope(current_user, Teacher.query, Teacher).order_by(Teacher.full_name).all()
    else:
        kind = "staff"
        members = svc.lending_scope(current_user, Staff.query, Staff).order_by(Staff.full_name).all()
    if request.method == "POST":
        try:
            svc.issue_book(current_user, book, request.form)
            flash("Book issued successfully.", "success")
            return redirect(url_for("library.issues"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("library/issue.html", book=book, kind=kind, members=members,
                           member_kinds=LIBRARY_MEMBER_KINDS,
                           default_due=(date.today() + timedelta(days=14)).strftime("%Y-%m-%d"))


@bp.route("/issues")
@guard("library.view")
def issues():
    status = request.args.get("status", "")
    q = (request.args.get("q") or "").strip()
    query = LibraryIssue.query
    query = svc.lending_scope(current_user, query, LibraryIssue)
    if status in ("issued", "returned", "lost"):
        query = query.filter(LibraryIssue.status == status)
    if q:
        query = query.join(LibraryBook).filter(db.or_(LibraryIssue.member_name.ilike(f"%{q}%"),
                                                       LibraryIssue.member_code.ilike(f"%{q}%"),
                                                       LibraryBook.title.ilike(f"%{q}%")))
    query = query.order_by(db.case((LibraryIssue.status == "issued", 0), else_=1),
                           LibraryIssue.due_date.asc())
    page = query.paginate(page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("library/issues.html", page=page, status=status, q=q, today=date.today())


@bp.route("/issues/<int:issue_id>/return", methods=["POST"])
@guard("library.edit")
def issue_return(issue_id):
    issue = db.get_or_404(LibraryIssue, issue_id)
    if not current_user.is_owner and issue.branch_id != current_user.branch_id:
        abort(403)
    try:
        svc.close_issue(current_user, issue, request.form.get("status", "returned"))
        flash("Issue closed and copy added back.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("library.issues"))


@bp.route("/my")
@permission_required("library.view")
def my_books():
    ids = []
    if current_user.role_name == "student":
        student = homework_service.my_student(current_user)
        if student:
            ids.append(("student", student.id))
    elif current_user.role_name == "teacher":
        teacher = Teacher.query.filter_by(user_id=current_user.id).first()
        if teacher:
            ids.append(("teacher", teacher.id))
    elif current_user.role_name == "parent":
        for child in homework_service.my_children(current_user):
            ids.append(("student", child.id))
    query = LibraryIssue.query
    if ids:
        query = query.filter(db.or_(
            *[db.and_(LibraryIssue.member_kind == kind, LibraryIssue.member_id == member_id)
              for kind, member_id in ids]
        ))
    else:
        query = query.filter(db.false())
    issues = query.order_by(LibraryIssue.status == "returned", LibraryIssue.due_date).all()
    return render_template("library/my.html", issues=issues, today=date.today())
