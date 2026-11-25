"""Student: assigned tasks, category views, submission and history."""
from __future__ import annotations

from typing import Optional

import streamlit as st

from components.cards import empty_state, key_value_line, page_header
from components.status_badges import category_badge, show_badges, task_state_badge
from components.tables import show_table
from core import api, session

from utils.constants import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB
from utils.helpers import fmt_dt, task_state, titleize

_STATE_FILTERS = {
    "All": None, "Open": "open", "Submitted": "submitted",
    "Deadline passed": "overdue", "Not open yet": "not_open",
}


def _load_tasks() -> Optional[list[dict]]:
    try:
        with st.spinner("Loading your tasks..."):
            return api.my_assignments()
    except api.ApiError as error:
        api.report_error(error, "Could not load your tasks")
        return None


def _submit_box(task: dict) -> None:
    state = task_state(task)

    if state == "not_open":
        st.info(f"This task opens on {fmt_dt(task.get('start_at'))}.")
        return
    if state == "overdue":
        st.error("The submission deadline has passed. The backend no longer accepts files for this task.")
        return
    if state == "submitted":
        st.success("You have submitted a document for this task. See Submission History for its status.")
        return

    st.markdown(f"**Upload the required document: {task.get('document_type')}**")
    file = st.file_uploader(
        f"PDF, PNG or JPG, up to {MAX_FILE_SIZE_MB} MB",
        type=ALLOWED_EXTENSIONS,
        key=f"upload_{task['id']}",
    )
    if st.button("Submit document", key=f"submit_{task['id']}", type="primary", disabled=file is None):
        content = file.getvalue()
        if len(content) > MAX_FILE_SIZE_BYTES:
            st.error(f"The file is larger than the {MAX_FILE_SIZE_MB} MB limit.")
            return
        try:
            with st.spinner("Submitting your document..."):
                result = api.submit_assignment(task["id"], file.name, content, file.type)
        except api.ApiError as error:
            api.report_error(error, "Submission failed")
            return
        submission = result.get("submission", {})
        session.set_notice(
            "success",
            f"Submitted '{file.name}' for '{task['title']}'. Confirmation reference: "
            f"submission #{submission.get('id')} (document #{submission.get('document_id')}).",
        )
        st.rerun()


def _render_task(task: dict) -> None:
    state = task_state(task)
    with st.expander(f"{task['title']}  |  {task.get('document_type')}", expanded=state == "open"):
        show_badges(task_state_badge(state), category_badge(task.get("category")))
        key_value_line([
            ("Required document", task.get("document_type") or "-"),
            ("Starts", fmt_dt(task.get("start_at"), "Immediately")),
            ("Deadline", fmt_dt(task.get("due_at"), "No deadline")),
            ("Availability", "Available" if task.get("available") else "Not yet available"),
        ])
        st.markdown("**Instructions**")
        st.write(task.get("instructions") or "No additional instructions were provided.")
        _submit_box(task)


def _render_list(title: str, subtitle: str, category: Optional[str]) -> None:
    page_header(title, subtitle)
    session.show_notice()

    tasks = _load_tasks()
    if tasks is None:
        return
    if category:
        tasks = [t for t in tasks if (t.get("category") or "").lower() == category]

    if not tasks:
        empty_state("No tasks are assigned to you here.",
                    "Make sure My Profile is complete so group assignments can reach you.")
        return

    choice = st.selectbox("Show", list(_STATE_FILTERS), key=f"filter_{category or 'all'}")
    wanted = _STATE_FILTERS[choice]
    shown = [t for t in tasks if wanted is None or task_state(t) == wanted]
    if not shown:
        empty_state("No tasks match this filter.")
    for task in shown:
        _render_task(task)


def render() -> None:
    _render_list("Assigned tasks", "Every published task assigned to you.", None)


def render_academic() -> None:
    _render_list("Academic documents", "Marksheets, certificates, transcripts and academic work.", "academic")


def render_admission() -> None:
    _render_list("Admission documents", "Identity, transfer and admission-related documents.", "admission")

def render_history() -> None:
    page_header(
        "Submission history",
        "View the documents you have submitted and their current status."
    )
    session.show_notice()

    tasks = _load_tasks()
    if tasks is None:
        return

    rows = []

    for task in tasks:
        for sub in task.get("submissions", []):
            rows.append({
                "task": task,
                "sub": sub,
            })

    rows.sort(
        key=lambda r: r["sub"].get("submitted_at") or "",
        reverse=True,
    )

    show_table(
        [
            {
                "task": r["task"]["title"],
                "category": titleize(r["task"].get("category")),
                "document": r["task"].get("document_type"),
                "submitted": fmt_dt(r["sub"].get("submitted_at")),
                "status": "Verification Pending",
            }
            for r in rows
        ],
        {
            "task": "Task",
            "category": "Category",
            "document": "Document type",
            "submitted": "Submitted",
            "status": "Status",
        },
        "You have not submitted any documents yet.",
    )

    if rows:
        st.info(
            "Your documents have been submitted successfully. "
            "Verification is processed automatically in the background."
        )


