"""Student profile (GET /auth/me, PATCH /auth/profile)."""
import streamlit as st

from components.cards import key_value_line, page_header
from core import api, session
from utils.constants import PROFILE_FIELDS


def render() -> None:
    page_header("My profile", "These details decide which group assignments you receive.")
    session.show_notice()

    try:
        with st.spinner("Loading profile..."):
            profile = api.get_me()
    except api.ApiError as error:
        api.report_error(error, "Could not load your profile")
        return

    key_value_line([
        ("Name", profile.get("full_name")),
        ("Email", profile.get("email")),
        ("Student ID", profile.get("id")),
    ])
    st.write("")

    missing = [label for key, label in PROFILE_FIELDS.items() if not profile.get(key)]
    if missing:
        st.warning("Not yet provided: " + ", ".join(missing))

    with st.form("profile_form"):
        values = {}
        left, right = st.columns(2)
        for index, (key, label) in enumerate(PROFILE_FIELDS.items()):
            with left if index % 2 == 0 else right:
                values[key] = st.text_input(label, value=profile.get(key) or "", key=f"profile_{key}")
        saved = st.form_submit_button("Save profile", type="primary")

    st.caption(
        "Enter values exactly as your institution writes them (for example 'B.Tech', 'Computer Science', "
        "'Semester 5'): administrators match them exactly. The backend does not allow clearing a saved field."
    )

    if saved:
        changes = {
            key: value.strip() for key, value in values.items()
            if value.strip() and value.strip() != (profile.get(key) or "")
        }
        if not changes:
            st.info("No changes to save.")
            return
        try:
            with st.spinner("Saving..."):
                result = api.update_profile(changes)
        except api.ApiError as error:
            api.report_error(error, "Could not update profile")
            return
        session.set_notice("success", result.get("message", "Profile updated."))
        st.rerun()
