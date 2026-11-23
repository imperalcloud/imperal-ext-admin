"""Admin · Dashboard: every number from its own source, a failure shown as a failure.

Rebuilt 2026-11-23 on the owner's report ("the Dashboard shows wrong numbers
of users... and not only"). What was wrong, each read in the code that day:

  * Users counted the first page of 50 (fixed in 5.21.1 by reading all pages).
  * Platform Actions asked the gateway without the ``user_id`` its door
    requires; the refusal came back as an error dict and the card drew
    0 actions, 0 completed and a red 0% success rate from it.
  * Any source that failed was drawn as zeros or silently left out, next to a
    badge that said "All systems operational" - a text constant, checked by
    nothing.
  * "Extensions" was one number over active, draft, suspended and pending apps.

The rule now: a source that could not be read is NAMED in one alert at the top
with the gateway's own words, and its card is not drawn. No number on this
screen comes from a source that did not answer. The status badge is the result
of two health probes and of that list, made on this render.

Money: the Revenue card is the headline of the Billing Analytics section -
same single aggregate endpoint, so the two screens cannot disagree.
"""
from __future__ import annotations

import asyncio

from imperal_sdk import ui

from app import AUTH_GW, REGISTRY_URL
from panels_billing_analytics import (
    _fetch_analytics, _panel_acting, _money,
)
from panels_sections import (
    _fetch_users_checked, _gw_checked, _fetch_extensions_checked,
    _fetch_action_stats_checked, _check_health,
    _fmt_tokens, _fmt_latency,
)

try:
    from imperal_sdk.ui import MorphingState, Affordance, CognitiveContext
except ImportError:
    MorphingState = None
    Affordance = None
    CognitiveContext = None


def _llm_today(raw: dict) -> dict:
    """The gateway's usage counters under the names the cards use."""
    calls = int(raw.get("calls", 0) or 0)
    latency = int(raw.get("total_latency_ms", 0) or 0)
    return {
        "total_calls": calls,
        "byollm_calls": int(raw.get("byollm_calls", 0) or 0),
        "total_tokens_in": int(raw.get("input_tokens", 0) or 0),
        "total_tokens_out": int(raw.get("output_tokens", 0) or 0),
        "failover_events": int(raw.get("failover_calls", 0) or 0),
        # no calls = no average, not an average of zero
        "avg_latency_ms": round(latency / calls) if calls > 0 else None,
    }


async def build_dashboard(ctx):
    """Seven reads and two health probes, side by side; then only what answered."""
    acting = _panel_acting(ctx)
    ((users, users_why), (roles, roles_why), (extensions, ext_problems),
     (llm_raw, llm_why), (actions, actions_why), billing, gw_health, reg_health) = await asyncio.gather(
        _fetch_users_checked(), _gw_checked("/v1/roles"), _fetch_extensions_checked(),
        _gw_checked("/v1/internal/config/llm/usage"), _fetch_action_stats_checked(acting),
        _fetch_analytics(acting, 30, 1),
        _check_health("auth_gateway", f"{AUTH_GW}/healthz"),
        _check_health("registry", f"{REGISTRY_URL}/health"),
    )
    if not roles_why and not isinstance(roles, list):
        roles_why = "the gateway did not answer with a list"
    if not llm_why and not isinstance(llm_raw, dict):
        llm_why = "the gateway did not answer with the counters"
    llm = _llm_today(llm_raw) if not llm_why else {}

    # what could not be read, in the source's own words
    unread: list[str] = []
    if users_why:
        unread.append(f"Users: {users_why}")
    if roles_why:
        unread.append(f"Roles: {roles_why}")
    unread += [f"Extensions, {p}" for p in ext_problems]
    if actions_why:
        unread.append(f"Actions this month: {actions_why}")
    if llm_why:
        unread.append(f"LLM usage today: {llm_why}")
    if not billing:
        unread.append("Billing: the analytics endpoint gave nothing")

    children: list = [
        ui.Header("Dashboard", level=3),
        ui.Card(
            title="Omnisearch (Global Control Plane)",
            content=ui.Stack([
                ui.Input(param_name="omni_query", placeholder="Search users, roles, extensions (Cmd+K)..."),
                ui.Button(
                    label="Search System",
                    variant="secondary",
                    on_click=ui.Call("omnisearch", query="{{omni_query}}"),
                ),
            ], direction="h", gap=2, align="end"),
        ),
    ]
    if unread:
        children.append(ui.Alert(
            title=f"{len(unread)} source(s) could not be read - their numbers are not shown",
            message=" | ".join(unread),
            type="error",
        ))

    _append_situational_card(children, extensions=extensions, billing=billing)
    _append_overview_card(children, users, users_why, roles, roles_why, extensions, ext_problems)
    _append_revenue_card(children, billing)
    if not actions_why:
        _append_actions_card(children, actions)
    if not llm_why:
        _append_llm_today_card(children, llm)
    if not actions_why:
        _append_llm_month_card(children, actions)
    _append_status_card(children, gw_health, reg_health, unread)

    return ui.Stack(children=children, direction="v", gap=4)


def _append_overview_card(children: list, users, users_why, roles, roles_why,
                          extensions, ext_problems) -> None:
    """Who and what is on the platform. A count whose source failed is absent."""
    stats: list = []
    if not users_why:
        active = sum(1 for u in users if u.get("is_active", True))
        stats += [
            ui.Stat(label="Users", value=str(len(users)), color="blue",
                    description=f"{active} active, {len(users) - active} inactive"),
            ui.Stat(label="Active users", value=str(active), color="green"),
        ]
    if not roles_why:
        stats.append(ui.Stat(label="Roles", value=str(len(roles)), color="purple"))
    if not ext_problems:
        by_status: dict[str, int] = {}
        for e in extensions:
            by_status[str(e.get("status") or "unknown")] = by_status.get(str(e.get("status") or "unknown"), 0) + 1
        rest = ", ".join(f"{n} {s.replace('_', ' ')}" for s, n in sorted(by_status.items()) if s != "active")
        stats.append(ui.Stat(
            label="Active extensions", value=str(by_status.get("active", 0)), color="cyan",
            description=f"{len(extensions)} in all" + (f": {rest}" if rest else "")))
    if stats:
        children.append(ui.Card(title="Overview", content=ui.Stats(children=stats, columns=2)))


def _append_situational_card(children: list, extensions: list, billing: dict) -> None:
    """Adaptive ICNLI Liquid Intent UI block.

    Dynamically morphs the dashboard into an incident or alert posture
    if pending approvals, payment configuration issues, or degraded models exist.
    """
    pending_apps = [e for e in extensions if e.get("status") == "pending_review"]
    pending_payouts_count = 0
    if billing and isinstance(billing, dict):
        pending_payouts_count = int(billing.get("pending_payouts_count") or 0)

    # Check situational triggers
    situations = []
    if pending_apps:
        situations.append(f"{len(pending_apps)} app submission(s) pending marketplace review")
    if pending_payouts_count > 0:
        situations.append(f"{pending_payouts_count} developer payout request(s) awaiting approval")

    if not situations:
        # Nothing waits for the admin. Said by drawing nothing: the old block
        # here announced "All cloud OS subsystems operational ... nodes, neural
        # router, and payment webhooks are synchronized" - none of it checked.
        return

    # Critical or elevated posture
    summary_text = " • ".join(situations)
    affordances = []
    if pending_apps:
        affordances.append(
            Affordance(
                id="review_apps",
                label=f"Review Apps ({len(pending_apps)})",
                primary=True,
                risk="write",
                shortcut="r",
                payload=ui.Call("__panel__tools", section="extensions", active="extensions").to_dict(),
            ) if Affordance else {"id": "review_apps", "label": f"Review Apps ({len(pending_apps)})"}
        )
    if pending_payouts_count > 0:
        affordances.append(
            Affordance(
                id="review_payouts",
                label="Process Payouts",
                risk="write",
                requires_confirmation=True,
                shortcut="p",
                payload=ui.Call("__panel__tools", section="payouts", active="payouts").to_dict(),
            ) if Affordance else {"id": "review_payouts", "label": "Process Payouts"}
        )

    if MorphingState:
        children.append(
            MorphingState(
                context="admin_attention_required",
                summary=summary_text,
                urgency="elevated",
                risk="write",
                details="Action required by administrative control plane to unblock marketplace operations.",
                affected_entities=[app.get("app_id", "app") for app in pending_apps[:4]],
                affordances=affordances,
                cognitive=CognitiveContext(
                    situation="administrative_triage",
                    urgency="elevated",
                    attention_budget="focused",
                ) if CognitiveContext else None,
            )
        )
    else:
        children.append(
            ui.Alert(
                title="Action Required",
                message=summary_text,
                type="warning",
            )
        )


# ── Section builders ──────────────────────────────────────────────────


def _append_revenue_card(children: list, billing: dict) -> None:
    """Money headline — the four figures an owner checks first.

    Deliberately NOT a second calculation: these are the exact fields the
    Billing Analytics section renders, so the Dashboard cannot drift from it.
    Omitted entirely when the billing gateway gives nothing, because a
    revenue card silently showing $0.00 would be worse than no card at all.

    "Paying" counts a real saved card on an active, non-cancelled
    subscription — never a plan name (see panels_billing_analytics).
    """
    if not billing:
        return

    paid = billing.get("paid") or {}
    buckets = ((billing.get("upcoming") or {}).get("buckets") or {})
    no_card = int(paid.get("card_mode_without_card") or 0)

    children.append(ui.Card(
        title="Revenue",
        content=ui.Stack(children=[
            ui.Stats(children=[
                ui.Stat(label="Paying (card on file)",
                        value=str(paid.get("paying_with_card") or 0),
                        color="green"),
                ui.Stat(label="MRR committed",
                        value=_money(paid.get("mrr_cents")), color="green"),
                ui.Stat(label="Due next 7 days",
                        value=_money((buckets.get("next_7d") or {}).get("cents")),
                        color="yellow"),
                ui.Stat(label="Card mode, NO card", value=str(no_card),
                        color="red" if no_card else "gray"),
            ], columns=2),
            ui.Button(
                label="Open Billing Analytics",
                variant="secondary",
                on_click=ui.Call("__panel__tools",
                                 section="billing_analytics"),
            ),
        ], direction="v", gap=3),
    ))


def _append_actions_card(children: list, actions: dict) -> None:
    """Platform Actions This Month.

    React API returns: {used, completed, failed, limit, period, ...}
    from /v1/internal/actions/stats?admin=true
    """
    total = int(actions.get("total_actions") or 0)
    completed = int(actions.get("completed") or 0)
    failed = int(actions.get("failed") or 0)
    # every other way an action ended that the gateway counts
    other = {k: int(actions.get(k) or 0) for k in
             ("cancelled", "partial_failure", "fabrication", "integrity_failure")}
    ended = completed + failed + sum(other.values())
    stats = [
        ui.Stat(label="Total Actions", value=str(total),
                description=str(actions.get("month") or "")),
        ui.Stat(label="Completed", value=str(completed), color="green"),
        ui.Stat(label="Failed", value=str(failed), color="red" if failed else "gray",
                description=", ".join(f"{n} {k.replace('_', ' ')}" for k, n in other.items() if n)),
    ]
    if ended:
        # of the actions that ended; with none ended there is no rate to show
        rate = round(completed / ended * 100)
        stats.append(ui.Stat(
            label="Success Rate", value=f"{rate}%",
            color="green" if rate >= 90 else "yellow" if rate >= 70 else "red",
            description=f"{completed} of {ended} ended actions"))

    children.append(ui.Card(
        title="Platform Actions This Month",
        content=ui.Stats(children=stats, columns=2),
    ))


def _append_llm_today_card(children: list, llm: dict) -> None:
    """Platform LLM Usage Today — 3x2 grid."""
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
            ui.Stat(label="BYOLLM Calls",
                    value=str(llm.get("byollm_calls", 0))),
            ui.Stat(label="Failover",
                    value=str(failover),
                    color="yellow" if failover > 0 else None),
        ], columns=3),
    ))


def _append_llm_month_card(children: list, actions: dict) -> None:
    """Platform LLM This Month — totals + per-model breakdown."""
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


def _append_status_card(children: list, gw_health: str, reg_health: str, unread: list[str]) -> None:
    """What was checked on THIS render: two health probes and the data sources.
    The old badge was the constant text "All systems operational"."""
    healthy = gw_health == "Operational" and reg_health == "Operational"
    if healthy and not unread:
        verdict, colour = "All checks passed", "green"
    elif healthy:
        verdict, colour = f"{len(unread)} data source(s) unread", "yellow"
    else:
        verdict, colour = "A service does not answer", "red"

    children.append(ui.Card(
        title="Platform Status",
        content=ui.Stack(children=[
            ui.Stack([
                ui.Text("Checked on this load", variant="body"),
                ui.Badge(label=verdict, color=colour),
            ], direction="h", gap=2, justify="between", align="center"),
            ui.Divider(),
            ui.KeyValue(items=[
                {"key": "Auth Gateway", "value": gw_health},
                {"key": "Registry", "value": reg_health},
                {"key": "Data sources", "value": "all read" if not unread else f"{len(unread)} not read"},
            ]),
            ui.Text("Covers the gateway, the registry and this page's data. "
                    "Workers, Temporal and the databases are not probed here.",
                    variant="caption"),
        ]),
    ))
