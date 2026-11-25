"""Entry point:  streamlit run frontend/app.py

Routing is session-state based. A single hidden st.navigation page is
declared on purpose: it switches off Streamlit's automatic multipage
discovery of the pages/ folder, so no page is reachable from a URL
without passing the role check below.
"""
import streamlit as st

st.set_page_config(
    page_title="Authenticity Validator",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

from components.sidebar import render_sidebar
from core import auth, session
from pages import (
    admin_dashboard, create_assignment, document_verification, login,
    manage_assignments, plagiarism_review, register, student_dashboard,
    student_profile, student_tasks, submissions,
)
from utils.constants import APP_NAME, PAGE_ROLES
from utils.helpers import apply_theme

PAGE_RENDERERS = {
    "admin_dashboard": admin_dashboard.render,
    "create_assignment": create_assignment.render,
    "manage_assignments": manage_assignments.render,
    "submissions": submissions.render,
    "document_verification": document_verification.render,
    "plagiarism_review": plagiarism_review.render,
    "student_dashboard": student_dashboard.render,
    "student_tasks": student_tasks.render,
    "student_academic": student_tasks.render_academic,
    "student_admission": student_tasks.render_admission,
    "student_history": student_tasks.render_history,
    "student_profile": student_profile.render,
}
assert set(PAGE_RENDERERS) == set(PAGE_ROLES), "Every page needs a renderer and a role."


def router() -> None:
    apply_theme()
    session.init_session()

    if not session.is_authenticated():
        if st.session_state.get("auth_view") == "register":
            register.render()
        else:
            login.render()
        return

    render_sidebar()

    page = session.get_page()
    if page not in PAGE_RENDERERS:
        page = "admin_dashboard" if session.is_admin() else "student_dashboard"
        session.set_page(page)

    if not auth.can_access(page):
        auth.deny_access(page)
        return

    PAGE_RENDERERS[page]()


navigation = st.navigation(
    [st.Page(router, title=APP_NAME, default=True)],
    position="hidden",
)
navigation.run()
