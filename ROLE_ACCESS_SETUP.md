# Role-based access setup

## Student access
- Students register through the normal registration form. Registration always assigns `role="user"`.
- Students can upload only `Research Paper` and `Academic Report` documents. The backend enforces this even if a request is sent outside Streamlit.

## Administrator access
- Certificate, marksheet, assignment, and other full-verification document types are administrator-only.
- Admin login now authenticates against the backend; typing any email/password no longer grants administrator access.
- Create or promote an administrator from the project root using the project's virtual environment:

  `python -m backend.create_admin`

  Enter the admin email and password when prompted. This is a local command, not a public API route.

## Important limitation
These changes enforce role boundaries and restrict certificate-code matching to the admin response. They do not, by themselves, implement a full corpus-based plagiarism detector. The existing document verification pipeline currently performs OCR, field extraction, rule-based checks, and AI consistency analysis; a true plagiarism feature needs text-similarity comparisons against prior permitted submissions or a reference corpus.
