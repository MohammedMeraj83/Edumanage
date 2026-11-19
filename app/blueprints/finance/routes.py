from datetime import date
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from sqlalchemy import or_
from extensions import db
from app.models import Expense, ExpenseCategory, Branch, PAYMENT_MODES
from app.services import expense_service as svc
from app.services import finance_report_service as rep
from app.utils.branch_access import scope_to_branch, ensure_branch_access
from app.utils.decorators import staff_permission, role_required
from app.utils.exports import xlsx_response
from app.utils.file_upload import send_private

bp = Blueprint("finance", __name__, url_prefix="/finance")
ADMIN = ("owner", "branch_admin")


def _date(text, default):
    try:
        return date.fromisoformat(text) if text else default
    except ValueError:
        return default


def _branch_arg():
    return request.args.get("branch", type=int) if current_user.is_owner else current_user.branch_id


# ------------------------------------------------------------------ expenses
def _expense_query():
    today = date.today()
    start, end = _date(request.args.get("from"), today.replace(day=1)), _date(request.args.get("to"), today)
    cat, q, branch_id = request.args.get("category", type=int), (request.args.get("q") or "").strip(), _branch_arg()
    status = request.args.get("status", "active")
    query = scope_to_branch(Expense.query, Expense).filter(Expense.expense_date >= start, Expense.expense_date <= end)
    if current_user.is_owner and branch_id:
        query = query.filter(Expense.branch_id == branch_id)
    if cat:
        query = query.filter(Expense.category_id == cat)
    if status in ("active", "cancelled"):
        query = query.filter(Expense.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Expense.description.ilike(like), Expense.vendor.ilike(like), Expense.reference.ilike(like)))
    return query.order_by(Expense.expense_date.desc(), Expense.id.desc()), start, end, cat, q, branch_id, status


@bp.route("/expenses")
@staff_permission("expenses.view")
def expenses():
    svc.ensure_default_categories()
    query, start, end, cat, q, branch_id, status = _expense_query()
    page = query.paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    total = sum((e.amount for e in query.all() if e.status == "active"), Decimal(0))
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("finance/expenses.html", page=page, args=args, start=start, end=end, cat=cat, q=q,
                           branch_id=branch_id, status=status, total=total,
                           categories=ExpenseCategory.query.order_by(ExpenseCategory.name).all(),
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


@bp.route("/expenses.xlsx")
@staff_permission("expenses.view")
def expenses_xlsx():
    query, *_ = _expense_query()
    rows = [(e.expense_date.strftime("%d-%m-%Y"), e.branch.name, e.category.name, e.description, e.vendor or "",
             e.amount, e.mode, e.reference or "", e.status, e.creator.full_name) for e in query.all()]
    return xlsx_response("expenses.xlsx", ["Date", "Branch", "Category", "Description", "Vendor", "Amount", "Mode",
                                           "Reference", "Status", "Entered by"], rows)


@bp.route("/expenses/new", methods=["GET", "POST"])
@staff_permission("expenses.create")
def expense_new():
    svc.ensure_default_categories()
    cats = ExpenseCategory.query.filter_by(is_active=True).order_by(ExpenseCategory.name).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all() if current_user.is_owner else []
    if request.method == "POST":
        try:
            branch_id = request.form.get("branch_id", type=int) if current_user.is_owner else current_user.branch_id
            if not branch_id or not db.session.get(Branch, branch_id):
                raise ValueError("Choose the branch.")
            exp = svc.create_expense(
                branch_id, request.form.get("category_id", type=int), request.form.get("amount"),
                _date(request.form.get("expense_date"), date.today()), request.form.get("description"),
                request.form.get("vendor"), request.form.get("mode"), request.form.get("reference"),
                request.files.get("bill"), current_user)
            flash("Expense saved.", "success")
            return redirect(url_for("finance.expense_detail", expense_id=exp.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("finance/expense_form.html", categories=cats, branches=branches, modes=PAYMENT_MODES,
                           today=date.today())


@bp.route("/expenses/<int:expense_id>")
@staff_permission("expenses.view")
def expense_detail(expense_id):
    e = db.get_or_404(Expense, expense_id)
    ensure_branch_access(e.branch_id)
    return render_template("finance/expense_detail.html", e=e)


@bp.route("/expenses/<int:expense_id>/cancel", methods=["POST"])
@role_required(*ADMIN)
def expense_cancel(expense_id):
    e = db.get_or_404(Expense, expense_id)
    ensure_branch_access(e.branch_id)
    try:
        svc.cancel_expense(e, request.form.get("reason"), current_user)
        flash("Expense cancelled.", "success")
    except ValueError as err:
        flash(str(err), "danger")
    return redirect(url_for("finance.expense_detail", expense_id=e.id))


@bp.route("/expenses/<int:expense_id>/bill")
@staff_permission("expenses.view")
def expense_bill(expense_id):
    e = db.get_or_404(Expense, expense_id)
    ensure_branch_access(e.branch_id)
    if not e.bill_file:
        abort(404)
    return send_private("documents", e.bill_file, download_name=e.bill_name)


# ------------------------------------------------------------------ categories
@bp.route("/categories", methods=["GET", "POST"])
@staff_permission("expenses.view")
def categories():
    svc.ensure_default_categories()
    if request.method == "POST":
        if current_user.role_name not in ADMIN:
            abort(403)
        try:
            cid = request.form.get("category_id", type=int)
            cat = db.get_or_404(ExpenseCategory, cid) if cid else None
            if request.form.get("action") == "toggle" and cat:
                cat.is_active = not cat.is_active
                db.session.commit()
            else:
                svc.save_category(request.form.get("name"), cat, current_user)
            flash("Saved.", "success")
        except ValueError as e:
            flash(str(e), "danger")
        return redirect(url_for("finance.categories"))
    return render_template("finance/categories.html", items=ExpenseCategory.query.order_by(ExpenseCategory.name).all())


# ------------------------------------------------------------------ reports
@bp.route("/reports")
@staff_permission("reports.view")
def reports():
    today = date.today()
    start, end = _date(request.args.get("from"), today.replace(day=1)), _date(request.args.get("to"), today)
    if end < start:
        start, end = end, start
    branch_id = _branch_arg()
    s = rep.summary(start, end, branch_id)
    series = rep.monthly_series(today.replace(day=1), 6, branch_id)
    chart = {"labels": [r[0] for r in series], "income": [float(r[1]) for r in series], "out": [float(r[2]) for r in series]}
    return render_template("finance/reports.html", s=s, start=start, end=end, branch_id=branch_id, chart=chart,
                           compare=rep.branch_comparison(start, end) if current_user.is_owner and not branch_id else [],
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


@bp.route("/reports.xlsx")
@staff_permission("reports.view")
def reports_xlsx():
    today = date.today()
    start, end = _date(request.args.get("from"), today.replace(day=1)), _date(request.args.get("to"), today)
    s = rep.summary(start, end, _branch_arg())
    rows = [("Fees received", "", "")] + [("", label, v) for label, v in s["by_mode"]] + [("Total fees received", "", s["income"])]
    rows += [("Expenses", "", "")] + [("", n, v) for n, v in s["by_category"]] + [("Total expenses", "", s["expenses"]),
             ("Salaries paid", "", s["salary"]), ("Profit / (loss)", "", s["profit"])]
    return xlsx_response("financial-report.xlsx", ["Section", "Item", "Amount"], rows)
