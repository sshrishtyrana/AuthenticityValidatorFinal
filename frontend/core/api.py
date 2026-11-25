"""The only module that talks to the FastAPI backend.

Every page calls a function from here; no page imports ``requests``.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests
import streamlit as st

from core import session
from utils.constants import API_BASE_URL, REQUEST_TIMEOUT, VERIFY_TIMEOUT


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    """Raised for any failed backend call."""

    def __init__(self, status_code: int, message: str, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail


def _detail_to_message(detail: Any, fallback: str) -> str:
    """FastAPI 'detail' can be a string, a dict or a list of validation errors."""
    if detail is None:
        return fallback
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail") or fallback
        reference = detail.get("reference_id")
        if reference:
            message += f" (existing record #{reference})"
        return message
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                where = ".".join(str(p) for p in item.get("loc", []) if p != "body")
                parts.append(f"{where}: {item.get('msg')}" if where else str(item.get("msg")))
            else:
                parts.append(str(item))
        return "; ".join(parts) or fallback
    return str(detail)


_STATUS_FALLBACKS = {
    400: "The request was not accepted.",
    401: "You are not signed in or your session has expired.",
    403: "You do not have permission to do this.",
    404: "The requested record was not found.",
    409: "This conflicts with an existing record.",
    413: "The file is larger than the allowed limit.",
    415: "This file type is not supported.",
    422: "Some of the submitted values are invalid.",
    500: "The server could not complete the request.",
}


# ---------------------------------------------------------------------------
# Core request function
# ---------------------------------------------------------------------------
def _request(
    method: str,
    path: str,
    *,
    auth: bool = True,
    json_body: Optional[dict] = None,
    data: Optional[dict] = None,
    files: Optional[dict] = None,
    timeout: int = REQUEST_TIMEOUT,
) -> Any:
    headers = {"Accept": "application/json"}

    if auth:
        token = session.get_token()
        if not token:
            raise ApiError(401, _STATUS_FALLBACKS[401])
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            headers=headers,
            json=json_body,
            data=data,
            files=files,
            timeout=timeout,
        )
    except requests.ConnectionError as exc:
        raise ApiError(
            0,
            f"Cannot reach the backend at {API_BASE_URL}. "
            "Start it with: uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload",
        ) from exc
    except requests.Timeout as exc:
        raise ApiError(408, "The backend took too long to respond. Please try again.") from exc
    except requests.RequestException as exc:
        raise ApiError(0, f"Network error: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = None
        fallback = _STATUS_FALLBACKS.get(
            response.status_code,
            _STATUS_FALLBACKS[500] if response.status_code >= 500 else "Request failed.",
        )
        raise ApiError(response.status_code, _detail_to_message(detail, fallback), detail)

    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(500, "The backend returned an unreadable response.") from exc


def report_error(error: ApiError, action: str = "") -> None:
    """Show an ApiError in the UI. Expired sessions return to the login page."""
    if error.status_code == 401 and session.get_token():
        session.logout("Your session has expired. Please sign in again.", "warning")
        st.rerun()

    prefix = f"{action}: " if action else ""
    text = f"{prefix}{error.message}"

    if error.status_code == 403:
        st.error(f"Access denied. {text}")
    elif error.status_code == 404:
        st.warning(f"Not found. {text}")
    elif error.status_code == 409:
        st.warning(f"Conflict. {text}")
    elif error.status_code >= 500 or error.status_code in (0, 408):
        st.error(f"Server problem. {text}")
    else:
        st.error(text)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
def health() -> bool:
    try:
        return _request("GET", "/health", auth=False, timeout=4).get("status") == "healthy"
    except ApiError:
        return False


# ---------------------------------------------------------------------------
# Authentication   (backend/routes/auth_routes.py)
# ---------------------------------------------------------------------------
def register(full_name: str, email: str, password: str) -> dict:
    return _request(
        "POST", "/auth/register", auth=False,
        json_body={"full_name": full_name, "email": email, "password": password},
    )


def login(email: str, password: str) -> dict:
    return _request(
        "POST", "/auth/login", auth=False,
        json_body={"email": email, "password": password},
    )


def get_me() -> dict:
    return _request("GET", "/auth/me")


def update_profile(fields: dict) -> dict:
    return _request("PATCH", "/auth/profile", json_body=fields)


# ---------------------------------------------------------------------------
# Assignments   (backend/routes/assignment_routes.py)
# ---------------------------------------------------------------------------
def create_assignment(payload: dict) -> dict:
    return _request("POST", "/assignments/", json_body=payload)


def admin_assignments() -> list[dict]:
    return _request("GET", "/assignments/admin/all").get("assignments", [])


def admin_assignment(assignment_id: int) -> dict:
    return _request("GET", f"/assignments/admin/{int(assignment_id)}")

def delete_assignment(assignment_id: int) -> dict:
    return _request("DELETE", f"/assignments/{int(assignment_id)}")
def my_assignments() -> list[dict]:
    return _request("GET", "/assignments/my").get("assignments", [])


def submit_assignment(assignment_id: int, filename: str, content: bytes, mime: str) -> dict:
    return _request(
        "POST",
        f"/assignments/{int(assignment_id)}/submit",
        files={"file": (filename, content, mime or "application/octet-stream")},
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Documents   (backend/routes/document_routes.py)
# ---------------------------------------------------------------------------
def upload_document(
    filename: str, content: bytes, mime: str, document_type: str, document_category: str
) -> dict:
    return _request(
        "POST", "/documents/upload",
        files={"file": (filename, content, mime or "application/octet-stream")},
        data={"document_type": document_type, "document_category": document_category},
        timeout=120,
    )


def verify_document(document_id: int) -> dict:
    return _request("POST", f"/documents/{int(document_id)}/verify", timeout=VERIFY_TIMEOUT)
def check_submission_plagiarism(submission_id: int) -> dict:
    return _request(
        "POST",
        f"/assignments/submissions/{int(submission_id)}/plagiarism-check",
        timeout=VERIFY_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# Admin overview (composed from the endpoints above; no extra backend needed)
# ---------------------------------------------------------------------------
def get_admin_overview(force: bool = False) -> dict:
    """Return {'assignments': [...], 'details': {id: detail}, 'loaded_at': ts}.

    ``details`` is fetched only for assignments that have submissions, because
    only those carry verification data. The result is cached in session state;
    pass force=True (the Refresh button) to reload.
    """
    cached = st.session_state.get("admin_overview")
    if cached and not force:
        return cached

    assignments = admin_assignments()
    details: dict[int, dict] = {}
    for item in assignments:
        if (item.get("submission_count") or 0) > 0:
            details[item["id"]] = admin_assignment(item["id"])

    overview = {"assignments": assignments, "details": details, "loaded_at": time.time()}
    st.session_state["admin_overview"] = overview
    return overview
def update_submission_review(
    submission_id: int,
    decision: str,
    notes: str = "",
) -> dict:
    return _request(
        "PATCH",
        f"/assignments/submissions/{int(submission_id)}/review",
        json_body={
            "decision": decision,
            "notes": notes,
        },
    )

def flatten_submissions(overview: dict) -> list[dict]:
    """One row per submission, enriched with assignment and student details."""
    rows: list[dict] = []
    for assignment in overview["assignments"]:
        detail = overview["details"].get(assignment["id"])
        if not detail:
            continue
        emails = {s["student_id"]: s.get("email") for s in detail.get("students", [])}
        for sub in detail.get("submissions", []):
            verification = sub.get("verification") or {}
            verification_details = verification.get("details") or {}
            exact_duplicate = verification_details.get("exact_file_duplicate_check") or {}
            verification_report = verification_details.get("verification_report") or {}
            code_check = (
                verification_report.get("certificate_code_check")
                or verification_details.get("certificate_code_check")
                or {}
            )
            has_code_match = bool(code_check.get("matches"))
            verdict = (verification.get("verdict") or "").casefold()
            review_status = (sub.get("review_status") or "").casefold()
            if exact_duplicate.get("is_duplicate") or has_code_match:
                detection_status = "Duplicate"
            elif verdict in {"flagged", "suspicious"} or review_status == "suspicious":
                detection_status = "Suspicious"
            elif verdict == "verified":
                detection_status = "Good to Go"
            elif verdict in {"manual review", "needs review"} or review_status == "needs_review":
                detection_status = "Needs Review"
            else:
                detection_status = "Pending checks"
            rows.append({
                "assignment_id": assignment["id"],
                "assignment_title": assignment["title"],
                "category": assignment.get("category"),
                "submission_id": sub.get("submission_id"),
                "student_id": sub.get("student_id"),
                "student_name": sub.get("student_name"),
                "student_email": emails.get(sub.get("student_id")),
                "document_id": sub.get("document_id"),
                "filename": sub.get("filename"),
                "document_type": sub.get("document_type"),
                "submitted_at": sub.get("submitted_at"),
                "review_status": sub.get("review_status"),
                "review_notes": sub.get("review_notes"),
                "reviewed_by": sub.get("reviewed_by"),
                "reviewed_at": sub.get("reviewed_at"),
                "verified": bool(verification),
                "verdict": verification.get("verdict"),
                "overall_score": verification.get("overall_score"),
                "authenticity_score": verification.get("authenticity_score"),
                "ocr_confidence": verification.get("ocr_confidence"),
                "detection_status": detection_status,
                "verification_details": verification_details,
                "verification": verification or None,
            })
    return rows
