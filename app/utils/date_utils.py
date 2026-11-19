from datetime import datetime, timedelta
from flask import current_app

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS_SHORT = [d[:3] for d in WEEKDAYS]


def local_now():
    """Current time shown to users (UTC + DISPLAY_UTC_OFFSET_MINUTES, India by default)."""
    return datetime.utcnow() + timedelta(minutes=current_app.config["DISPLAY_UTC_OFFSET_MINUTES"])


def fmt_time(t):
    return t.strftime("%I:%M %p").lstrip("0") if t else "—"


def _offset():
    return timedelta(minutes=current_app.config["DISPLAY_UTC_OFFSET_MINUTES"])


def local_to_utc(day, t):
    """Wall-clock lecture time (local) -> naive UTC datetime, which is what the database stores."""
    return datetime.combine(day, t) - _offset()


def utc_to_local(dt):
    return dt + _offset() if dt else None
