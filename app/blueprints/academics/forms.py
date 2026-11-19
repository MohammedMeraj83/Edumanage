from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SelectField, IntegerField, SelectMultipleField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, ValidationError
from wtforms.widgets import ListWidget, CheckboxInput
from sqlalchemy import func
from app.models import Course, Subject, Room


class _Unique:
    """Mixin: name must be unique (case-insensitive) inside `model` (and `scope`)."""
    model = None

    def _check_name(self, field, extra=()):
        q = self.model.query.filter(func.lower(self.model.name) == field.data.strip().lower(), *extra)
        if getattr(self, "_obj_id", None):
            q = q.filter(self.model.id != self._obj_id)
        if q.first():
            raise ValidationError("This name is already used.")


class SubjectForm(FlaskForm, _Unique):
    model = Subject
    name = StringField("Subject name", validators=[DataRequired(), Length(max=80)])
    is_active = BooleanField("Active", default=True)

    def __init__(self, *a, obj_id=None, **kw):
        super().__init__(*a, **kw)
        self._obj_id = obj_id

    def validate_name(self, field):
        self._check_name(field)


class CourseForm(FlaskForm, _Unique):
    model = Course
    name = StringField("Course name", validators=[DataRequired(), Length(max=100)])
    description = StringField("Description", validators=[Optional(), Length(max=255)])
    subjects = SelectMultipleField("Subjects in this course", coerce=int,
                                   widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())
    is_active = BooleanField("Active", default=True)

    def __init__(self, *a, obj_id=None, **kw):
        super().__init__(*a, **kw)
        self._obj_id = obj_id
        self.subjects.choices = [(s.id, s.name) for s in Subject.query.filter_by(is_active=True).order_by(Subject.name)]

    def validate_name(self, field):
        self._check_name(field)


class RoomForm(FlaskForm, _Unique):
    model = Room
    branch_id = SelectField("Branch", coerce=int, validators=[DataRequired()])
    name = StringField("Room name", validators=[DataRequired(), Length(max=60)])
    capacity = IntegerField("Seating capacity", validators=[Optional(), NumberRange(min=1, max=1000)])
    is_active = BooleanField("Active", default=True)

    def __init__(self, *a, obj_id=None, branch_id=None, **kw):
        super().__init__(*a, **kw)
        self._obj_id, self._branch_id = obj_id, branch_id

    def validate_name(self, field):
        bid = self.branch_id.data if self.branch_id else self._branch_id
        self._check_name(field, extra=(Room.branch_id == bid,))
