from flask import Blueprint, render_template, redirect, url_for, flash
from extensions import db
from app.models import Institute, AcademicSession
from app.services.audit_service import log_action
from app.utils.decorators import permission_required
from app.utils.file_upload import save_image, delete_upload
from .forms import InstituteForm, SessionForm

bp = Blueprint("settings", __name__, url_prefix="/owner")

INSTITUTE_FIELDS = ["name", "tagline", "registration_no", "phone", "email", "website", "address"]


@bp.route("/institute", methods=["GET", "POST"])
@permission_required("institute.edit")
def institute():
    inst = Institute.query.first()
    form = InstituteForm(obj=inst)
    if form.validate_on_submit():
        new_logo = None
        upload = form.logo.data
        if upload is not None and getattr(upload, "filename", ""):
            try:
                new_logo = save_image(upload, "institute")
            except ValueError as e:
                form.logo.errors.append(str(e))
        if not form.logo.errors:
            for k in INSTITUTE_FIELDS:
                setattr(inst, k, (getattr(form, k).data or None))
            inst.name = form.name.data.strip()
            if new_logo:
                delete_upload("institute", inst.logo)
                inst.logo = new_logo
            elif form.remove_logo.data and inst.logo:
                delete_upload("institute", inst.logo)
                inst.logo = None
            log_action("update", "institutes", inst.id, "Updated institute profile")
            db.session.commit()
            flash("Institute profile saved.", "success")
            return redirect(url_for("settings.institute"))
    return render_template("settings/institute.html", form=form, inst=inst)


@bp.route("/sessions")
@permission_required("sessions.view")
def sessions():
    items = AcademicSession.query.order_by(AcademicSession.start_date.desc()).all()
    return render_template("settings/sessions.html", sessions=items)


@bp.route("/sessions/new", methods=["GET", "POST"])
@permission_required("sessions.create")
def session_new():
    form = SessionForm()
    if form.validate_on_submit():
        s = AcademicSession(name=form.name.data.strip(), start_date=form.start_date.data,
                            end_date=form.end_date.data, is_current=False)
        db.session.add(s)
        db.session.flush()
        if form.is_current.data or AcademicSession.query.filter_by(is_current=True).count() == 0:
            _make_current(s)
        log_action("create", "academic_sessions", s.id, s.name)
        db.session.commit()
        flash(f"Session {s.name} created.", "success")
        return redirect(url_for("settings.sessions"))
    return render_template("settings/session_form.html", form=form, item=None)


@bp.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
@permission_required("sessions.edit")
def session_edit(session_id):
    s = db.get_or_404(AcademicSession, session_id)
    form = SessionForm(obj=s, session_id=s.id)
    if form.validate_on_submit():
        s.name = form.name.data.strip()
        s.start_date, s.end_date = form.start_date.data, form.end_date.data
        if form.is_current.data and not s.is_current:
            _make_current(s)
        log_action("update", "academic_sessions", s.id, s.name)
        db.session.commit()
        flash("Session saved.", "success")
        return redirect(url_for("settings.sessions"))
    return render_template("settings/session_form.html", form=form, item=s)


@bp.route("/sessions/<int:session_id>/set-current", methods=["POST"])
@permission_required("sessions.edit")
def session_set_current(session_id):
    s = db.get_or_404(AcademicSession, session_id)
    _make_current(s)
    log_action("set_current", "academic_sessions", s.id, s.name)
    db.session.commit()
    flash(f"{s.name} is now the current session. Older sessions and their records stay available.", "success")
    return redirect(url_for("settings.sessions"))


def _make_current(session):
    AcademicSession.query.filter(AcademicSession.id != session.id).update({"is_current": False})
    session.is_current = True
