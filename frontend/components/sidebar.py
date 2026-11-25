"""Role-aware sidebar navigation."""
from __future__ import annotations

from html import escape

import streamlit as st

from core import session
from utils.constants import ADMIN_NAV, APP_NAME, STUDENT_NAV
from utils.helpers import STRETCH


def _go(page: str) -> None:
    session.set_page(page)


def _logout() -> None:
    session.logout("You have been signed out.", "info")


def render_sidebar() -> None:
    user = session.get_user()
    role = session.get_role()
    nav = ADMIN_NAV if role == "admin" else STUDENT_NAV
    current = session.get_page()
    # The two category pages share the task renderer; keep their own highlight.

    with st.sidebar:
        st.markdown(
            f'<div class="ava-brand">{escape(APP_NAME)}</div>'
            f'<div class="ava-brand-sub">'
            f'{"Administrator console" if role == "admin" else "Student portal"}</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        for key, label in nav:
            st.button(
                label,
                key=f"nav_{key}",
                type="primary" if key == current else "secondary",
                on_click=_go,
                args=(key,),
                **STRETCH,
            )

        st.divider()
        st.markdown(
            f'<div class="ava-user"><b>{escape(user.get("full_name", ""))}</b><br>'
            f'{escape(user.get("email", ""))}<br>'
            f'Role: {"Administrator" if role == "admin" else "Student"}</div>',
            unsafe_allow_html=True,
        )
        st.button("Sign out", key="nav_logout", on_click=_logout, **STRETCH)
