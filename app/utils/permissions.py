"""Permission catalogue + default role mapping.

Permission code format:  <module>.<action>   e.g. students.view
`flask seed` loads these into the DB; Owner is a super-role (all permissions).
"""
ACTIONS = ["view", "create", "edit", "delete"]

MODULES = [
    "institute", "branches", "sessions", "students", "admissions", "teachers", "staff",
    "parents", "courses", "subjects", "classes", "batches", "timetable", "attendance",
    "fees", "payments", "expenses", "salary", "exams", "results", "homework",
    "materials", "enquiries", "id_cards", "certificates", "documents", "library",
    "transport", "inventory", "online_exams", "online_classes", "notices",
    "notifications", "reports", "website", "users", "backups", "audit_logs", "settings",
]

ALL_PERMISSIONS = [f"{m}.{a}" for m in MODULES for a in ACTIONS]

_OWNER_ONLY_MODULES = {"institute", "branches", "sessions", "users", "backups", "audit_logs", "settings", "website"}
_FINANCE_MODULES = ["fees", "payments", "expenses", "salary", "reports"]
_TEACHING_MODULES = ["attendance", "homework", "materials"]


def _all(modules, actions=ACTIONS):
    return [f"{m}.{a}" for m in modules for a in actions]


DEFAULT_ROLE_PERMISSIONS = {
    "owner": None,  # super role, handled via Role.is_super
    "branch_admin": [
        p for p in ALL_PERMISSIONS if p.split(".")[0] not in _OWNER_ONLY_MODULES
    ] + ["users.view"],
    "accountant": _all(_FINANCE_MODULES) + [
        "students.view", "admissions.view", "notices.view", "notifications.view",
    ],
    "teacher": _all(_TEACHING_MODULES) + [
        # exams: teachers see exams of their own batches and enter / submit marks (no create, edit or delete of exams)
        "exams.view", "online_exams.view", "online_exams.create", "online_exams.edit", "online_exams.delete",
        "online_classes.view", "online_classes.create", "online_classes.edit", "online_classes.delete",
        "results.view", "results.create", "results.edit",
        "students.view", "batches.view", "timetable.view", "notices.view", "notifications.view",
        "documents.view", "library.view"],
    "student": ["notices.view", "homework.view", "materials.view", "library.view", "results.view",
                "online_classes.view", "online_exams.view",
                "notifications.view", "attendance.view", "timetable.view"],
    "parent": ["notices.view", "notifications.view", "homework.view", "library.view", "online_classes.view", "online_exams.view", "results.view", "attendance.view"],
}

ROLE_DISPLAY = {
    "owner": "Owner / Main Admin",
    "branch_admin": "Branch Admin",
    "accountant": "Accountant",
    "teacher": "Teacher",
    "student": "Student",
    "parent": "Parent",
}
