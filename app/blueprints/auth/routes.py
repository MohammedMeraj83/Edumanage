from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, limiter
from app.services.auth_service import authenticate
from app.services.audit_service import log_action
from app.utils.helpers import is_safe_redirect, dashboard_endpoint
from app.utils.validators import validate_password_strength
from .forms import LoginForm, ChangePasswordForm

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint(current_user)))

    form = LoginForm()
    if form.validate_on_submit():
        user, error = authenticate(form.identifier.data, form.password.data)
        if error:
            flash(error, "danger")
        else:
            login_user(user, remember=form.remember.data)
            if user.must_change_password:
                flash("Please set a new password before continuing.", "warning")
                return redirect(url_for("auth.change_password"))
            nxt = request.args.get("next")
            return redirect(nxt if is_safe_redirect(nxt) else url_for(dashboard_endpoint(user)))
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_action("logout", "users", current_user.id)
    db.session.commit()
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
        else:
            problems = validate_password_strength(form.new_password.data)
            if problems:
                flash("New password needs " + ", ".join(problems) + ".", "danger")
            elif form.new_password.data == form.current_password.data:
                flash("New password must be different from the current one.", "danger")
            else:
                current_user.set_password(form.new_password.data)
                current_user.must_change_password = False
                log_action("password_change", "users", current_user.id)
                db.session.commit()
                flash("Password updated.", "success")
                return redirect(url_for(dashboard_endpoint(current_user)))
    return render_template("auth/change_password.html", form=form)
