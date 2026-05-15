"""Admin · Dashboard panel section builder.

Mirrors React DashboardWidgets — Card-wrapped stats sections.
Action stats from /v1/internal/actions/stats?admin=true (same as React).
LLM usage from /v1/internal/config/llm/usage.
"""
from __future__ import annotations

import asyncio

from imperal_sdk import ui

from panels_sections import (
    _fetch_users, _fetch_roles, _fetch_extensions,
    _fetch_llm_usage, _fetch_action_stats,
    _fmt_tokens, _fmt_latency,
)


async def build_dashboard(ctx):
    """Dashboard: Card-wrapped stats + actions + LLM usage + status."""
    users, roles, extensions, llm, actions = await asyncio.gather(
        _fetch_users(ctx), _fetch_roles(ctx), _fetch_extensions(ctx),
        _fetch_llm_usage(ctx), _fetch_action_stats(ctx),
    )

    active_count = sum(1 for u in users if u.get("is_active"))

    children = [
        ui.Header("Dashboard", level=3),

        # 1 · Overview — 2x2 grid (no icons — matches React MetricCard)
        ui.Card(title="Overview", content=ui.Stats(children=[
            ui.Stat(label="Users", value=str(len(users)), color="blue"),
            ui.Stat(label="Active", value=str(active_count), color="green"),
            ui.Stat(label="Roles", value=str(len(roles)), color="purple"),
            ui.Stat(label="Extensions", value=str(len(extensions)),
                    color="cyan"),
        ], columns=2)),
    ]

    _append_actions_card(children, actions)
    _append_llm_today_card(children, llm)
    _append_llm_month_card(children, actions)
    _append_status_card(children, llm)

    return ui.Stack(children=children, direction="v", gap=4)


# ── Section builders ──────────────────────────────────────────────────


def _append_actions_card(children: list, actions: dict) -> None:
    """Platform Actions This Month.

    React API returns: {used, completed, failed, limit, period, ...}
    from /v1/internal/actions/stats?admin=true
    """
    if not actions:
        return

    total = actions.get("total_actions") or actions.get("used") or 0
    completed = actions.get("completed", 0)
    failed = actions.get("failed", 0)
    rate = round(completed / total * 100) if total > 0 else 0

    if rate >= 90:
        rate_color = "green"
    elif rate >= 70:
        rate_color = "yellow"
    else:
        rate_color = "red"

    children.append(ui.Card(
        title="Platform Actions This Month",
        content=ui.Stats(children=[
            ui.Stat(label="Total Actions", value=str(total)),
            ui.Stat(label="Completed", value=str(completed), color="green"),
            ui.Stat(label="Failed", value=str(failed), color="red"),
            ui.Stat(label="Success Rate", value=f"{rate}%",
                    color=rate_color),
        ], columns=2),
    ))


def _append_llm_today_card(children: list, llm: dict) -> None:
    """Platform LLM Usage Today — 3x2 grid."""
    if not llm:
        return

    failover = llm.get("failover_events", 0)

    children.append(ui.Card(
        title="Platform LLM Usage Today",
        content=ui.Stats(children=[
            ui.Stat(label="Calls",
                    value=str(llm.get("total_calls", 0))),
            ui.Stat(label="Tokens In",
                    value=_fmt_tokens(llm.get("total_tokens_in"))),
            ui.Stat(label="Tokens Out",
                    value=_fmt_tokens(llm.get("total_tokens_out"))),
            ui.Stat(label="Avg Latency",
                    value=_fmt_latency(llm.get("avg_latency_ms"))),
            ui.Stat(label="BYOLLM Users",
                    value=str(llm.get("byollm_users", 0))),
            ui.Stat(label="Failover",
                    value=str(failover),
                    color="yellow" if failover > 0 else None),
        ], columns=3),
    ))


def _append_llm_month_card(children: list, actions: dict) -> None:
    """Platform LLM This Month — totals + per-model breakdown."""
    if not actions:
        return

    llm_calls = actions.get("llm_total_calls", 0)
    llm_tokens = actions.get("llm_total_tokens", 0)
    if not llm_calls and not llm_tokens:
        return

    card_items: list = [
        ui.Stats(children=[
            ui.Stat(label="LLM Calls", value=str(llm_calls)),
            ui.Stat(label="Tokens Used", value=_fmt_tokens(llm_tokens)),
        ], columns=2),
    ]

    by_model = (actions.get("llm_by_model") or [])[:4]
    if by_model:
        kv_items = [
            {"key": m.get("model", "?"),
             "value": f"{m.get('calls', 0)} calls"}
            for m in by_model
        ]
        card_items.append(ui.Divider())
        card_items.append(ui.KeyValue(items=kv_items, columns=2))

    children.append(ui.Card(
        title="Platform LLM Usage This Month",
        content=ui.Stack(children=card_items),
    ))


def _append_status_card(children: list, llm: dict) -> None:
    """Platform Status — system health + LLM counts."""
    calls_today = str(llm.get("total_calls", 0)) if llm else "0"
    tokens_in = llm.get("total_tokens_in", 0) or 0
    tokens_out = llm.get("total_tokens_out", 0) or 0
    tokens_today = _fmt_tokens(tokens_in + tokens_out) if llm else "0"

    children.append(ui.Card(
        title="Platform Status",
        content=ui.Stack(children=[
            ui.Stack([
                ui.Text("Imperal Cloud ICNLI OS", variant="body"),
                ui.Badge(label="All systems operational", color="green"),
            ], direction="h", gap=2, justify="between", align="center"),
            ui.Divider(),
            ui.KeyValue(items=[
                {"key": "LLM Calls Today", "value": calls_today},
                {"key": "Tokens Today", "value": tokens_today},
            ]),
        ]),
    ))
