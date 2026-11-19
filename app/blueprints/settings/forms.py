from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, TextAreaField, BooleanField, DateField
from wtforms.validators import DataRequired, Length, Optional, Regexp, Email, URL, ValidationError
from sqlalchemy import func
from app.models import AcademicSession

PHONE_RE = r"^[0-9+\-\s()]{7,20}$"


class InstituteForm(FlaskForm):
    name = StringField("Institute name", validators=[DataRequired(), Length(max=150)])
    tagline = StringField("Tagline", validators=[Optional(), Length(max=200)])
    registration_no = StringField("Registration number", validators=[Optional(), Length(max=80)])
    phone = StringField("Phone", validators=[Optional(), Regexp(PHONE_RE, message="Enter a valid phone number.")])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=120)])
    website = StringField("Website", validators=[Optional(), URL(), Length(max=200)])
    address = TextAreaField("Address", validators=[Optional(), Length(max=500)])
    logo = FileField("Logo")
    remove_logo = BooleanField("Remove current logo")


class SessionForm(FlaskForm):
    name = StringField("Session name", validators=[DataRequired(), Length(max=30)])
    start_date = DateField("Starts on", validators=[DataRequired()])
    end_date = DateField("Ends on", validators=[DataRequired()])
    is_current = BooleanField("Make this the current session")

    def __init__(self, *args, session_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_id = session_id

    def validate_name(self, field):
        q = AcademicSession.query.filter(func.lower(AcademicSession.name) == field.data.strip().lower())
        if self._session_id:
            q = q.filter(AcademicSession.id != self._session_id)
        if q.first():
            raise ValidationError("A session with this name already exists.")

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data <= self.start_date.data:
            raise ValidationError("End date must be after the start date.")
