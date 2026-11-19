from urllib.parse import urlparse, urljoin
from flask import request


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""


def is_safe_redirect(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def dashboard_endpoint(user):
    """Each role has its own blueprint named after the role: '<role>.dashboard'."""
    return f"{user.role.name}.dashboard"


def generate_temp_password(length=10):
    """Readable temporary password that always passes the strength rules."""
    import secrets
    upper, lower, digits = "ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789"
    chars = [secrets.choice(upper), secrets.choice(lower), secrets.choice(digits)]
    chars += [secrets.choice(upper + lower + digits) for _ in range(length - 3)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
