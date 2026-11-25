"""Small coloured status labels."""
from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st

from utils.helpers import titleize


def badge_html(text: str, tone: str = "neutral") -> str:
    return f'<span class="ava-badge {tone}">{escape(str(text))}</span>'


def show_badges(*badges: str) -> None:
    st.markdown("".join(badges), unsafe_allow_html=True)


_ASSIGNMENT_TONES = {"published": "ok", "draft": "neutral", "closed": "bad"}
_REVIEW_TONES = {
    "pending": "warn", "verified": "ok", "suspicious": "bad", "needs_review": "warn",
}
_VERDICT_TONES = {"verified": "ok", "flagged": "bad", "manual review": "warn"}
_TASK_LABELS = {
    "submitted": ("Submitted", "ok"),
    "overdue": ("Deadline passed", "bad"),
    "not_open": ("Not open yet", "neutral"),
    "open": ("Open", "info"),
}


def assignment_status_badge(status: Optional[str]) -> str:
    return badge_html(titleize(status), _ASSIGNMENT_TONES.get((status or "").lower(), "neutral"))


def review_status_badge(status: Optional[str]) -> str:
    return badge_html(titleize(status), _REVIEW_TONES.get((status or "").lower(), "neutral"))


def verdict_badge(verdict: Optional[str]) -> str:
    if not verdict:
        return badge_html("Not verified yet", "neutral")
    return badge_html(verdict, _VERDICT_TONES.get(verdict.casefold(), "info"))


def task_state_badge(state: str) -> str:
    label, tone = _TASK_LABELS.get(state, (titleize(state), "neutral"))
    return badge_html(label, tone)


def category_badge(category: Optional[str]) -> str:
    return badge_html(titleize(category), "info")
