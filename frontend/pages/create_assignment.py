"""Admin: create a document collection task (POST /assignments/)."""
from datetime import date, time, timedelta

import streamlit as st

from components.cards import page_header, panel
from core import api, session
from utils.constants import CATEGORIES, DOCUMENT_TYPES_BY_CATEGORY, ELIGIBILITY_OPTIONS, PROFILE_FIELDS
from utils.helpers import local_to_utc_iso, now_local, parse_student_ids


def render() -> None:
    page_header("Create assignment", "Publish a document collection task to students.")
    session.show_notice()

    # Widgets that change other widgets stay outside st.form so they update live.
    col_a, col_b = st.columns(2)
    with col_a:
        title = st.text_input("Assignment title", key="ca_title", max_chars=255)
        category_label = st.radio("Category", list(CATEGORIES), horizontal=True, key="ca_category")
        category = CATEGORIES[category_label]
        document_type = st.selectbox(
            "Required document type", DOCUMENT_TYPES_BY_CATEGORY[category], key=f"ca_doc_{category}"
        )
    with col_b:
        instructions = st.text_area("Instructions for students", key="ca_instructions", height=190)

    st.markdown("**Eligibility**")
    eligibility_label = st.selectbox("Assign this task to", list(ELIGIBILITY_OPTIONS), key="ca_elig")
    eligibility, profile_field = ELIGIBILITY_OPTIONS[eligibility_label]

    student_ids: list[int] = []
    criteria: dict[str, str] = {}

    if eligibility == "individual":
        raw = st.text_area(
            "Student IDs",
            key="ca_ids",
            placeholder="e.g. 4, 7, 12",
            help="Separate IDs with commas, spaces or new lines.",
        )
        student_ids, invalid = parse_student_ids(raw)
        if invalid:
            st.error(f"These are not valid student IDs: {', '.join(invalid)}")
        elif student_ids:
            st.caption(f"{len(student_ids)} student ID(s) entered.")
        st.caption(
            "The backend has no student-list endpoint, so IDs must be entered by hand. "
            "It rejects unknown or inactive IDs."
        )
    elif profile_field:
        label = PROFILE_FIELDS[profile_field]
        value = st.text_input(
            label, key=f"ca_{profile_field}",
            help="Must match the value students saved in My Profile exactly (case-sensitive).",
        )
        criteria[profile_field] = value.strip()

    st.markdown("**Schedule**")
    today = now_local().date()
    col1, col2, col3, _ = st.columns(4)
    with col1:
        start_now = st.checkbox("Open immediately", value=True, key="ca_start_now")
    with col2:
        start_date = st.date_input("Start date", value=today, key="ca_start_date", disabled=start_now)
    with col3:
        start_time = st.time_input("Start time", value=time(9, 0), key="ca_start_time", disabled=start_now)
    col5, col6, _, _ = st.columns(4)
    with col5:
        due_date = st.date_input("Deadline date", value=today + timedelta(days=14), key="ca_due_date")
    with col6:
        due_time = st.time_input("Deadline time", value=time(17, 0), key="ca_due_time")

    status_label = st.radio(
        "Status", ["Draft", "Published"], horizontal=True, key="ca_status",
        help="Drafts are hidden from students. Published tasks appear immediately for assigned students.",
    )

    if st.button("Create assignment", type="primary"):
        errors = []
        if len(title.strip()) < 3:
            errors.append("Title must contain at least 3 characters.")
        if eligibility == "individual":
            if not student_ids:
                errors.append("Enter at least one valid student ID.")
        elif profile_field and not criteria.get(profile_field):
            errors.append(f"{PROFILE_FIELDS[profile_field]} is required for this eligibility option.")

        start_iso = None if start_now else local_to_utc_iso(start_date, start_time)
        due_iso = local_to_utc_iso(due_date, due_time)
        if not start_now and (due_date, due_time) <= (start_date, start_time):
            errors.append("The deadline must be later than the start date and time.")
        if start_now and (due_date, due_time) <= (now_local().date(), now_local().time().replace(microsecond=0)):
            errors.append("The deadline must be in the future.")

        if errors:
            for message in errors:
                st.error(message)
            return

        payload = {
            "title": title.strip(),
            "instructions": instructions.strip() or None,
            "category": category,
            "document_type": document_type,
            "eligibility_type": eligibility,
            "student_ids": student_ids if eligibility == "individual" else [],
            "start_at": start_iso,
            "due_at": due_iso,
            "status": status_label.lower(),
            **{field: criteria.get(field) or None for field in PROFILE_FIELDS},
        }
        try:
            with st.spinner("Creating assignment..."):
                result = api.create_assignment(payload)
        except api.ApiError as error:
            api.report_error(error, "Could not create assignment")
            return

        created = result.get("assignment", {})
        session.clear_admin_cache()
        st.success(
            f"{result.get('message', 'Assignment created.')} "
            f"'{created.get('title')}' (ID {created.get('id')}) was assigned to "
            f"{created.get('assigned_students', 0)} student(s) as {created.get('status')}."
        )
        if created.get("status") == "draft":
            panel("Draft saved", "<p>Students cannot see this task yet. Publishing an existing draft "
                  "needs a backend update endpoint (PATCH /assignments/{id}); create it as Published to "
                  "make it visible.</p>", "info")
