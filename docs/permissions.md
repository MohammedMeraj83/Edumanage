# Roles

| Role | URL prefix | Scope |
|---|---|---|
| Owner | /owner | All branches, all permissions |
| Branch Admin | /branch-admin | Own branch, all modules except institute/branches/users/backups/audit/settings/website |
| Accountant | /accountant | Own branch: fees, payments, expenses, salary, reports |
| Teacher | /teacher | Own branch: attendance, homework, materials, timetable, document library (view); exams (view only) and marks entry for own batches |
| Student | /student | Own records only |
| Parent | /parent | Own children only |

Defaults live in `app/utils/permissions.py`. Re-run `flask seed` after adding modules
(new permission codes are added; existing role mappings are not overwritten).

## Phase 2 URLs (Owner only)
/owner/dashboard · /owner/branches/ · /owner/branches/new · /owner/branches/<id> ·
/owner/institute · /owner/sessions

## Phase 3 URLs
/admissions/ · /admissions/new · /admissions/<id> · /admissions/<id>/approve ·
/students/ · /students/<id> · /students/<id>/edit · /students/<id>/transfer (owner only)

Branch Admin: full access in own branch. Accountant: view students and admissions.
Teacher: view students. Student / Parent: no access to these pages.

## Phase 4 URLs
/teachers/ · /staff/ · /parents/ (+ /new, /<id>, /<id>/edit, /<id>/status ...)
Branch Admin manages teachers, staff and parents of own branch. Owner manages all and picks the branch.
Teacher / Student / Parent dashboards show only their own linked profile.
IDs: teacher TCH000001, staff STF000001, parent PAR000001 (institute-wide, never reused).

## Phase 5 URLs
/academics/courses · /academics/subjects · /academics/rooms · /batches/ · /batches/<id> · /timetable/
Courses and subjects: Owner edits, Branch Admin views. Batches, rooms, timetable: Branch Admin of that branch
(Owner picks a branch). Teacher: sees only own batches and own timetable (view only).

## Phase 6 URLs
/attendance/live · /attendance/reports · /attendance/location · /attendance/qr · /attendance/my ·
/attendance/session/<id> · /attendance/scan/<token> · /leave/ · /student/attendance · /parent/child/<id>/attendance

Rules (config.py -> ATTENDANCE_RULES): teacher may start a lecture 15 min before it begins; arriving up to 5 min after
the start is "on time"; students may check in from 10 min before; teacher may edit attendance until 60 min after the
lecture ends (afterwards only Branch Admin / Owner, recorded in the audit log); GPS accuracy must be 100 m or better and
the person must be inside the branch circle (default 100 m).

## Phase 7 URLs
/fees/ · /fees/student/<id> · /fees/collect/<id> · /fees/pending · /fees/payments · /fees/receipt/<id>(.pdf) · /fees/settings
Owner, Branch Admin, Accountant: collect fees, see dues, receipts, pending list, Excel exports.
Owner and Branch Admin only: discounts, cancelling a due, cancelling a payment, refunds, fee settings, entering a
payment older than 30 days. Students and parents see only their own fees and receipts (/student/fees, /parent/child/<id>/fees).
Money rules: payments are never edited or deleted - a mistake is cancelled with a reason, returned money is a refund.

## Phase 8 URLs
/finance/expenses · /finance/categories · /finance/reports · /payroll/ · /payroll/structures · /payroll/<id> · /payroll/my
Owner, Branch Admin, Accountant: add expenses, see reports, make payroll drafts, adjust drafts, pay finalized salaries.
Owner and Branch Admin only: set salaries, finalize or cancel payroll, cancel a salary payment, cancel an expense,
manage expense categories. Teachers and accountants see only their own finalized salary slips (/payroll/my).

## Phase 9 URLs (exams)
/exams/ · /exams/new · /exams/<id> · /exams/<id>/edit · /exams/<id>/papers · /exams/paper/<id>/marks ·
/exams/paper/<id>/unlock · /exams/<id>/publish · /exams/<id>/results (+ .xlsx) · /exams/<id>/marksheet/<student_id> (+ .pdf)
Student: /student/results · /student/results/<exam_id> (+ .pdf). Parent: /parent/child/<id>/results · .../results/<exam_id> (+ .pdf).

Owner / Branch Admin: create exams, add papers, enter or unlock marks, publish, see all results of their branch.
Teacher: sees only exams that contain a paper of their own batch; enters and submits marks for their own papers only.
Accountant: no access. Student / Parent: only published results of themselves (parent: own children).

## Phase 10 URLs (homework and materials)
/homework/ · /homework/new · /homework/<id> · /homework/<id>/edit · /homework/<id>/check · /homework/<id>/file ·
/materials/ · /materials/new · /materials/<id>/edit · /materials/<id>/file
Student: /student/homework · /student/homework/<id> · /student/materials.
Parent: /parent/child/<id>/homework · /parent/child/<id>/homework/<hw_id>.

Owner: all branches. Branch Admin: own branch. Teacher: only batches they teach. Accountant: no access.
Student: batches they are enrolled in. Parent: homework (not materials) of their own children.

## Phase 11 URLs (ID cards, certificates, documents)
/id-cards/ · /id-cards/issue/<kind>/<id> · /id-cards/card/<id>.pdf · /id-cards/bulk
/certificates/ · /certificates/new · /certificates/issue/<student_id> · /certificates/<id> (+ .pdf) · /certificates/<id>/cancel
/documents/ (library) · /documents/new · /documents/<id>/file · /documents/papers (uploaded papers of students and staff)
Public (no sign-in, rate limited): /verify/id/<token> · /verify/certificate/<token>
Student: /student/documents (+ certificate and ID card PDFs). Parent: /parent/child/<id>/documents.

Owner and Branch Admin: ID cards, certificates, document center (Branch Admin: own branch only).
Teacher: read the library (teachers / everyone documents). Accountant: no access.
Student and Parent: only their own certificates and ID card, and library files meant for students and parents.

## Phase 15 public website
`/` · `/about` · `/courses` · `/branches` · `/p/<slug>` · `/website-admin/`

Owner can grant a selected user both `website.view` and `website.edit` permissions.
The granted user sees Website Admin in the management sidebar. Public pages require no sign-in.

## Phase 13 URLs (physical library)
`/library/` · `/library/new` · `/library/<id>/edit` · `/library/<id>/issue` · `/library/issues` · `/library/my`

Owner: every branch. Branch Admin: own branch only. Staff can issue and return books.
Teacher, Student and Parent: view their own issue history through `/library/my`.
