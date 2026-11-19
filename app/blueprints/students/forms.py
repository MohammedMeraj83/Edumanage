from datetime import date
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, TextAreaField, SelectField, DateField
from wtforms.validators import DataRequired, Length, Optional, Regexp, Email, ValidationError
from app.models import GENDERS, BLOOD_GROUPS

PHONE_RE = r"^[0-9+\-\s()]{7,20}$"
PHONE_MSG = "Enter a valid phone number."


class PersonForm(FlaskForm):
    """Fields shared by admission and student edit forms."""
    full_name = StringField("Student full name", validators=[DataRequired(), Length(max=120)])
    dob = DateField("Date of birth", validators=[DataRequired()])
    gender = SelectField("Gender", choices=[(g, g) for g in GENDERS], validators=[DataRequired()])
    blood_group = SelectField("Blood group", choices=[("", "Not known")] + [(b, b) for b in BLOOD_GROUPS],
                              validators=[Optional()])
    phone = StringField("Student phone", validators=[Optional(), Regexp(PHONE_RE, message=PHONE_MSG)])
    email = StringField("Student email", validators=[Optional(), Email(), Length(max=120)])
    class_name = StringField("Class / grade", validators=[DataRequired(), Length(max=40)])
    previous_school = StringField("Previous school", validators=[Optional(), Length(max=150)])
    address = TextAreaField("Address", validators=[Optional(), Length(max=500)])
    city = StringField("City", validators=[Optional(), Length(max=80)])
    state = StringField("State", validators=[Optional(), Length(max=80)])
    pincode = StringField("Pincode", validators=[Optional(), Regexp(r"^[0-9]{4,10}$", message="Digits only.")])

    father_name = StringField("Father's name", validators=[Optional(), Length(max=120)])
    mother_name = StringField("Mother's name", validators=[Optional(), Length(max=120)])
    guardian_phone = StringField("Parent / guardian phone", validators=[DataRequired(), Regexp(PHONE_RE, message=PHONE_MSG)])
    guardian_email = StringField("Parent / guardian email", validators=[Optional(), Email(), Length(max=120)])

    photo = FileField("Photo")
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=1000)])

    def validate_dob(self, field):
        today = date.today()
        if field.data > today:
            raise ValidationError("Date of birth cannot be in the future.")
        age = (today - field.data).days / 365.25
        if age < 2 or age > 60:
            raise ValidationError("Please check the date of birth.")
