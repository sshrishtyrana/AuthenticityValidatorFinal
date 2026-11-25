"""Student dashboard built from GET /assignments/my."""
import streamlit as st

from components.cards import empty_state, metric_grid, page_header
from components.status_badges import show_badges, task_state_badge
from components.tables import show_table
from core import api, session
from utils.helpers import fmt_dt, is_approaching, task_state


def render() -> None:
    user = session.get_user()
    page_header(f"Welcome, {user.get('full_name', '')}", "Your document tasks at a glance.")

    try:
        with st.spinner("Loading your tasks..."):
            tasks = api.my_assignments()
            profile = api.get_me()
    except api.ApiError as error:
        api.report_error(error, "Could not load your dashboard")
        return

    missing = [
        label for key, label in [
            ("course", "course"), ("department", "department"), ("academic_year", "academic year"),
            ("semester", "semester"), ("admission_batch", "admission batch"),
        ] if not profile.get(key)
    ]
    if missing:
        st.warning(
            "Your profile is incomplete (" + ", ".join(missing) + "). Tasks assigned by course, "
            "department, semester, academic year or batch reach you only when these match. "
            "Open My Profile to complete it."
        )

    states = [task_state(t) for t in tasks]
    submitted_docs = sum(t.get("submission_count", 0) for t in tasks)
    verified = sum(
        1 for t in tasks for s in t.get("submissions", [])
        if (s.get("review_status") or "").lower() == "verified"
    )
    approaching = [t for t in tasks if task_state(t) == "open" and is_approaching(t)]

    metric_grid([
        ("Assigned tasks", len(tasks)),
        ("Pending submissions", states.count("open") + states.count("not_open") + states.count("overdue"),
         f"{states.count('overdue')} past deadline", "warn"),
        ("Submitted documents", submitted_docs, "", "ok"),
        ("Verified documents", verified, "Marked verified by the institution", "ok"),
    ])

    st.subheader("Tasks approaching deadline")
    if not approaching:
        empty_state("No open tasks are due in the next 3 days.")
    for task in approaching:
        with st.container(border=True):
            show_badges(task_state_badge("open"))
            st.markdown(f"**{task['title']}** - {task.get('document_type')}")
            st.caption(f"Due {fmt_dt(task.get('due_at'))}")

    st.subheader("All tasks")
    show_table(
        [
            {
                "title": t["title"], "category": (t.get("category") or "").title(),
                "document": t.get("document_type"), "deadline": fmt_dt(t.get("due_at"), "No deadline"),
                "state": {"submitted": "Submitted", "overdue": "Deadline passed",
                          "not_open": "Not open yet", "open": "Open"}[task_state(t)],
            }
            for t in tasks
        ],
        {"title": "Task", "category": "Category", "document": "Required document",
         "deadline": "Deadline", "state": "Status"},
        "No tasks have been assigned to you yet.",
    )
