"""Streamlit session-state management.

The JWT lives only in ``st.session_state`` (server-side memory for this
browser session). It is never written to disk, cookies or query parameters.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Optional

import streamlit as st

from utils.constants import DEFAULT_PAGE
from utils.helpers import normalize_role

_DEFAULTS: dict[str, Any] = {
    "token": None,
    "user": None,
    "page": None,
    "auth_view": "login",
    "notice": None,              # (kind, message) shown once
    "admin_overview": None,      # cached admin data
    "verification_results": {},  # document_id -> verification result
    "admin_verification": None,  # last result from the admin upload tool
}


def init_session() -> None:
    for key, value in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, dict) else value


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
def _token_expired(token: str) -> bool:
    """Read the 'exp' claim for UX only. The backend remains the authority."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp")
        return exp is not None and float(exp) <= time.time()
    except Exception:
        return False


def get_token() -> Optional[str]:
    return st.session_state.get("token")


def is_authenticated() -> bool:
    token = get_token()
    if not token or not st.session_state.get("user"):
        return False
    if _token_expired(token):
        logout("Your session has expired. Please sign in again.", "warning")
        return False
    return True


def get_user() -> dict:
    return st.session_state.get("user") or {}


def get_role() -> str:
    return normalize_role(get_user().get("role"))


def is_admin() -> bool:
    return get_role() == "admin"


def is_student() -> bool:
    return get_role() == "student"


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------
def login_user(response: dict) -> None:
    st.session_state["token"] = response["access_token"]
    st.session_state["user"] = response["user"]
    st.session_state["admin_overview"] = None
    st.session_state["verification_results"] = {}
    st.session_state["admin_verification"] = None
    st.session_state["page"] = DEFAULT_PAGE.get(get_role())


def logout(message: Optional[str] = None, kind: str = "info") -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_session()
    if message:
        st.session_state["notice"] = (kind, message)


# ---------------------------------------------------------------------------
# Navigation and notices
# ---------------------------------------------------------------------------
def get_page() -> Optional[str]:
    return st.session_state.get("page")


def set_page(page: str) -> None:
    st.session_state["page"] = page


def set_notice(kind: str, message: str) -> None:
    """Queue a one-time message shown on the next render."""
    st.session_state["notice"] = (kind, message)


def show_notice() -> None:
    notice = st.session_state.pop("notice", None)
    if not notice:
        return
    kind, message = notice
    {"success": st.success, "warning": st.warning, "error": st.error}.get(
        kind, st.info
    )(message)


def clear_admin_cache() -> None:
    st.session_state["admin_overview"] = None
