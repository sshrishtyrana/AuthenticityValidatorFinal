"""Table helpers built on st.dataframe."""
from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from components.cards import empty_state
from utils.helpers import (
    STRETCH, fmt_confidence, fmt_dt, fmt_score, titleize,
)


def show_table(
    rows: list[dict],
    columns: dict[str, str],
    empty_message: str = "Nothing to show yet.",
    key: Optional[str] = None,
    height: Optional[int] = None,
) -> None:
    """Render rows as a table. ``columns`` maps row key -> display header."""
    if not rows:
        empty_state(empty_message)
        return
    frame = pd.DataFrame(rows)
    for column in columns:
        if column not in frame:
            frame[column] = None
    frame = frame[list(columns)].rename(columns=columns)
    options = {"height": height} if height else {}
    st.dataframe(frame, hide_index=True, key=key, **STRETCH, **options)


def assignment_rows(assignments: list[dict]) -> list[dict]:
    return [
        {
            "id": a["id"],
            "title": a["title"],
            "category": titleize(a.get("category")),
            "document_type": a.get("document_type"),
            "assigned": a.get("assigned_students", 0),
            "submissions": a.get("submission_count", 0),
            "start": fmt_dt(a.get("start_at"), "Immediately"),
            "deadline": fmt_dt(a.get("due_at"), "No deadline"),
            "status": titleize(a.get("status")),
        }
        for a in assignments
    ]


ASSIGNMENT_COLUMNS = {
    "id": "ID",
    "title": "Title",
    "category": "Category",
    "document_type": "Required document",
    "assigned": "Assigned students",
    "submissions": "Submissions",
    "start": "Start",
    "deadline": "Deadline",
    "status": "Status",
}


def submission_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "student": r.get("student_name"),
            "email": r.get("student_email"),
            "assignment": r.get("assignment_title"),
            "filename": r.get("filename"),
            "category": titleize(r.get("category")),
            "document_type": r.get("document_type"),
            "submitted": fmt_dt(r.get("submitted_at")),
            "review": titleize(r.get("review_status")),
            "detection": r.get("detection_status") or "Pending checks",
            "verification": r.get("verdict") or "Not verified yet",
            "ocr": fmt_confidence(r.get("ocr_confidence")) if r.get("verified") else "Not verified yet",
            "score": fmt_score(r.get("overall_score"), fallback="Not verified yet"),
        }
        for r in rows
    ]


SUBMISSION_COLUMNS = {
    "student": "Student",
    "email": "Email",
    "assignment": "Assignment",
    "filename": "Document",
    "category": "Category",
    "document_type": "Document type",
    "submitted": "Submitted",
    "review": "Review status",
    "detection": "Detection status",
    "verification": "AI Verification Finding",
    "ocr": "OCR confidence",
    "score": "Overall score",
}
