from flask import Blueprint, redirect, url_for
from app.utils.decorators import role_required

bp = Blueprint("accountant", __name__, url_prefix="/accountant")


@bp.route("/dashboard")
@role_required("accountant")
def dashboard():
    return redirect(url_for("fees.index"))
