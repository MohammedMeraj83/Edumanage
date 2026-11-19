from datetime import date, timedelta
from app.models import (Branch, LibraryBook, LibraryIssue, Student, AcademicSession)
from conftest import add_branch, login, make_user
from extensions import db


def make_student(username="librarystudent", branch_code="MAIN"):
    user = make_user("student", username, branch_code=branch_code)
    branch = Branch.query.filter_by(code=branch_code).one()
    session = AcademicSession.query.filter_by(is_current=True).one()
    student = Student(student_code="LIB" + username[-4:].upper(), admission_no="ADM" + username,
                      branch_id=branch.id, session_id=session.id, user_id=user.id,
                      status="active", admitted_on=date.today(), full_name=username.title(),
                      dob=date(2010, 1, 1), gender="other", class_name="Class 10",
                      guardian_phone="9876543210")
    db.session.add(student)
    db.session.commit()
    return user, student


def test_owner_adds_book_and_branch_admin_manages_only_own_branch(client):
    city = add_branch("CITY1", "City Branch")
    make_user("owner", "boss")
    login(client, "boss")
    response = client.post("/library/new", data={
        "branch_id": str(city.id), "title": "Mobile Science", "author": "A. Kumar",
        "isbn": "9781234567890", "category": "Science", "total_copies": "3",
        "shelf_location": "Rack A"
    })
    assert response.status_code == 302
    book = LibraryBook.query.one()
    assert (book.branch_id, book.available_copies, book.total_copies) == (city.id, 3, 3)

    make_user("branch_admin", "cityadmin", branch_code="CITY1")
    other = client.application.test_client()
    login(other, "cityadmin")
    assert other.get("/library/").status_code == 200
    assert b"Mobile Science" in other.get("/library/").data


def test_issue_return_and_mobile_portal(client):
    user, student = make_student()
    make_user("branch_admin", "manager")
    login(client, "manager")
    branch = Branch.query.filter_by(code="MAIN").one()
    book = LibraryBook(branch_id=branch.id, title="Maths Basics", author="R. Sharma",
                       total_copies=2, available_copies=2, category="Maths")
    db.session.add(book)
    db.session.commit()

    due = (date.today() + timedelta(days=14)).isoformat()
    response = client.post(f"/library/{book.id}/issue", data={
        "member_kind": "student", "member_id": str(student.id), "due_date": due,
        "notes": "For exam practice"
    })
    assert response.status_code == 302
    issue = LibraryIssue.query.one()
    assert issue.member_name == student.full_name
    assert db.session.get(LibraryBook, book.id).available_copies == 1

    response = client.post(f"/library/issues/{issue.id}/return", data={"status": "returned"})
    assert response.status_code == 302
    assert db.session.get(LibraryIssue, issue.id).status == "returned"
    assert db.session.get(LibraryBook, book.id).available_copies == 2

    own = client.application.test_client()
    login(own, "librarystudent")
    page = own.get("/library/my")
    assert page.status_code == 200 and b"Maths Basics" in page.data


def test_issue_rejects_unavailable_and_duplicate_member(client):
    make_user("branch_admin", "manager")
    login(client, "manager")
    _, student = make_student()
    branch = Branch.query.filter_by(code="MAIN").one()
    book = LibraryBook(branch_id=branch.id, title="One Copy", author="Author",
                       total_copies=1, available_copies=1)
    db.session.add(book)
    db.session.commit()
    due = (date.today() + timedelta(days=7)).isoformat()
    data = {"member_kind": "student", "member_id": str(student.id), "due_date": due}
    assert client.post(f"/library/{book.id}/issue", data=data).status_code == 302
    assert client.post(f"/library/{book.id}/issue", data=data).status_code == 200


def test_branch_admin_cannot_edit_another_branch_book(client):
    city = add_branch("CITY1", "City Branch")
    make_user("branch_admin", "manager")
    login(client, "manager")
    book = LibraryBook(branch_id=city.id, title="City Book", author="Author", total_copies=1,
                       available_copies=1)
    db.session.add(book)
    db.session.commit()
    assert client.get(f"/library/{book.id}/edit").status_code == 403
