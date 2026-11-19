from extensions import db


class TimetableSlot(db.Model):
    """A repeating weekly lecture of a batch. Phase 6 turns these into dated lecture sessions."""
    __tablename__ = "timetable_slots"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batches.id"), nullable=False, index=True)
    weekday = db.Column(db.Integer, nullable=False, index=True)        # 0 = Monday ... 6 = Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))         # empty = batch's default room
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"))   # empty = batch's teacher

    batch = db.relationship("Batch", back_populates="slots")
    room = db.relationship("Room", lazy="joined")
    teacher = db.relationship("Teacher", lazy="joined")

    @property
    def effective_teacher(self):
        return self.teacher or self.batch.teacher

    @property
    def effective_room(self):
        return self.room or self.batch.room

    @property
    def minutes(self):
        return (self.end_time.hour * 60 + self.end_time.minute) - (self.start_time.hour * 60 + self.start_time.minute)
