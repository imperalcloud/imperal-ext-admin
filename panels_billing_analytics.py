"""Admin · Billing Analytics panel section.

Owner ask (2026-08-13): "сколько реально paid юзеров — именно тех у кого есть
карточки привязанные, и когда конкретно будут списания... какие были списания,
может, но не прошли... или прошли и каким методом".

WHY A SEPARATE SECTION
----------------------
The Dashboard answers "is the platform alive" (users, actions, LLM). None of
that says whether MONEY will arrive. This section answers only the money
question, and it reads ONE aggregate endpoint
(GET /v1/internal/billing/analytics) rather than N+1 per-user calls.

THE HONESTY RULE
----------------
Every number here comes from a real column, never from a plan name:

  * "Paying" means subscriptions.payment_method_id actually holds a card
    reference AND settlement is by card AND the amount is non-zero. Inferring
    it from plan price is the exact bug that trapped 11 accounts in an
    add-card loop.
  * The charge schedule mirrors the daily sweep's own WHERE clause, so this
    panel never promises a charge the sweep would not attempt.
  * Test rows (provider='stripe_test') are excluded from money figures and
    the count of what was excluded is shown, so the numbers can be audited
    instead of trusted blindly.

Deliberately NOT read through the panel's own ``_gw_request``: the endpoint
is service-token-only, so that helper would 403 and render an empty section
(same reason as _fetch_billing_mode in panels_user_profile.py).
"""
from __future__ import annotations

import logging

from imperal_sdk import ui
from fmt import money as _money, when_with_color as _when
from app import _panel_acting

log = logging.getLogger("admin")

_DASH = "\u2014"


# ── Formatting ────────────────────────────────────────────────────────


def _status_color(status: str) -> str:
    return {
        "completed": "green",
        "pending": "yellow",
        "failed": "red",
        "disputed": "red",
    }.get((status or "").lower(), "gray")


# ── Data ──────────────────────────────────────────────────────────────


async def _fetch_analytics(acting: str, window_days: int, limit: int) -> dict:
    """Read the one aggregate endpoint. Best-effort like every panel fetch."""
    try:
        # local import: panels never import handlers at module scope
        from handlers_billing_mode import _admin_get
        resp = await _admin_get(
            f"/v1/internal/billing/analytics"
            f"?window_days={window_days}&limit={limit}",
            acting,
            timeout=8.0,
        )
        if resp.status_code != 200:
            log.warning("billing analytics HTTP %s", resp.status_code)
            return {}
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}
    except Exception as e:  # never break the panel
        log.warning("billing analytics fetch failed: %s", e)
        return {}


async def fetch_user_billing_index(acting: str) -> dict:
    """Per-user billing facts for the USER LIST — one call for every row.

    /v1/users carries a plan NAME but no billing period, so the list cannot
    say when anyone actually pays next. This map fills that gap without an
    N+1 read per row.

    Returns ``{"users": {user_id: {...}}, "orphaned_subscriptions": [...]}``.
    Best-effort: a billing outage must degrade the user list to what it
    showed before, never break it.
    """
    try:
        # local import: panels never import handlers at module scope
        from handlers_billing_mode import _admin_get
        resp = await _admin_get("/v1/internal/billing/user-index", acting,
                                timeout=8.0)
        if resp.status_code != 200:
            log.warning("billing user-index HTTP %s", resp.status_code)
            return {}
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}
    except Exception as e:
        log.warning("billing user-index fetch failed: %s", e)
        return {}


# ── Card builders ─────────────────────────────────────────────────────


def _card_money(paid: dict, upcoming: dict) -> ui.Card:
    """The headline: who ACTUALLY pays, and what is already committed."""
    buckets = upcoming.get("buckets") or {}
    next7 = (buckets.get("next_7d") or {}).get("cents", 0)
    next30 = (buckets.get("next_30d") or {}).get("cents", 0)

    return ui.Card(
        title="Money · what is actually chargeable",
        content=ui.Stack(children=[
            ui.Stats(children=[
                ui.Stat(label="Paying (card on file)",
                        value=str(paid.get("paying_with_card", 0)),
                        color="green"),
                ui.Stat(label="MRR committed",
                        value=_money(paid.get("mrr_cents")),
                        color="green"),
                ui.Stat(label="Due next 7 days", value=_money(next7),
                        color="yellow" if next7 else None),
                ui.Stat(label="Due next 30 days", value=_money(next30)),
            ], columns=2),
            ui.Divider(),
            ui.Stats(children=[
                ui.Stat(label="Manual / invoice",
                        value=str(paid.get("manual", 0)), color="blue"),
                ui.Stat(label="Free (owner-set)",
                        value=str(paid.get("free", 0)), color="gray"),
                ui.Stat(label="Card mode, NO card",
                        value=str(paid.get("card_mode_without_card", 0)),
                        color="red" if paid.get("card_mode_without_card")
                        else "green"),
            ], columns=3),
            ui.Text(
                "\"Paying\" counts a real saved card on an active, "
                "non-cancelled subscription with an amount to charge \u2014 "
                "not a plan name. Anyone in card mode without a card cannot "
                "be charged at all.",
                variant="caption",
            ),
        ]),
    )


def _card_subscriptions(subs: dict) -> ui.Card:
    """Population: how subscriptions split by state, settlement and plan."""
    by_status = subs.get("by_status") or {}
    by_mode = subs.get("by_mode") or {}

    rows = []
    for row in (subs.get("by_plan") or []):
        plan = row.get("plan") or _DASH
        count = row.get("count", 0)
        with_card = row.get("with_card", 0)
        mode = row.get("mode") or _DASH
        rows.append({
            "key": f"{plan} · {mode}",
            "value": f"{count} subs · {with_card} with card",
        })

    children = [
        ui.Stats(children=[
            ui.Stat(label="Active", value=str(by_status.get("active", 0)),
                    color="green"),
            ui.Stat(label="Expired", value=str(by_status.get("expired", 0)),
                    color="gray"),
            ui.Stat(label="By card", value=str(by_mode.get("card", 0))),
            ui.Stat(label="Manual", value=str(by_mode.get("manual", 0))),
        ], columns=2),
    ]
    if rows:
        children.append(ui.Divider())
        children.append(ui.KeyValue(items=rows, columns=1))

    return ui.Card(title="Subscriptions · population",
                   content=ui.Stack(children=children))


def _card_schedule(upcoming: dict) -> ui.Card:
    """The 'what is coming and when' log — one row per real future charge."""
    schedule = upcoming.get("schedule") or []
    if not schedule:
        return ui.Card(
            title="Upcoming charges",
            content=ui.Alert(
                title="Nothing scheduled",
                message="No active card-settled subscription is due in this "
                        "window. That is a fact about the data, not an error.",
                type="info",
            ),
        )

    items = []
    for row in schedule:
        stamp, rel, colour = _when(row.get("due_at"))
        fails = row.get("failures") or 0
        items.append(ui.ListItem(
            id=str(row.get("user_id", "")),
            title=row.get("email") or row.get("user_id") or _DASH,
            subtitle=f"{row.get('plan', _DASH)} · "
                     f"{_money(row.get('amount_cents'))} · {stamp}",
            badge=ui.Badge(label=rel, color=colour),
            meta=f"{fails} failed" if fails else "",
            expandable=True,
            expanded_content=[ui.KeyValue(items=[
                {"key": "User", "value": row.get("user_id", _DASH)},
                {"key": "Plan", "value": row.get("plan", _DASH)},
                {"key": "Period", "value": row.get("period", _DASH)},
                {"key": "Amount", "value": _money(row.get("amount_cents"))},
                {"key": "Charges on", "value": stamp},
                {"key": "Settles by", "value": row.get("mode", _DASH)},
                {"key": "Past failures", "value": str(fails)},
            ], columns=2)],
        ))

    return ui.Card(
        title=f"Upcoming charges · {len(items)} scheduled",
        content=ui.Stack(children=[
            ui.Text(
                "Exactly what the daily renewal sweep will attempt, in its "
                "own order. If a row is not here, nothing will be charged.",
                variant="caption",
            ),
            ui.List(items=items, searchable=True),
        ]),
    )


def _card_at_risk(at_risk: list) -> ui.Card | None:
    """Money that will NOT arrive unless someone acts."""
    if not at_risk:
        return None

    reasons = {
        "no_card_on_file": ("No saved card", "red"),
        "renewal_failing": ("Renewal failing", "red"),
        "grace_exhausted": ("Grace exhausted", "red"),
    }

    items = []
    for row in at_risk:
        label, colour = reasons.get(
            row.get("risk", ""), (row.get("risk", "at risk"), "yellow"))
        stamp, rel, _ = _when(row.get("due_at"))
        items.append(ui.ListItem(
            id=str(row.get("user_id", "")),
            title=row.get("email") or row.get("user_id") or _DASH,
            subtitle=f"{row.get('plan', _DASH)} · "
                     f"{_money(row.get('amount_cents'))} · due {stamp}",
            badge=ui.Badge(label=label, color=colour),
            meta=rel,
            expandable=True,
            expanded_content=[
                ui.KeyValue(items=[
                    {"key": "User", "value": row.get("user_id", _DASH)},
                    {"key": "Subscription", "value": row.get("status", _DASH)},
                    {"key": "Amount at risk",
                     "value": _money(row.get("amount_cents"))},
                    {"key": "Failed attempts",
                     "value": str(row.get("failures") or 0)},
                ], columns=2),
                ui.Button(
                    label="Open profile",
                    variant="secondary",
                    on_click=ui.Call("__panel__tools",
                                     section="user_profile",
                                     user_id=row.get("user_id", "")),
                ),
            ],
        ))

    return ui.Card(
        title=f"At risk · {len(items)} subscriptions",
        content=ui.Stack(children=[
            ui.Text(
                "These are billed by card but cannot be charged as they "
                "stand \u2014 no saved card, or repeated failures. Settle "
                "them manually or switch their billing mode.",
                variant="caption",
            ),
            ui.List(items=items, searchable=True),
        ]),
    )


def _card_payments(payments: dict, window_days: int) -> ui.Card:
    """What actually happened: paid, pending, failed — and by which method."""
    by_status = payments.get("by_status") or {}
    excluded = payments.get("test_rows_excluded", 0)

    stat_children = []
    for status in ("completed", "pending", "failed", "disputed"):
        row = by_status.get(status) or {}
        if not row.get("count"):
            continue
        stat_children.append(ui.Stat(
            label=f"{status.title()} · {row.get('count', 0)}",
            value=_money(row.get("cents")),
            color=_status_color(status),
        ))
    if not stat_children:
        stat_children = [ui.Stat(label="No real payments", value=_DASH)]

    method_rows = [
        {"key": f"{r.get('method', '?')} · {r.get('status', '?')}",
         "value": f"{r.get('count', 0)} × {_money(r.get('cents'))}"}
        for r in (payments.get("by_method") or [])
    ]

    log_items = []
    for row in (payments.get("recent") or []):
        status = row.get("status", "?")
        stamp, rel, _ = _when(row.get("created_at"))
        method = row.get("method") or "unrecorded"
        detail = [
            {"key": "User", "value": row.get("user_id", _DASH)},
            {"key": "Amount", "value": _money(row.get("amount_cents"))},
            {"key": "Status", "value": status},
            {"key": "Method", "value": method},
            {"key": "Tokens", "value": str(row.get("tokens") or 0)},
            {"key": "When", "value": stamp},
            {"key": "Auto top-up",
             "value": "yes" if row.get("auto_topup") else "no"},
            {"key": "Payment intent",
             "value": row.get("payment_intent_id", _DASH)},
        ]
        nodes: list = [ui.KeyValue(items=detail, columns=2)]
        if row.get("error"):
            nodes.append(ui.Alert(title="Why it did not go through",
                                  message=str(row["error"]), type="error"))
        log_items.append(ui.ListItem(
            id=str(row.get("payment_intent_id", "")),
            title=row.get("email") or row.get("user_id") or _DASH,
            subtitle=f"{_money(row.get('amount_cents'))} · {method} · {stamp}",
            badge=ui.Badge(label=status, color=_status_color(status)),
            meta=rel,
            expandable=True,
            expanded_content=nodes,
        ))

    children: list = [
        ui.Text(f"Real charges only, last {window_days} days. "
                f"{excluded} test-mode rows excluded from every figure.",
                variant="caption"),
        ui.Stats(children=stat_children, columns=2),
    ]
    if method_rows:
        children.append(ui.Divider())
        children.append(ui.Text("By payment method", variant="caption"))
        children.append(ui.KeyValue(items=method_rows, columns=1))
    if log_items:
        children.append(ui.Divider())
        children.append(ui.Text("Payment log", variant="caption"))
        children.append(ui.List(items=log_items, searchable=True))

    return ui.Card(title="Payments · what actually happened",
                   content=ui.Stack(children=children))


# ── Main builder ──────────────────────────────────────────────────────


async def build_billing_analytics(ctx, window_days: str | int = 30,
                                  **kwargs) -> object:
    """Billing analytics: money, population, schedule, risk, payment log."""
    try:
        window = int(window_days)
    except (TypeError, ValueError):
        window = 30

    data = await _fetch_analytics(_panel_acting(ctx), window, 50)

    if not data:
        return ui.Stack(children=[
            ui.Header("Billing Analytics", level=3),
            ui.Alert(
                title="Billing analytics unavailable",
                message="The billing gateway did not return data. Nothing is "
                        "shown rather than showing numbers that might be "
                        "wrong.",
                type="warning",
            ),
        ])

    children: list = [
        ui.Header("Billing Analytics", level=3),
        _card_money(data.get("paid") or {}, data.get("upcoming") or {}),
        _card_subscriptions(data.get("subscriptions") or {}),
        _card_schedule(data.get("upcoming") or {}),
    ]

    risk_card = _card_at_risk(data.get("at_risk") or [])
    if risk_card:
        children.append(risk_card)

    children.append(_card_payments(data.get("payments") or {}, window))

    generated = data.get("generated_at")
    if generated:
        stamp, rel, _ = _when(generated)
        children.append(ui.Text(f"Read live from the billing database · "
                                f"{stamp} ({rel})", variant="caption"))

    return ui.Stack(children=children, direction="v", gap=4)
