"""Sign-in page."""
import streamlit as st

from components.cards import page_header
from core import api, auth, session
from utils.constants import APP_NAME, APP_TAGLINE
from utils.helpers import STRETCH, is_valid_email


def _show_register() -> None:
    st.session_state["auth_view"] = "register"


def render() -> None:
    _, centre, _ = st.columns([1, 1.6, 1])
    with centre:
        page_header(APP_NAME, APP_TAGLINE)
        session.show_notice()

        with st.form("login_form"):
            email = st.text_input("Email address", placeholder="name@university.edu")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", **STRETCH)

        if submitted:
            if not email.strip() or not password:
                st.error("Enter both your email address and password.")
            elif not is_valid_email(email):
                st.error("Enter a valid email address.")
            elif auth.sign_in(email, password):
                st.rerun()

        st.button("New student? Create an account", on_click=_show_register, **STRETCH)

        if not api.health():
            st.warning(
                "The backend is not responding at http://127.0.0.1:8001. "
                "Start it before signing in."
            )
