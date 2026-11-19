from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from extensions import db
from app.models import Institute, Branch, Course, WebsitePage, User, Role
from app.services import website_service as svc
from app.utils.decorators import permission_required

public_bp = Blueprint("website_public", __name__, url_prefix="")
admin_bp = Blueprint("website_admin", __name__, url_prefix="/website-admin")


@public_bp.route("/")
def home():
    inst = Institute.query.first()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.is_main.desc(), Branch.name).all()
    courses = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    pages = WebsitePage.query.filter_by(is_published=True).order_by(WebsitePage.sort_order, WebsitePage.title).all()
    return render_template("website/public_home.html", inst=inst, branches=branches, courses=courses,
                           pages=pages, hero_title=svc.setting("hero_title", inst.name if inst else "EduManage"),
                           hero_subtitle=svc.setting("hero_subtitle", inst.tagline if inst and inst.tagline else "Learn, grow and succeed."),
                           cta_title=svc.setting("cta_title", "Admissions are open"),
                           cta_text=svc.setting("cta_text", "Contact our admissions team or submit an enquiry online."))


@public_bp.route("/about")
def about():
    page = WebsitePage.query.filter_by(slug="about", is_published=True).first()
    inst = Institute.query.first()
    return render_template("website/public_page.html", page=page, inst=inst,
                           title=(page.title if page else "About us"),
                           subtitle=(page.subtitle if page else (inst.tagline if inst else "")),
                           content=(page.content if page else (inst.address if inst else "")))


@public_bp.route("/p/<slug>")
def page(slug):
    page = WebsitePage.query.filter_by(slug=slug, is_published=True).first()
    if page is None:
        abort(404)
    return render_template("website/public_page.html", page=page, inst=Institute.query.first(),
                           title=page.title, subtitle=page.subtitle, content=page.content)


@public_bp.route("/courses")
def courses():
    items = Course.query.filter_by(is_active=True).order_by(Course.name).all()
    return render_template("website/public_courses.html", courses=items,
                           inst=Institute.query.first())


@public_bp.route("/branches")
def branches():
    items = Branch.query.filter_by(is_active=True).order_by(Branch.is_main.desc(), Branch.name).all()
    return render_template("website/public_branches.html", branches=items,
                           inst=Institute.query.first())


@admin_bp.route("/")
@permission_required("website.view")
def dashboard():
    inst = Institute.query.first()
    pages = WebsitePage.query.order_by(WebsitePage.sort_order, WebsitePage.title).all()
    permissions = []
    if current_user.is_owner:
        permissions = (User.query.join(Role, User.role_id == Role.id)
                       .filter(User.is_active_user.is_(True), Role.name != "owner")
                       .order_by(User.full_name).all())
    return render_template("website/admin.html", inst=inst, pages=pages, users=permissions,
                           hero_title=svc.setting("hero_title", ""), hero_subtitle=svc.setting("hero_subtitle", ""),
                           cta_title=svc.setting("cta_title", ""), cta_text=svc.setting("cta_text", ""))


@admin_bp.route("/settings", methods=["POST"])
@permission_required("website.edit")
def settings():
    for key in ("hero_title", "hero_subtitle", "cta_title", "cta_text"):
        svc.save_setting(key, request.form.get(key, ""), current_user)
    flash("Website settings saved.", "success")
    return redirect(url_for("website_admin.dashboard"))


@admin_bp.route("/pages", methods=["POST"])
@permission_required("website.edit")
def page_save():
    try:
        page = svc.save_page(request.form.get("slug"), request.form.get("title"),
                             request.form.get("subtitle"), request.form.get("content"),
                             request.form.get("published") == "on", current_user)
        flash(f"{page.title} saved.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("website_admin.dashboard") + "#page-editor")


@admin_bp.route("/pages/<int:page_id>/toggle", methods=["POST"])
@permission_required("website.edit")
def page_toggle(page_id):
    page = db.get_or_404(WebsitePage, page_id)
    page.is_published = not page.is_published
    db.session.commit()
    flash(f"{page.title} is now {'published' if page.is_published else 'hidden'}.", "success")
    return redirect(url_for("website_admin.dashboard"))


@admin_bp.route("/permission", methods=["POST"])
@permission_required("website.edit")
def permission_grant():
    if not current_user.is_owner:
        abort(403)
    try:
        svc.grant_user_permission(current_user, request.form.get("user_id", type=int),
                                  request.form.get("grant") == "1")
        flash("Website permission updated.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("website_admin.dashboard") + "#permissions")
