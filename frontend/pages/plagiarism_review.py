
"""Admin-only plagiarism review."""
import streamlit as st

from components.tables import show_table
from core import api, session
from utils.constants import PLAGIARISM_DOCUMENT_TYPES
from utils.helpers import fmt_dt, norm_text, titleize

def render() -> None:
    page_header_text = (
        "Administrator-only review of research papers, assignments, "
        "project reports and academic reports."
    )
    st.title("Plagiarism review")
    st.caption(page_header_text)

    if st.button("Refresh data"):
        session.clear_admin_cache()
        st.rerun()

    try:
        with st.spinner("Loading submissions..."):
            overview = api.get_admin_overview()
    except api.ApiError as error:
        api.report_error(error, "Could not load submissions")
        return

    rows = [
        r for r in api.flatten_submissions(overview)
        if norm_text(r["document_type"]) in PLAGIARISM_DOCUMENT_TYPES
    ]

    st.subheader(f"Submissions ({len(rows)})")

    show_table(
        [
            {
                "Student": r["student_name"],
                "Email": r["student_email"],
                "Assignment": r["assignment_title"],
                "Document type": r["document_type"],
                "Filename": r["filename"],
                "Submitted": fmt_dt(r["submitted_at"]),
                "Review": titleize(r["review_status"]),
            }
            for r in rows
        ],
        {
            "Student": "Student",
            "Email": "Email",
            "Assignment": "Assignment",
            "Document type": "Document type",
            "Filename": "Filename",
            "Submitted": "Submitted",
            "Review": "Review",
        },
        "No research papers, assignments, project reports or academic reports found.",
    )

    st.divider()
    st.subheader("Run plagiarism check")

    if not rows:
        return

    for row in rows:
        submission_id = row["submission_id"]

        with st.container(border=True):
            st.write(f"**{row['filename']}**")
            st.caption(
                f"Student: {row['student_name']} | "
                f"Submission ID: {submission_id}"
            )

            result_key = f"plagiarism_result_{submission_id}"

            if st.button(
                "Check plagiarism",
                key=f"plagiarism_check_{submission_id}",
            ):
                try:
                    with st.spinner("Comparing documents..."):
                        result = api.check_submission_plagiarism(
                            submission_id
                        )
                    st.session_state[result_key] = result
                    st.success("Plagiarism comparison completed.")
                except api.ApiError as error:
                    api.report_error(error, "Plagiarism check failed")

            result = st.session_state.get(result_key)

            if result:
                score = result.get("similarity_percentage")

                if score is not None:
                    st.metric("Overall similarity", f"{score}%")

                    if score > 50:
                        st.warning("High similarity detected.")
                    elif score > 20:
                        st.info("Moderate similarity detected.")
                    else:
                        st.success("Low similarity detected.")

                comparisons = result.get("comparisons", [])

                if comparisons:
                    st.write("**Compared documents**")

                    for comparison in comparisons:
                        with st.expander(
                            f"{comparison.get('filename', 'Document')} "
                            f"— {comparison.get('similarity_percentage', 0)}%"
                        ):
                            st.write(
                                f"**Similarity:** "
                                f"{comparison.get('similarity_percentage', 0)}%"
                            )
                            st.write(
                                f"**Label:** "
                                f"{comparison.get('label', 'Not available')}"
                            )

                            matches = comparison.get(
                                "matching_sections", []
                            )

                            if matches:
                                st.write("**Matching passages**")

                                for index, match in enumerate(matches, 1):
                                    st.markdown(f"**Match {index}**")
                                    st.write(
                                        "Document being checked:",
                                        match.get("document_1_text", ""),
                                    )
                                    st.write(
                                        "Compared document:",
                                        match.get("document_2_text", ""),
                                    )
                                    st.caption(
                                        "Passage similarity: "
                                        f"{match.get('similarity_percentage', 0)}%"
                                    )
                                    st.divider()
                            else:
                                st.write("No matching passages returned.")
                else:
                    st.write("No comparison details returned.")

                st.caption(
                    "Similarity is a text-matching indicator, not a final "
                    "finding of plagiarism. A reviewer should examine the "
                    "matched passages before making a decision."
                )