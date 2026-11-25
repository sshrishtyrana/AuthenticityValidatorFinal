# Authenticity Validator for Academia - Streamlit frontend

A role-based university portal on top of the existing FastAPI backend.
Admins create and manage document collection tasks and review submissions;
students complete assigned tasks and manage their profile. Assignment uploads trigger
backend verification automatically when the backend pipeline is enabled.

## Installation and run

From the project root (`Authenticity-Validator-for-Academia/`):

```bash
# 1. Backend (unchanged)
python -m backend.migrate_assignments      # once, adds profile columns / assignment tables
python -m backend.create_admin             # once, creates an administrator account
uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload

# 2. Frontend (second terminal)
pip install -r frontend/requirements.txt
streamlit run frontend/app.py
```

Optional environment variables: `AVA_API_URL` (default `http://127.0.0.1:8001`),
`AVA_TIMEZONE` (default `Asia/Kolkata`, used to display and enter dates).
Requires Streamlit 1.46 or newer.

## Structure

```
frontend/
  app.py                     entry point and role-checked router
  core/api.py                the ONLY module that calls the backend
  core/auth.py               sign-in and page access control
  core/session.py            JWT + state in st.session_state (never on disk)
  components/                sidebar, cards, tables, status badges
  pages/                     one module per screen
  utils/                     constants, formatting helpers, theme CSS
```

## Backend files inspected

`backend/main.py`, `database.py`, `models.py`, `auth.py`, `create_admin.py`,
`migrate_assignments.py`, `routes/auth_routes.py`, `routes/assignment_routes.py`,
`routes/document_routes.py`, `verification/duplicate_detector.py`,
`verification/verification_engine.py` (report and verdict values).

## API integration map

| Frontend screen | Backend call |
|---|---|
| Login | `POST /auth/login` (JSON `email`, `password`) |
| Register | `POST /auth/register` (creates role `user`) |
| Profile | `GET /auth/me`, `PATCH /auth/profile` |
| Create assignment | `POST /assignments/` |
| Admin dashboard, Manage, Submissions, Plagiarism list | `GET /assignments/admin/all`, `GET /assignments/admin/{id}` |
| Student dashboard, tasks, history | `GET /assignments/my` |
| Submit document | `POST /assignments/{id}/submit` (multipart `file`) |
| Student verification | `POST /documents/{id}/verify` |
| Admin verification tool | `POST /documents/upload`, `POST /documents/{id}/verify` |
| Login page health indicator | `GET /health` |

Errors 401 (returns to login), 403, 404, 409 (duplicate document), 413, 415,
422 and 500 are mapped to readable messages in `core/api.py`.

## Backend changes required (none were made)

The frontend works against the backend as it is, but these gaps limit features.
Each is shown in the UI where it matters; nothing is faked.

1. **Student list**: no endpoint lists students. Individual assignment needs IDs typed by hand,
   and "total registered students" cannot be shown.
   Add `GET /auth/students` (admin only) in `backend/routes/auth_routes.py`.
2. **Plagiarism**: no route, service or data. Add `backend/verification/plagiarism_detector.py`, then in a new
   `backend/routes/plagiarism_routes.py`: `POST /plagiarism/submissions/{id}/check` and
   `GET /plagiarism/submissions/{id}`. `VerificationResult.similarity_score` exists but is never filled.
3. **Admin final review workflow**: assignment uploads can run the verification pipeline automatically,
   and the admin UI displays the stored verification details. Final admin decisions and review notes
   still need a protected `PATCH /assignments/submissions/{id}/review` endpoint (status, notes, reviewer).
5. **Download**: no endpoint serves stored files. Add `GET /documents/{id}/file` (admin or owner).
6. **Authenticity score**: `authenticity_score` is never populated (the engine marks it uncalibrated)
   and `/assignments/admin/{id}` does not return it. The overall consistency score is shown instead.
7. **Publishing drafts**: no update endpoint for assignments; a draft cannot be published later.
8. **Assignment document type vs student verification**: students can verify only types in
   `STUDENT_DOCUMENT_TYPES`; use the document types listed in the Create Assignment form.
9. A student can submit more than once to the same task (backend does not prevent it); the UI allows one.

## Testing instructions

Admin: `python -m backend.create_admin`, sign in, then
1. Create Assignment: Academic, Marksheet, eligibility "All students", Published, future deadline.
2. Manage Assignments: open it; check the assigned students and submission counts.
3. After a student submits, the assignment upload route attempts automatic verification; open Submissions and Manage Assignments to inspect stored results.
4. Document Verification: upload a PDF or image and review the checks and extracted fields.
5. Plagiarism Review: confirms scope and lists missing backend pieces.

Student: use Create account, sign in, then
1. My Profile: fill course, department, academic year, semester, admission batch.
2. Assigned Tasks / Academic Documents / Admission Documents: open a task, upload a file, submit.
3. Submit the same file again: the duplicate (409) message appears.
4. Submission History: confirm the upload and review status. The admin can inspect stored verification evidence from Manage Assignments / Submissions.
5. Confirm admin pages and plagiarism review are not reachable from the student sidebar.

## Test status

The frontend was exercised end to end with Streamlit's `AppTest` against the real
`backend` routers (OCR libraries stubbed): registration, both logins, role guards,
profile update, assignment creation by course, task listing, submission, duplicate
(409), invalid type (415), role errors (403), missing record (404), student verification,
and the admin dashboard, manage, submissions and plagiarism pages. The real OCR pipeline,
file-upload widget clicks in a browser and visual styling were not exercised.
