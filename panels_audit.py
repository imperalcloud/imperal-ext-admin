"""Admin · Audit log panel section builder.

Displays audit log entries with time presets, filter dropdowns (action,
source, target_type) and colored action badges. Each entry is expandable,
showing full details, state diffs as code blocks.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from imperal_sdk import ui

from app import _gw_request
from panels_sections import _cached

log = logging.getLogger("admin")

_ACTION_COLORS: dict[str, str] = {
    "create":   "green",
    "update":   "yellow",
    "delete":   "red",
    "login":    "purple",
    "denied":   "red",
    "suspend":  "orange",
    "activate": "cyan",
}

_PRESETS: list[tuple[str, int]] = [
    ("1h",  1),
    ("24h", 24),
    ("7d",  168),
    ("30d", 720),
]


# ── Helpers ───────────────────────────────────────────────────────────


def _relative_time(ts: str) -> str:
    if not ts:
        return "\u2014"
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - then
        mins = int(diff.total_seconds() / 60)
        if mins < 1:
            return "now"
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 30:
            return f"{days}d ago"
        return then.strftime("%Y-%m-%d")
    except Exception:
        return "\u2014"


def _format_timestamp(ts: str) -> str:
    """Format ISO timestamp to human-readable local string."""
    if not ts:
        return "\u2014"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts


async def _fetch_audit_raw(ctx, hours: int = 24) -> list:
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = await _gw_request(ctx, "GET", f"/v1/audit?since={since}&limit=200")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("entries", result.get("items", []))
        return []
    except Exception:
        return []


async def _fetch_audit(ctx, hours: int = 24) -> list:
    return await _cached(ctx, f"audit:{hours}", lambda ctx: _fetch_audit_raw(ctx, hours))


def _action_color(action: str) -> str:
    return _ACTION_COLORS.get(action.lower(), "gray") if action else "gray"


# ── Expanded content builder ──────────────────────────────────────────


def _build_entry_expanded(entry: dict) -> list:
    """Return expanded_content nodes for a single audit ListItem."""
    nodes: list = []
    _dash = "—"
    t_type = entry.get("target_type", _dash)
    t_id = entry.get("target_id", "")
    target_val = f"{t_type}:{t_id}" if t_id else t_type


    nodes.append(ui.KeyValue(
        items=[
            {"key": "Time",   "value": _format_timestamp(
                entry.get("created_at", entry.get("timestamp", "\u2014")))},
            {"key": "Actor",  "value": entry.get("actor", entry.get("actor_id", "system"))},
            {"key": "Action", "value": entry.get("action", "\u2014")},
            {"key": "Target", "value": target_val},
            {"key": "Source", "value": entry.get("source", "\u2014")},
            {"key": "IP",     "value": entry.get("ip", entry.get("ip_address", "\u2014"))},
        ],
        columns=2,
    ))

    details = entry.get("details") or entry.get("message")
    if details:
        nodes.append(ui.Text(str(details), variant="body"))

    before = entry.get("before_state")
    after  = entry.get("after_state")
    if before or after:
        nodes.append(ui.Divider())
        diff_nodes: list = []
        if before:
            diff_nodes.append(ui.Code(
                content=json.dumps(before, indent=2, ensure_ascii=False),
                language="json",
            ))
        if after:
            diff_nodes.append(ui.Code(
                content=json.dumps(after, indent=2, ensure_ascii=False),
                language="json",
            ))
        nodes.append(ui.Stack(children=diff_nodes, direction="h", gap=2))

    return nodes


# ── Main builder ──────────────────────────────────────────────────────


async def build_audit(ctx, **kwargs) -> object:
    """Audit log: presets + 3 filter dropdowns + searchable expandable list."""
    try:
        hours = int(kwargs.get("hours", 24))
    except (TypeError, ValueError):
        hours = 24

    action_filter = kwargs.get("action_filter", "")
    source_filter = kwargs.get("source_filter", "")
    target_type_filter = kwargs.get("target_type_filter", "")

    all_entries = await _fetch_audit(ctx, hours)

    # Build filter options from full unfiltered dataset
    actions = sorted(set(e.get("action", "") for e in all_entries if e.get("action")))
    sources = sorted(set(e.get("source", "") for e in all_entries if e.get("source")))
    target_types = sorted(set(
        e.get("target_type", "") for e in all_entries if e.get("target_type")
    ))

    # Apply filters
    entries = all_entries
    if action_filter:
        entries = [e for e in entries if e.get("action") == action_filter]
    if source_filter:
        entries = [e for e in entries if e.get("source") == source_filter]
    if target_type_filter:
        entries = [e for e in entries if e.get("target_type") == target_type_filter]

    count = len(entries)

    # ── Preset bar ────────────────────────────────────────────────────
    preset_buttons: list = []
    for label, h in _PRESETS:
        variant = "primary" if h == hours else "ghost"
        preset_buttons.append(ui.Button(
            label,
            variant=variant,
            on_click=ui.Call(
                "__panel__tools",
                section="audit",
                hours=h,
                action_filter=action_filter,
                source_filter=source_filter,
                target_type_filter=target_type_filter,
            ),
        ))
    preset_buttons.append(ui.Text(f"{count} events", variant="caption"))

    preset_bar = ui.Stack(children=preset_buttons, direction="h", gap=1)

    # ── Filter dropdowns (3: action, source, target_type) ─────────────
    filter_bar = ui.Stack(children=[
        ui.Select(
            options=[{"value": "", "label": "All Actions"}] + [
                {"value": a, "label": a} for a in actions
            ],
            value=action_filter,
            param_name="action_filter",
            on_change=ui.Call(
                "__panel__tools", section="audit", hours=hours,
                source_filter=source_filter,
                target_type_filter=target_type_filter,
            ),
        ),
        ui.Select(
            options=[{"value": "", "label": "All Sources"}] + [
                {"value": s, "label": s} for s in sources
            ],
            value=source_filter,
            param_name="source_filter",
            on_change=ui.Call(
                "__panel__tools", section="audit", hours=hours,
                action_filter=action_filter,
                target_type_filter=target_type_filter,
            ),
        ),
        ui.Select(
            options=[{"value": "", "label": "All Targets"}] + [
                {"value": t, "label": t} for t in target_types
            ],
            value=target_type_filter,
            param_name="target_type_filter",
            on_change=ui.Call(
                "__panel__tools", section="audit", hours=hours,
                action_filter=action_filter,
                source_filter=source_filter,
            ),
        ),
    ], direction="h", gap=2)

    # ── Empty state ───────────────────────────────────────────────────
    if not entries:
        return ui.Stack(children=[
            ui.Header("Audit Log", level=3),
            preset_bar,
            filter_bar,
            ui.Empty(
                message=f"No audit events in the last {hours}h.",
                icon="FileText",
            ),
        ])

    # ── Entry list ────────────────────────────────────────────────────
    items: list = []
    for entry in entries:
        action   = entry.get("action", "")
        actor    = entry.get("actor", entry.get("actor_id")) or "system"
        target_type = entry.get("target_type", "")
        target_id   = entry.get("target_id", "")
        ts       = entry.get("created_at", entry.get("timestamp", ""))
        entry_id = entry.get("id", ts or str(entries.index(entry)))

        subtitle = target_type
        if target_id:
            subtitle = f"{target_type}:{target_id}" if target_type else target_id

        badge = ui.Badge(action, color=_action_color(action)) if action else None

        items.append(ui.ListItem(
            id=str(entry_id),
            title=actor,
            subtitle=subtitle,
            badge=badge,
            meta=_relative_time(ts),
            expandable=True,
            expanded_content=_build_entry_expanded(entry),
        ))

    return ui.Stack(children=[
        ui.Header("Audit Log", level=3),
        preset_bar,
        filter_bar,
        ui.List(items=items, searchable=True),
    ])
