import re


def validate_password_strength(pw):
    """Return list of problems (empty list = OK)."""
    problems = []
    if len(pw) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Z]", pw):
        problems.append("one uppercase letter")
    if not re.search(r"[a-z]", pw):
        problems.append("one lowercase letter")
    if not re.search(r"\d", pw):
        problems.append("one number")
    return problems
