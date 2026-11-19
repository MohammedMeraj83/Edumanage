import io
from datetime import date, timedelta
from flask import (Blueprint, render_template, redirect, url_for, flash, request, abort, Response)
from flask_login import current_user, login_required
from extensions import db
from app.models import LectureSession, BranchGeo, Branch, Student, ATTENDANCE_STATUSES
from app.services import attendance_service as svc
from app.services import academic_service
from app.services.audit_service import log_action
from app.utils.branch_access import ensure_branch_access
from app.utils.date_utils import local_now
from app.utils.decorators import role_required

bp = Blueprint("attendance", __name__, url_prefix="/attendance")

ADMIN_ROLES = ("owner", "branch_admin")


def _branch_scope():
    """Branch id the admin is working on. Owner: ?branch=ID (None = all)."""
    return request.args.get("branch", type=int) if current_user.is_owner else current_user.branch_id


def _me_teacher():
    return academic_service.teacher_for_user(current_user)


def _session(session_id):
    s = db.get_or_404(LectureSession, session_id)
    ensure_branch_access(s.branch_id)
    if current_user.role_name == "teacher":
        me = _me_teacher()
        if not me or me.id != s.teacher_id:
            abort(403)
    elif current_user.role_name not in ADMIN_ROLES:
        abort(403)
    return s


def _pos():
    return request.form.get("lat"), request.form.get("lng"), request.form.get("accuracy")


# ------------------------------------------------------------------ live board (admin / owner)
@bp.route("/live")
@role_required(*ADMIN_ROLES)
def live():
    branch_id = _branch_scope()
    today = local_now().date()
    sessions = svc.ensure_sessions(today, branch_id=branch_id)
    rows, tally = [], {}
    for s in sessions:
        key, label, css = svc.session_state(s)
        tally[key] = tally.get(key, 0) + 1
        recs = s.records
        rows.append({"s": s, "key": key, "label": label, "css": css, "late": svc.late_minutes(s),
                     "present": sum(1 for r in recs if r.status in ("present", "late")),
                     "absent": sum(1 for r in recs if r.status == "absent"),
                     "verified": sum(1 for r in recs if r.verified)})
    order = {"late": 0, "waiting": 1, "running": 2, "upcoming": 3, "missed": 4, "completed": 5}
    rows.sort(key=lambda r: (order.get(r["key"], 9), r["s"].start_at))
    return render_template("attendance/live.html", rows=rows, tally=tally, total=len(rows), today=today,
                           branch_id=branch_id,
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])


# ------------------------------------------------------------------ teacher: my lectures
@bp.route("/my")
@role_required("teacher")
def my():
    me = _me_teacher()
    if not me:
        flash("Your teacher profile is not linked yet. Ask your branch admin.", "warning")
        return redirect(url_for("teacher.dashboard"))
    today = local_now().date()
    todays = svc.ensure_sessions(today, branch_id=me.branch_id, teacher_id=me.id)
    since = today - timedelta(days=14)
    past = (LectureSession.query.filter(LectureSession.teacher_id == me.id, LectureSession.lecture_date < today,
                                        LectureSession.lecture_date >= since)
            .order_by(LectureSession.start_at.desc()).all())
    decorate = lambda items: [(s, *svc.session_state(s), svc.late_minutes(s)) for s in items]
    return render_template("attendance/my.html", today_rows=decorate(todays), past_rows=decorate(past), today=today)


# ------------------------------------------------------------------ one lecture
@bp.route("/session/<int:session_id>")
@login_required
def session_view(session_id):
    s = _session(session_id)
    me = _me_teacher() if current_user.role_name == "teacher" else None
    try:
        mode, block_reason = svc.marking_allowed(s, current_user, me), None
    except (PermissionError, ValueError) as e:
        mode, block_reason = None, str(e)
    key, label, css = svc.session_state(s)
    rows = svc.roster(s)
    return render_template("attendance/session.html", s=s, state=(key, label, css), late=svc.late_minutes(s),
                           rows=rows, mode=mode, block_reason=block_reason, statuses=ATTENDANCE_STATUSES,
                           can_checkin=(current_user.role_name == "teacher" and svc.teacher_checkin_open(s)),
                           opens=svc.checkin_window(s)[0], rules=svc.rule)


@bp.route("/session/<int:session_id>/checkin", methods=["POST"])
@role_required("teacher")
def checkin(session_id):
    s = _session(session_id)
    try:
        svc.teacher_checkin(s, _me_teacher(), *_pos())
        late = svc.late_minutes(s)
        flash("Lecture started. You are marked on time." if not late else f"Lecture started. You are {late} minutes late.",
              "success" if not late else "warning")
    except (ValueError, PermissionError) as e:
        flash(str(e), "danger")
    return redirect(url_for("attendance.session_view", session_id=s.id))


@bp.route("/session/<int:session_id>/end", methods=["POST"])
@role_required("teacher")
def end(session_id):
    s = _session(session_id)
    try:
        svc.end_class(s, _me_teacher())
        flash("Lecture ended.", "success")
    except (ValueError, PermissionError) as e:
        flash(str(e), "danger")
    return redirect(url_for("attendance.session_view", session_id=s.id))


@bp.route("/session/<int:session_id>/mark", methods=["POST"])
@role_required("teacher", *ADMIN_ROLES)
def mark(session_id):
    s = _session(session_id)
    statuses = {}
    for key, value in request.form.items():
        if key.startswith("status_") and key[7:].isdigit():
            statuses[int(key[7:])] = value
    try:
        svc.mark_attendance(s, statuses, current_user, _me_teacher() if current_user.role_name == "teacher" else None,
                            *_pos())
        flash("Attendance saved.", "success")
    except (ValueError, PermissionError) as e:
        flash(str(e), "danger")
    return redirect(url_for("attendance.session_view", session_id=s.id))


@bp.route("/session/<int:session_id>/cancel", methods=["POST"])
@role_required(*ADMIN_ROLES)
def cancel_session(session_id):
    s = _session(session_id)
    s.cancelled = not s.cancelled
    s.note = (request.form.get("note") or "").strip()[:200] or None
    log_action("lecture_cancel" if s.cancelled else "lecture_restore", "lecture_sessions", s.id, s.batch.name)
    db.session.commit()
    flash("Lecture cancelled." if s.cancelled else "Lecture restored.", "success")
    return redirect(url_for("attendance.session_view", session_id=s.id))


# ------------------------------------------------------------------ student check-in
@bp.route("/session/<int:session_id>/self-checkin", methods=["POST"])
@role_required("student")
def self_checkin(session_id):
    s = db.get_or_404(LectureSession, session_id)
    me = Student.query.filter_by(user_id=current_user.id).first()
    try:
        if not me:
            raise PermissionError("Your student profile is not linked.")
        svc.student_self_checkin(s, me, *_pos())
        flash("You are checked in. Your location was verified.", "success")
    except (ValueError, PermissionError) as e:
        flash(str(e), "danger")
    return redirect(request.form.get("next") or url_for("student.dashboard"))


# ------------------------------------------------------------------ QR scan landing page
@bp.route("/scan/<token>")
@login_required
def scan(token):
    geo = BranchGeo.query.filter_by(qr_token=token).first_or_404()
    today = local_now().date()
    items = []
    if current_user.role_name == "teacher":
        me = _me_teacher()
        if me and me.branch_id == geo.branch_id:
            items = [(s, *svc.session_state(s)) for s in
                     svc.ensure_sessions(today, branch_id=geo.branch_id, teacher_id=me.id)]
    elif current_user.role_name == "student":
        me = Student.query.filter_by(user_id=current_user.id).first()
        if me and me.branch_id == geo.branch_id:
            items = [(s, *svc.session_state(s)) for s, _ in svc.todays_status_for(me, today)]
    else:
        flash("Only teachers and students use this QR.", "warning")
    return render_template("attendance/scan.html", geo=geo, items=items, now_open=svc.teacher_checkin_open,
                           student_open=svc.student_checkin_open)


# ------------------------------------------------------------------ branch location + QR (admin / owner)
def _geo_branch():
    bid = _branch_scope()
    if current_user.is_owner and not bid:
        return None
    return db.get_or_404(Branch, bid)


@bp.route("/location", methods=["GET", "POST"])
@role_required(*ADMIN_ROLES)
def location():
    branch = _geo_branch()
    if branch is None:
        return render_template("attendance/choose_branch.html", branches=Branch.query.order_by(Branch.name).all())
    geo = BranchGeo.query.filter_by(branch_id=branch.id).first()
    if request.method == "POST":
        try:
            svc.save_branch_geo(branch.id, request.form.get("lat"), request.form.get("lng"),
                                request.form.get("radius") or 100, current_user)
            flash("Branch location saved. Teachers and students must now be inside this area.", "success")
            return redirect(url_for("attendance.location", branch=branch.id))
        except (ValueError, TypeError) as e:
            flash(str(e) or "Check the values.", "danger")
    return render_template("attendance/location.html", branch=branch, geo=geo, default_radius=svc.rule("default_radius_m"))


@bp.route("/qr")
@role_required(*ADMIN_ROLES)
def qr_page():
    branch = _geo_branch()
    if branch is None:
        return render_template("attendance/choose_branch.html", branches=Branch.query.order_by(Branch.name).all())
    geo = BranchGeo.query.filter_by(branch_id=branch.id).first()
    link = url_for("attendance.scan", token=geo.qr_token, _external=True) if geo else None
    return render_template("attendance/qr.html", branch=branch, geo=geo, link=link)


@bp.route("/qr.png")
@role_required(*ADMIN_ROLES)
def qr_png():
    import qrcode
    branch = _geo_branch()
    if branch is None:
        abort(404)
    geo = BranchGeo.query.filter_by(branch_id=branch.id).first_or_404()
    img = qrcode.make(url_for("attendance.scan", token=geo.qr_token, _external=True), box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "no-store"})


@bp.route("/qr/regenerate", methods=["POST"])
@role_required(*ADMIN_ROLES)
def qr_regenerate():
    branch = _geo_branch()
    geo = BranchGeo.query.filter_by(branch_id=branch.id).first_or_404() if branch else abort(404)
    svc.regenerate_qr(geo, current_user)
    flash("A new QR code was created. The old printed QR no longer works - print the new one.", "success")
    return redirect(url_for("attendance.qr_page", branch=branch.id))


# ------------------------------------------------------------------ reports
@bp.route("/reports")
@role_required(*ADMIN_ROLES)
def reports():
    branch_id = _branch_scope()
    today = local_now().date()
    try:
        end = date.fromisoformat(request.args.get("to", "")) if request.args.get("to") else today
        start = date.fromisoformat(request.args.get("from", "")) if request.args.get("from") else end - timedelta(days=6)
    except ValueError:
        start, end = today - timedelta(days=6), today
    if end < start or (end - start).days > 92:
        start, end = end - timedelta(days=6), end
    return render_template("attendance/reports.html", start=start, end=end, branch_id=branch_id,
                           teachers=svc.teacher_report(start, end, branch_id),
                           batches=svc.batch_report(start, end, branch_id),
                           branches=Branch.query.order_by(Branch.name).all() if current_user.is_owner else [])
