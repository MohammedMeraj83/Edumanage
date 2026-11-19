import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from PIL import Image
from extensions import db
from app.models import (Expense, ExpenseCategory, Payroll, SalaryPayment, SalaryStructure, LectureSession, LeaveRequest,
                        Payment, Staff, AcademicSession)
from app.services import payroll_service as psvc
from app.services import finance_report_service as rep
from conftest import make_user, login, add_branch, flashes
from test_batches import mk_teacher, mk_student, mk_batch, main_branch, admin

TODAY = date.today()
PREV = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=1)          # first day of last month
PREV_ARG = PREV.strftime("%Y-%m")


def accountant(client, code="MAIN", username="ann"):
    make_user("accountant", username, branch_code=code)
    c = client.application.test_client()
    login(c, username)
    return c


def mk_staff(branch, name="Asha", designation="Accountant"):
    n = Staff.query.count() + 1
    s = Staff(employee_code=f"STF{n:06d}", branch_id=branch.id, full_name=name, gender="Female", phone=f"91000{n:05d}",
              joining_date=date(2025, 1, 1), designation=designation, status="active")
    db.session.add(s)
    db.session.commit()
    return s


def lecture(batch, teacher, day, taught=True, cancelled=False):
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=4)
    s = LectureSession(branch_id=batch.branch_id, batch_id=batch.id, teacher_id=teacher.id, lecture_date=day,
                       start_at=start, end_at=start + timedelta(hours=1), cancelled=cancelled,
                       checkin_at=start - timedelta(minutes=2) if taught else None)
    db.session.add(s)
    db.session.commit()
    return s


def set_salary(client, kind, person, pay_type, base="", rate="", missed=""):
    return client.post(f"/payroll/structures/{kind}/{person.id}", data={
        "pay_type": pay_type, "base_salary": base, "per_lecture_rate": rate, "missed_deduction": missed})


# ------------------------------------------------------------------ expenses
def expense_form(branch_cat, **over):
    d = {"category_id": branch_cat.id, "amount": "2500", "expense_date": TODAY.isoformat(), "description": "Office rent",
         "vendor": "Landlord", "mode": "cash", "reference": ""}
    d.update(over)
    return d


def test_expense_add_validate_cancel_and_privacy(client):
    main, other = main_branch(), add_branch("CITY1")
    acc = accountant(client)
    assert acc.get("/finance/expenses").status_code == 200           # also creates the default categories
    cat = ExpenseCategory.query.filter_by(name="Rent").one()
    assert acc.post("/finance/expenses/new", data=expense_form(cat), content_type="multipart/form-data").status_code == 302
    e = Expense.query.one()
    assert e.amount == Decimal("2500") and e.branch_id == main.id and e.status == "active"
    for bad in ({"amount": "0"}, {"amount": "abc"}, {"description": ""}, {"expense_date": (TODAY + timedelta(days=2)).isoformat()},
                {"category_id": 9999}, {"mode": "gold"}):
        acc.post("/finance/expenses/new", data=expense_form(cat, **bad), content_type="multipart/form-data")
    assert Expense.query.count() == 1
    # bill upload is private
    pdf = (io.BytesIO(b"%PDF-1.4 bill"), "bill.pdf")
    acc.post("/finance/expenses/new", data={**expense_form(cat, description="Printing"), "bill": pdf}, content_type="multipart/form-data")
    withbill = Expense.query.filter_by(description="Printing").one()
    assert acc.get(f"/finance/expenses/{withbill.id}/bill").status_code == 200
    make_user("branch_admin", "cara", branch_code="CITY1")
    cara = client.application.test_client()
    login(cara, "cara")
    assert cara.get(f"/finance/expenses/{withbill.id}").status_code == 403
    assert cara.get(f"/finance/expenses/{withbill.id}/bill").status_code == 403
    assert b"Printing" not in cara.get("/finance/expenses").data
    # only admin / owner cancel
    assert acc.post(f"/finance/expenses/{e.id}/cancel", data={"reason": "x"}).status_code == 403
    boss = admin(client)
    boss.post(f"/finance/expenses/{e.id}/cancel", data={"reason": ""})
    assert e.status == "active"
    boss.post(f"/finance/expenses/{e.id}/cancel", data={"reason": "duplicate entry"})
    db.session.refresh(e)
    assert e.status == "cancelled"
    x = boss.get("/finance/expenses.xlsx")
    assert x.status_code == 200 and x.data[:2] == b"PK"


def test_categories_admin_only(client):
    acc = accountant(client)
    assert acc.get("/finance/categories").status_code == 200
    assert acc.post("/finance/categories", data={"name": "Snacks"}).status_code == 403
    boss = admin(client)
    boss.post("/finance/categories", data={"name": "Snacks"})
    assert ExpenseCategory.query.filter_by(name="Snacks").count() == 1
    boss.post("/finance/categories", data={"name": "snacks"})
    assert ExpenseCategory.query.filter_by(name="Snacks").count() == 1 and "exists" in flashes(boss)[-1]


# ------------------------------------------------------------------ salary setup
def test_salary_setup_rules(client):
    main = main_branch()
    t, staff = mk_teacher(main), mk_staff(main)
    acc = accountant(client)
    assert set_salary(acc, "teacher", t, "fixed", base="20000").status_code == 403
    boss = admin(client)
    set_salary(boss, "teacher", t, "fixed", base="")                         # needs a salary
    set_salary(boss, "teacher", t, "per_lecture", rate="")
    set_salary(boss, "teacher", t, "mixed", base="5000", rate="")
    set_salary(boss, "staff", staff, "per_lecture", rate="100")              # staff are fixed only
    assert SalaryStructure.query.count() == 0
    set_salary(boss, "teacher", t, "per_lecture", base="999", rate="300", missed="50")
    st = SalaryStructure.query.one()
    assert st.pay_type == "per_lecture" and st.base_salary == 0 and st.per_lecture_rate == Decimal("300")
    set_salary(boss, "teacher", t, "mixed", base="5000", rate="200")
    assert SalaryStructure.query.count() == 1 and SalaryStructure.query.one().base_salary == Decimal("5000")
    set_salary(boss, "staff", staff, "fixed", base="15000", missed="99")
    assert SalaryStructure.query.filter_by(staff_id=staff.id).one().missed_lecture_deduction == 0


# ------------------------------------------------------------------ payroll numbers
def test_payroll_from_attendance(client):
    main = main_branch()
    t1, t2, t3, staff = mk_teacher(main, "Fixed"), mk_teacher(main, "Lecture"), mk_teacher(main, "Both"), mk_staff(main)
    mk_teacher(main, "NoSalary")
    b1, b2, b3 = mk_batch(main, t1, subject="Physics"), mk_batch(main, t2, subject="Chemistry"), mk_batch(main, t3, subject="Biology")
    for d in (3, 4, 5, 6):
        lecture(b2, t2, PREV.replace(day=d))                                   # 4 taught
    lecture(b2, t2, PREV.replace(day=7), taught=False)                         # missed
    lecture(b2, t2, PREV.replace(day=8), taught=False)                         # missed
    lecture(b2, t2, PREV.replace(day=9), taught=False, cancelled=True)         # cancelled: not counted
    lecture(b2, t2, PREV.replace(day=10), taught=False)                        # on approved leave: not missed
    db.session.add(LeaveRequest(branch_id=main.id, kind="teacher", teacher_id=t2.id, requested_by=1,
                                from_date=PREV.replace(day=10), to_date=PREV.replace(day=10), reason="x", status="approved"))
    for d in (3, 4):
        lecture(b3, t3, PREV.replace(day=d))
    db.session.commit()
    boss = admin(client)
    set_salary(boss, "teacher", t1, "fixed", base="20000")
    set_salary(boss, "teacher", t2, "per_lecture", rate="300", missed="50")
    set_salary(boss, "teacher", t3, "mixed", base="5000", rate="200")
    set_salary(boss, "staff", staff, "fixed", base="15000")
    r = boss.post("/payroll/generate", data={"m": PREV_ARG})
    assert r.status_code == 302 and "NoSalary" in flashes(boss)[-1]
    rows = {p.person.full_name: p for p in Payroll.query.all()}
    assert set(rows) == {"Fixed", "Lecture", "Both", "Asha"}
    assert rows["Fixed"].net_amount == Decimal("20000") and rows["Fixed"].lecture_amount == 0
    lec = rows["Lecture"]
    assert (lec.lectures_taught, lec.lectures_missed) == (4, 2)
    assert lec.lecture_amount == Decimal("1200") and lec.auto_deduction == Decimal("100") and lec.net_amount == Decimal("1100")
    assert rows["Both"].net_amount == Decimal("5400")                           # 5000 + 2 x 200
    assert rows["Asha"].net_amount == Decimal("15000") and rows["Asha"].lectures_taught == 0
    slips = sorted(p.slip_no for p in rows.values())
    assert slips[0] == f"SAL-MAIN-{PREV:%y%m}-0001" and len(set(slips)) == 4
    boss.post("/payroll/generate", data={"m": PREV_ARG})                        # again: nothing new
    assert Payroll.query.count() == 4
    page = boss.get(f"/payroll/?m={PREV_ARG}")
    assert page.status_code == 200 and b"Lecture" in page.data
    assert boss.get(f"/payroll/month.xlsx?m={PREV_ARG}").data[:2] == b"PK"


def test_payroll_workflow_and_money_rules(client):
    main = main_branch()
    t = mk_teacher(main)
    boss, acc = admin(client), accountant(client)
    set_salary(boss, "teacher", t, "fixed", base="20000")
    acc.post("/payroll/generate", data={"m": PREV_ARG})
    p = Payroll.query.one()
    assert p.status == "draft"
    acc.post(f"/payroll/{p.id}/adjust", data={"allowance": "500", "bonus": "1000", "deduction": "300", "note": ""})
    assert p.allowance == 0                                                    # deduction needs a note
    acc.post(f"/payroll/{p.id}/adjust", data={"allowance": "500", "bonus": "1000", "deduction": "300", "note": "advance"})
    db.session.refresh(p)
    assert p.net_amount == Decimal("21200")
    acc.post(f"/payroll/{p.id}/adjust", data={"allowance": "0", "bonus": "0", "deduction": "99999", "note": "x"})
    assert p.net_amount == Decimal("21200")
    acc.post(f"/payroll/{p.id}/pay", data={"amount": "100", "mode": "cash"})
    assert SalaryPayment.query.count() == 0                                    # not finalized yet
    assert acc.post(f"/payroll/{p.id}/finalize").status_code == 403
    boss.post(f"/payroll/{p.id}/finalize")
    db.session.refresh(p)
    assert p.status == "finalized"
    acc.post(f"/payroll/{p.id}/adjust", data={"allowance": "1", "bonus": "0", "deduction": "0", "note": ""})
    assert p.allowance == Decimal("500")                                       # locked after finalizing
    acc.post(f"/payroll/{p.id}/pay", data={"amount": "99999", "mode": "cash"})
    acc.post(f"/payroll/{p.id}/pay", data={"amount": "5000", "mode": "upi", "reference": ""})
    assert SalaryPayment.query.count() == 0
    acc.post(f"/payroll/{p.id}/pay", data={"amount": "10000", "mode": "cash", "paid_on": TODAY.isoformat()})
    db.session.refresh(p)
    assert (p.status, p.paid_amount) == ("finalized", Decimal("10000"))
    boss.post(f"/payroll/{p.id}/cancel", data={"reason": "no"})
    assert p.status == "finalized" and "already paid" in flashes(boss)[-1]
    acc.post(f"/payroll/{p.id}/pay", data={"amount": "11200", "mode": "bank", "reference": "UTR9"})
    db.session.refresh(p)
    assert (p.status, p.balance) == ("paid", Decimal("0"))
    first = SalaryPayment.query.order_by(SalaryPayment.id).first()
    assert acc.post(f"/payroll/payment/{first.id}/cancel", data={"reason": "x"}).status_code == 403
    boss.post(f"/payroll/payment/{first.id}/cancel", data={"reason": "entered twice"})
    db.session.refresh(p)
    assert p.status == "finalized" and p.paid_amount == Decimal("11200")


def test_slip_access(client):
    main = main_branch()
    t, other = mk_teacher(main, "Mine"), mk_teacher(main, "Theirs")
    boss = admin(client)
    set_salary(boss, "teacher", t, "fixed", base="10000")
    set_salary(boss, "teacher", other, "fixed", base="12000")
    boss.post("/payroll/generate", data={"m": PREV_ARG})
    mine = Payroll.query.filter_by(teacher_id=t.id).one()
    theirs = Payroll.query.filter_by(teacher_id=other.id).one()
    u = make_user("teacher", "tina")
    t.user_id = u.id
    db.session.commit()
    me = client.application.test_client()
    login(me, "tina")
    assert me.get(f"/payroll/{mine.id}/slip").status_code == 403               # still a draft
    assert b"Mine" not in me.get("/payroll/my").data
    boss.post(f"/payroll/{mine.id}/finalize")
    boss.post(f"/payroll/{theirs.id}/finalize")
    assert me.get(f"/payroll/{mine.id}/slip").status_code == 200
    pdf = me.get(f"/payroll/{mine.id}/slip.pdf")
    assert pdf.status_code == 200 and pdf.data[:5] == b"%PDF-"
    assert me.get(f"/payroll/{theirs.id}/slip").status_code == 403
    assert me.get("/payroll/").status_code == 403 and me.get(f"/payroll/{mine.id}").status_code == 403
    assert b"10,000" in me.get("/payroll/my").data and b"12,000" not in me.get("/payroll/my").data
    stu = make_user("student", "sam")
    other_client = client.application.test_client()
    login(other_client, "sam")
    assert other_client.get(f"/payroll/{mine.id}/slip").status_code == 403


def test_payroll_branch_isolation(client):
    main, other = main_branch(), add_branch("CITY1")
    t = mk_teacher(main)
    boss = admin(client)
    set_salary(boss, "teacher", t, "fixed", base="10000")
    boss.post("/payroll/generate", data={"m": PREV_ARG})
    p = Payroll.query.one()
    make_user("branch_admin", "cara", branch_code="CITY1")
    cara = client.application.test_client()
    login(cara, "cara")
    assert cara.get(f"/payroll/{p.id}").status_code == 403
    assert cara.post(f"/payroll/{p.id}/finalize").status_code == 403
    assert cara.get(f"/payroll/{p.id}/slip").status_code == 403
    assert b"Meena" not in cara.get(f"/payroll/?m={PREV_ARG}").data


# ------------------------------------------------------------------ report
def test_financial_report_profit(client):
    main = main_branch()
    t, s = mk_teacher(main), mk_student(main)
    owner = make_user("owner", "boss")
    db.session.add(Payment(receipt_no="RCT-T-1", branch_id=main.id, student_id=s.id, session_id=AcademicSession.query.first().id,
                           amount=Decimal("5000"), mode="cash", paid_on=TODAY, received_by=owner.id))
    db.session.add(Payment(receipt_no="RCT-T-2", branch_id=main.id, student_id=s.id, session_id=AcademicSession.query.first().id,
                           amount=Decimal("999"), mode="cash", paid_on=TODAY, received_by=owner.id, status="cancelled"))
    db.session.commit()
    acc = accountant(client)
    acc.get("/finance/expenses")
    cat = ExpenseCategory.query.filter_by(name="Rent").one()
    acc.post("/finance/expenses/new", data=expense_form(cat, amount="1000"), content_type="multipart/form-data")
    boss = admin(client)
    set_salary(boss, "teacher", t, "fixed", base="700")
    boss.post("/payroll/generate", data={"m": PREV_ARG})
    p = Payroll.query.one()
    boss.post(f"/payroll/{p.id}/finalize")
    boss.post(f"/payroll/{p.id}/pay", data={"amount": "700", "mode": "cash", "paid_on": TODAY.isoformat()})
    r = rep.summary(TODAY, TODAY, main.id)
    assert (r["income"], r["expenses"], r["salary"], r["profit"]) == (Decimal("5000"), Decimal("1000"), Decimal("700"), Decimal("3300"))
    assert r["by_category"] == [("Rent", Decimal("1000"))]
    e = Expense.query.one()
    boss.post(f"/finance/expenses/{e.id}/cancel", data={"reason": "wrong"})
    assert rep.summary(TODAY, TODAY, main.id)["profit"] == Decimal("4300")
    assert len(rep.monthly_series(TODAY.replace(day=1), 6, main.id)) == 6
    assert boss.get("/finance/reports").status_code == 200 and acc.get("/finance/reports").status_code == 200
    assert boss.get("/finance/reports.xlsx").data[:2] == b"PK"
    stu = make_user("student", "sam")
    sc = client.application.test_client()
    login(sc, "sam")
    for url in ("/finance/reports", "/finance/expenses", "/payroll/"):
        assert sc.get(url).status_code == 403, url


# ------------------------------------------------------------------ attendance photo grid
def test_attendance_page_shows_student_photos_with_absent_button(client, app):
    from test_attendance import make_world, enroll, teacher_login, NEAR
    main, t, b, sess = make_world(client)
    with_photo, no_photo = mk_student(main, "Amit Photo"), mk_student(main, "Sita Plain")
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "blue").save(buf, "PNG")
    import os
    os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], "students"), exist_ok=True)
    with open(os.path.join(app.config["UPLOAD_FOLDER"], "students", "amit.png"), "wb") as fh:
        fh.write(buf.getvalue())
    with_photo.photo = "amit.png"
    db.session.commit()
    enroll(b, with_photo)
    enroll(b, no_photo)
    me = teacher_login(client, t)
    me.post(f"/attendance/session/{sess.id}/checkin", data=NEAR)
    html = me.get(f"/attendance/session/{sess.id}").data.decode()
    assert f"/students/{with_photo.id}/photo" in html and f"/students/{no_photo.id}/photo" not in html
    assert "Amit Photo" in html and "Sita Plain" in html and html.count("Absent</label>") == 2
    assert me.get(f"/students/{with_photo.id}/photo").status_code == 200       # the teacher can load the photo
    me.post(f"/attendance/session/{sess.id}/mark", data={f"status_{with_photo.id}": "present",
                                                         f"status_{no_photo.id}": "absent", **NEAR})
    from app.models import AttendanceRecord
    assert {r.student_id: r.status for r in AttendanceRecord.query} == {with_photo.id: "present", no_photo.id: "absent"}
