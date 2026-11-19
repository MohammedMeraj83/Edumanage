from wtforms import SelectField, BooleanField
from wtforms.validators import DataRequired
from app.blueprints.students.forms import PersonForm


class AdmissionForm(PersonForm):
    branch_id = SelectField("Branch", coerce=int, validators=[DataRequired()])
    session_id = SelectField("Academic session", coerce=int, validators=[DataRequired()])
    approve_now = BooleanField("Approve immediately (walk-in admission)")
