# EduManage

Complete tuition management system — single institute, multiple branches, six roles.
Stack: Flask · MySQL · SQLAlchemy · Bootstrap 5 · vanilla JS.

## Phase 1 status (foundation)
Done: project setup, MySQL config, app factory, 11 core tables, authentication
(login, logout, lockout, forced password change, audit + login logs), 6 roles,
permission system (`module.action`), branch isolation helpers, role dashboards, tests.

## Phase 2 status (Owner dashboard + branch management)
Done: mobile-friendly app shell (slide-in menu on phones, tables turn into cards),
owner dashboard (stats, branch cards, recent activity), branch add / edit / activate / deactivate,
branch admin accounts (temporary password, reset, disable), institute profile with logo,
academic sessions (add, edit, make current). **No new database tables, so no migration is needed.**

## Phase 3 status (Admissions + Students)
Done: admission applications (walk-in or pending approval), approve / reject, automatic
admission number (e.g. `MAIN-2627-0001`) and institute-wide student ID (`STU000001`, never changes),
student list with search and filters, student profile, edit, active / inactive / left,
branch transfer with history, student login creation, photo and document uploads (private files),
parent / guardian details stored on the student (parent accounts come in Phase 4).
**New tables -> run the migration** (see below).

```bash
flask --app app db migrate -m "phase 3 admissions and students"
flask --app app db upgrade
```
Forgot / broke a password? `flask --app app reset-password USERNAME` (no SQL needed).

## Phase 4 status (Teachers, Staff, Parents)
Done: teacher and staff records (with branch, photo, documents, status), sign-in accounts for
teachers and accountants, parent accounts created from a student's guardian details (siblings share one parent
by phone number), link / unlink children, role dashboards for teacher, student, parent and branch admin.
**New tables** (teachers, staff, employee_documents, parents, student_parents): run `flask --app app init-db`.
Salary details are added in Phase 8.

## Phase 5 status (Courses, Batches, Timetable)
Done: courses and subjects (starter set for Class 8-10, 11-12, NEET, JEE, MHT-CET), rooms, batches
(one subject + one teacher + own fee), student enrollment (a student can be in many batches, each with its own fee),
seat limit, male / female count per batch, weekly timetable with clash checks (teacher, room, batch, and the student's
own other batches), teacher / student / parent dashboards with today's lectures, branch-transfer ends old seats.
**New tables** (courses, subjects, course_subjects, rooms, batches, batch_students, timetable_slots):
run `flask --app app init-db`, then `flask --app app sync-permissions` (teachers become view-only on timetable).

## Phase 6 status (Attendance, location, leave)
Done: lecture sessions made from the timetable, branch location + QR code, teacher start-class check-in (QR + GPS),
on-time / late tracking, student attendance by teacher (location checked), student self check-in (GPS), live board,
teacher punctuality and batch attendance reports, leave requests (teacher / student / parent) with approval,
attendance pages for student and parent.
**New tables** (branch_geo, lecture_sessions, attendance_records, leave_requests): run `flask --app app init-db`.
**Location needs HTTPS.** Phones only share GPS on `https://` pages (or localhost). Deploy to a host with HTTPS
(Render gives it free) before testing check-in on phones. Admin must set the branch location first
(Location & QR page, standing inside the tuition).

## Phase 7 status (Fees, payments, receipts)
Done: fee dues made automatically when a student joins a batch (monthly / per quarter / yearly / one-time, or
"pay the whole fee now" with an optional discount), collecting full or part payments (cash, UPI, card, bank, cheque),
receipt numbers per branch and session, printable receipt page and PDF, pending-fees list, payment history,
Excel exports, discount / cancel due / cancel payment / refund (owner and branch admin only), custom charges
(late fee, books, test series), settings for the monthly due day, student and parent fee pages with receipts.
**New tables** (fee_dues, payments, payment_allocations, refunds): run `flask --app app init-db`.
Then run `flask --app app sync-permissions` and `flask --app app generate-dues` (creates dues for students who were
already in batches).
Receipt PDFs use reportlab, so no extra system libraries are needed on Windows.

## Phase 8 status (Expenses, salary, payroll, financial report)
Done: expenses with categories and bill upload, salary setup per person (fixed, per lecture, or fixed + per lecture,
optional deduction per missed lecture), monthly payroll drafts built from attendance (lectures taught and missed),
adjustments (allowance, bonus, deduction with a note), finalize, part or full salary payments, salary slips (page + PDF),
teachers see their own slips, financial report (fees received, expenses, salaries, profit, last 6 months chart,
branch-wise comparison for the owner), Excel exports. Attendance page now shows each student's photo and name with
Present / Late / Absent buttons under it.
**New tables** (expense_categories, expenses, salary_structures, payrolls, salary_payments):
run `flask --app app init-db`.

## Phase 9 status (Exams, marks, results, marksheets)
Done: exams per branch and session (unit test, monthly, mid-term, final, mock), one paper per batch with date, time,
maximum and passing marks (add many batches at once), marks entry per paper (write `AB` for absent, blank = not entered;
one wrong cell saves nothing), teachers enter marks only for their own batches and submit (lock) the paper, only an admin
can unlock, results with total, percentage, grade (A+ to F), pass / fail (failing any paper fails the exam), rank (ties share a
rank) and a subject summary (average, highest, passed), publish / unpublish (every paper must be submitted first; students and
parents see nothing until published; a published exam is frozen), printable marksheet page and PDF, Excel export of the whole
exam, "Marks to enter" box on the teacher dashboard, "My results" for students and "Results" for each child on the parent page.
The grade scale is `GRADE_SCALE` at the top of `app/services/exam_service.py`.
**Permissions changed:** teachers can now only *view* exams and enter marks (no create / edit / delete of exams).
**New tables** (exams, exam_papers, exam_marks): run `flask --app app init-db`,
then `flask --app app sync-permissions` (applies the new teacher permissions).

## Phase 10 status (Homework and study materials)
Done: **Homework** is given to one batch with title, details, last date and an optional file (PDF, image, Word, PowerPoint,
Excel, text, up to 10 MB). The teacher gets a **checking sheet**: Done / Partly done / Not done per student with a short remark
(blank = not checked yet). Homework list shows due labels ("Due tomorrow") and how many students are checked.
**Study materials** are files or links shared with one batch (links must start with http:// or https://).
Teachers work only with the batches they teach, branch admins with their branch, the owner with everything.
Students see homework and materials of the batches they are actively enrolled in (a student who left a batch stops seeing
new content), with their own check status. Parents see homework of their children (not materials) with the teacher's note.
Uploaded files are private: every download checks role, branch and enrolment, and the real file content is verified
(a `.pdf` must be a PDF, `.docx` a real Office file, and so on). Office files and text always download instead of opening in the browser.
**New tables** (homework, homework_checks, study_materials): run `python -m flask --app app init-db`.

## Phase 11 status (ID cards, certificates, document center)
Done:
- **ID cards** for students, teachers and staff: issue a card, print one (front and back, credit-card size) or tick many and
  print A4 sheets (10 a page, backs mirrored for double-sided printing). Cards are valid until the end of the current session.
  Replacing a damaged or lost card closes the old one. The QR on the back opens a public page that says whether the card is
  genuine, expired or no longer valid, and shows only name, role, ID, branch and validity (no photo, phone or address).
- **Certificates** (bonafide, character, course completion, transfer / leaving, achievement) with numbers like
  `CRT-MAIN-2627-0001`, a printable A4 PDF with QR code, and a public verification page. Pending fees block a transfer
  certificate unless the admin allows it. Certificates are never deleted: a wrong one is cancelled (stamped CANCELLED, number
  stays used) and a new one is issued.
- **Document center**: a library of circulars, forms, syllabus and rules shared with everyone, teachers only, or students and
  parents (per branch, or all branches by the owner), plus one searchable list of every paper uploaded on student, teacher and
  staff profiles.
- Students and parents get a **Documents** page: ID card, issued certificates and the library files meant for them.
Notes: names are printed with the standard PDF fonts, so use English (Latin) letters for names on cards and certificates.
Set `PUBLIC_BASE_URL` in `.env` when the app runs behind a proxy so QR codes open the real website address.
JSON column: certificates need MySQL 5.7 or newer.
**Permissions changed:** teachers can now see the document library (documents.view).
**New tables** (id_cards, certificates, institute_documents): run `python -m flask --app app init-db`,
then `python -m flask --app app sync-permissions`.

## Phase 12 status (Enquiries and in-app communication)
Done:
- **Enquiries** can be entered by staff from calls or walk-ins, or submitted through the public
  enquiry form at `/enquiries/public` (also linked from sign-in). Public submissions are rate-limited,
  require a phone number or email address, and can be assigned to an active branch or left unassigned.
- Staff can search and filter enquiries, track follow-up dates and notes, and move each enquiry through
  New, Contacted, Admitted or Closed. Branch admins only see enquiries assigned to their branch; the owner
  can see every branch and unassigned enquiries, and assign unassigned leads to an active branch.
- **Notices** can be published in-app to staff, students and parents, or one role, for one branch or all branches.
  Students, parents, teachers and staff receive an in-app notification inbox with unread counts and read status.
  Parents receive branch notices when at least one linked student belongs to that branch.
- In-app updates stream live while a page is open. Installable PWA push notifications can alert a phone
  when the app is closed, after the user installs the app, grants notification permission and subscribes.
  SMS and email delivery are not included.

**New tables** (enquiries, notices, notifications): run `python -m flask --app app init-db`,
then `python -m flask --app app sync-permissions`.
The public enquiry page is available before the Phase 15 public website is built.

## Phase 13 status (Library management)
Done:
- Branch-wise physical book catalogue with title, author, ISBN, category, publisher, edition, shelf location,
  total copies and live available-copy count.
- Owners and branch admins can add and edit books, and search the catalogue by title, author or ISBN.
- Issue books to active students, teachers or staff with a due date and notes. An unavailable or duplicate active
  issue is rejected. The issue register supports search and status filters.
- Mark issued copies as returned or lost; closing an issue restores the copy and calculates a ₹5-per-day overdue fine
  for returns after the due date.
- Students, teachers and parents can open a mobile-friendly `My library` view showing their current and returned issues.
  Branch admins see only their branch, while the owner sees every branch.

**New tables** (library_books, library_issues): run `python -m flask --app app init-db`,
then `python -m flask --app app sync-permissions`.

## Phase 14 status (Online classes and exams)
Done:
- Staff can schedule branch/batch online classes with a secure external meeting URL, date, time, duration and description.
  Teachers are restricted to batches they teach; branch admins see their own branch and owners see every branch.
- Mobile-friendly class pages show live, scheduled, completed and cancelled states, with one-tap join and status controls.
- Staff can create published MCQ online exams for batches, set the exam window and duration, passing marks and instructions,
  add four-option questions and assign marks to each question.
- Active students can open published exams only during the configured window, answer every question and submit once.
- Answers are scored immediately and the student receives obtained/total marks, passing status and submission time.

**New tables** (online_classes, online_exams, online_exam_questions, online_exam_attempts, online_exam_answers):
run `python -m flask --app app init-db`, then `python -m flask --app app sync-permissions`.

## Automatic event notifications
Owner, branch admin, teacher and student actions now create relevant in-app notifications automatically.
The recipients are resolved by the affected batch or branch:
- Batch create/edit/status and student enrolment: active batch students, their parents, batch teacher, branch admins and owner.
- Homework and study material: active batch students, their parents, batch teacher and branch management.
- Regular and online exam publication: enrolled students, their parents, the batch teacher and branch management.
- Online class creation/status changes and student exam submission: relevant batch users and branch management.
- Library issues and returns: the member plus linked parents for student members, while branch management and owner are also notified.
- Each notification also appears live in the inbox and triggers a browser push when that user has enabled phone alerts.

## Public website and Website Admin
The public institute website is available at `/` and is mobile-first. It includes home, about, courses,
branches and the public enquiry form. The owner can edit home-page content and custom published pages
from `/website-admin/`.

Owner can grant or revoke a specific person's `website.view` permission. The grant is user-specific, so
only that person gains Website Admin access; branch admins, teachers and other staff do not receive it
automatically. A granted user will see **Website Admin** in their management sidebar and can open the
panel after signing in. Website editing still requires `website.edit` permission.

**New tables** (website_pages, website_settings, user_permissions): run `python -m flask --app app init-db`,
then `python -m flask --app app sync-permissions`.

## Installable app and phone notifications
Serve the app over **HTTPS** (or `localhost` while developing); browsers do not allow service workers or web push
on ordinary HTTP sites. After signing in, use **Install app** (or the browser's Add to Home Screen menu on iPhone).
When the installed app opens, it shows an **Allow notifications** prompt if phone alerts are not enabled. Tap it to
open the browser's permission dialog; browsers require this explicit user action and do not allow an app to force
the native permission dialog without a tap. On iPhone/iPad, use iOS/iPadOS 16.4 or newer and open the installed
Home Screen app.

Generate a VAPID key pair once:
```bash
flask --app app generate-vapid-keys
```
Copy the printed values into the private `.env` file and set `VAPID_CLAIMS_EMAIL` to a real contact email.
Restart the app after editing `.env`. Never publish or commit `VAPID_PRIVATE_KEY`. Browser notifications are delivered
through the browser's push service; the in-app inbox continues to work without VAPID keys or notification permission.
Keep the public and private values from the same generated pair. If changing keys, disable phone alerts and enable them
again on each phone. Notification sound and vibration follow the phone's browser/OS notification settings; the app
requests vibration where supported but cannot override a device's silent mode.
An HTTP `POST /notifications/push-subscriptions` response of `201` means that the browser which made that request
successfully registered its push endpoint with the app server. It does not confirm delivery to a different device.
Open the installed app on every phone and enable notifications there; notifications are sent to registered devices
belonging to the notice recipient.

The service worker handles push alerts and notification clicks; authenticated pages use Server-Sent Events to update
the inbox and unread count without refreshing. Private pages are not cached for offline use.

## Setup
```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then edit DB_* values and SECRET_KEY
```
WeasyPrint needs system libraries on Linux/macOS (Pango). It is only used from Phase 7+,
so if install fails now, remove it from requirements.txt temporarily.

## Database
```sql
CREATE DATABASE edumanage CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
```bash
flask --app app db init           # first time only
flask --app app db migrate -m "phase 1 foundation"
flask --app app db upgrade
flask --app app seed              # roles, permissions, institute, main branch, owner
flask --app app run
```
Open http://127.0.0.1:5000 and sign in with OWNER_USERNAME / OWNER_PASSWORD from `.env`.
You will be asked to change the password on first login.

## Tests
```bash
pytest
```
(Tests use in-memory SQLite, no MySQL needed. If an old `conftest.py` exists in the project root, delete it - tests/conftest.py replaces it.)

## Rules to follow in every later phase
1. Every branch-specific table gets `branch_id`; query through `scope_to_branch()`.
2. Protect routes with `@role_required(...)` or `@permission_required("module.action")`.
3. Call `log_action()` for create / update / delete of important records.
4. Never delete financial records — reverse them with a new entry.

 