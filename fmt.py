"""Admin · Shared money/date formatting helpers.

Before this module, ``_money`` was copy-pasted verbatim into THREE files
(panels_billing_analytics.py, panels_credits.py, handlers_billing_mode.py)
and ``_when`` was copy-pasted into TWO (panels_billing_analytics.py,
panels_credits.py) with subtly different behaviour on the edges (see below).
Any bugfix to one copy silently would not apply to its siblings — the exact
kind of drift the owner asked to have swept out of this extension.

This module is the single source of truth for both. Each caller's PRIOR
behaviour is preserved exactly via named variants/flags so consolidating
this changes zero rendered output anywhere it is used.
"""
from __future__ import annotations

from datetime import datetime, timezone

DASH = "\u2014"


def money(cents, *, dash_on_zero: bool = False) -> str:
    """Cents -> "$X.XX". Money is never rendered from a float field.

    ``dash_on_zero``: handlers_billing_mode's original copy treated a falsy
    (None OR 0) amount as "no amount to show" and rendered DASH; the two
    panel copies only guarded against non-numeric input and rendered
    "$0.00" for an explicit zero. Both are legitimate depending on whether
    0 is a real answer (a $0 credit line) or "nothing configured" (no
    contract amount set) — the flag keeps each call site's original,
    deliberate behaviour.
    """
    if dash_on_zero and not cents:
        return DASH
    try:
        return f"${int(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return DASH


def when_with_color(iso: str | None) -> tuple[str, str, str]:
    """(absolute, relative, colour) for a DUE date — billing_analytics style.

    Returns a colour so an overdue row LOOKS overdue: the point of the
    schedule is to see trouble before it happens, not to read timestamps.
    """
    if not iso:
        return (DASH, "no date", "gray")
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return (str(iso), "", "gray")

    days = (dt - datetime.now(timezone.utc)).days
    stamp = dt.strftime("%d %b %Y, %H:%M")
    if days < 0:
        return (stamp, f"overdue {abs(days)}d", "red")
    if days == 0:
        return (stamp, "today", "red")
    if days <= 7:
        return (stamp, f"in {days}d", "yellow")
    return (stamp, f"in {days}d", "green")


def when_relative(iso: str | None) -> tuple[str, str]:
    """(absolute, relative) for a PAST ledger timestamp — credits style.

    Granular "Xm ago / Xh ago / yesterday / Xd ago / Xmo ago" — for events
    that already happened, unlike ``when_with_color`` which is about a
    future due date and needs an urgency colour instead of granularity.
    """
    if not iso:
        return (DASH, "")
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return (str(iso), "")

    stamp = dt.strftime("%d %b %Y, %H:%M")
    delta = datetime.now(timezone.utc) - dt
    days = delta.days
    if days < 0:
        return (stamp, "")
    if days == 0:
        hours = delta.seconds // 3600
        if hours < 1:
            return (stamp, f"{delta.seconds // 60}m ago")
        return (stamp, f"{hours}h ago")
    if days == 1:
        return (stamp, "yesterday")
    if days < 31:
        return (stamp, f"{days}d ago")
    return (stamp, f"{days // 30}mo ago")
