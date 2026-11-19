from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp, Email, ValidationError
from sqlalchemy import func
from app.models import Branch, User

PHONE_RE = r"^[0-9+\-\s()]{7,20}$"


class BranchForm(FlaskForm):
    name = StringField("Branch name", validators=[DataRequired(), Length(max=120)])
    code = StringField("Branch code", validators=[
        DataRequired(), Regexp(r"^[A-Za-z0-9]{2,10}$", message="Use 2-10 letters or numbers, no spaces.")])
    phone = StringField("Phone", validators=[Optional(), Regexp(PHONE_RE, message="Enter a valid phone number.")])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=120)])
    address = TextAreaField("Address", validators=[Optional(), Length(max=500)])
    city = StringField("City", validators=[Optional(), Length(max=80)])
    state = StringField("State", validators=[Optional(), Length(max=80)])
    pincode = StringField("Pincode", validators=[Optional(), Regexp(r"^[0-9]{4,10}$", message="Digits only.")])

    def validate_code(self, field):
        exists = Branch.query.filter(func.upper(Branch.code) == field.data.upper()).first()
        if exists:
            raise ValidationError("This branch code is already used.")


class BranchAdminForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    username = StringField("Username", validators=[
        DataRequired(), Regexp(r"^[A-Za-z0-9._]{3,30}$", message="3-30 letters, numbers, dots or underscores.")])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField("Phone", validators=[Optional(), Regexp(PHONE_RE, message="Enter a valid phone number.")])

    def validate_username(self, field):
        if User.query.filter(func.lower(User.username) == field.data.lower()).first():
            raise ValidationError("This username is taken.")

    def validate_email(self, field):
        if User.query.filter(func.lower(User.email) == field.data.lower()).first():
            raise ValidationError("This email is already registered.")
