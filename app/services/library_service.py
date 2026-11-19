"""Institute document library: circulars, forms, syllabus and rules shared with an audience.

- A document belongs to one branch, or to every branch (branch empty, owner only).
- Audience: everyone, teachers only, or students and parents. Owner and branch admin always see what is in their scope.
- Branch admins manage only their own branch's documents. The owner manages all.
"""
from extensions import db
from app.models import InstituteDocument, Branch, LIBRARY_CATEGORIES, LIBRARY_AUDIENCES
from app.services import homework_service
from app.services.audit_service import log_action
from app.utils.file_upload import save_attachment, delete_upload

FOLDER = "library"
CATEGORIES = dict(LIBRARY_CATEGORIES)
AUDIENCES = dict(LIBRARY_AUDIENCES)


def can_manage(user, doc):
    if user.role_name == "owner":
        return True
    return user.role_name == "branch_admin" and doc.branch_id == user.branch_id


def _branch_ok(doc, branch_ids):
    return doc.branch_id is None or doc.branch_id in branch_ids


def can_view(user, doc):
    role = user.role_name
    if role == "owner":
        return True
    if role == "branch_admin":
        return _branch_ok(doc, {user.branch_id})
    if role == "teacher":
        return doc.audience in ("all", "teachers") and _branch_ok(doc, {user.branch_id})
    if role == "student":
        me = homework_service.my_student(user)
        return bool(me) and doc.audience in ("all", "students") and _branch_ok(doc, {me.branch_id})
    if role == "parent":
        ids = {c.branch_id for c in homework_service.my_children(user)}
        return doc.audience in ("all", "students") and _branch_ok(doc, ids)
    return False


def staff_query(user):
    q = InstituteDocument.query
    role = user.role_name
    if role == "owner":
        return q
    q = q.filter(db.or_(InstituteDocument.branch_id.is_(None), InstituteDocument.branch_id == user.branch_id))
    if role == "teacher":
        q = q.filter(InstituteDocument.audience.in_(("all", "teachers")))
    elif role != "branch_admin":
        q = q.filter(db.false())
    return q


def docs_for_student_side(branch_ids):
    """Documents for students / parents of the given branches."""
    return (InstituteDocument.query.filter(InstituteDocument.audience.in_(("all", "students")),
                                           db.or_(InstituteDocument.branch_id.is_(None),
                                                  InstituteDocument.branch_id.in_(list(branch_ids))))
            .order_by(InstituteDocument.created_at.desc(), InstituteDocument.id.desc()).all())


def _clean(title, category, audience, description):
    title = (title or "").strip()
    if not title:
        raise ValueError("Title is required.")
    if len(title) > 150:
        raise ValueError("Title is too long (maximum 150 characters).")
    if category not in CATEGORIES:
        raise ValueError("Choose a category.")
    if audience not in AUDIENCES:
        raise ValueError("Choose who can see this.")
    description = (description or "").strip()
    if len(description) > 500:
        raise ValueError("Description is too long (maximum 500 characters).")
    return title, description or None


def create_doc(user, branch_id, title, category, audience, description, file):
    title, description = _clean(title, category, audience, description)
    if user.role_name == "branch_admin":
        branch_id = user.branch_id                      # a branch admin can only post for their own branch
    elif user.role_name != "owner":
        raise ValueError("You cannot add documents.")
    if branch_id and db.session.get(Branch, branch_id) is None:
        raise ValueError("Choose a branch from the list.")
    if file is None or not getattr(file, "filename", ""):
        raise ValueError("Choose a file to upload.")
    stored, original, size = save_attachment(file, FOLDER)
    doc = InstituteDocument(branch_id=branch_id or None, title=title, category=category, audience=audience,
                            description=description, filename=stored, original_name=original, size=size,
                            uploaded_by=user.id)
    db.session.add(doc)
    db.session.flush()
    log_action("library_add", "institute_documents", doc.id, title, user=user)
    db.session.commit()
    return doc


def update_doc(doc, user, title, category, audience, description, file=None):
    if not can_manage(user, doc):
        raise ValueError("You cannot change this document.")
    title, description = _clean(title, category, audience, description)
    old = None
    if file is not None and getattr(file, "filename", ""):
        new = save_attachment(file, FOLDER)
        old = doc.filename
        doc.filename, doc.original_name, doc.size = new
    doc.title, doc.category, doc.audience, doc.description = title, category, audience, description
    log_action("library_edit", "institute_documents", doc.id, title, user=user)
    db.session.commit()
    if old:
        delete_upload(FOLDER, old)
    return doc


def delete_doc(doc, user):
    if not can_manage(user, doc):
        raise ValueError("You cannot delete this document.")
    old = doc.filename
    log_action("library_delete", "institute_documents", doc.id, doc.title, user=user)
    db.session.delete(doc)
    db.session.commit()
    delete_upload(FOLDER, old)


# ---- Phase 13: physical book catalogue and circulation ----
from datetime import date, datetime
from decimal import Decimal
from app.models import (LibraryBook, LibraryIssue, Student, Teacher, Staff)


def lending_scope(user, query, model):
    if not user.is_owner:
        query = query.filter(model.branch_id == user.branch_id)
    return query


def parse_date(value, label):
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Enter a valid {label.lower()}.")


def create_book(user, form):
    title = (form.get("title") or "").strip()
    author = (form.get("author") or "").strip()
    if not title or not author:
        raise ValueError("Title and author are required.")
    try:
        total = int(form.get("total_copies") or 1)
    except ValueError:
        raise ValueError("Copies must be a whole number.")
    if total < 1:
        raise ValueError("At least one copy is required.")
    branch_id = user.branch_id if not user.is_owner else form.get("branch_id", type=int)
    if not branch_id:
        raise ValueError("Choose a branch.")
    book = LibraryBook(branch_id=branch_id, title=title[:180], author=author[:120],
                       isbn=(form.get("isbn") or "").strip()[:30] or None,
                       category=(form.get("category") or "General").strip()[:60],
                       publisher=(form.get("publisher") or "").strip()[:120] or None,
                       edition=(form.get("edition") or "").strip()[:40] or None,
                       total_copies=total, available_copies=total,
                       shelf_location=(form.get("shelf_location") or "").strip()[:80] or None)
    db.session.add(book)
    db.session.flush()
    log_action("library_create_book", "library_books", book.id, title, user=user)
    db.session.commit()
    return book


def update_book(user, book, form):
    title = (form.get("title") or "").strip()
    author = (form.get("author") or "").strip()
    if not title or not author:
        raise ValueError("Title and author are required.")
    try:
        total = int(form.get("total_copies") or book.total_copies)
    except ValueError:
        raise ValueError("Copies must be a whole number.")
    issued = book.total_copies - book.available_copies
    if total < issued:
        raise ValueError(f"Copies cannot be below the {issued} currently issued.")
    book.title, book.author = title[:180], author[:120]
    book.isbn = (form.get("isbn") or "").strip()[:30] or None
    book.category = (form.get("category") or "General").strip()[:60]
    book.publisher = (form.get("publisher") or "").strip()[:120] or None
    book.edition = (form.get("edition") or "").strip()[:40] or None
    book.total_copies = total
    book.available_copies = max(0, total - issued)
    book.shelf_location = (form.get("shelf_location") or "").strip()[:80] or None
    log_action("library_edit_book", "library_books", book.id, title, user=user)
    db.session.commit()
    return book


def _member(user, kind, member_id):
    model = {"student": Student, "teacher": Teacher, "staff": Staff}.get(kind)
    if model is None:
        raise ValueError("Choose a valid member type.")
    member = db.session.get(model, member_id)
    if not member:
        raise ValueError("Choose a valid member.")
    if not user.is_owner and member.branch_id != user.branch_id:
        raise ValueError("You cannot issue a book to a member from another branch.")
    code = getattr(member, "student_code", None) or getattr(member, "employee_code", None)
    return member.full_name, code


def issue_book(user, book, form):
    if book.status != "active" or book.available_copies < 1:
        raise ValueError("This book has no copies available.")
    kind = (form.get("member_kind") or "student").strip()
    try:
        member_id = int(form.get("member_id") or 0)
    except ValueError:
        raise ValueError("Choose a member.")
    name, code = _member(user, kind, member_id)
    due = parse_date(form.get("due_date"), "Due date")
    if due < date.today():
        raise ValueError("Due date cannot be before today.")
    already = LibraryIssue.query.filter_by(book_id=book.id, member_kind=kind, member_id=member_id,
                                           status="issued").first()
    if already:
        raise ValueError("This member already has a copy of this book issued.")
    issue = LibraryIssue(branch_id=book.branch_id, book_id=book.id, member_kind=kind, member_id=member_id,
                         member_name=name, member_code=code, due_date=due,
                         notes=(form.get("notes") or "").strip()[:300] or None)
    db.session.add(issue)
    book.available_copies -= 1
    db.session.flush()
    log_action("library_issue", "library_issues", issue.id, f"{book.title} -> {name}", user=user)
    db.session.commit()
    from app.services.communication_service import notify_event
    recipient_ids = []
    if kind == "student":
        member = db.session.get(Student, member_id)
        if member:
            if member.user_id:
                recipient_ids.append(member.user_id)
            recipient_ids.extend(link.parent.user_id for link in member.parent_links if link.parent.user_id)
    elif kind == "teacher":
        member = db.session.get(Teacher, member_id)
        if member and member.user_id:
            recipient_ids.append(member.user_id)
    elif kind == "staff":
        member = db.session.get(Staff, member_id)
        if member and member.user_id:
            recipient_ids.append(member.user_id)
    notify_event(actor=user, title="Library book issued",
                 body=f"{book.title} was issued to {name}. Due date: {due.strftime('%d %b %Y')}.",
                 branch_id=book.branch_id, recipient_ids=recipient_ids)
    from app.services.communication_service import notify_event
    recipient_ids = []
    if issue.member_kind == "student":
        member = db.session.get(Student, issue.member_id)
        if member:
            if member.user_id:
                recipient_ids.append(member.user_id)
            recipient_ids.extend(link.parent.user_id for link in member.parent_links if link.parent.user_id)
    elif issue.member_kind == "teacher":
        member = db.session.get(Teacher, issue.member_id)
        if member and member.user_id:
            recipient_ids.append(member.user_id)
    elif issue.member_kind == "staff":
        member = db.session.get(Staff, issue.member_id)
        if member and member.user_id:
            recipient_ids.append(member.user_id)
    notify_event(actor=user, title="Library issue closed",
                 body=f"{issue.book.title} was marked {issue.status}.",
                 branch_id=issue.branch_id, recipient_ids=recipient_ids)
    return issue


def calculate_fine(issue, fine_per_day=5):
    end = issue.return_date or date.today()
    if end <= issue.due_date:
        return Decimal("0")
    return Decimal((end - issue.due_date).days * fine_per_day).quantize(Decimal("0.01"))


def close_issue(user, issue, status="returned", fine_per_day=5):
    if issue.status in ("returned", "lost"):
        raise ValueError("This issue is already closed.")
    issue.return_date = date.today()
    issue.status = status
    issue.fine_amount = calculate_fine(issue, fine_per_day)
    issue.book.available_copies = min(issue.book.total_copies, issue.book.available_copies + 1)
    log_action("library_return", "library_issues", issue.id, f"{issue.book.title} {status}", user=user)
    db.session.commit()
    return issue
