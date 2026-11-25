"""Document verification UI.

The OCR / extraction / duplicate / verification pipeline runs in the backend.
This module only triggers it and displays what the backend returns.
"""
from __future__ import annotations

import streamlit as st

from components.cards import backend_gap, metric_card, page_header
from components.status_badges import show_badges, verdict_badge
from components.tables import show_table
from core import api
from utils.constants import ADMIN_UPLOAD_TYPES, ALLOWED_EXTENSIONS, CATEGORIES, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB
from utils.helpers import fmt_confidence, fmt_score, titleize


# ---------------------------------------------------------------------------
# Result display (shared by admin and student views)
# ---------------------------------------------------------------------------
def render_result(result: dict) -> None:
    verdict = result.get("verdict")
    report = result.get("report") or {}

    show_badges(verdict_badge(verdict))
    col1, col2, col3 = st.columns(3)
    with col1:
        metric_card("Overall consistency score", fmt_score(result.get("overall_score"), "/100"))
    with col2:
        metric_card("OCR confidence", fmt_confidence(result.get("ocr_confidence")))
    with col3:
        metric_card(
            "Authenticity score",
            fmt_score(result.get("authenticity_score")),
            "Not calibrated by the backend" if result.get("authenticity_score") is None else "",
            "neutral",
        )

    if report.get("summary"):
        st.info(report["summary"])
    st.caption(
        "The score measures consistency of the extracted evidence. It is not a proof of authenticity."
    )

    checks = report.get("checks") or []
    if checks:
        st.markdown("**Verification checks**")
        show_table(
            [
                {
                    "name": titleize(c.get("name")), "status": titleize(c.get("status")),
                    "points": c.get("points"), "message": c.get("message"),
                    "evidence": c.get("evidence") or "",
                }
                for c in checks
            ],
            {"name": "Check", "status": "Result", "points": "Points", "message": "Details", "evidence": "Evidence"},
        )

    fields = result.get("extracted_fields") or {}
    shown = [{"field": titleize(k), "value": v} for k, v in fields.items() if v not in (None, "")]
    if shown:
        st.markdown("**Extracted information**")
        show_table(shown, {"field": "Field", "value": "Value"})

    code_check = report.get("certificate_code_check")
    if code_check:
        st.markdown("**Certificate code check (administrator only)**")
        st.write(code_check.get("message", ""))
        if code_check.get("matches"):
            show_table(code_check["matches"], {
                "document_id": "Matching document", "filename": "File", "same_identity": "Same identity",
            })

    llm = result.get("llm_consistency_analysis") or {}
    if llm:
        with st.expander("Cross-document consistency analysis"):
            st.write(llm.get("message") or titleize(llm.get("status")))
            for finding in llm.get("findings") or []:
                st.write(f"- {finding}" if isinstance(finding, str) else finding)

    if result.get("ocr_text"):
        with st.expander("Extracted text"):
            st.text(result["ocr_text"][:20000])
    with st.expander("Raw backend response"):
        st.json(result)


# ---------------------------------------------------------------------------
# Student: verify one of their own submitted documents
# ---------------------------------------------------------------------------
def render_student_check(document_id: int, label: str = "") -> None:
    results = st.session_state.setdefault("verification_results", {})
    existing = results.get(document_id)

    if st.button(
        "Re-run verification" if existing else "Run verification",
        key=f"verify_{document_id}",
        help="Runs OCR, information extraction and the verification checks on the backend.",
    ):
        try:
            with st.spinner("Running OCR and verification. This can take a minute..."):
                response = api.verify_document(document_id)
        except api.ApiError as error:
            if error.status_code == 403:
                st.error(error.message)
            else:
                api.report_error(error, "Verification failed")
            return
        results[document_id] = response.get("verification_result", {})
        existing = results[document_id]
        st.success("Verification completed.")

    if existing:
        render_result(existing)
    else:
        st.caption("No verification has been run in this session.")


# ---------------------------------------------------------------------------
# Admin: upload and verify an administrator-owned document
# ---------------------------------------------------------------------------
def render() -> None:
    page_header(
        "Document verification",
        "Upload a document and run the backend OCR, extraction, duplicate and verification pipeline.",
    )

    with st.container(border=True):
        file = st.file_uploader(
            label=f"Document (PDF, DOCX, PNG, JPG or JPEG, up to {MAX_FILE_SIZE_MB} MB)",
            type=ALLOWED_EXTENSIONS,
            key="admin_verify_file",
        )
        col1, col2 = st.columns(2)
        with col1:
            document_type = st.selectbox("Document type", ADMIN_UPLOAD_TYPES)
        with col2:
            category_label = st.selectbox("Category", list(CATEGORIES))

        if st.button("Upload and verify", type="primary", disabled=file is None):
            content = file.getvalue()
            if len(content) > MAX_FILE_SIZE_BYTES:
                st.error(f"The file is larger than {MAX_FILE_SIZE_MB} MB.")
            else:
                try:
                    with st.status("Processing document...", expanded=True) as status:
                        st.write("Uploading and checking for duplicates...")
                        uploaded = api.upload_document(
                            file.name, content, file.type, document_type, CATEGORIES[category_label]
                        )
                        st.write("Running OCR and verification...")
                        response = api.verify_document(uploaded["document_id"])
                        status.update(label="Verification completed", state="complete")
                except api.ApiError as error:
                    api.report_error(error, "Verification could not be completed")
                else:
                    st.session_state["admin_verification"] = {
                        "filename": response.get("filename"),
                        "document_id": response.get("document_id"),
                        "result": response.get("verification_result", {}),
                    }

    last = st.session_state.get("admin_verification")
    if last:
        st.subheader(f"Result for {last['filename']} (document {last['document_id']})")
        render_result(last["result"])

    backend_gap("What this page covers", [
        "It verifies documents owned by the signed-in administrator. Student submissions are verified "
        "by the student from Submission History, because the backend verify endpoint only accepts the "
        "document owner. Their stored results appear on the Submissions page.",
        "Results are shown right after a run; the backend has no endpoint to fetch a stored result later.",
    ])
