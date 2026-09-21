"""
talonx_ingest.intelligence.delivery.escape
==========================================
HTML escaping for Telegram ``parse_mode=HTML``.

Telegram's HTML mode needs only ``&``, ``<`` and ``>`` escaped in text
nodes, and ``&``/``<``/``>``/``"`` escaped inside an attribute value. A
company name like ``AT&T Inc. <Class A>`` or a filing label with an
underscore therefore cannot break a message — unlike legacy Markdown,
where a stray ``_`` rejects the whole send (the documented 2026-08-18
incident). Control characters are stripped so a mangled source string
cannot inject raw bytes.
"""
from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"[ \t]+")


def clean(text: str | None) -> str:
    """Collapse whitespace, drop control chars. Not HTML-escaped yet."""
    if not text:
        return ""
    t = _CONTROL.sub("", str(text))
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # collapse runs of spaces/tabs but keep newlines
    t = "\n".join(_WS.sub(" ", line).strip() for line in t.split("\n"))
    return t.strip()


def esc(text: str | None) -> str:
    """Escape a text node for Telegram HTML mode."""
    t = clean(text)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_attr(value: str | None) -> str:
    """Escape a value destined for an attribute (e.g. an href)."""
    t = clean(value)
    return (
        t.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_SAFE_URL = re.compile(r"^https?://", re.IGNORECASE)


def link(label: str, url: str | None) -> str:
    """An ``<a href>`` if ``url`` is a plain http(s) URL, else just the
    escaped label. A non-http scheme (``javascript:``, ``data:``) is never
    emitted as a link."""
    lab = esc(label)
    if url and _SAFE_URL.match(url.strip()):
        return f'<a href="{esc_attr(url.strip())}">{lab}</a>'
    return lab


def bold(text: str | None) -> str:
    return f"<b>{esc(text)}</b>"


def italic(text: str | None) -> str:
    return f"<i>{esc(text)}</i>"
