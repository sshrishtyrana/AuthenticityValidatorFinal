
"""Admin: all submissions across assignments, with verification data."""

import streamlit as st

from components.cards import backend_gap, metric_grid, page_header
from components.verification_details import render_verification_details
from components.tables import SUBMISSION_COLUMNS, show_table, submission_rows
from core import api, session


def render() -> None:
    page_header(
        "Submission management",
        "Documents received from students and their stored verification results.",
    )

    if st.button("Refresh data"):
        session.clear_admin_cache()
        st.rerun()

    try:
        with st.spinner("Loading submissions..."):
            overview = api.get_admin_overview()
    except api.ApiError as error:
        api.report_error(error, "Could not load submissions")
        return

    rows = api.flatten_submissions(overview)
    assignments = overview["assignments"]

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        options = {
            "All assignments": None,
            **{
                f"#{a['id']} - {a['title']}": a["id"]
                for a in assignments
            },
        }
        selected = options[st.selectbox("Assignment", list(options))]

    with col2:
        verdict_filter = st.selectbox(
            "AI Verification Finding",
            ["All", "Verified", "Flagged", "Manual Review", "Not verified yet"],
        )

    with col3:
        review_filter = st.selectbox(
            "Admin Review Status",
            ["All", "pending", "verified", "suspicious", "needs_review"],
        )

    with col4:
        search = st.text_input("Search student or file")

    def keep(row: dict) -> bool:
        if selected is not None and row["assignment_id"] != selected:
            return False

        if verdict_filter == "Not verified yet" and row["verified"]:
            return False

        if verdict_filter not in ("All", "Not verified yet"):
            if (row["verdict"] or "").casefold() != verdict_filter.casefold():
                return False

        if review_filter != "All":
            if (row.get("review_status") or "pending") != review_filter:
                return False

        if search:
            needle = search.casefold()
            haystack = " ".join(
                str(row.get(key) or "")
                for key in (
                    "student_name",
                    "student_email",
                    "filename",
                )
            ).casefold()

            if needle not in haystack:
                return False

        return True

    filtered = [row for row in rows if keep(row)]

    metric_grid([
        ("Shown", len(filtered), f"of {len(rows)} total submissions"),
        (
            "AI Verified",
            sum(
                1 for row in filtered
                if (row.get("verdict") or "").casefold() == "verified"
            ),
            "",
            "ok",
        ),
        (
            "AI Flagged",
            sum(
                1 for row in filtered
                if (row.get("verdict") or "").casefold() == "flagged"
            ),
            "",
            "bad",
        ),
        (
            "Not verified yet",
            sum(1 for row in filtered if not row["verified"]),
            "",
            "warn",
        ),
    ])

    table_rows = submission_rows(filtered)

    show_table(
        table_rows,
        SUBMISSION_COLUMNS,
        "No submissions match the current filters.",
    )

    if table_rows:
        import pandas as pd

        csv = (
            pd.DataFrame(table_rows)
            .rename(columns=SUBMISSION_COLUMNS)
            .to_csv(index=False)
        )

        st.download_button(
            "Download this table (CSV)",
            csv,
            "submissions.csv",
            "text/csv",
        )

    if filtered:
        st.subheader("Submission evidence")

        for row in filtered:
            submission_id = row["submission_id"]

            with st.expander(
                f"{row.get('student_name') or 'Student'} — "
                f"{row.get('filename') or 'Document'}"
            ):
                st.write(
                    f"Detection status: "
                    f"**{row.get('detection_status', 'Pending checks')}**"
                )

                st.markdown("### AI Verification Findings")

                render_verification_details(
                    {
                        "overall_score": row.get("overall_score"),
                        "authenticity_score": row.get("authenticity_score"),
                        "ocr_confidence": row.get("ocr_confidence"),
                        "verdict": row.get("verdict"),
                        "details": row.get("verification_details") or {},
                    }
                    if row.get("verified")
                    else None
                )

                st.divider()
                st.markdown("### Admin Final Decision")

                current_status = row.get("review_status") or "pending"

                decision_options = {
                    "Pending": "pending",
                    "Verified": "verified",
                    "Suspicious": "suspicious",
                    "Needs Review": "needs_review",
                }

                current_label = next(
                    (
                        label
                        for label, value in decision_options.items()
                        if value == current_status
                    ),
                    "Pending",
                )

                decision = st.selectbox(
                    "Final Decision",
                    list(decision_options.keys()),
                    index=list(decision_options.keys()).index(current_label),
                    key=f"decision_{submission_id}",
                )

                notes = st.text_area(
                    "Review Notes",
                    value=row.get("review_notes") or "",
                    key=f"notes_{submission_id}",
                )

                if st.button(
                    "Save Final Decision",
                    key=f"save_decision_{submission_id}",
                    disabled=(decision == "Pending"),
                ):
                    try:
                        api.update_submission_review(
                            submission_id,
                            decision_options[decision],
                            notes,
                        )

                        session.clear_admin_cache()
                        st.success("Admin decision saved successfully!")
                        st.rerun()

                    except api.ApiError as error:
                        api.report_error(
                            error,
                            "Could not save admin decision",
                        )

                if row.get("reviewed_by"):
                    st.caption(
                        f"Last reviewed by: {row['reviewed_by']}"
                    )

                if row.get("reviewed_at"):
                    st.caption(
                        f"Last reviewed at: {row['reviewed_at']}"
                    )

    backend_gap(
        "Backend features still required",
        [
            "Downloading submitted files needs an admin/owner-protected "
            "GET /documents/{id}/file endpoint.",
            "An authenticity score may be blank until the backend "
            "verification engine calculates and stores one.",
        ],
    )
