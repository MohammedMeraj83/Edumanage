# Phase 1 schema

| Table | Purpose |
|---|---|
| institutes | Single institute record |
| institute_settings | Key/value settings |
| branches | Branches (code unique, one is_main) |
| branch_settings | Per-branch key/value settings |
| roles | 6 fixed roles; owner has is_super |
| permissions | `module.action` codes (view/create/edit/delete) |
| role_permissions | Role <-> permission link |
| users | Login accounts; role_id, branch_id (NULL for owner) |
| academic_sessions | e.g. 2026-27, one is_current |
| audit_logs | Who did what, where, when |
| login_logs | Every login attempt (success/fail, IP) |

Later phases add students, parents, etc. with `branch_id` on branch-specific rows.


# Phase 9 tables (exams)

| Table | Purpose |
|---|---|
| exams | One exam of one branch + session (name unique per branch and session). `results_published` controls what students / parents can see |
| exam_papers | One paper per exam and batch (unique): date, optional time and duration, `max_marks`, `pass_marks`, `locked` (submitted by the teacher; only an admin unlocks) |
| exam_marks | A student's entry in a paper (unique per paper + student): `marks`, or `absent` = true. No row means not entered yet |

Results (totals, percentage, grade, rank) are calculated when needed from `exam_marks`, so they can never disagree with the marks.


# Phase 10 tables (homework and study materials)

| Table | Purpose |
|---|---|
| homework | Work given to one batch: title, details, `assigned_on`, `due_date`, optional private attachment |
| homework_checks | Teacher's note for one student on one homework (unique per homework + student): done / partial / not_done, remark. No row = not checked yet |
| study_materials | A file or a link shared with one batch. Files are stored privately under uploads/materials |


# Phase 11 tables (ID cards, certificates, document library)

| Table | Purpose |
|---|---|
| id_cards | Every ID card ever issued to a student / teacher / staff member (`person_kind` + `person_id`). One `active` card per person; replaced, lost or cancelled cards stay for history. `token` is the secret in the QR link |
| certificates | Certificates issued to students: unique `certificate_no`, type, `fields` (JSON with the type-specific details), status `issued` / `cancelled`. Never deleted |
| institute_documents | Institute document library files with category and audience (all / teachers / students). `branch_id` empty = every branch |

# Phase 15 tables (public website)

| Table | Purpose |
|---|---|
| website_pages | Published/unpublished public website pages and custom content |
| website_settings | Public home-page title, subtitle and call-to-action settings |
| user_permissions | User-specific extra permissions such as Website Admin access |

# Phase 14 tables (online classes and exams)

| Table | Purpose |
|---|---|
| online_classes | Scheduled batch meeting URL, time, duration and live status |
| online_exams | Published/draft batch exam window, instructions, duration and pass marks |
| online_exam_questions | Four-option MCQ questions, correct option and marks |
| online_exam_attempts | One submitted attempt per student per exam with total and obtained marks |
| online_exam_answers | Selected answer and correctness for each question |

# Phase 13 tables (physical library management)

| Table | Purpose |
|---|---|
| library_books | Branch-wise physical book catalogue, copy counts and shelf location |
| library_issues | Student, teacher or staff issue records with due date, return/lost status and fine |
