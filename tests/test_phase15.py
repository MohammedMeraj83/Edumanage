from app.models import (Institute, WebsitePage, WebsiteSetting, User, Permission)
from conftest import login, make_user


def test_public_mobile_website_and_enquiry_link(client):
    inst = Institute.query.first()
    inst.name = "Mobile Tuition"
    inst.tagline = "Best learning for every student"
    from extensions import db
    db.session.commit()

    page = client.get("/")
    assert page.status_code == 200
    assert b"Mobile Tuition" in page.data
    assert b"Admission enquiry" in page.data
    assert b"Explore courses" in page.data
    assert client.get("/courses").status_code == 200
    assert client.get("/branches").status_code == 200
    assert client.get("/about").status_code == 200


def test_owner_grants_website_admin_to_branch_admin(client):
    make_user("owner", "boss")
    branch_admin = make_user("branch_admin", "webadmin")
    login(client, "boss")

    denied = client.application.test_client()
    login(denied, "webadmin")
    assert denied.get("/website-admin/").status_code == 403

    response = client.post("/website-admin/permission", data={
        "user_id": str(branch_admin.id), "grant": "1"
    })
    assert response.status_code == 302

    assert denied.get("/website-admin/").status_code == 200


def test_only_owner_can_grant_website_permission(client):
    make_user("branch_admin", "manager")
    login(client, "manager")
    assert client.post("/website-admin/permission", data={
        "user_id": "1", "grant": "1"
    }).status_code == 403


def test_website_admin_saves_settings_and_custom_page(client):
    make_user("owner", "boss")
    login(client, "boss")

    response = client.post("/website-admin/settings", data={
        "hero_title": "Welcome to our institute",
        "hero_subtitle": "Learn on mobile or computer",
        "cta_title": "Join now",
        "cta_text": "Send an admission enquiry",
    })
    assert response.status_code == 302
    assert WebsiteSetting.query.count() == 4

    response = client.post("/website-admin/pages", data={
        "slug": "achievements", "title": "Our achievements",
        "subtitle": "Proud of our students", "content": "Students achieved excellent results.",
        "published": "on"
    })
    assert response.status_code == 302
    page = WebsitePage.query.filter_by(slug="achievements").one()
    assert page.is_published is True
    public = client.get("/")
    assert b"Welcome to our institute" in public.data
