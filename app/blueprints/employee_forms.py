from datetime import date
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, TextAreaField, SelectField, DateField, IntegerField, BooleanField
from wtforms.validators import DataRequired, Length, Optional, Regexp, Email, NumberRange, ValidationError
from app.models import GENDERS, STAFF_DESIGNATIONS

PHONE_RE = r"^[0-9+\-\s()]{7,20}$"


class EmployeeForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    gender = SelectField("Gender", choices=[(g, g) for g in GENDERS], validators=[DataRequired()])
    dob = DateField("Date of birth", validators=[Optional()])
    phone = StringField("Phone", validators=[DataRequired(), Regexp(PHONE_RE, message="Enter a valid phone number.")])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=120)])
    qualification = StringField("Qualification", validators=[Optional(), Length(max=150)])
    joining_date = DateField("Joining date", validators=[DataRequired()], default=date.today)
    address = TextAreaField("Address", validators=[Optional(), Length(max=500)])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=1000)])
    photo = FileField("Photo")
    branch_id = SelectField("Branch", coerce=int, validators=[DataRequired()])
    create_login = BooleanField("Create a sign-in account now")

    def validate_dob(self, field):
        if field.data:
            age = (date.today() - field.data).days / 365.25
            if age < 16 or age > 90:
                raise ValidationError("Please check the date of birth.")


class TeacherForm(EmployeeForm):
    specialization = StringField("Subjects / specialization", validators=[Optional(), Length(max=150)])
    experience_years = IntegerField("Experience (years)", validators=[Optional(), NumberRange(min=0, max=60)])


class StaffForm(EmployeeForm):
    designation = SelectField("Designation", choices=[(d, d) for d in STAFF_DESIGNATIONS], validators=[DataRequired()])
