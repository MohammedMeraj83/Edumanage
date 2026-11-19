import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _mysql_uri():
    user = os.getenv("DB_USER", "root")
    pwd = quote_plus(os.getenv("DB_PASSWORD", ""))
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    name = os.getenv("DB_NAME", "edumanage")
    return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{name}?charset=utf8mb4"


def _get_database_uri():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        return db_url
    if os.getenv("DB_HOST") or os.getenv("DB_NAME") or os.getenv("DB_USER"):
        return _mysql_uri()
    instance_dir = os.path.join(BASE_DIR, "instance")
    os.makedirs(instance_dir, exist_ok=True)
    return f"sqlite:///{os.path.join(instance_dir, 'edumanage.db')}"


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    GENERATED_FOLDER = os.path.join(BASE_DIR, "generated")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Address printed inside the QR codes of ID cards and certificates (e.g. https://school.example.com).
    # Leave empty to use the address the admin is browsing from.
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
    VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 hours

    # Login security
    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 15
    RATELIMIT_STORAGE_URI = "memory://"

    # Attendance rules (minutes / metres). Change here if the institute's policy changes.
    ATTENDANCE_RULES = {
        "teacher_checkin_opens_min": 15,   # teacher can start the lecture this long before it begins
        "ontime_grace_min": 5,             # arriving up to this long after start still counts on time
        "student_checkin_opens_min": 10,   # students can check in this long before the lecture
        "edit_window_min": 60,             # teacher may change attendance until this long after the lecture ends
        "max_accuracy_m": 100,             # reject GPS readings less accurate than this
        "default_radius_m": 100,           # allowed distance from the branch point
    }

    # Shown times are UTC + this offset (330 = India, IST)
    DISPLAY_UTC_OFFSET_MINUTES = int(os.getenv("DISPLAY_UTC_OFFSET_MINUTES", "330"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SECRET_KEY = "test"


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
