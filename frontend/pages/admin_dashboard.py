"""Admin dashboard: metrics computed only from real backend responses."""
import time

import streamlit as st

from components.cards import backend_gap, metric_grid, page_header
from components.tables import ASSIGNMENT_COLUMNS, assignment_rows, show_table
from core import api, session


def render() -> None:
    page_header("Administrator dashboard", "Live overview of assignments, submissions and verification outcomes.")

    if st.button("Refresh data"):
        session.clear_admin_cache()

    try:
        with st.spinner("Loading dashboard..."):
            overview = api.get_admin_overview()
    except api.ApiError as error:
        api.report_error(error, "Could not load dashboard")
        return

    assignments = overview["assignments"]
    submissions = api.flatten_submissions(overview)

    published = sum(1 for a in assignments if (a.get("status") or "").lower() == "published")
    drafts = sum(1 for a in assignments if (a.get("status") or "").lower() == "draft")
    allocations = sum(a.get("assigned_students", 0) for a in assignments)

    verified = sum(1 for s in submissions if (s["verdict"] or "").casefold() == "verified")
    flagged = sum(1 for s in submissions if (s["verdict"] or "").casefold() == "flagged")
    manual = sum(1 for s in submissions if (s["verdict"] or "").casefold() == "manual review")
    pending = sum(1 for s in submissions if not s["verified"])

    st.subheader("Assignments")
    metric_grid([
        ("Total assignments", len(assignments), "All categories"),
        ("Published", published, "Visible to assigned students", "ok"),
        ("Drafts", drafts, "Not yet visible to students", "neutral"),
        ("Task allocations", allocations, "Student-task pairs created"),
    ])

    st.subheader("Document submissions")
    metric_grid([
        ("Total submissions", len(submissions)),
        ("Pending verification", pending, "No verification result stored yet", "warn"),
        ("Verified", verified, "Verdict: Verified", "ok"),
        ("Suspicious", flagged, "Verdict: Flagged", "bad"),
    ])
    metric_grid([("Requires review", manual, "Verdict: Manual Review", "warn")])

    st.subheader("Recent assignments")
    show_table(
        assignment_rows(assignments[:8]),
        ASSIGNMENT_COLUMNS,
        "No assignments have been created yet. Use Create Assignment to start.",
    )

    loaded = time.strftime("%H:%M:%S", time.localtime(overview["loaded_at"]))
    st.caption(f"Data loaded at {loaded}. Verdicts come from stored verification results.")

    with st.expander("Metrics the backend does not provide yet"):
        backend_gap("Not shown because no real data source exists", [
            "Total registered students: there is no student-list or count endpoint "
            "(suggested: GET /auth/students, admin only).",
            "Submission review status is always 'pending': no endpoint updates "
            "AssignmentSubmission.review_status.",
            "Verification only runs when a student (owner of the document) calls "
            "POST /documents/{id}/verify, so 'Pending verification' stays high until they do.",
        ])
