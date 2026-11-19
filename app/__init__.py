import os
from datetime import timedelta
from flask import Flask, redirect, request, url_for, render_template, send_from_directory, abort, make_response
from flask_login import current_user
from config import config
from extensions import db, migrate, login_manager, csrf, limiter, mail

PUBLIC_MEDIA_FOLDERS = {"institute"}


def create_app(config_name=None):
    config_name = config_name or os.getenv("FLASK_ENV", "development")
    app = Flask(__name__)
    app.config.from_object(config.get(config_name, config["development"]))

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    from app import models  # noqa: F401  (register models for migrations)
    _register_blueprints(app)
    _register_hooks(app)
    _register_errors(app)
    _register_cli(app)
    return app


def _register_blueprints(app):
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.owner import bp as owner_bp
    from app.blueprints.branches import bp as branches_bp
    from app.blueprints.settings import bp as settings_bp
    from app.blueprints.admissions import bp as admissions_bp
    from app.blueprints.students import bp as students_bp
    from app.blueprints.parents import bp as parents_bp
    from app.blueprints.teachers import bp as teachers_bp
    from app.blueprints.academics import bp as academics_bp
    from app.blueprints.batches import bp as batches_bp
    from app.blueprints.timetable import bp as timetable_bp
    from app.blueprints.attendance import bp as attendance_bp
    from app.blueprints.leave import bp as leave_bp
    from app.blueprints.exams import bp as exams_bp
    from app.blueprints.homework import bp as homework_bp
    from app.blueprints.materials import bp as materials_bp
    from app.blueprints.id_cards import bp as id_cards_bp
    from app.blueprints.certificates import bp as certificates_bp
    from app.blueprints.documents import bp as documents_bp
    from app.blueprints.verify import bp as verify_bp
    from app.blueprints.fees import bp as fees_bp
    from app.blueprints.finance import bp as finance_bp
    from app.blueprints.payroll import bp as payroll_bp
    from app.blueprints.staff import bp as staff_bp
    from app.blueprints.branch_admin import bp as branch_admin_bp
    from app.blueprints.accountant import bp as accountant_bp
    from app.blueprints.teacher import bp as teacher_bp
    from app.blueprints.student import bp as student_bp
    from app.blueprints.parent import bp as parent_bp
    from app.blueprints.enquiries import bp as enquiries_bp
    from app.blueprints.notices import notices_bp, notifications_bp
    from app.blueprints.library import bp as library_bp
    from app.blueprints.online import bp as online_bp
    from app.blueprints.website import public_bp as public_website_bp, admin_bp as website_admin_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    for bp in (public_website_bp, website_admin_bp, owner_bp, branches_bp, settings_bp, admissions_bp, students_bp, parents_bp, teachers_bp, staff_bp, academics_bp, batches_bp, timetable_bp, attendance_bp, leave_bp, exams_bp, homework_bp, materials_bp, id_cards_bp, certificates_bp, documents_bp, verify_bp, fees_bp, finance_bp, payroll_bp, branch_admin_bp, accountant_bp,
               teacher_bp, student_bp, parent_bp, enquiries_bp, notices_bp, notifications_bp, library_bp, online_bp):
        app.register_blueprint(bp)

    @app.route("/app")
    def home():
        from app.utils.helpers import dashboard_endpoint
        if current_user.is_authenticated:
            return redirect(url_for(dashboard_endpoint(current_user)))
        return redirect(url_for("auth.login"))

    @app.route("/media/<folder>/<path:filename>")
    def media(folder, filename):
        """Public images only (institute logo). Private uploads get permission-checked routes later."""
        if folder not in PUBLIC_MEDIA_FOLDERS:
            abort(404)
        return send_from_directory(os.path.join(app.config["UPLOAD_FOLDER"], folder), filename)

    @app.route("/sw.js")
    def service_worker():
        response = make_response(send_from_directory(
            os.path.join(app.static_folder, "pwa"), "sw.js", mimetype="application/javascript"
        ))
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response


def _register_hooks(app):
    @app.before_request
    def force_password_change():
        if (current_user.is_authenticated and current_user.must_change_password
                and request.endpoint not in (
                    "auth.change_password", "auth.logout", "static", "service_worker"
                )):
            return redirect(url_for("auth.change_password"))

    @app.context_processor
    def inject_globals():
        from app.models import Institute, Notification
        try:
            inst = Institute.query.first()
            if current_user.is_authenticated and current_user.has_permission("notifications.view"):
                unread_notification_count = Notification.query.filter_by(
                    user_id=current_user.id, read_at=None
                ).count()
                notification_cursor = (
                    db.session.query(db.func.max(Notification.id))
                    .filter_by(user_id=current_user.id).scalar() or 0
                )
            else:
                unread_notification_count = 0
                notification_cursor = 0
        except Exception:  # DB not ready (e.g. before migrations)
            db.session.rollback()
            inst = None
            unread_notification_count = 0
            notification_cursor = 0
        return {
            "institute_name": inst.name if inst else "EduManage",
            "institute_logo": inst.logo if inst else None,
            "unread_notification_count": unread_notification_count,
            "notification_cursor": notification_cursor,
            "vapid_public_key": app.config["VAPID_PUBLIC_KEY"],
        }

    @app.template_filter("localtime")
    def localtime(value, fmt="%d %b %Y, %I:%M %p"):
        if not value:
            return "—"
        offset = timedelta(minutes=app.config["DISPLAY_UTC_OFFSET_MINUTES"])
        return (value + offset).strftime(fmt)

    @app.template_filter("inr")
    def inr(value):
        """12345.5 -> ₹12,345.50 (Indian digit grouping; whole rupees show no decimals)."""
        from decimal import Decimal
        d = Decimal(value or 0).quantize(Decimal("0.01"))
        sign, d = ("-", -d) if d < 0 else ("", d)
        whole, frac = f"{d:.2f}".split(".")
        head, tail = whole[:-3], whole[-3:]
        if head:
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:])
                head = head[:-2]
            if head:
                parts.insert(0, head)
            whole = ",".join(parts) + "," + tail
        return f"{sign}₹{whole}" + ("" if frac == "00" else "." + frac)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp


def _register_errors(app):
    for code in (403, 404, 500):
        app.register_error_handler(code, lambda e, c=code: (render_template(f"errors/{c}.html"), c))


def _register_cli(app):
    import click

    @app.cli.command("seed")
    def seed():
        """Create roles, permissions, institute, main branch and the Owner account."""
        from app.services.seed_service import seed_all
        for line in seed_all() or ["nothing to do - already seeded"]:
            click.echo(f"  + {line}")
        click.echo("Seed complete.")

    @app.cli.command("generate-dues")
    def generate_dues_cmd():
        """Create fee dues for active batch enrollments that have none yet."""
        from app.services.fee_service import generate_missing_dues
        click.echo(f"{generate_missing_dues()} fee due(s) created.")

    @app.cli.command("sync-permissions")
    def sync_permissions():
        """Re-apply default permissions to all roles (run after updating the app)."""
        from app.services.seed_service import sync_role_permissions
        click.echo("Updated roles: " + ", ".join(sync_role_permissions()))

    @app.cli.command("reset-password")
    @click.argument("username")
    @click.option("--force-change", is_flag=True, help="Ask the user to change it at next login.")
    def reset_password(username, force_change):
        """Set a new password for any user (also unlocks the account)."""
        from app.services.auth_service import find_user
        from app.utils.validators import validate_password_strength
        user = find_user(username)
        if not user:
            raise click.ClickException(f"No user found with username/email '{username}'.")
        pw = click.prompt("New password", hide_input=True, confirmation_prompt=True)
        problems = validate_password_strength(pw)
        if problems:
            raise click.ClickException("Password needs " + ", ".join(problems) + ".")
        user.set_password(pw)
        user.must_change_password = force_change
        user.failed_attempts = 0
        user.locked_until = None
        db.session.commit()
        click.echo(f"Password updated for {user.username}.")

    @app.cli.command("init-db")
    def init_db():
        """Quick table creation (use `flask db upgrade` for real migrations)."""
        db.create_all()
        click.echo("Tables created.")

    @app.cli.command("generate-vapid-keys")
    def generate_vapid_keys():
        """Print a VAPID key pair for browser push notifications."""
        import base64
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid

        vapid = Vapid()
        vapid.generate_keys()
        public_key = vapid.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        private_key = vapid.private_pem().decode().strip().replace("\n", "\\n")
        click.echo("Add these values to .env and keep the private key secret:")
        click.echo(f"VAPID_PUBLIC_KEY={base64.urlsafe_b64encode(public_key).decode().rstrip('=')}")
        click.echo(f"VAPID_PRIVATE_KEY={private_key}")


# Allow WSGI servers (like Gunicorn 'gunicorn app:app') to load the Flask application directly
def __getattr__(name):
    if name == "app":
        global _application
        try:
            return _application
        except NameError:
            _application = create_app()
            return _application
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

