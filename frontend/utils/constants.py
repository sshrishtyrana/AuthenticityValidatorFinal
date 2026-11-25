"""Static configuration shared by the whole frontend."""
import os

# ---------------------------------------------------------------------------
# Backend connection
# ---------------------------------------------------------------------------
API_BASE_URL = os.getenv("AVA_API_URL", "http://127.0.0.1:8001").rstrip("/")
REQUEST_TIMEOUT = 30            # seconds, normal calls
VERIFY_TIMEOUT = 600            # OCR + verification can be slow
DISPLAY_TZ = os.getenv("AVA_TIMEZONE", "Asia/Kolkata")

# ---------------------------------------------------------------------------
# Files (mirrors backend/routes/document_routes.py)
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = ["pdf", "docx", "png", "jpg", "jpeg"]

# ---------------------------------------------------------------------------
# Roles (mirrors backend: admin / user / student)
# ---------------------------------------------------------------------------
ADMIN_ROLES = {"admin"}
STUDENT_ROLES = {"user", "student"}

# ---------------------------------------------------------------------------
# Assignment vocabulary
# ---------------------------------------------------------------------------
CATEGORIES = {"Academic": "academic", "Admission": "admission"}

DOCUMENT_TYPES_BY_CATEGORY = {
    "academic": [
        "Marksheet",
        "Certificate",
        "Degree certificate",
        "Transcript",
        "Academic certificate",
        "Research paper",
        "Academic report",
        "Assignment",
        "Project report",
        "Other academic document",
    ],
    "admission": [
        "ID proof",
        "Transfer certificate",
        "Migration certificate",
        "Entrance scorecard",
        "Admission form",
        "Passport",
        "Other admission document",
    ],
}

# label -> (backend eligibility_type, profile field that must be supplied)
ELIGIBILITY_OPTIONS = {
    "All students": ("all", None),
    "Individual students": ("individual", None),
    "Course": ("course", "course"),
    "Department": ("department", "department"),
    "Semester": ("semester", "semester"),
    "Academic year": ("academic_year", "academic_year"),
    "Admission batch": ("admission_batch", "admission_batch"),
}

PROFILE_FIELDS = {
    "course": "Course",
    "department": "Department",
    "academic_year": "Academic year",
    "semester": "Semester",
    "admission_batch": "Admission batch",
}

# Document types accepted by the admin-side upload endpoint
ADMIN_UPLOAD_TYPES = [
    "Auto Detect", "Certificate", "Marksheet", "Research Paper",
    "Academic Report", "Assignment", "Other",
]

# Types in scope for the (admin-only) plagiarism review
PLAGIARISM_DOCUMENT_TYPES = {
    "research paper", "assignment", "project report", "academic report",
}

APPROACHING_DEADLINE_DAYS = 3

# ---------------------------------------------------------------------------
# Navigation: (page key, sidebar label)
# ---------------------------------------------------------------------------
ADMIN_NAV = [
    ("admin_dashboard", "Dashboard"),
    ("create_assignment", "Create Assignment"),
    ("manage_assignments", "Manage Assignments"),
    ("submissions", "Submissions"),
    ("document_verification", "Document Verification"),
    ("plagiarism_review", "Plagiarism Review"),
]

STUDENT_NAV = [
    ("student_dashboard", "Dashboard"),
    ("student_tasks", "Assigned Tasks"),
    ("student_academic", "Academic Documents"),
    ("student_admission", "Admission Documents"),
    ("student_history", "Submission History"),
    ("student_profile", "My Profile"),
]

PAGE_ROLES = {
    **{key: "admin" for key, _ in ADMIN_NAV},
    **{key: "student" for key, _ in STUDENT_NAV},
}

DEFAULT_PAGE = {"admin": "admin_dashboard", "student": "student_dashboard"}

APP_NAME = "Authenticity Validator"
APP_TAGLINE = "Academic Document Collection and Verification Portal"
