"""Admin · Credits panel section — bought vs spent, and the purchase history.

Owner ask (2026-08-13): "я до сих пор не вижу где можно посмотреть историю
покупки системных кредитов. А так же видеть наглядно разницу сколько кредитов
было куплено и потрачено и всего по системе и по юзеру отдельно."

WHY A SEPARATE SECTION
----------------------
Nothing in the panel showed credit HISTORY. The wallet shows one number (the
current balance, a Redis cache with no history at all), and Billing Analytics
answers the SUBSCRIPTION question — who pays, when, by which card. Neither
answers "how many credits were bought, how many were burned, and by whom".
This section reads ONE aggregate endpoint,
GET /v1/internal/billing/credits, instead of N+1 per-user calls.

THE TWO HONESTY RULES (enforced gateway-side in app/billing/credits.py)
-----------------------------------------------------------------------
1. `reason` in token_ledger is FREE TEXT, not an enum. Alongside the machine
   written `topup` sit hand-typed strings: 'admin_grant', 'admin_credit_1M',
   'rhtlbnjd', 'выдача 1M по просьбе администратора'. So BOUGHT and GRANTED
   are shown as two different numbers and are never added together — folding
   ~42.6M of admin gifts into "bought" would invent revenue that nobody paid.

2. Credits CANNOT be reconciled to money. Every topup row on this database
   carries reference_id = NULL, so there is no join back to
   payment_transactions. The money figure is therefore rendered in its own
   card, labelled as unreconciled, and never summed with credit totals.

Deliberately NOT read through the panel's own ``_gw_request``: the endpoint is
service-token-only, so that helper would 403 and render an empty section (same
reason as _fetch_analytics in panels_billing_analytics.py).
"""
from __future__ import annotations

import logging

from imperal_sdk import ui
from fmt import money as _money, when_relative as _when
from app import _panel_acting

log = logging.getLogger("admin")

_DASH = "\u2014"


# ── Formatting ────────────────────────────────────────────────────────


def _credits(value) -> str:
    """Credits are integers, always. Never rendered as money."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return _DASH


# Shared with panels_billing_analytics.py / handlers_billing_mode.py — see
# fmt.py docstring for why this used to be 3 copy-pasted definitions.
from fmt import money as _money, when_relative as _when


_KIND_COLOR = {
    "purchase": "green",
    "grant": "yellow",
    "starter": "blue",
}


def _kind_label(kind: str) -> str:
    return {
        "purchase": "bought",
        "grant": "admin grant",
        "starter": "signup gift",
    }.get(kind, kind or "?")


# ── Data ──────────────────────────────────────────────────────────────



async def _fetch_credits(acting: str, window_days: int, limit: int) -> dict:
    """Read the one aggregate endpoint. Best-effort like every panel fetch."""
    try:
        # local import: panels never import handlers at module scope
        from handlers_billing_mode import _admin_get
        resp = await _admin_get(
            f"/v1/internal/billing/credits"
            f"?window_days={window_days}&limit={limit}",
            acting,
            timeout=8.0,
        )
        if resp.status_code != 200:
            log.warning("credit analytics HTTP %s", resp.status_code)
            return {}
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}
    except Exception as e:  # never break the panel
        log.warning("credit analytics fetch failed: %s", e)
        return {}


async def fetch_user_credits(acting: str, user_id: str) -> dict:
    """One account's credit totals + purchase history, for the user profile.

    Best-effort: a billing outage must degrade the profile card to nothing,
    never break the profile.
    """
    if not user_id:
        return {}
    try:
        from handlers_billing_mode import _admin_get
        resp = await _admin_get(f"/v1/internal/billing/credits/{user_id}",
                                acting, timeout=8.0)
        if resp.status_code != 200:
            log.warning("user credits HTTP %s", resp.status_code)
            return {}
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}
    except Exception as e:
        log.warning("user credits fetch failed: %s", e)
        return {}


# ── Card builders ─────────────────────────────────────────────────────


def _card_totals(all_time: dict, window: dict, window_days: int) -> ui.Card:
    """The headline answer: bought vs spent, all time and in the window.

    `bought` and `granted` stay separate on purpose — see the module
    docstring. `net_spent` is spending AFTER refunds, because ~19,943 refund
    rows would otherwise overstate consumption.
    """
    rows = all_time.get("rows") or {}

    stats = [
        ui.Stat(label=f"Bought · {rows.get('bought', 0)} top-ups",
                value=_credits(all_time.get("bought")), color="green"),
        ui.Stat(label=f"Granted by admins · {rows.get('granted', 0)}",
                value=_credits(all_time.get("granted")), color="yellow"),
        ui.Stat(label=f"Spent · {rows.get('spent', 0)} actions",
                value=_credits(all_time.get("net_spent")), color="red"),
        ui.Stat(label="Left across all wallets",
                value=_credits(all_time.get("net")), color="blue"),
    ]

    detail = [
        {"key": "Bought (paid top-ups)",
         "value": _credits(all_time.get("bought"))},
        {"key": "Granted by admins",
         "value": _credits(all_time.get("granted"))},
        {"key": "Signup gifts",
         "value": _credits(all_time.get("starter"))},
        {"key": "Total received",
         "value": _credits(all_time.get("received"))},
        {"key": "Spent (gross)", "value": _credits(all_time.get("spent"))},
        {"key": "Refunded back",
         "value": _credits(all_time.get("refunded"))},
        {"key": "Spent (net of refunds)",
         "value": _credits(all_time.get("net_spent"))},
        {"key": "Remaining", "value": _credits(all_time.get("net"))},
    ]

    win_rows = [
        {"key": "Bought", "value": _credits(window.get("bought"))},
        {"key": "Granted", "value": _credits(window.get("granted"))},
        {"key": "Spent (net)", "value": _credits(window.get("net_spent"))},
    ]

    return ui.Card(
        title="Credits · bought vs spent",
        content=ui.Stack(children=[
            ui.Text(
                "Bought and granted are shown separately and never added: "
                "'bought' counts only real top-ups, while admin grants are "
                "credits nobody paid for. Spending is net of refunds.",
                variant="caption",
            ),
            ui.Stats(children=stats, columns=2),
            ui.Divider(),
            ui.Text("All time", variant="caption"),
            ui.KeyValue(items=detail, columns=2),
            ui.Divider(),
            ui.Text(f"Last {window_days} days", variant="caption"),
            ui.KeyValue(items=win_rows, columns=3),
        ]),
    )


def _card_money(payments: dict) -> ui.Card:
    """Real money — kept in its own card because it does NOT reconcile.

    Every topup ledger row carries reference_id = NULL, so credits cannot be
    joined to payments. Showing the two side by side without saying so would
    imply a link that does not exist in this database.
    """
    children: list = [
        ui.Stats(children=[
            ui.Stat(label=f"Real payments · {payments.get('real_completed', 0)}",
                    value=_money(payments.get("real_cents")), color="green"),
            ui.Stat(label="Credits delivered by those payments",
                    value=_credits(payments.get("real_tokens")), color="blue"),
        ], columns=2),
    ]

    if not payments.get("reconcilable_with_ledger", False):
        children.append(ui.Alert(
            title="Credits and payments cannot be cross-checked",
            message=(
                "Top-up ledger rows do not store which payment created them "
                "(reference_id is empty on every row), so these two figures "
                "cannot be reconciled and are never added together. New "
                "top-ups will reconcile once the payment id is recorded."
            ),
            type="info",
        ))

    excluded = payments.get("test_rows_excluded", 0)
    if excluded:
        children.append(ui.Text(
            f"{excluded} test-mode payment rows "
            f"({_credits(payments.get('test_tokens_excluded'))} credits) are "
            f"excluded from the money figures above.",
            variant="caption",
        ))

    return ui.Card(title="Money · what was actually paid",
                   content=ui.Stack(children=children))


def _card_history(history: list) -> ui.Card:
    """The purchase history that had nowhere to be seen until now."""
    if not history:
        return ui.Card(
            title="Credit purchase history",
            content=ui.Text("No credits have been added yet.",
                            variant="caption"),
        )

    items = []
    for row in history:
        kind = row.get("kind", "")
        stamp, rel = _when(row.get("at"))
        who = row.get("email") or row.get("user_id") or _DASH
        detail = [
            {"key": "User", "value": who},
            {"key": "Account id", "value": row.get("user_id", _DASH)},
            {"key": "Credits", "value": _credits(row.get("credits"))},
            {"key": "Type", "value": _kind_label(kind)},
            {"key": "Recorded reason", "value": row.get("reason") or _DASH},
            {"key": "When", "value": stamp},
        ]
        if row.get("description"):
            detail.append({"key": "Description",
                           "value": str(row["description"])})
        if row.get("app_id"):
            detail.append({"key": "App", "value": str(row["app_id"])})

        items.append(ui.ListItem(
            id=f"{row.get('user_id', '')}-{row.get('at', '')}",
            title=who,
            subtitle=f"+{_credits(row.get('credits'))} · "
                     f"{_kind_label(kind)} · {stamp}",
            badge=ui.Badge(label=_kind_label(kind),
                           color=_KIND_COLOR.get(kind, "gray")),
            meta=rel,
            expandable=True,
            expanded_content=[ui.KeyValue(items=detail, columns=2)],
        ))

    return ui.Card(
        title="Credit purchase history",
        content=ui.Stack(children=[
            ui.Text(
                "Every credit ever added to any wallet, newest first. "
                "'bought' is a real top-up; 'admin grant' is credits issued "
                "by hand.",
                variant="caption",
            ),
            ui.List(items=items, searchable=True),
        ]),
    )


def _card_per_user(per_user: list) -> ui.Card:
    """Same split, per account — so one heavy user is visible at a glance."""
    if not per_user:
        return ui.Card(
            title="Per user",
            content=ui.Text("No credit activity recorded yet.",
                            variant="caption"),
        )

    items = []
    for row in per_user:
        who = row.get("email") or row.get("user_id") or _DASH
        rows = row.get("rows") or {}
        detail = [
            {"key": "Bought", "value": _credits(row.get("bought"))},
            {"key": "Granted by admins", "value": _credits(row.get("granted"))},
            {"key": "Signup gift", "value": _credits(row.get("starter"))},
            {"key": "Total received", "value": _credits(row.get("received"))},
            {"key": "Spent (gross)", "value": _credits(row.get("spent"))},
            {"key": "Refunded", "value": _credits(row.get("refunded"))},
            {"key": "Spent (net)", "value": _credits(row.get("net_spent"))},
            {"key": "Left", "value": _credits(row.get("net"))},
            {"key": "Top-ups", "value": str(rows.get("bought", 0))},
            {"key": "Actions charged", "value": str(rows.get("spent", 0))},
        ]
        bought = int(row.get("bought") or 0)
        badge = (ui.Badge(label="paying", color="green") if bought
                 else ui.Badge(label="granted only", color="yellow"))
        items.append(ui.ListItem(
            id=str(row.get("user_id", "")),
            title=who,
            subtitle=f"spent {_credits(row.get('net_spent'))} · "
                     f"left {_credits(row.get('net'))}",
            badge=badge,
            meta=f"bought {_credits(row.get('bought'))}",
            expandable=True,
            expanded_content=[ui.KeyValue(items=detail, columns=2)],
        ))

    return ui.Card(
        title="Per user · who bought, who was granted, who burned it",
        content=ui.Stack(children=[
            ui.Text("Ranked by net spending. 'granted only' means the "
                    "account never paid for credits.", variant="caption"),
            ui.List(items=items, searchable=True),
        ]),
    )


# ── Main builder ──────────────────────────────────────────────────────


async def build_credits(ctx, window_days: str | int = 30, **kwargs) -> object:
    """Credits section: totals, money, purchase history, per-user split."""
    try:
        window = int(window_days)
    except (TypeError, ValueError):
        window = 30

    data = await _fetch_credits(_panel_acting(ctx), window, 100)

    if not data:
        return ui.Stack(children=[
            ui.Header("Credits", level=3),
            ui.Alert(
                title="Credit analytics unavailable",
                message="The billing gateway did not return data. Nothing is "
                        "shown rather than showing numbers that might be "
                        "wrong.",
                type="warning",
            ),
        ])

    platform = data.get("platform") or {}
    children: list = [
        ui.Header("Credits", level=3),
        _card_totals(platform.get("all_time") or {},
                     platform.get("window") or {}, window),
        _card_money(data.get("payments") or {}),
        _card_history(data.get("history") or []),
        _card_per_user(data.get("per_user") or []),
    ]

    generated = data.get("generated_at")
    if generated:
        stamp, rel = _when(generated)
        children.append(ui.Text(
            f"Read live from the billing ledger · {stamp} ({rel})",
            variant="caption"))

    return ui.Stack(children=children, direction="v", gap=4)


# ── Per-user section, embedded in the user profile ────────────────────


def build_user_credits_section(credits: dict) -> ui.Section | None:
    """ONE account's credits, rendered inside its profile page.

    Answers the per-user half of the owner ask: the profile already shows a
    wallet balance, but a balance is a single number with no history — it
    cannot say whether those credits were PAID FOR or HANDED OUT, which is
    exactly the distinction being asked for.

    Lives here rather than in panels_user_profile so the bought-vs-granted
    formatting has one home: if the classification ever changes, it changes
    in one file, not two.

    Returns None when there is nothing to show, so a billing outage leaves
    the profile untouched instead of adding an empty or zeroed card.
    """
    if not credits:
        return None

    totals = credits.get("totals") or {}
    rows = totals.get("rows") or {}
    if not any(totals.get(k) for k in
               ("bought", "granted", "starter", "spent", "net")):
        return None

    bought = int(totals.get("bought") or 0)
    granted = int(totals.get("granted") or 0)

    stats = [
        ui.Stat(label=f"Bought · {rows.get('bought', 0)} top-ups",
                value=_credits(bought), color="green"),
        ui.Stat(label=f"Granted by admins · {rows.get('granted', 0)}",
                value=_credits(granted), color="yellow"),
        ui.Stat(label=f"Spent · {rows.get('spent', 0)} actions",
                value=_credits(totals.get("net_spent")), color="red"),
        ui.Stat(label="Left in wallet",
                value=_credits(totals.get("net")), color="blue"),
    ]

    children: list = [ui.Stats(children=stats)]

    # The one sentence an admin actually needs: did this account pay, or was
    # it topped up by hand? Stated explicitly, because two identical balances
    # can have completely different origins.
    if bought and granted:
        children.append(ui.Text(
            f"{_credits(bought)} bought, {_credits(granted)} granted by "
            "admins — the balance is not all paid-for.",
            variant="caption"))
    elif granted and not bought:
        children.append(ui.Text(
            "Every credit on this account was granted by an admin, none "
            "were bought.", variant="caption"))
    elif bought and not granted:
        children.append(ui.Text(
            "All credits on this account were bought.", variant="caption"))

    purchases = credits.get("purchases") or []
    if purchases:
        items = []
        for row in purchases[:15]:
            kind = row.get("kind", "")
            stamp, rel = _when(row.get("at"))
            items.append(ui.ListItem(
                id=f"{row.get('at', '')}-{row.get('reason', '')}",
                title=f"+{_credits(row.get('credits'))} · {_kind_label(kind)}",
                subtitle=f"{stamp} ({rel}) · {row.get('reason') or _DASH}",
                badge=ui.Badge(label=_kind_label(kind),
                               color=_KIND_COLOR.get(kind, "gray")),
            ))
        children.append(ui.Divider())
        children.append(ui.Text(
            f"Credit history · {len(purchases)} top-up(s) and grant(s)",
            variant="caption"))
        children.append(ui.List(items=items))
    else:
        children.append(ui.Text(
            "No top-ups or grants recorded for this account.",
            variant="caption"))

    return ui.Section(title="Credits", collapsible=True, children=children)
