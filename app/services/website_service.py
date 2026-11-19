from extensions import db
from app.models import Institute, Course, Branch, WebsitePage, WebsiteSetting, User, Permission
from app.services.audit_service import log_action


def setting(key, default=""):
    row = WebsiteSetting.query.filter_by(key=key).first()
    return row.value if row and row.value is not None else default


def save_setting(key, value, user=None):
    row = WebsiteSetting.query.filter_by(key=key).first()
    if row is None:
        row = WebsiteSetting(key=key, value=(value or "").strip())
        db.session.add(row)
    else:
        row.value = (value or "").strip()
    db.session.flush()
    log_action("website_setting_update", "website_settings", row.id, key, user=user)
    db.session.commit()


def save_page(slug, title, subtitle, content, published, user):
    slug = (slug or "").strip().lower().replace(" ", "-")
    title = (title or "").strip()
    if not slug or not title:
        raise ValueError("Page slug and title are required.")
    page = WebsitePage.query.filter_by(slug=slug).first()
    if page is None:
        page = WebsitePage(slug=slug)
        db.session.add(page)
    page.title = title[:150]
    page.subtitle = (subtitle or "").strip()[:300] or None
    page.content = (content or "").strip()[:10000] or None
    page.is_published = bool(published)
    db.session.flush()
    log_action("website_page_save", "website_pages", page.id, title, user=user)
    db.session.commit()
    return page


def grant_user_permission(actor, user_id, grant):
    user = db.session.get(User, user_id)
    permissions = Permission.query.filter(Permission.code.in_(("website.view", "website.edit"))).all()
    if not user or len(permissions) != 2:
        raise ValueError("Choose a valid active user and refresh permissions first.")
    if grant:
        for permission in permissions:
            if permission not in user.extra_permissions:
                user.extra_permissions.append(permission)
    else:
        for permission in permissions:
            if permission in user.extra_permissions:
                user.extra_permissions.remove(permission)
    log_action("website_permission_grant" if grant else "website_permission_revoke",
               "users", user.id, f"{user.username}: website admin", user=actor)
    db.session.commit()
