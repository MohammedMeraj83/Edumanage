from flask import Blueprint, render_template
from flask_login import current_user
from app.utils.decorators import role_required


def make_panel(role, url_prefix, title):
    """Create the placeholder dashboard blueprint of a role.
    Real module routes get added to these panels phase by phase."""
    bp = Blueprint(role, __name__, url_prefix=url_prefix)

    @bp.route("/dashboard")
    @role_required(role)
    def dashboard():
        return render_template("components/panel_dashboard.html", panel_title=title)

    return bp
