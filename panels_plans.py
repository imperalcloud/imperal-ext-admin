# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · Plans panel — one coherent place for every billing plan and its
features. Per plan: toggle voice / connectors / Webbee Code / Connections
(SSH & MCP) + a user count. Each toggle saves via the set_plan_feature handler.

Feature access is ADDITIVE (OR): a user gets a feature if their PLAN (here),
their ROLE default_scopes (Roles tab), or a per-user override (Users panel)
grants it. This page is the plan axis of that model, pulled out of the Voice
panel where it used to be buried.
"""
from __future__ import annotations

import asyncio
import json
import logging

from imperal_sdk import ui

from panels_sections import _fetch_plans, _fetch_users

log = logging.getLogger("admin")

# (feature-key, human label) — the order shown per plan.
_FEATURES = [
    ("voice",       "Voice"),
    ("connectors",  "Connectors (Telegram / Discord)"),
    ("coding",      "Webbee Code"),
    ("connections", "Connections (SSH / MCP)"),
    ("file_reader", "File Reader"),
]


def _plan_features(plan: dict) -> dict:
    """Plan.features is a JSON *string* on the wire — decode fail-soft to {}."""
    f = plan.get("features")
    if isinstance(f, str):
        try:
            return json.loads(f) or {}
        except Exception:
            return {}
    return f if isinstance(f, dict) else {}


def _plan_name_of_user(u: dict) -> str:
    return (
        u.get("plan")
        or (u.get("subscription") or {}).get("plan")
        or (u.get("attributes") or {}).get("plan")
        or "free"
    )


async def build_plans(ctx, **kwargs):
    """Plans management: every plan with per-feature toggles + a user count."""
    plans, users = await asyncio.gather(_fetch_plans(), _fetch_users())

    counts: dict[str, int] = {}
    for u in users:
        counts[_plan_name_of_user(u)] = counts.get(_plan_name_of_user(u), 0) + 1

    if not plans:
        return ui.Stack(children=[
            ui.Header("Plans", level=3, subtitle="Billing plans and their features"),
            ui.Empty(message="No plans found. Auth Gateway may be unreachable.", icon="Layers"),
        ])

    items: list = []
    for p in plans:
        pid = p.get("id")
        pname = p.get("name") or str(pid)
        feats = _plan_features(p)
        n_users = counts.get(pname, 0)

        on_keys = [label for key, label in _FEATURES if bool(feats.get(key))]
        toggles: list = [
            ui.Text("Additive (OR) with the per-role grants (Roles tab) and per-user "
                    "overrides (Users panel).", variant="caption"),
        ]
        for key, label in _FEATURES:
            on = bool(feats.get(key))
            toggles.append(ui.Button(
                label=f"{label}: {'Disable' if on else 'Enable'}  ({'ON' if on else 'off'})",
                variant=("danger" if on else "primary"),
                on_click=ui.Call("set_plan_feature", plan_id=pid, feature=key, enabled=(not on)),
            ))

        items.append(ui.ListItem(
            id=str(pname),
            title=pname,
            subtitle=(", ".join(on_keys) if on_keys else "no features enabled"),
            meta=f"{n_users} users",
            expandable=True,
            expanded_content=[ui.Stack(direction="v", gap=1, children=toggles)],
        ))

    return ui.Stack(children=[
        ui.Header("Plans", level=3, subtitle="Billing plans and their features"),
        ui.Text("Each plan and its features in one place — voice, connectors, Webbee Code, and "
                "Connections (a user's own SSH / MCP targets). Toggles are additive with the "
                "per-role (Roles tab) and per-user (Users panel) grants.", variant="caption"),
        ui.List(items=items, searchable=True),
    ])
