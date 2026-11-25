"""Authentication flows and page-level access control."""
from __future__ import annotations

import streamlit as st

from core import api, session
from utils.constants import PAGE_ROLES


def sign_in(email: str, password: str) -> bool:
    """Call the backend and store the JWT. Returns True on success."""
    try:
        with st.spinner("Signing in..."):
            response = api.login(email.strip().lower(), password)
    except api.ApiError as error:
        api.report_error(error, "Sign in failed")
        return False

    if not response.get("access_token") or not response.get("user"):
        st.error("The backend returned an unexpected login response.")
        return False

    session.login_user(response)
    if session.get_role() == "unknown":
        session.logout("This account has an unsupported role.", "error")
        return False
    return True


def can_access(page: str) -> bool:
    """A page is reachable only by the role it belongs to."""
    required = PAGE_ROLES.get(page)
    return bool(required) and session.is_authenticated() and session.get_role() == required


def deny_access(page: str) -> None:
    required = PAGE_ROLES.get(page, "another")
    st.error(
        f"This page is restricted to {required} accounts. "
        "Use the sidebar to open a page available to your role."
    )
