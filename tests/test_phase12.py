from app.models import Branch, Enquiry, Notification, Notice, PushSubscription, User
from conftest import add_branch, login, make_user
from extensions import db


def test_public_enquiry_submission_is_saved_for_selected_branch(client):
    branch = add_branch("CITY1", "City Branch")
    response = client.post("/enquiries/public", data={
        "full_name": "Asha Patil",
        "phone": "9876543210",
        "email": "",
        "branch_id": str(branch.id),
        "course_interest": "Class 9",
        "message": "Please call after 5 pm.",
        "website": "",
    })
    assert response.status_code == 302
    assert response.location.endswith("/enquiries/thanks")
    enquiry = Enquiry.query.one()
    assert (enquiry.full_name, enquiry.branch_id, enquiry.source, enquiry.status) == (
        "Asha Patil", branch.id, "public", "new"
    )


def test_public_enquiry_form_and_invalid_branch(client):
    assert client.get("/enquiries/public").status_code == 200
    response = client.post("/enquiries/public", data={
        "full_name": "Asha Patil", "phone": "9876543210", "branch_id": "not-a-branch",
        "website": "",
    })
    assert response.status_code == 200 and b"valid branch" in response.data
    assert Enquiry.query.count() == 0


def test_staff_enquiry_and_notice_forms_render(client):
    make_user("owner", "boss")
    login(client, "boss")
    assert client.get("/enquiries/new").status_code == 200
    assert client.get("/notices/new").status_code == 200
    assert client.get("/notices/").status_code == 200


def test_public_enquiry_requires_contact_and_rejects_bad_phone(client):
    data = {"full_name": "Asha Patil", "phone": "", "email": "", "website": ""}
    response = client.post("/enquiries/public", data=data)
    assert response.status_code == 200 and b"at least one contact method" in response.data
    data.update(phone="123", email="")
    response = client.post("/enquiries/public", data=data)
    assert response.status_code == 200 and b"valid phone number" in response.data
    assert Enquiry.query.count() == 0


def test_honeypot_rejects_public_enquiry(client):
    response = client.post("/enquiries/public", data={
        "full_name": "Bot", "phone": "9876543210", "website": "filled"
    })
    assert response.status_code == 400
    assert Enquiry.query.count() == 0


def test_branch_admin_manages_only_branch_enquiries(client):
    city = add_branch("CITY1", "City Branch")
    main_admin = make_user("branch_admin", "mainadmin")
    city_admin = make_user("branch_admin", "cityadmin", branch_code="CITY1")
    db.session.add(Enquiry(full_name="Main lead", phone="9876543210", branch_id=main_admin.branch_id))
    db.session.add(Enquiry(full_name="City lead", phone="9876543211", branch_id=city.id))
    db.session.commit()

    login(client, "mainadmin")
    page = client.get("/enquiries/")
    assert page.status_code == 200 and b"Main lead" in page.data and b"City lead" not in page.data

    other = client.application.test_client()
    login(other, "cityadmin")
    enquiry = Enquiry.query.filter_by(branch_id=main_admin.branch_id).first()
    assert other.get(f"/enquiries/{enquiry.id}").status_code == 403
    assert city_admin.branch_id == city.id


def test_staff_can_track_enquiry_followup(client):
    make_user("branch_admin", "manager")
    login(client, "manager")
    response = client.post("/enquiries/new", data={
        "full_name": "Asha Patil", "phone": "9876543210",
        "course_interest": "NEET", "message": "Walk-in",
    })
    assert response.status_code == 302
    enquiry = Enquiry.query.one()
    response = client.post(f"/enquiries/{enquiry.id}/edit", data={
        "status": "contacted", "follow_up_at": "2026-11-25", "staff_notes": "Call next week",
    })
    assert response.status_code == 302
    db_enquiry = db.session.get(Enquiry, enquiry.id)
    assert (db_enquiry.status, db_enquiry.staff_notes, db_enquiry.follow_up_at.isoformat()) == (
        "contacted", "Call next week", "2026-11-25"
    )


def test_owner_can_assign_unassigned_public_enquiry(client):
    make_user("owner", "boss")
    branch = Branch.query.filter_by(code="MAIN").first()
    enquiry = Enquiry(full_name="Unassigned lead", phone="9876543210", source="public")
    db.session.add(enquiry)
    db.session.commit()
    login(client, "boss")
    response = client.post(f"/enquiries/{enquiry.id}/edit", data={
        "branch_id": str(branch.id), "status": "new", "follow_up_at": "", "staff_notes": "",
    })
    assert response.status_code == 302
    assert db.session.get(Enquiry, enquiry.id).branch_id == branch.id


def test_notice_creates_notifications_only_for_matching_role_and_branch(client):
    city = add_branch("CITY1", "City Branch")
    make_user("owner", "boss")
    main_student = make_user("student", "mainstudent")
    make_user("student", "citystudent", branch_code="CITY1")
    admin = make_user("branch_admin", "admin")
    login(client, "boss")
    main = Branch.query.filter_by(code="MAIN").first()
    response = client.post("/notices/new", data={
        "branch_id": str(main.id), "audience": "student",
        "title": "Exam date", "body": "The exam is on Monday.",
    })
    assert response.status_code == 302
    notice = Notice.query.one()
    notifications = Notification.query.filter_by(notice_id=notice.id).all()
    assert [item.user_id for item in notifications] == [main_student.id]
    assert admin.branch_id == main.id and city.id != main.id


def test_owner_cannot_turn_invalid_branch_selection_into_global_notice(client):
    make_user("owner", "boss")
    login(client, "boss")
    response = client.post("/notices/new", data={
        "branch_id": "invalid", "audience": "student", "title": "Exam date", "body": "Monday",
    })
    assert response.status_code == 200 and b"valid branch" in response.data
    assert Notice.query.count() == 0


def test_all_notice_includes_accountants_with_inbox_access(client):
    make_user("owner", "boss")
    accountant = make_user("accountant", "accountant1")
    login(client, "boss")
    response = client.post("/notices/new", data={
        "branch_id": "", "audience": "all", "title": "Institute update", "body": "Please read this.",
    })
    assert response.status_code == 302
    notification = Notification.query.filter_by(user_id=accountant.id).one()

    account_client = client.application.test_client()
    login(account_client, "accountant1")
    assert account_client.get("/notifications/").status_code == 200
    assert notification.notice.title == "Institute update"


def test_user_cannot_read_or_mark_another_users_notification(client):
    make_user("owner", "boss")
    student = make_user("student", "student1")
    other_student = make_user("student", "student2")
    notice = Notice(title="Reminder", body="Read this", audience="all")
    db.session.add(notice)
    db.session.flush()
    notification = Notification(notice_id=notice.id, user_id=student.id)
    db.session.add(notification)
    db.session.commit()

    login(client, "student2")
    assert client.get(f"/notifications/{notification.id}").status_code == 403
    assert client.post(f"/notifications/{notification.id}/read").status_code == 403
    assert db.session.get(Notification, notification.id).read_at is None

    own = client.application.test_client()
    login(own, "student1")
    assert own.get(f"/notifications/{notification.id}").status_code == 200
    assert own.get("/notifications/").status_code == 200
    assert own.post(f"/notifications/{notification.id}/read").status_code == 302
    assert db.session.get(Notification, notification.id).read_at is not None
    assert other_student.id != student.id


def test_service_worker_manifest_and_install_button(client):
    worker = client.get("/sw.js")
    assert worker.status_code == 200
    assert worker.headers["Service-Worker-Allowed"] == "/"
    assert b"notificationclick" in worker.data
    manifest = client.get("/static/pwa/manifest.webmanifest")
    assert manifest.status_code == 200 and b'"display": "standalone"' in manifest.data
    assert client.get("/static/pwa/icon-192.png").status_code == 200

    make_user("owner", "boss")
    login(client, "boss")
    dashboard = client.get("/owner/dashboard")
    assert dashboard.status_code == 200 and b'id="pwa-install"' in dashboard.data
    assert b'id="push-enable"' in dashboard.data
    assert b'id="pwa-push-prompt"' in dashboard.data


def test_push_subscription_is_owned_by_logged_in_user(client, app):
    make_user("student", "pushstudent")
    login(client, "pushstudent")
    app.config["VAPID_PUBLIC_KEY"] = "configured-test-key"
    app.config["VAPID_PRIVATE_KEY"] = "configured-test-private-key"
    payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-endpoint",
        "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
    }
    response = client.post("/notifications/push-subscriptions", json=payload)
    assert response.status_code == 201
    subscription = PushSubscription.query.one()
    assert subscription.user.username == "pushstudent"
    assert client.get("/notifications/push-subscriptions/status").json == {"subscribed": True}

    payload["endpoint"] = "http://127.0.0.1/admin"
    response = client.post("/notifications/push-subscriptions", json=payload)
    assert response.status_code == 400
    assert PushSubscription.query.count() == 1


def test_push_subscription_rejects_an_endpoint_owned_by_another_user(client):
    make_user("student", "firstdeviceowner")
    make_user("student", "seconddeviceowner")
    endpoint = "https://fcm.googleapis.com/fcm/send/shared-endpoint"
    payload = {"endpoint": endpoint, "keys": {"p256dh": "A" * 87, "auth": "B" * 22}}
    login(client, "firstdeviceowner")
    assert client.post("/notifications/push-subscriptions", json=payload).status_code == 201

    other = client.application.test_client()
    login(other, "seconddeviceowner")
    response = other.post("/notifications/push-subscriptions", json=payload)
    assert response.status_code == 400 and b"another account" in response.data
    assert PushSubscription.query.count() == 1


def test_notice_sends_browser_push_for_saved_subscriptions(client, app, monkeypatch):
    import base64
    from cryptography.hazmat.primitives import serialization
    import pywebpush
    from py_vapid import Vapid

    owner = make_user("owner", "pushadmin")
    student = make_user("student", "pushrecipient")
    db.session.add(PushSubscription(
        user_id=student.id,
        endpoint="https://fcm.googleapis.com/fcm/send/push-test",
        endpoint_hash="a" * 64,
        p256dh="A" * 87,
        auth="B" * 22,
    ))
    db.session.commit()
    calls = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)
        return type("PushResponse", (), {"status_code": 201})()

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    vapid = Vapid()
    vapid.generate_keys()
    app.config["VAPID_PUBLIC_KEY"] = base64.urlsafe_b64encode(
        vapid.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
    ).decode("ascii").rstrip("=")
    app.config["VAPID_PRIVATE_KEY"] = vapid.private_pem().decode("utf-8")
    login(client, "pushadmin")
    response = client.post("/notices/new", data={
        "branch_id": "", "audience": "student", "title": "Phone alert", "body": "Hello phone",
    })
    assert response.status_code == 302
    assert len(calls) == 1
    assert calls[0]["subscription_info"]["endpoint"].endswith("push-test")
    assert '"title": "Phone alert"' in calls[0]["data"]
    assert calls[0]["vapid_private_key"].private_key.curve.name == "secp256r1"


def test_push_config_rejects_malformed_or_mismatched_vapid_keys(client, app):
    from py_vapid import Vapid

    make_user("student", "pushconfigstudent")
    login(client, "pushconfigstudent")
    app.config["VAPID_PUBLIC_KEY"] = "configured-public-key"
    app.config["VAPID_PRIVATE_KEY"] = "not-a-private-key"

    response = client.get("/notifications/push-config")

    assert response.status_code == 200
    assert response.json["enabled"] is False
    assert response.json["publicKey"] == ""
    assert "private key is invalid" in response.json["error"]

    vapid = Vapid()
    vapid.generate_keys()
    app.config["VAPID_PRIVATE_KEY"] = vapid.private_pem().decode("utf-8")
    response = client.get("/notifications/push-config")

    assert response.json["enabled"] is False
    assert "do not match" in response.json["error"]


def test_live_stream_delivers_new_notification_without_refresh(client):
    make_user("student", "livestudent")
    notice = Notice(title="Live update", body="Arriving now", audience="student")
    db.session.add(notice)
    db.session.flush()
    notification = Notification(notice_id=notice.id, user_id=User.query.filter_by(username="livestudent").one().id)
    db.session.add(notification)
    db.session.commit()
    login(client, "livestudent")
    response = client.get("/notifications/stream?after=0", buffered=False)
    first_event = next(response.response)
    response.close()
    assert response.mimetype == "text/event-stream"
    assert b"event: notification" in first_event
    assert b"Live update" in first_event
