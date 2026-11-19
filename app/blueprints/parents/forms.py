from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp, Email

PHONE_RE = r"^[0-9+\-\s()]{7,20}$"


class ParentForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Phone", validators=[DataRequired(), Regexp(PHONE_RE, message="Enter a valid phone number.")])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=120)])
    occupation = StringField("Occupation", validators=[Optional(), Length(max=100)])
    address = TextAreaField("Address", validators=[Optional(), Length(max=500)])
