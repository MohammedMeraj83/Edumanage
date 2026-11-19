from datetime import date, timedelta
from decimal import Decimal
from extensions import db
from app.models import FeeDue, Payment, Refund, Batch, BatchStudent, AcademicSession
from app.services import fee_service as svc
from conftest import make_user, login, add_branch, flashes
from test_batches import mk_teacher, mk_student, mk_batch, main_branch, admin

TODAY = date.today()


def three_month_batch(main, subject="Physics", fee=1500, freq="monthly", teacher=None):
    b = mk_batch(main, teacher or mk_teacher(main), subject=subject, fee=fee)
    first = svc._add_months(TODAY.replace(day=1), 2)
    b.end_date = date(first.year, first.month, 28)             # this month + 2 more = exactly 3 months
    b.fee_frequency = freq
    db.session.commit()
    return b


def enroll(client, batch, student, **extra):
    return client.post(f"/batches/{batch.id}/enroll", data={"student_id": student.id, **extra})


def dues_of(student):
    return FeeDue.query.filter_by(student_id=student.id).order_by(FeeDue.due_date, FeeDue.id).all()


def pay(client, student, amount, ids=None, mode="cash", reference="", token=None, paid_on=None):
    ids = ids if ids is not None else [d.id for d in dues_of(student) if d.status in ("pending", "partial")]
    return client.post(f"/fees/collect/{student.id}", data={
        "due_id": ids, "amount": str(amount), "mode": mode, "reference": reference, "note": "",
        "paid_on": (paid_on or TODAY).isoformat(), "token": token or ""})


def accountant(client, code="MAIN", username="ann"):
    make_user("accountant", username, branch_code=code)
    c = client.application.test_client()
    login(c, username)
    return c


# ------------------------------------------------------------------ generating dues
def test_monthly_enrollment_creates_one_due_per_month(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    admin(client)
    enroll(client, b, s)
    dues = dues_of(s)
    assert len(dues) == 3 and all(d.amount == Decimal("1500") and d.kind == "monthly" for d in dues)
    assert dues[0].due_date >= TODAY and dues[1].due_date > dues[0].due_date
    assert [d.period_key for d in dues] == sorted(d.period_key for d in dues)
    # generating again must not duplicate
    enr = BatchStudent.query.one()
    assert svc.generate_dues(enr, "monthly") == [] and FeeDue.query.count() == 3


def test_pay_full_creates_single_due_with_discount(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    admin(client)
    enroll(client, b, s, pay_style="full", discount="500")
    (d,) = dues_of(s)
    assert d.kind == "full" and d.amount == Decimal("4500") and d.discount == Decimal("500") and d.balance == Decimal("4000")


def test_other_fee_frequencies_and_free_batch(client):
    main = main_branch()
    once = three_month_batch(main, subject="Physics", freq="one_time", fee=8000)
    yearly = three_month_batch(main, subject="Chemistry", freq="yearly", fee=20000)
    quarterly = three_month_batch(main, subject="Biology", freq="quarterly", fee=4000)
    free = three_month_batch(main, subject="Mathematics", fee=0)
    s = mk_student(main)
    admin(client)
    for b in (once, yearly, quarterly, free):
        enroll(client, b, s)
    kinds = sorted((d.kind, d.amount) for d in dues_of(s))
    assert kinds == [("one_time", Decimal("8000")), ("quarterly", Decimal("4000")), ("yearly", Decimal("20000"))]


def test_leaving_cancels_only_future_unpaid_dues(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    admin(client)
    enroll(client, b, s)
    first = dues_of(s)[0]
    pay(client, s, 1500, ids=[first.id])
    client.post(f"/batches/{b.id}/unenroll/{s.id}")
    statuses = [d.status for d in dues_of(s)]
    assert statuses[0] == "paid" and statuses[1:] == ["cancelled", "cancelled"]


def test_generate_missing_dues_for_old_enrollments(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    db.session.add(BatchStudent(batch_id=b.id, student_id=s.id, status="active", enrolled_on=TODAY, fee_amount=1500))
    db.session.commit()
    assert FeeDue.query.count() == 0
    assert svc.generate_missing_dues() == 3 and svc.generate_missing_dues() == 0


def test_due_day_setting(client):
    main = main_branch()
    boss = admin(client)
    assert svc.due_day() == 5
    boss.post("/fees/settings", data={"due_day": "40"})
    assert svc.due_day() == 5
    boss.post("/fees/settings", data={"due_day": "10"})
    assert svc.due_day() == 10
    b, s = three_month_batch(main), mk_student(main)
    enroll(boss, b, s)
    assert dues_of(s)[1].due_date.day == 10


# ------------------------------------------------------------------ taking money
def test_partial_payments_spread_oldest_first_and_receipts_are_numbered(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    admin(client)
    enroll(client, b, s)
    r = pay(client, s, 2000, token="t1")
    assert r.status_code == 302 and "/fees/receipt/" in r.location
    d1, d2, d3 = dues_of(s)
    assert (d1.status, d1.paid) == ("paid", Decimal("1500")) and (d2.status, d2.paid) == ("partial", Decimal("500"))
    assert d3.status == "pending"
    p1 = Payment.query.one()
    tag = f"{AcademicSession.query.first().start_date.year % 100:02d}{AcademicSession.query.first().end_date.year % 100:02d}"
    assert p1.receipt_no == f"RCT-MAIN-{tag}-000001" and p1.received_by
    pay(client, s, 2500, token="t2")
    assert [d.status for d in dues_of(s)] == ["paid", "paid", "paid"]
    assert Payment.query.order_by(Payment.id).all()[1].receipt_no.endswith("000002")


def test_payment_rules(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    admin(client)
    enroll(client, b, s)
    pay(client, s, 9999)                                                   # more than the dues
    assert "more than" in flashes(client)[-1] and Payment.query.count() == 0
    pay(client, s, 0)
    pay(client, s, -5)
    pay(client, s, 500, mode="upi", reference="")                          # cashless needs a reference
    assert "transaction" in flashes(client)[-1].lower() and Payment.query.count() == 0
    pay(client, s, 500, paid_on=TODAY + timedelta(days=1))
    assert Payment.query.count() == 0
    pay(client, s, 500, mode="upi", reference="UTR123")
    assert Payment.query.one().reference == "UTR123"
    pay(client, s, 500, ids=[])                                            # nothing selected
    assert Payment.query.count() == 1


def test_double_click_does_not_charge_twice(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    admin(client)
    enroll(client, b, s)
    pay(client, s, 1000, token="same")
    pay(client, s, 1000, token="same")
    assert Payment.query.count() == 1 and dues_of(s)[0].paid == Decimal("1000")


def test_old_payment_date_needs_admin(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    admin(client)
    enroll(client, b, s)
    acc = accountant(client)
    old = TODAY - timedelta(days=45)
    pay(acc, s, 500, paid_on=old)
    assert Payment.query.count() == 0
    pay(client, s, 500, paid_on=old)
    assert Payment.query.one().paid_on == old


# ------------------------------------------------------------------ corrections
def test_cancel_payment_reopens_dues_and_keeps_receipt(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    boss = admin(client)
    enroll(boss, b, s)
    pay(boss, s, 1500)
    p = Payment.query.one()
    boss.post(f"/fees/payment/{p.id}/cancel", data={"reason": ""})
    assert p.status == "active"
    boss.post(f"/fees/payment/{p.id}/cancel", data={"reason": "wrong student"})
    db.session.refresh(p)
    assert p.status == "cancelled" and dues_of(s)[0].status == "pending" and dues_of(s)[0].paid == 0
    assert b"CANCELLED" in boss.get(f"/fees/receipt/{p.id}").data
    boss.post(f"/fees/payment/{p.id}/cancel", data={"reason": "again"})
    assert "already" in flashes(boss)[-1]


def test_refund_reverses_latest_due_first_and_is_limited(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    boss = admin(client)
    enroll(boss, b, s)
    pay(boss, s, 3000)                                                      # d1 + d2 paid
    p = Payment.query.one()
    boss.post(f"/fees/payment/{p.id}/refund", data={"amount": "1000", "mode": "cash", "reason": "left early"})
    d1, d2, d3 = dues_of(s)
    assert d1.status == "paid" and (d2.status, d2.paid) == ("partial", Decimal("500"))
    r = Refund.query.one()
    assert r.refund_no.startswith("RFD-MAIN-") and r.amount == Decimal("1000")
    db.session.refresh(p)
    assert p.refunded_amount == Decimal("1000") and p.net_amount == Decimal("2000")
    boss.post(f"/fees/payment/{p.id}/refund", data={"amount": "5000", "mode": "cash", "reason": "too much"})
    assert Refund.query.count() == 1
    boss.post(f"/fees/payment/{p.id}/cancel", data={"reason": "x"})
    assert p.status == "active" and "refunds" in flashes(boss)[-1]


def test_discount_rules(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    boss = admin(client)
    enroll(boss, b, s)
    d = dues_of(s)[0]
    boss.post(f"/fees/due/{d.id}/discount", data={"discount": "300", "reason": ""})
    assert d.discount == 0                                                   # reason required
    boss.post(f"/fees/due/{d.id}/discount", data={"discount": "300", "reason": "sibling"})
    db.session.refresh(d)
    assert d.discount == Decimal("300") and d.balance == Decimal("1200")
    boss.post(f"/fees/due/{d.id}/discount", data={"discount": "9999", "reason": "x"})
    assert d.discount == Decimal("300")
    pay(boss, s, 1200, ids=[d.id])
    boss.post(f"/fees/due/{d.id}/discount", data={"discount": "1400", "reason": "more"})   # would be below what is paid
    db.session.refresh(d)
    assert d.discount == Decimal("300") and d.status == "paid"


def test_cancel_due_only_when_nothing_paid(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    boss = admin(client)
    enroll(boss, b, s)
    d1, d2, _ = dues_of(s)
    pay(boss, s, 500, ids=[d1.id])
    boss.post(f"/fees/due/{d1.id}/cancel", data={"reason": "x"})
    assert d1.status == "partial"
    boss.post(f"/fees/due/{d2.id}/cancel", data={"reason": "scholarship"})
    db.session.refresh(d2)
    assert d2.status == "cancelled" and d2.balance == 0


def test_accountant_collects_but_cannot_correct(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    boss = admin(client)
    enroll(boss, b, s)
    acc = accountant(client)
    assert acc.get("/fees/").status_code == 200
    assert pay(acc, s, 1500).status_code == 302
    p, d = Payment.query.one(), dues_of(s)[1]
    assert acc.post(f"/fees/payment/{p.id}/cancel", data={"reason": "x"}).status_code == 403
    assert acc.post(f"/fees/payment/{p.id}/refund", data={"amount": "1", "mode": "cash", "reason": "x"}).status_code == 403
    assert acc.post(f"/fees/due/{d.id}/discount", data={"discount": "1", "reason": "x"}).status_code == 403
    assert acc.post(f"/fees/due/{d.id}/cancel", data={"reason": "x"}).status_code == 403
    assert acc.get("/fees/settings").status_code == 403
    assert acc.post(f"/fees/student/{s.id}/charge", data={"label": "Late fee", "amount": "100"}).status_code == 302
    assert FeeDue.query.filter_by(kind="custom").one().amount == Decimal("100")


# ------------------------------------------------------------------ who may see what
def test_branch_isolation(client):
    main, other = main_branch(), add_branch("CITY1")
    b, s = three_month_batch(main), mk_student(main)
    boss = admin(client)
    enroll(boss, b, s)
    pay(boss, s, 500)
    p = Payment.query.one()
    make_user("branch_admin", "cara", branch_code="CITY1")
    cara = client.application.test_client()
    login(cara, "cara")
    assert cara.get(f"/fees/student/{s.id}").status_code == 403
    assert cara.get(f"/fees/receipt/{p.id}").status_code == 403
    assert cara.get(f"/fees/receipt/{p.id}.pdf").status_code == 403
    assert cara.post(f"/fees/collect/{s.id}", data={}).status_code == 403
    assert b"Rohan" not in cara.get("/fees/pending?overdue=0").data


def test_student_and_parent_see_only_their_own(client):
    from app.services.student_service import create_student_login
    from app.services.parent_service import link_from_student, create_parent_login
    main = main_branch()
    b = three_month_batch(main)
    mine, other = mk_student(main, "Mine"), mk_student(main, "Other")
    other.guardian_phone = "9000000099"
    db.session.commit()
    boss = admin(client)
    enroll(boss, b, mine)
    enroll(boss, b, other)
    pay(boss, mine, 500)
    pay(boss, other, 500)
    mp, op = [p for p in Payment.query.order_by(Payment.id)]
    su, spw = create_student_login(mine)
    su.must_change_password = False
    parent, _ = link_from_student(mine, "Father", None)
    pu, ppw = create_parent_login(parent)
    pu.must_change_password = False
    db.session.commit()

    stu = client.application.test_client()
    login(stu, su.username, spw)
    assert stu.get(f"/fees/receipt/{mp.id}").status_code == 200
    assert stu.get(f"/fees/receipt/{op.id}").status_code == 403
    assert stu.get("/student/fees").status_code == 200
    for url in ("/fees/", "/fees/pending", "/fees/payments", f"/fees/student/{mine.id}", f"/fees/collect/{mine.id}"):
        assert stu.get(url).status_code == 403, url
    par = client.application.test_client()
    login(par, pu.username, ppw)
    assert par.get(f"/fees/receipt/{mp.id}").status_code == 200
    assert par.get(f"/fees/receipt/{op.id}").status_code == 403
    assert par.get(f"/parent/child/{mine.id}/fees").status_code == 200
    assert par.get(f"/parent/child/{other.id}/fees").status_code == 404
    assert par.get("/fees/pending").status_code == 403
    assert par.get("/parent/dashboard").status_code == 200


# ------------------------------------------------------------------ lists, exports, pdf
def test_pending_list_exports_and_pdf(client):
    main = main_branch()
    s = mk_student(main, "Late Payer")
    boss = admin(client)
    svc.add_charge(s, "Old test series", "750", TODAY - timedelta(days=12), make_user("owner", "boss"))
    page = boss.get("/fees/pending")
    assert page.status_code == 200 and b"Late Payer" in page.data and b"750" in page.data
    due = FeeDue.query.one()
    assert due.overdue
    x = boss.get("/fees/pending.xlsx")
    assert x.status_code == 200 and "spreadsheetml" in x.content_type and x.data[:2] == b"PK"
    pay(boss, s, 750)
    p = Payment.query.one()
    assert b"Late Payer" not in boss.get("/fees/pending").data
    assert b"Late Payer" in boss.get("/fees/payments").data
    assert boss.get("/fees/payments.xlsx").data[:2] == b"PK"
    pdf = boss.get(f"/fees/receipt/{p.id}.pdf")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf" and pdf.data[:5] == b"%PDF-"
    assert boss.get(f"/fees/receipt/{p.id}").status_code == 200


def test_money_filter_uses_indian_grouping(client):
    f = client.application.jinja_env.filters["inr"]
    assert f(Decimal("1234567.5")) == "₹12,34,567.50"
    assert f(1500) == "₹1,500" and f(0) == "₹0" and f(None) == "₹0" and f(Decimal("99")) == "₹99"
    assert f(Decimal("-250")) == "-₹250"


def test_dashboard_totals(client):
    main = main_branch()
    b, s = three_month_batch(main), mk_student(main)
    boss = admin(client)
    enroll(boss, b, s)
    pay(boss, s, 1000)
    assert svc.collection_between(TODAY, TODAY, main.id) == Decimal("1000.00")
    total, overdue, n = svc.outstanding_total(main.id)
    assert total == Decimal("3500.00")
    assert boss.get("/fees/").status_code == 200
    assert boss.get("/fees/?q=rohan").status_code == 200
    assert boss.get(f"/fees/student/{s.id}").status_code == 200
    assert boss.get(f"/fees/collect/{s.id}").status_code == 200
