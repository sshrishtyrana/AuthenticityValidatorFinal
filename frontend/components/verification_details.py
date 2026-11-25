"""Admin-facing rendering for stored document verification evidence."""
from __future__ import annotations

import streamlit as st

from components.cards import key_value_line
from components.tables import show_table
from utils.helpers import fmt_confidence, fmt_score, titleize


def _first_value(fields: dict, *keys: str):
    for key in keys:
        value = fields.get(key)
        if value not in (None, "", [], {}):
            return value
    return "-"


def render_verification_details(verification: dict | None) -> None:
    if not verification:
        st.info("Verification has not produced a stored result for this submission yet.")
        return

    details = verification.get("details") or {}
    report = details.get("verification_report") or {}
    extracted = details.get("extracted_fields") or report.get("extracted_fields") or {}
    code_check = (
        report.get("certificate_code_check")
        or details.get("certificate_code_check")
        or {}
    )
    exact_duplicate = details.get("exact_file_duplicate_check") or {}

    key_value_line([
        ("Extracted student name", _first_value(extracted, "student_name", "name", "candidate_name", "full_name")),
        ("Certificate ID", _first_value(extracted, "certificate_number", "certificate_id", "serial_number", "registration_number")),
        ("Course", _first_value(extracted, "course", "program", "qualification", "degree")),
        ("Issuing organisation", _first_value(extracted, "issuing_organization", "issuing_organisation", "institution", "university", "board")),
        ("OCR confidence", fmt_confidence(verification.get("ocr_confidence"))),
        ("Overall score", fmt_score(verification.get("overall_score"))),
        ("Authenticity score", fmt_score(verification.get("authenticity_score"))),
        ("Similarity score", fmt_score(verification.get("similarity_score"))),
        ("Backend verdict", verification.get("verdict") or "Not available"),
    ])

    if exact_duplicate:
        st.markdown("**Exact-file duplicate check**")
        st.write("Duplicate detected" if exact_duplicate.get("is_duplicate") else "No exact-file duplicate detected")
        if exact_duplicate.get("reference_id") is not None:
            st.write(f"Matching reference: document #{exact_duplicate['reference_id']}")

    matches = code_check.get("matches") or []
    if code_check:
        st.markdown("**Certificate-code matching**")
        st.write(code_check.get("message") or "Certificate-code comparison was performed.")
        if matches:
            show_table(
                [
                    {
                        "document_id": item.get("document_id"),
                        "filename": item.get("filename"),
                        "student": item.get("student_name"),
                        "certificate_number": item.get("certificate_number"),
                        "same_identity": item.get("same_identity"),
                    }
                    for item in matches
                ],
                {
                    "document_id": "Matching document",
                    "filename": "File",
                    "student": "Student",
                    "certificate_number": "Matched certificate ID",
                    "same_identity": "Same identity",
                },
            )

    llm = details.get("llm_consistency_analysis") or report.get("llm_consistency_analysis") or {}
    if llm:
        with st.expander("Ollama consistency explanation"):
            st.write(llm.get("message") or titleize(llm.get("status")))
            for finding in llm.get("findings") or []:
                st.write(f"• {finding}" if isinstance(finding, str) else finding)

    if extracted:
        with st.expander("All extracted fields"):
            show_table(
                [{"field": titleize(key), "value": value} for key, value in extracted.items()],
                {"field": "Field", "value": "Extracted value"},
            )

    warnings = details.get("ocr_warnings") or report.get("ocr_warnings") or []
    if warnings:
        with st.expander("OCR warnings"):
            for warning in warnings:
                st.write(f"• {warning}")
