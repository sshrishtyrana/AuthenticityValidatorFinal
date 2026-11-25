"""Formatting helpers and the global visual theme."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import streamlit as st

from utils.constants import (
    ADMIN_ROLES,
    APPROACHING_DEADLINE_DAYS,
    DISPLAY_TZ,
    STUDENT_ROLES,
)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
def normalize_role(role: Optional[str]) -> str:
    """Map backend roles (admin / user / student) to 'admin' or 'student'."""
    value = (role or "").strip().casefold()
    if value in ADMIN_ROLES:
        return "admin"
    if value in STUDENT_ROLES:
        return "student"
    return "unknown"


# ---------------------------------------------------------------------------
# Date and time
# ---------------------------------------------------------------------------
def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(DISPLAY_TZ)
    except Exception:  # pragma: no cover - missing tzdata
        return ZoneInfo("UTC")


def parse_utc(value: Any) -> Optional[datetime]:
    """Backend datetimes are naive UTC strings; return an aware datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def fmt_dt(value: Any, fallback: str = "Not set") -> str:
    parsed = parse_utc(value)
    if parsed is None:
        return fallback
    return parsed.astimezone(_tz()).strftime("%d %b %Y, %I:%M %p %Z")


def fmt_date(value: Any, fallback: str = "Not set") -> str:
    parsed = parse_utc(value)
    if parsed is None:
        return fallback
    return parsed.astimezone(_tz()).strftime("%d %b %Y")


def local_to_utc_iso(day: date, clock: time) -> str:
    """Combine inputs entered in the display time zone into an aware ISO string.

    The backend converts aware datetimes to naive UTC, so the offset matters.
    """
    return datetime.combine(day, clock).replace(tzinfo=_tz()).isoformat()


def now_local() -> datetime:
    return datetime.now(_tz())


def deadline_state(due_at: Any) -> Optional[timedelta]:
    parsed = parse_utc(due_at)
    if parsed is None:
        return None
    return parsed - datetime.now(timezone.utc)


def is_approaching(task: dict) -> bool:
    remaining = deadline_state(task.get("due_at"))
    if remaining is None:
        return False
    return timedelta(0) <= remaining <= timedelta(days=APPROACHING_DEADLINE_DAYS)


# ---------------------------------------------------------------------------
# Task state (student view of /assignments/my items)
# ---------------------------------------------------------------------------
def task_state(task: dict) -> str:
    """One of: submitted, overdue, not_open, open."""
    if (task.get("submission_count") or 0) > 0:
        return "submitted"
    if task.get("deadline_passed"):
        return "overdue"
    if task.get("available") is False:
        return "not_open"
    return "open"


# ---------------------------------------------------------------------------
# Numbers and text
# ---------------------------------------------------------------------------
def fmt_score(value: Any, suffix: str = "", fallback: str = "Not available") -> str:
    if value is None:
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number.is_integer():
        return f"{int(number)}{suffix}"
    return f"{number:.1f}{suffix}"


def fmt_confidence(value: Any) -> str:
    """OCR confidence may be stored as 0-1 or 0-100; show a percentage."""
    if value is None:
        return "Not available"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Not available"
    if 0 <= number <= 1:
        number *= 100
    return f"{number:.1f}%"


def titleize(value: Any, fallback: str = "-") -> str:
    if not value:
        return fallback
    return str(value).replace("_", " ").strip().title()


def norm_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match((value or "").strip()))


def parse_student_ids(raw: str) -> tuple[list[int], list[str]]:
    """Parse '3, 5 8' style input. Returns (ids, invalid_tokens)."""
    ids: list[int] = []
    invalid: list[str] = []
    for token in re.split(r"[\s,;]+", (raw or "").strip()):
        if not token:
            continue
        if token.isdigit() and int(token) > 0:
            number = int(token)
            if number not in ids:
                ids.append(number)
        else:
            invalid.append(token)
    return ids, invalid


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
THEME_CSS = """
<style>
:root {
  --ava-navy: #14284b;
  --ava-navy-2: #1f3a68;
  --ava-ink: #1d2433;
  --ava-muted: #5f6878;
  --ava-bg: #faf8f3;
  --ava-surface: #ffffff;
  --ava-line: #e4dfd3;
  --ava-ok: #1e6b4a;
  --ava-ok-bg: #e5f2ea;
  --ava-warn: #8a5a00;
  --ava-warn-bg: #fbf0d6;
  --ava-bad: #9b2c2c;
  --ava-bad-bg: #f8e3e1;
  --ava-info: #1f3a68;
  --ava-info-bg: #e6ecf6;
}
html, body, [class*="stApp"] {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: var(--ava-ink);
}
.stApp { background: var(--ava-bg); }
.block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1280px; }
h1, h2, h3 { font-family: Georgia, "Times New Roman", serif; color: var(--ava-navy); letter-spacing: 0; }
h1 { font-size: 1.9rem; }
header[data-testid="stHeader"] { background: transparent; }

/* Sidebar */
[data-testid="stSidebar"] { background: var(--ava-navy); border-right: 0; }
[data-testid="stSidebar"] * { color: #e9edf5; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.15); }
[data-testid="stSidebar"] .stButton > button {
  width: 100%; justify-content: flex-start; text-align: left;
  background: transparent; border: 0; border-radius: 6px;
  padding: 0.55rem 0.8rem; font-weight: 500; box-shadow: none;
}
[data-testid="stSidebar"] .stButton > button:hover { background: rgba(255,255,255,0.09); }
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] {
  background: #f3efe4; color: var(--ava-navy);
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] *,
[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] * { color: var(--ava-navy); }
.ava-brand { font-family: Georgia, serif; font-size: 1.25rem; font-weight: 700; line-height: 1.2; }
.ava-brand-sub { font-size: 0.78rem; opacity: 0.75; margin-top: 2px; }
.ava-user { font-size: 0.85rem; line-height: 1.4; }
.ava-user b { font-size: 0.95rem; }

/* Page header */
.ava-header { border-bottom: 1px solid var(--ava-line); padding-bottom: 0.9rem; margin-bottom: 1.4rem; }
.ava-header h1 { margin: 0; padding: 0; }
.ava-header p { margin: 0.3rem 0 0 0; color: var(--ava-muted); font-size: 0.98rem; }

/* Metric cards */
.ava-metric {
  background: var(--ava-surface); border: 1px solid var(--ava-line);
  border-left: 4px solid var(--ava-navy); border-radius: 6px;
  padding: 0.85rem 1rem; margin-bottom: 0.8rem; min-height: 98px;
}
.ava-metric.ok { border-left-color: var(--ava-ok); }
.ava-metric.warn { border-left-color: #c58b1a; }
.ava-metric.bad { border-left-color: var(--ava-bad); }
.ava-metric.neutral { border-left-color: #9aa3b2; }
.ava-metric-label { font-size: 0.82rem; color: var(--ava-muted); }
.ava-metric-value { font-family: Georgia, serif; font-size: 1.9rem; color: var(--ava-navy); line-height: 1.25; }
.ava-metric-caption { font-size: 0.76rem; color: var(--ava-muted); }

/* Badges */
.ava-badge {
  display: inline-block; padding: 0.12rem 0.55rem; border-radius: 999px;
  font-size: 0.78rem; font-weight: 600; margin-right: 0.35rem; white-space: nowrap;
}
.ava-badge.ok { background: var(--ava-ok-bg); color: var(--ava-ok); }
.ava-badge.warn { background: var(--ava-warn-bg); color: var(--ava-warn); }
.ava-badge.bad { background: var(--ava-bad-bg); color: var(--ava-bad); }
.ava-badge.info { background: var(--ava-info-bg); color: var(--ava-info); }
.ava-badge.neutral { background: #ecebe6; color: #4a5160; }

/* Panels */
.ava-panel {
  background: var(--ava-surface); border: 1px solid var(--ava-line);
  border-radius: 6px; padding: 1rem 1.2rem; margin-bottom: 1rem;
}
.ava-panel.info { background: var(--ava-info-bg); border-color: #c9d5ea; }
.ava-panel.warn { background: var(--ava-warn-bg); border-color: #ecd9a4; }
.ava-panel h4 { margin: 0 0 0.35rem 0; font-size: 1rem; color: var(--ava-navy); }
.ava-panel p, .ava-panel li { font-size: 0.92rem; margin: 0.2rem 0; }
.ava-kv { font-size: 0.9rem; color: var(--ava-muted); }
.ava-kv b { color: var(--ava-ink); }

/* Expanders, tables, inputs */
[data-testid="stExpander"] { background: var(--ava-surface); border: 1px solid var(--ava-line); border-radius: 6px; }
[data-testid="stDataFrame"] { border: 1px solid var(--ava-line); border-radius: 6px; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"],
.stFormSubmitButton > button[data-testid="stBaseButton-primary"] {
  background: var(--ava-navy); border-color: var(--ava-navy); color: #fff;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover { background: var(--ava-navy-2); border-color: var(--ava-navy-2); }
.stTabs [data-baseweb="tab-list"] { gap: 0.4rem; }
.stTabs [aria-selected="true"] { color: var(--ava-navy); }

@media (max-width: 768px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .ava-metric-value { font-size: 1.5rem; }
}
</style>
"""


def apply_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Streamlit version compatibility: 'use_container_width' is deprecated in
# favour of width="stretch" from 1.50 onwards.
# ---------------------------------------------------------------------------
def _stretch_kwargs() -> dict:
    try:
        major, minor = (int(part) for part in st.__version__.split(".")[:2])
    except ValueError:
        return {"width": "stretch"}
    if (major, minor) >= (1, 50):
        return {"width": "stretch"}
    return {"use_container_width": True}


STRETCH = _stretch_kwargs()
