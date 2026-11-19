import json
import time
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask import Response, current_app, stream_with_context
from flask_login import current_user
from extensions import db
from app.models import Branch, Notice, Notification, PushSubscription
from app.services import communication_service as svc
from app.utils.branch_access import ensure_branch_access, scope_to_branch
from app.utils.decorators import permission_required, role_required

notices_bp = Blueprint("notices", __name__, url_prefix="/notices")
notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")
NOTICE_MANAGERS = ("owner", "branch_admin")


def _selected_branch_id(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        branch_id = int(value)
    except ValueError:
        raise ValueError("Choose a valid branch.")
    if branch_id <= 0:
        raise ValueError("Choose a valid branch.")
    return branch_id


def _managed_notice(notice_id):
    notice = db.get_or_404(Notice, notice_id)
    if notice.branch_id is not None:
        ensure_branch_access(notice.branch_id)
    elif not current_user.is_owner:
        abort(403)
    return notice


def _owned_notification(notification_id):
    notification = db.get_or_404(Notification, notification_id)
    if notification.user_id != current_user.id:
        abort(403)
    return notification


@notices_bp.route("/")
@role_required(*NOTICE_MANAGERS)
@permission_required("notices.view")
def index():
    page = scope_to_branch(Notice.query, Notice).order_by(
        Notice.created_at.desc(), Notice.id.desc()
    ).paginate(page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("notices/index.html", page=page)


@notices_bp.route("/new", methods=["GET", "POST"])
@role_required(*NOTICE_MANAGERS)
@permission_required("notices.create")
def new():
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all() if current_user.is_owner else []
    errors = []
    if request.method == "POST":
        try:
            branch_id = _selected_branch_id(request.form.get("branch_id")) if current_user.is_owner else current_user.branch_id
            svc.create_notice(user=current_user, branch_id=branch_id, title=request.form.get("title"),
                             body=request.form.get("body"), audience=request.form.get("audience"))
            flash("Notice published in the app.", "success")
            return redirect(url_for("notices.index"))
        except ValueError as exc:
            errors.append(str(exc))
    return render_template("notices/form.html", notice=None, branches=branches,
                           audiences=svc.NOTICE_AUDIENCES, errors=errors, form=request.form)


@notices_bp.route("/<int:notice_id>/edit", methods=["GET", "POST"])
@role_required(*NOTICE_MANAGERS)
@permission_required("notices.edit")
def edit(notice_id):
    notice = _managed_notice(notice_id)
    errors = []
    if request.method == "POST":
        try:
            svc.update_notice(notice, title=request.form.get("title"), body=request.form.get("body"),
                              audience=request.form.get("audience"), user=current_user)
            flash("Notice updated.", "success")
            return redirect(url_for("notices.index"))
        except ValueError as exc:
            errors.append(str(exc))
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all() if current_user.is_owner else []
    return render_template("notices/form.html", notice=notice, branches=branches,
                           audiences=svc.NOTICE_AUDIENCES, errors=errors, form=request.form)


@notices_bp.route("/<int:notice_id>/delete", methods=["POST"])
@role_required(*NOTICE_MANAGERS)
@permission_required("notices.delete")
def delete(notice_id):
    notice = _managed_notice(notice_id)
    svc.delete_notice(notice, user=current_user)
    flash("Notice withdrawn.", "success")
    return redirect(url_for("notices.index"))


@notifications_bp.route("/")
@permission_required("notifications.view")
def inbox():
    page = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc(), Notification.id.desc()
    ).paginate(page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("notices/inbox.html", page=page)


@notifications_bp.route("/stream")
@permission_required("notifications.view")
def stream():
    user_id = current_user.id
    try:
        cursor = max(0, int(request.headers.get("Last-Event-ID") or request.args.get("after", "0")))
    except ValueError:
        abort(400)

    @stream_with_context
    def events():
        last_id = cursor
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            rows = Notification.query.filter(
                Notification.user_id == user_id,
                Notification.id > last_id,
            ).order_by(Notification.id).limit(50).all()
            for item in rows:
                data = json.dumps({
                    "id": item.id,
                    "title": item.notice.title,
                    "body": item.notice.body[:240],
                    "url": url_for("notifications.detail", notification_id=item.id),
                })
                yield f"id: {item.id}\nevent: notification\ndata: {data}\n\n"
                last_id = item.id
            db.session.remove()
            if not rows:
                yield ": keep-alive\n\n"
                time.sleep(3)

    response = Response(events(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@notifications_bp.route("/push-config")
@permission_required("notifications.view")
def push_config():
    public_key = current_app.config["VAPID_PUBLIC_KEY"]
    vapid_key, error = svc.configured_vapid_key()
    return {
        "publicKey": public_key if vapid_key else "",
        "enabled": vapid_key is not None,
        "error": error,
    }


@notifications_bp.route("/push-subscriptions", methods=["POST"])
@permission_required("notifications.view")
def subscribe_push():
    data = request.get_json()
    if not isinstance(data, dict):
        return {"error": "A JSON push subscription is required."}, 400
    endpoint = data.get("endpoint")
    keys = data.get("keys")
    if not isinstance(keys, dict):
        return {"error": "Push subscription keys are required."}, 400
    try:
        svc.save_push_subscription(
            user=current_user,
            endpoint=endpoint,
            p256dh=keys.get("p256dh"),
            auth=keys.get("auth"),
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"subscribed": True}, 201


@notifications_bp.route("/push-subscriptions", methods=["DELETE"])
@permission_required("notifications.view")
def unsubscribe_push():
    data = request.get_json()
    if not isinstance(data, dict):
        return {"error": "A JSON push subscription is required."}, 400
    try:
        svc.remove_push_subscription(user=current_user, endpoint=data.get("endpoint"))
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"subscribed": False}


@notifications_bp.route("/push-subscriptions/status")
@permission_required("notifications.view")
def push_status():
    return {"subscribed": PushSubscription.query.filter_by(user_id=current_user.id).first() is not None}


@notifications_bp.route("/<int:notification_id>")
@permission_required("notifications.view")
def detail(notification_id):
    notification = _owned_notification(notification_id)
    return render_template("notices/detail.html", notification=notification)


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@permission_required("notifications.view")
def mark_read(notification_id):
    notification = _owned_notification(notification_id)
    svc.mark_notification_read(notification, user=current_user)
    flash("Notification marked as read.", "success")
    return redirect(url_for("notifications.detail", notification_id=notification.id))
