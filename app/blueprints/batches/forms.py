from datetime import date
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, IntegerField, DecimalField, DateField, TimeField
from wtforms.validators import DataRequired, InputRequired, Length, Optional, NumberRange, ValidationError
from app.models import FEE_FREQUENCIES
from app.utils.date_utils import WEEKDAYS


class BatchForm(FlaskForm):
    name = StringField("Batch name", validators=[Optional(), Length(max=150)])
    course_id = SelectField("Course", coerce=int, validators=[DataRequired()])
    subject_id = SelectField("Subject", coerce=int, validators=[DataRequired()])
    teacher_id = SelectField("Teacher", coerce=int, validators=[DataRequired()])
    room_id = SelectField("Default room", coerce=int, validators=[Optional()])
    capacity = IntegerField("Seats", validators=[DataRequired(), NumberRange(min=1, max=500)], default=30)
    fee_amount = DecimalField("Fee (₹)", places=2, validators=[InputRequired(), NumberRange(min=0, max=10000000)],
                              default=0)
    fee_frequency = SelectField("Fee is", choices=FEE_FREQUENCIES, validators=[DataRequired()])
    start_date = DateField("Starts on", validators=[Optional()], default=date.today)
    end_date = DateField("Ends on", validators=[Optional()])

    def validate_end_date(self, field):
        if field.data and self.start_date.data and field.data < self.start_date.data:
            raise ValidationError("End date cannot be before the start date.")


class SlotForm(FlaskForm):
    weekday = SelectField("Day", coerce=int, choices=list(enumerate(WEEKDAYS)))
    start_time = TimeField("Starts", validators=[DataRequired()])
    end_time = TimeField("Ends", validators=[DataRequired()])
    room_id = SelectField("Room", coerce=int, validators=[Optional()])
    teacher_id = SelectField("Teacher", coerce=int, validators=[Optional()])
