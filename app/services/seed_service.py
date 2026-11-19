import os
from datetime import date
from extensions import db
from app.models import (Role, Permission, Institute, Branch, User, AcademicSession, ALL_ROLES)
from app.utils.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, ROLE_DISPLAY


def seed_all():
    summary = []

    # permissions
    existing = {p.code for p in Permission.query.all()}
    for code in ALL_PERMISSIONS:
        if code not in existing:
            module, action = code.split(".")
            db.session.add(Permission(code=code, module=module, description=f"{action.title()} {module.replace('_', ' ')}"))
    db.session.flush()
    perm_map = {p.code: p for p in Permission.query.all()}

    # roles
    for name in ALL_ROLES:
        role = Role.query.filter_by(name=name).first()
        if not role:
            role = Role(name=name, display_name=ROLE_DISPLAY[name], is_super=(name == "owner"))
            db.session.add(role)
            summary.append(f"role: {name}")
        codes = DEFAULT_ROLE_PERMISSIONS.get(name)
        if codes is not None and not role.permissions:
            role.permissions = [perm_map[c] for c in dict.fromkeys(codes) if c in perm_map]
    db.session.flush()

    # institute (single)
    inst = Institute.query.first()
    if not inst:
        inst = Institute(name=os.getenv("INSTITUTE_NAME", "My Tuition Institute"))
        db.session.add(inst)
        db.session.flush()
        summary.append("institute created")

    # main branch
    branch = Branch.query.filter_by(is_main=True).first()
    if not branch:
        branch = Branch(
            institute_id=inst.id,
            code=os.getenv("MAIN_BRANCH_CODE", "MAIN").upper(),
            name=os.getenv("MAIN_BRANCH_NAME", "Main Branch"),
            is_main=True,
        )
        db.session.add(branch)
        summary.append("main branch created")

    # academic session
    if not AcademicSession.query.first():
        y = date.today().year
        start_year = y if date.today().month >= 4 else y - 1
        db.session.add(AcademicSession(
            name=f"{start_year}-{str(start_year + 1)[-2:]}",
            start_date=date(start_year, 4, 1), end_date=date(start_year + 1, 3, 31),
            is_current=True,
        ))
        summary.append("academic session created")

    # owner user
    owner_role = Role.query.filter_by(name="owner").first()
    if not User.query.filter_by(role_id=owner_role.id).first():
        owner = User(
            username=os.getenv("OWNER_USERNAME", "owner"),
            email=os.getenv("OWNER_EMAIL", "owner@example.com").lower(),
            full_name=os.getenv("OWNER_NAME", "Institute Owner"),
            role_id=owner_role.id,
        )
        owner.set_password(os.getenv("OWNER_PASSWORD", "ChangeMe@123"))
        owner.must_change_password = True
        db.session.add(owner)
        summary.append(f"owner user created: {owner.username}")

    db.session.commit()
    return summary


def sync_role_permissions():
    """Re-apply the default permission set to every non-owner role (after new modules / rule changes)."""
    from app.models import Role, Permission
    from app.utils.permissions import DEFAULT_ROLE_PERMISSIONS, ALL_PERMISSIONS, ROLE_DISPLAY
    existing = {p.code for p in Permission.query.all()}
    for code in ALL_PERMISSIONS:
        if code not in existing:
            module, action = code.split(".")
            db.session.add(Permission(code=code, module=module, description=f"{action.title()} {module.replace('_', ' ')}"))
    db.session.flush()
    perm_map = {p.code: p for p in Permission.query.all()}
    changed = []
    for role in Role.query.all():
        codes = DEFAULT_ROLE_PERMISSIONS.get(role.name)
        if codes is None:
            continue
        role.permissions = [perm_map[c] for c in dict.fromkeys(codes) if c in perm_map]
        changed.append(role.name)
    db.session.commit()
    return changed
