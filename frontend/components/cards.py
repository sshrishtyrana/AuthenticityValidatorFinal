"""Page headers, metric cards and message panels."""
from __future__ import annotations

from html import escape
from typing import Iterable, Optional

import streamlit as st


def page_header(title: str, subtitle: str = "") -> None:
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f'<div class="ava-header"><h1>{escape(title)}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )


def metric_card(label: str, value, caption: str = "", tone: str = "") -> None:
    st.markdown(
        f'<div class="ava-metric {tone}">'
        f'<div class="ava-metric-label">{escape(str(label))}</div>'
        f'<div class="ava-metric-value">{escape(str(value))}</div>'
        f'<div class="ava-metric-caption">{escape(caption)}</div></div>',
        unsafe_allow_html=True,
    )


def metric_grid(items: Iterable[tuple], per_row: int = 4) -> None:
    """items: (label, value, caption, tone) tuples; caption/tone optional."""
    items = list(items)
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        columns = st.columns(per_row)
        for column, item in zip(columns, chunk):
            with column:
                metric_card(*item)


def panel(title: str, body_html: str, tone: str = "") -> None:
    """body_html must already be escaped by the caller where needed."""
    st.markdown(
        f'<div class="ava-panel {tone}"><h4>{escape(title)}</h4>{body_html}</div>',
        unsafe_allow_html=True,
    )


def key_value_line(pairs: Iterable[tuple[str, str]]) -> None:
    html = " &nbsp;|&nbsp; ".join(
        f"{escape(str(k))}: <b>{escape(str(v))}</b>" for k, v in pairs
    )
    st.markdown(f'<div class="ava-kv">{html}</div>', unsafe_allow_html=True)


def empty_state(message: str, hint: Optional[str] = None) -> None:
    body = f"<p>{escape(message)}</p>"
    if hint:
        body += f'<p class="ava-kv">{escape(hint)}</p>'
    st.markdown(f'<div class="ava-panel">{body}</div>', unsafe_allow_html=True)


def backend_gap(title: str, items: list[str]) -> None:
    """Visible note about a feature the existing backend does not provide."""
    lis = "".join(f"<li>{escape(item)}</li>" for item in items)
    panel(title, f"<ul>{lis}</ul>", "warn")
