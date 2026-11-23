"""Admin · Full user profile editor (section switch from users list).

Matches React Full Profile: identity, role, scopes, individual
limits, ABAC attributes, extension access.
Each area in a named Section for clarity.
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import ui

from app import _gw_request, _tenant_id
from panels_sections import (
    _fetch_roles, _fetch_extensions, _fetch_user_extensions,
    _fetch_scope_names, _fetch_plans, _cached,
)
from panels_user_profile_info import build_info_sections

log = logging.getLogger("admin")


async def _fetch_effective_scopes_raw(user_id: str) -> list[str]:
    try:
        result = await _gw_request("GET", f"/v1/scopes/effective/{user_id}")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("expanded", result.get("scopes", []))
        return []
    except Exception:
        return []


async def _fetch_effective_scopes(user_id: str) -> list[str]:
    return await _cached(
        f"eff_scopes:{user_id}",
        lambda: _fetch_effective_scopes_raw(user_id),
    )


async def _fetch_developer_profile(user_id: str) -> dict:
    """Developer profile (tier/nickname/apps/earnings) — {} when the user is
    not a registered developer (gateway 403) or on any error; never breaks
    the profile editor."""
    try:
        result = await _gw_request("GET", f"/v1/developer/profile?user_id={user_id}")
        return result if isinstance(result, dict) and "error" not in result else {}
    except Exception:
        return {}


async def _fetch_user_billing(user_id: str) -> tuple[dict, dict]:
    """Subscription (plan/status/renewal) + wallet for a user. Both gateway
    endpoints key on the canonical imperal_id — same truth the user's own
    billing extension reads. Best-effort: never breaks the profile editor."""
    async def _sub():
        return await _gw_request("GET", f"/v1/billing/internal/subscription/{user_id}")

    async def _bal():
        return await _gw_request("GET", f"/v1/billing/internal/balance/{user_id}")

    sub, bal = await asyncio.gather(_sub(), _bal())
    sub = sub if isinstance(sub, dict) and "error" not in sub else {}
    bal = bal if isinstance(bal, dict) and "error" not in bal else {}
    return sub, bal


def _panel_acting(ctx) -> str:
    """The admin viewing this panel (mirrors handlers_billing_mode._acting)."""
    try:
        return str(getattr(getattr(ctx, "user", None), "imperal_id", "") or "")
    except Exception:
        return ""


async def _fetch_billing_mode(user_id: str, acting: str) -> dict:
    """HOW this subscription settles: card / manual / free, plus the two answers
    the gateway DERIVES from that (card_required, charges_automatically).

    Deliberately NOT read through ``_gw_request``: this lives behind the
    admin-only /v1/internal/billing/subscription-billing endpoint, which
    requires the service token that the panel's own helper does not send —
    reading it that way would 403 and render an empty section.

    Best-effort like every other fetch here: never breaks the profile editor.
    """
    try:
        from handlers_billing_mode import _admin_get  # local: panels never import handlers at module scope
        resp = await _admin_get(
            f"/v1/internal/billing/subscription-billing/{user_id}", acting,
        )
        if resp.status_code != 200:
            return {}
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


async def _fetch_credits(user_id: str, acting: str) -> dict:
    """This account's credit story: bought / granted / spent, plus its history.

    Answers the per-user half of the owner ask (2026-08-13): "see clearly the difference between credits bought and spent per user separately".
    The wallet balance already on this page is ONE number with no history —
    it cannot say whether those credits were paid for or handed out.

    Local import, like _fetch_billing_mode above: panels never import sibling
    modules at module scope, which also keeps this free of an import cycle
    (panels_credits reaches back into this module for user emails).

    Best-effort: never breaks the profile editor.
    """
    try:
        from panels_credits import fetch_user_credits
        return await fetch_user_credits(acting, user_id)
    except Exception:
        return {}


async def _fetch_confirmation(user_id: str, tenant: str) -> dict | None:
    """The user's 2-step confirmation settings from the store the kernel reads
    (unified_config user_settings, see handlers_system.fn_set_user_confirmation).
    None = they could not be read; the profile then says so and offers no
    switch, because a switch drawn from a guess would save the guess."""
    try:
        r = await _gw_request(
            "GET", f"/v1/internal/users/{user_id}/settings?tenant_id={tenant}")
    except Exception:
        return None
    if not isinstance(r, dict) or r.get("error"):
        return None
    settings = r.get("settings", r)
    return settings if isinstance(settings, dict) else None


_ACCESS_OPTIONS = [
    {"value": "inherit", "label": "Plan default"},
    {"value": "allow", "label": "Allow"},
    {"value": "deny", "label": "Deny"},
]

# (title, the tool that saves it, the attribute that holds it)
_ACCESS_FEATURES = [
    ("Webbee Code", "set_user_coding_access", "coding_access"),
    ("Connections (SSH / MCP targets)", "set_user_connections_access", "connections_access"),
    ("File Reader (document ingestion)", "set_user_file_reader_access", "file_reader_access"),
]


def _role_default(roles, role_name, field, fallback) -> str:
    r = next((r for r in roles if r.get("name") == role_name), None)
    if r and r.get(field) is not None:
        return str(r[field])
    return str(fallback)


async def build_user_profile(ctx, user_id: str = "", **kwargs):
    if not user_id:
        return ui.Alert(message="No user selected", type="error")

    async def _get_user():
        return await _gw_request("GET", f"/v1/users/{user_id}")

    back = ui.Button(
        "\u2190 Back to Users", variant="ghost",
        on_click=ui.Call("__panel__tools", section="management", user_id=""),
    )
    try:
        user = await _cached(f"user:{user_id}", _get_user)
    except Exception as e:
        user = {"error": f"{type(e).__name__}: {e}"}
    if not isinstance(user, dict) or "error" in user:
        # the gateway's own words: "not found" and "the gateway is down" are
        # different facts and were both shown as "not found"
        why = user.get("error") if isinstance(user, dict) else "the gateway did not answer with a user"
        return ui.Stack(children=[back, ui.Alert(
            title=f"User {user_id} could not be read", message=str(why), type="error")])

    _acting = _panel_acting(ctx)
    (roles, all_scopes, extensions, user_exts, effective, billing, dev_profile, bmode,
     credits, plans, confirmation) = await asyncio.gather(
        _fetch_roles(), _fetch_scope_names(), _fetch_extensions(),
        _fetch_user_extensions(user_id), _fetch_effective_scopes(user_id),
        _fetch_user_billing(user_id), _fetch_developer_profile(user_id),
        _fetch_billing_mode(user_id, _acting),
        _fetch_credits(user_id, _acting),
        _fetch_plans(), _fetch_confirmation(user_id, _tenant_id(ctx)),
    )
    sub_data, bal_data = billing

    email = user.get("email", "?")
    role = user.get("role", "user")
    is_active = user.get("is_active", True)
    scopes = user.get("scopes", [])
    attrs = user.get("attributes", {})

    role_options = [
        {"value": r.get("name", ""),
         "label": r.get("display_name", r.get("name", ""))}
        for r in roles
    ]

    nodes: list = [
        back,
        ui.Header(email, level=3, subtitle=user_id),

        # ── Role & Status ─────────────────────────────────────────
        ui.Section(title="Role & Status", children=[
            ui.Form(
                action="update_user",
                submit_label="Save Role & Status",
                defaults={"user_id": user_id},
                children=[
                    ui.Text("Role", variant="caption"),
                    ui.Select(
                        options=role_options,
                        value=role,
                        param_name="role",
                    ),
                    ui.Toggle(
                        label="Account active",
                        value=is_active,
                        param_name="is_active",
                    ),
                ],
            ),
        ]),

        # ── User Scopes ───────────────────────────────────────────
        ui.Section(
            title=f"User Scopes ({len(scopes)})",
            children=[
                ui.Form(
                    action="update_user",
                    submit_label="Save Scopes",
                    defaults={"user_id": user_id},
                    children=[
                        ui.TagInput(
                            values=scopes,
                            suggestions=all_scopes,
                            param_name="scopes",
                            placeholder="Add scope...",
                            grouped_by=":",
                        ),
                    ],
                ),
            ],
        ),
    ]

    # ── Full read-only info, organized: Identity & Contact, Business /
    #    Account Type, Billing Address, Subscription & Billing, Organization &
    #    IDs, plus a collapsible raw dump so NO field is hidden. Inserted right
    #    after the header, above the editable controls below.
    nodes[2:2] = build_info_sections(user, sub_data, bal_data)

    # ── Effective Scopes (role + user combined) ────────────────────
    if effective:
        eff_badges = [ui.Badge(label=s, color="blue")
                      for s in effective[:20]]
        if len(effective) > 20:
            eff_badges.append(
                ui.Badge(f"+{len(effective) - 20} more", color="gray"))
        nodes.append(ui.Section(
            title=f"Effective Scopes ({len(effective)})",
            collapsible=True,
            children=[
                ui.Text("Combined from role defaults + user overrides",
                        variant="caption"),
                ui.Stack(eff_badges, direction="h", gap=1, wrap=True),
            ],
        ))

    # ── Developer (tier = the developer "group"; independent of RBAC role) ──
    dev_tier = dev_profile.get("tier") or ""
    dev_children: list = []
    if dev_profile:
        dev_children.append(ui.KeyValue(items=[
            {"key": "Tier", "value": dev_tier or "—"},
            {"key": "Nickname", "value": str(dev_profile.get("nickname") or "—")},
            {"key": "Apps", "value": str(dev_profile.get("apps_count", 0))},
            {"key": "Total earnings", "value": str(dev_profile.get("total_earnings", 0))},
            {"key": "Registered", "value": str(dev_profile.get("registered_at") or "—")},
        ], columns=2))
    else:
        dev_children.append(ui.Text(
            "Not registered as a developer — setting a tier below grants "
            "developer status (audited admin comp, no charge).",
            variant="caption",
        ))
    dev_children.append(ui.Form(
        action="set_developer_tier",
        submit_label="Set Developer Tier",
        defaults={"user": user_id},
        children=[
            ui.Text("Developer tier (admin comp — no charge)", variant="caption"),
            ui.Select(
                options=[{"value": t, "label": t.capitalize()}
                         for t in ("explorer", "indie", "studio", "partner")],
                value=dev_tier or "explorer",
                param_name="tier",
            ),
        ],
    ))
    nodes.append(ui.Section(title="Developer", children=dev_children))

    # ── Plan ───────────────────────────────────────────────────────
    # Moved here from the user list 2026-11-23: there the plan changed the
    # moment a select moved, with no Save and no second look.
    current_plan = str(sub_data.get("plan") or user.get("plan") or "")
    plan_options = [{"value": p.get("name", ""), "label": p.get("name", "")}
                    for p in plans if isinstance(p, dict) and p.get("name")]
    if current_plan and current_plan not in {o["value"] for o in plan_options}:
        plan_options.insert(0, {"value": current_plan, "label": current_plan})
    if plan_options:
        plan_children: list = [ui.Form(
            action="set_user_plan",
            submit_label="Save Plan",
            defaults={"user_id": user_id},
            children=[
                ui.Text(f"Current plan: {current_plan or 'none on record'}", variant="caption"),
                ui.Select(options=plan_options, value=current_plan or plan_options[0]["value"],
                          param_name="plan_ref"),
            ],
        )]
    else:
        plan_children = [ui.Alert(
            message="The plan list could not be read, so the plan cannot be changed from here right now.",
            type="warning")]
    nodes.append(ui.Section(title="Plan", children=plan_children))

    # ── Billing Settlement (owner control: HOW and WHEN they pay) ──
    # Added 2026-08-13. The two billing-mode tools existed but had NO panel at
    # all, so the owner could only reach them by asking Webbee in chat. Same
    # rule as everywhere else: whether a card is required is the GATEWAY's
    # answer (card_required), never re-derived here from a plan name — that
    # re-derivation is exactly the bug that trapped 11 accounts in an
    # add-card loop.
    _mode = (bmode.get("billing_mode") or "card").lower()
    _mode_label = {
        "card": "By card — the saved card is charged on renewal",
        "manual": "By invoice / bank transfer — no card, never auto-charged",
        "free": "Free — comped access, never charged",
    }.get(_mode, _mode)
    _amount_cents = bmode.get("contract_amount_cents")
    _amount_now = "" if _amount_cents in (None, "") else f"{int(_amount_cents) / 100:.2f}"

    _settle_children: list = []
    if not bmode:
        _settle_children.append(ui.Alert(
            type="info",
            title="No active subscription",
            message=(
                "Settlement applies to an active subscription. Assign a plan "
                "first, then choose how this customer pays."
            ),
        ))
    else:
        _settle_children.extend([
            ui.Stack([
                ui.Badge(
                    label=_mode.upper(),
                    color={"card": "blue", "manual": "orange", "free": "green"}.get(_mode, "gray"),
                ),
                ui.Badge(
                    label=("card required" if bmode.get("card_required") else "no card needed"),
                    color=("red" if bmode.get("card_required") else "green"),
                ),
                ui.Badge(
                    label=("auto-charge on" if bmode.get("charges_automatically") else "auto-charge off"),
                    color=("blue" if bmode.get("charges_automatically") else "gray"),
                ),
            ], direction="h", gap=2),
            ui.Text(_mode_label, variant="caption"),
            ui.KeyValue(items=[
                {"key": "Contract amount",
                 "value": (f"${_amount_now}/period" if _amount_now else "— uses the plan price")},
                {"key": ("Period ends" if _mode in ("manual", "free") else "Renews"),
                 "value": ("never expires" if bmode.get("never_expires")
                           else (bmode.get("expires_at") or "—"))},
                {"key": "Note", "value": bmode.get("billing_note") or "—"},
            ], columns=2),
            ui.Form(
                action="set_user_billing_mode",
                submit_label="Save Settlement",
                defaults={"user_id": user_id},
                children=[
                    ui.Text("How they pay", variant="caption"),
                    ui.Select(
                        param_name="mode",
                        value=_mode,
                        options=[
                            {"value": "card", "label": "Card — charge the saved card automatically"},
                            {"value": "manual", "label": "Manual — invoice / bank transfer (no card)"},
                            {"value": "free", "label": "Free — comped access"},
                        ],
                    ),
                    ui.Text(
                        "Contract amount in dollars per period — what finally makes a "
                        "price-0 enterprise contract chargeable. Empty = use the plan price.",
                        variant="caption",
                    ),
                    ui.Input(
                        param_name="contract_amount",
                        value=_amount_now,
                        placeholder="e.g. 500.00",
                    ),
                    ui.Text(
                        "Extend the paid period by N days — the manual equivalent of a "
                        "renewal, for a customer who just paid an invoice.",
                        variant="caption",
                    ),
                    ui.Input(param_name="extend_days", value="", placeholder="e.g. 30"),
                    ui.Text(
                        "Or set the period end explicitly — an ISO date, or 'never' for "
                        "a seat that never expires.",
                        variant="caption",
                    ),
                    ui.Input(
                        param_name="expires_at",
                        value="",
                        placeholder="2027-01-31  ·  never",
                    ),
                    ui.Text("Why, for the record", variant="caption"),
                    ui.Input(
                        param_name="note",
                        value=bmode.get("billing_note") or "",
                        placeholder="pays by bank transfer, contract INV-2026-04",
                    ),
                    ui.Toggle(
                        label="Drop the custom amount (fall back to the plan price)",
                        value=False,
                        param_name="clear_contract_amount",
                    ),
                ],
            ),
        ])
    nodes.append(ui.Section(title="Billing Settlement", children=_settle_children))

    # ── Credits (bought vs granted vs spent) ───────────────────────
    # Sits right after settlement on purpose: "how they pay" and "what they
    # actually got" belong together. Renders nothing at all when the billing
    # gateway is silent — an empty card on a money screen reads as "zero",
    # which is a different (and wrong) statement.
    try:
        from panels_credits import build_user_credits_section
        _credits_section = build_user_credits_section(credits)
        if _credits_section is not None:
            nodes.append(_credits_section)
    except Exception:  # never break the profile editor over a read-only card
        pass

    nodes.append(ui.Section(
        title="Individual Limits",
        children=[
            ui.Text("Leave empty to inherit from role defaults",
                    variant="caption"),
            ui.Form(
                action="update_user_limits",
                submit_label="Save Limits",
                defaults={"user_id": user_id},
                children=[
                    ui.Text("Monthly action limit", variant="caption"),
                    ui.Input(
                        param_name="monthly_action_limit",
                        value=str(attrs.get("monthly_action_limit", "")),
                        placeholder=f"Role default: {_role_default(roles, role, 'monthly_action_limit', 500)}",
                    ),
                    ui.Text("Max concurrent tasks", variant="caption"),
                    ui.Input(
                        param_name="max_concurrent_tasks",
                        value=str(attrs.get("max_concurrent_tasks", "")),
                        placeholder=f"Role default: {_role_default(roles, role, 'max_concurrent_tasks', 3)}",
                    ),
                    ui.Text("History window (messages, default 6)", variant="caption"),
                    ui.Input(
                        param_name="context_window",
                        value=str(attrs.get("context_window", "")),
                        placeholder=f"Role default: {_role_default(roles, role, 'context_window', 6)}",
                    ),
                ],
            ),
        ],
    ))

    # ── Feature access (per-user override of the plan) ─────────────
    nodes.append(ui.Section(
        title="Feature access",
        children=[
            ui.Text("Each feature follows the plan unless it is allowed or denied here.",
                    variant="caption"),
            *[ui.Form(
                action=tool,
                submit_label=f"Save {title.split(' (')[0]}",
                defaults={"user_id": user_id},
                children=[
                    ui.Text(title, variant="caption"),
                    ui.Select(options=_ACCESS_OPTIONS, value=attrs.get(attr) or "inherit",
                              param_name="access"),
                ],
            ) for title, tool, attr in _ACCESS_FEATURES],
        ],
    ))

    # ── Confirmation (2-step) ──────────────────────────────────────
    # The value shown is the one the kernel acts on, not the attribute mirror
    # the old list card printed.
    if confirmation is None:
        conf_children: list = [ui.Alert(
            message="The confirmation settings could not be read, so no switch is offered.",
            type="warning")]
    else:
        _conf = confirmation.get("confirmation_enabled")
        conf_children = [
            ui.Text(
                "Not set for this user: the role's policy applies." if _conf is None
                else f"Set for this user: {'on' if _conf else 'off'}.",
                variant="caption"),
            ui.Form(
                action="set_user_confirmation",
                submit_label="Save Confirmation",
                defaults={"user_id": user_id},
                children=[
                    ui.Toggle(label="Ask before a change is made", value=bool(_conf),
                              param_name="enabled"),
                    ui.Toggle(label="Do not ask for read-only actions",
                              value=bool(confirmation.get("confirmation_skip_read")),
                              param_name="skip_read"),
                ],
            ),
        ]
    nodes.append(ui.Section(title="Confirmation (2-step)", children=conf_children))

    # ── Custom Attributes (ABAC) ───────────────────────────────────
    # Hide keys already shown in the organized sections above + the limit/
    # confirmation keys that have their own controls — the catch-all then lists
    # only genuinely-leftover attributes (nothing hidden, nothing duplicated).
    _surfaced = {
        "monthly_action_limit", "max_concurrent_tasks", "context_window",
        "confirmation_enabled", "confirmation_skip_read",
        "coding_access", "connections_access", "file_reader_access",
        "account_type", "billing", "company", "display_name", "full_name",
        "email_verified", "email_verified_at", "stripe_customer_id", "auto_topup",
        # shown in the Developer section above
        "developer_tier", "developer_registered_at", "developer_tier_started_at",
        "developer_tier_expires_at", "developer_tier_grace_until",
        "developer_tier_pending_downgrade",
    }
    display_attrs = {k: v for k, v in attrs.items() if k not in _surfaced}
    attr_children: list = []
    if display_attrs:
        attr_children.append(ui.KeyValue(
            items=[{"key": k, "value": str(v)}
                   for k, v in display_attrs.items()],
            columns=2,
        ))
        for k in display_attrs:
            attr_children.append(ui.Button(
                f"Remove \u201c{k}\u201d", variant="ghost",
                on_click=ui.Call("remove_user_attribute",
                                 user_id=user_id, attr_key=k),
            ))
    else:
        attr_children.append(
            ui.Text("No custom attributes", variant="caption"))

    attr_children.append(ui.Form(
        action="set_user_attribute",
        submit_label="Add Attribute",
        defaults={"user_id": user_id},
        children=[
            ui.Stack([
                ui.Input(param_name="attr_key", placeholder="Key"),
                ui.Input(param_name="attr_value", placeholder="Value"),
            ], direction="h", gap=2),
        ],
    ))
    nodes.append(ui.Section(
        title=f"Custom Attributes ({len(display_attrs)})",
        collapsible=True,
        children=attr_children,
    ))

    # ── Extension Access ───────────────────────────────────────────
    if user_exts:
        ue_map = {e.get("app_id"): e for e in user_exts}
        ext_badges = []
        for ext in extensions:
            app_id = ext.get("app_id", "")
            name = ext.get("display_name", app_id)
            ue = ue_map.get(app_id)
            if ue is None:
                continue
            enabled = ue.get("enabled", True)
            has_access = ue.get("has_access", True)
            if not has_access or not enabled:
                ext_badges.append(
                    ui.Badge(label=f"{name} (off)", color="red"))
            elif ue.get("source") == "role_default":
                ext_badges.append(
                    ui.Badge(label=f"{name} (role)", color="gray"))
            else:
                ext_badges.append(ui.Badge(label=name, color="blue"))

        if ext_badges:
            nodes.append(ui.Section(
                title="Extension Access",
                children=[
                    ui.Stack(ext_badges, direction="h", gap=1, wrap=True),
                ],
            ))

    # ── Danger Zone ────────────────────────────────────────────────
    nodes.append(ui.Section(
        title="Danger Zone",
        children=[
            ui.Text(
                "Destructive actions for this user account.",
                variant="caption",
            ),
            ui.Stack([
                ui.Button(
                    "Deactivate User", variant="danger",
                    on_click=ui.Call(
                        "deactivate_user", user_id=user_id,
                        confirm="Deactivate this user? They lose access "
                                "immediately. You can Activate them again "
                                "any time.",
                    ),
                ) if is_active else ui.Button(
                    "Activate User", variant="primary",
                    on_click=ui.Call("update_user", user_id=user_id, is_active=True),
                ),
                ui.Button(
                    "Permanent Delete User",
                    variant="danger",
                    on_click=ui.Call(
                        "hard_delete_user", user_id=user_id,
                        confirm=("Permanently delete this user? This erases "
                                 "the account, its balance, roles and history "
                                 "for good — there is nothing to restore "
                                 "afterwards. If you just want to lock them "
                                 "out, use Deactivate instead."),
                    ),
                ),
            ], direction="h", gap=2, wrap=True),
        ],
    ))

    return ui.Stack(children=[
        ui.Card(
            title="User Workspace",
            content=ui.Stack(children=nodes, gap=2),
        )
    ])
