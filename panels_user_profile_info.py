"""Admin · read-only, well-organized info sections for the user profile.

Kept separate from panels_user_profile.py to stay under the 300-LOC ceiling.
Renders the FULL non-secret user record from the gateway (`/v1/users/{id}` +
billing endpoints), grouped into clean sections — and a collapsible raw dump so
NOTHING is hidden. password_hash is never returned by the API, so it can't leak.
"""
from __future__ import annotations

import json

from imperal_sdk import ui


def _kv(items: list[tuple[str, object]]):
    """KeyValue from (label, value) pairs; None/empty rendered as '—'."""
    return ui.KeyValue(
        items=[{"key": k, "value": ("—" if v in (None, "", [], {}) else str(v))}
               for k, v in items],
        columns=2,
    )


def build_info_sections(user: dict, sub: dict, bal: dict) -> list:
    """Return the ordered read-only display sections for a user."""
    attrs = user.get("attributes") or {}
    billing = attrs.get("billing") or {}
    company = attrs.get("company") or {}
    auto = attrs.get("auto_topup") or {}
    verified = attrs.get("email_verified")
    email = user.get("email", "—")
    sections: list = []

    # ── Identity & Contact ─────────────────────────────────────────
    sections.append(ui.Section(title="Identity & Contact", children=[_kv([
        ("Full name", attrs.get("full_name")),
        ("Nickname / handle", user.get("nickname") or attrs.get("display_name")),
        ("Email", f"{email}  {'✓ verified' if verified else '✗ unverified'}"),
        ("Phone", billing.get("phone")),
        ("Imperal ID", user.get("imperal_id")),
        ("Role", user.get("role")),
        ("Account active", "yes" if user.get("is_active") else "NO — deactivated"),
        ("Auth method", user.get("auth_method")),
        ("Created", user.get("created_at")),
        ("Last login", user.get("last_login") or "Never"),
    ])]))

    # ── Business / Account Type ────────────────────────────────────
    acct = attrs.get("account_type") or "personal"
    biz_items: list[tuple[str, object]] = [("Account type", acct)]
    if company:
        biz_items += [
            ("Business name", company.get("company_name")),
            ("Tax ID type", company.get("tax_id_type")),
            ("Tax ID", company.get("tax_id_value")),
        ]
    sections.append(ui.Section(title="Business / Account Type", children=[_kv(biz_items)]))

    # ── Billing Address ────────────────────────────────────────────
    if billing:
        sections.append(ui.Section(title="Billing Address", children=[_kv([
            ("Country", billing.get("country")),
            ("Address line 1", billing.get("address_line1")),
            ("Address line 2", billing.get("address_line2")),
            ("City", billing.get("city")),
            ("State / region", billing.get("state")),
            ("Postal code", billing.get("postal_code")),
        ])]))

    # ── Subscription & Billing (gateway, keyed by imperal_id) ──────
    plan = (sub.get("plan") or bal.get("plan") or "free")
    cancel = bool(sub.get("cancel_at_period_end"))
    balance = int(bal.get("balance") or 0)
    cap = int(bal.get("cap") or 0)
    sections.append(ui.Section(title="Subscription & Billing", children=[_kv([
        ("Plan", str(plan).upper()),
        ("Status", sub.get("status") or "unknown"),
        ("Cancels on" if cancel else "Renews", sub.get("expires_at")),
        ("Started", sub.get("started_at")),
        ("Token balance", f"{balance:,} / {cap:,}" if cap else f"{balance:,}"),
        ("Stripe customer", attrs.get("stripe_customer_id")),
        ("Auto top-up", "on" if auto.get("enabled") else "off"),
    ])]))

    # ── Organization & IDs ─────────────────────────────────────────
    sections.append(ui.Section(title="Organization & IDs", collapsible=True, children=[_kv([
        ("Tenant", user.get("tenant_id")),
        ("Agency", user.get("agency_id")),
        ("Org ID", user.get("org_id")),
        ("Cases user ID", user.get("cases_user_id")),
        ("DB id (uuid)", user.get("id")),
    ])]))

    # ── Raw record (every field the API exposes — nothing hidden) ──
    sections.append(ui.Section(
        title="Raw record (all DB fields)", collapsible=True,
        children=[ui.Code(
            content=json.dumps(user, indent=2, ensure_ascii=False, default=str),
            language="json",
        )],
    ))
    return sections
