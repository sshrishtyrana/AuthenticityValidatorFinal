"""Student self-registration (POST /auth/register creates a 'user' role account)."""
import streamlit as st

from components.cards import page_header
from core import api, session
from utils.constants import APP_NAME
from utils.helpers import STRETCH, is_valid_email


def _show_login() -> None:
    st.session_state["auth_view"] = "login"


def render() -> None:
    _, centre, _ = st.columns([1, 1.6, 1])
    with centre:
        page_header("Create student account", f"Register to use the {APP_NAME} portal.")

        with st.form("register_form"):
            full_name = st.text_input("Full name")
            email = st.text_input("Email address", placeholder="name@university.edu")
            password = st.text_input("Password", type="password", help="At least 6 characters.")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create account", type="primary", **STRETCH)

        if submitted:
            if not full_name.strip():
                st.error("Full name is required.")
            elif not is_valid_email(email):
                st.error("Enter a valid email address.")
            elif len(password) < 6:
                st.error("Password must contain at least 6 characters.")
            elif password != confirm:
                st.error("The two passwords do not match.")
            else:
                try:
                    with st.spinner("Creating your account..."):
                        api.register(full_name.strip(), email.strip().lower(), password)
                except api.ApiError as error:
                    api.report_error(error, "Registration failed")
                else:
                    session.set_notice(
                        "success",
                        "Account created. Sign in, then complete My Profile so you "
                        "receive tasks assigned by course, department or semester.",
                    )
                    st.session_state["auth_view"] = "login"
                    st.rerun()

        st.button("Already registered? Sign in", on_click=_show_login, **STRETCH)
