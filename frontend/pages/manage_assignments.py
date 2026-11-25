"""Admin: list assignments and inspect one in detail."""
import streamlit as st

from components.cards import backend_gap, key_value_line, page_header
from components.status_badges import assignment_status_badge, category_badge, review_status_badge, show_badges, verdict_badge
from components.verification_details import render_verification_details
from components.tables import (
    ASSIGNMENT_COLUMNS, SUBMISSION_COLUMNS, assignment_rows, show_table, submission_rows,
)
from core import api, session
from utils.helpers import fmt_dt, titleize


def render() -> None:
    page_header("Manage assignments", "Review every task, its recipients and the documents received.")

    if st.button("Refresh data"):
        session.clear_admin_cache()

    try:
        with st.spinner("Loading assignments..."):
            overview = api.get_admin_overview()
    except api.ApiError as error:
        api.report_error(error, "Could not load assignments")
        return

    assignments = overview["assignments"]

    col1, col2, col3 = st.columns(3)
    with col1:
        category = st.selectbox("Category", ["All", "Academic", "Admission"])
    with col2:
        status = st.selectbox("Status", ["All", "Published", "Draft", "Closed"])
    with col3:
        search = st.text_input("Search title")

    filtered = [
        a for a in assignments
        if (category == "All" or (a.get("category") or "").lower() == category.lower())
        and (status == "All" or (a.get("status") or "").lower() == status.lower())
        and (not search or search.casefold() in (a.get("title") or "").casefold())
    ]

    show_table(
        assignment_rows(filtered),
        ASSIGNMENT_COLUMNS,
        "No assignments match the filters." if assignments else "No assignments exist yet.",
    )
    if not filtered:
        return

    st.subheader("Assignment details")
    options = {f"#{a['id']} - {a['title']}": a["id"] for a in filtered}
    choice = st.selectbox("Open an assignment", list(options))
    assignment_id = options[choice]
    st.divider()
    st.subheader("Delete assignment")

    confirm_delete = st.checkbox(
        f"I confirm that I want to delete assignment #{assignment_id}",
        key=f"confirm_delete_{assignment_id}",
    )

    if st.button(
        "Delete assignment",
        type="primary",
        disabled=not confirm_delete,
        key=f"delete_assignment_{assignment_id}",
    ):
        try:
            with st.spinner("Deleting assignment..."):
                result = api.delete_assignment(assignment_id)

            session.clear_admin_cache()
            st.success(result.get("message", "Assignment deleted successfully."))
            st.rerun()

        except api.ApiError as error:
            api.report_error(error, "Could not delete assignment")

    try:
        with st.spinner("Loading details..."):
            detail = api.admin_assignment(assignment_id)
    except api.ApiError as error:
        api.report_error(error, "Could not load assignment")
        return

    show_badges(
        assignment_status_badge(detail.get("status")),
        category_badge(detail.get("category")),
    )
    key_value_line([
        ("Required document", detail.get("document_type") or "-"),
        ("Eligibility", titleize(detail.get("eligibility_type"))),
        ("Start", fmt_dt(detail.get("start_at"), "Immediately")),
        ("Deadline", fmt_dt(detail.get("due_at"), "No deadline")),
    ])
    criteria = [
        (label, detail.get(field)) for field, label in
        [("course", "Course"), ("department", "Department"), ("semester", "Semester"),
         ("academic_year", "Academic year"), ("admission_batch", "Admission batch")]
        if detail.get(field)
    ]
    if criteria:
        key_value_line(criteria)
    if detail.get("instructions"):
        st.markdown("**Instructions**")
        st.write(detail["instructions"])

    students = detail.get("students", [])
    submissions = detail.get("submissions", [])
    submitted_ids = {s.get("student_id") for s in submissions}

    tab_students, tab_subs = st.tabs(
        [f"Assigned students ({len(students)})", f"Submissions ({len(submissions)})"]
    )

    with tab_students:
        show_table(
            [
                {
                    "id": s["student_id"], "name": s["student_name"], "email": s["email"],
                    "submitted": "Yes" if s["student_id"] in submitted_ids else "No",
                }
                for s in students
            ],
            {"id": "Student ID", "name": "Name", "email": "Email", "submitted": "Submitted"},
            "No students are assigned to this task.",
        )

    with tab_subs:
        rows = [r for r in api.flatten_submissions({"assignments": [detail], "details": {detail["id"]: detail}})]
        show_table(
            submission_rows(rows), SUBMISSION_COLUMNS, "No documents have been submitted yet."
        )
        for row in rows:
            with st.expander(f"{row['student_name']} - {row['filename']}"):
                show_badges(review_status_badge(row["review_status"]), verdict_badge(row["verdict"]))
                key_value_line([
                    ("Student ID", row["student_id"]),
                    ("Email", row["student_email"] or "-"),
                    ("Document ID", row["document_id"]),
                    ("Submitted", fmt_dt(row["submitted_at"])),
                ])
                verification = row.get("verification")
                render_verification_details(verification)
        backend_gap("Backend features still required", [
            "Admin final decisions and review notes need a protected PATCH endpoint for AssignmentSubmission.review_status.",
            "Downloading the submitted file needs an admin/owner-protected GET /documents/{id}/file endpoint.",
            "An authenticity score may be blank until the backend verification engine calculates and stores one.",
        ])
