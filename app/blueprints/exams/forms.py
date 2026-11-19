from datetime import date
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, DateField
from wtforms.validators import DataRequired, Length, Optional, ValidationError
from app.models import EXAM_TYPES


class ExamForm(FlaskForm):
    name = StringField("Exam name", validators=[DataRequired(), Length(max=120)])
    exam_type = SelectField("Type", choices=EXAM_TYPES, validators=[DataRequired()])
    start_date = DateField("First day", validators=[DataRequired()], default=date.today)
    end_date = DateField("Last day", validators=[DataRequired()], default=date.today)
    note = StringField("Note (optional)", validators=[Optional(), Length(max=255)])

    def validate_end_date(self, field):
        if field.data and self.start_date.data and field.data < self.start_date.data:
            raise ValidationError("The last day cannot be before the first day.")
