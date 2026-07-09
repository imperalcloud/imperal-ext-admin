# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""Admin · Voice panel — STT/TTS pricing, global master-switch, per-role access.

Prefills from the gateway internal GET endpoints + /v1/roles; saves via the
save_voice_costs / save_voice_enabled / set_role_voice handlers.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import _gw_request

log = logging.getLogger("admin")

_DEFAULT_COSTS = {"stt": 20, "speak": 15}
VOICE_SCOPE = "voice:use"
CONNECTORS_SCOPE = "connectors:use"


async def _get(path: str) -> dict:
    try:
        result = await _gw_request("GET", path)
        return result if isinstance(result, dict) else {}
    except Exception as e:
        log.warning("voice _get %s error: %s: %s", path, type(e).__name__, e)
        return {}


async def build_voice(ctx, **kwargs):
    costs = await _get("/v1/internal/billing/voice-costs") or {}
    master = await _get("/v1/internal/billing/voice-enabled") or {}
    enabled = bool(master.get("enabled", True))
    roles = await _gw_request("GET", "/v1/roles")
    roles = roles if isinstance(roles, list) else []
    plans = await _get("/v1/billing/plans")
    plans = plans if isinstance(plans, list) else []

    # ── Pricing ──────────────────────────────────────────────────────────
    costs_form = ui.Form(
        action="save_voice_costs",
        submit_label="Save Voice Pricing",
        defaults={
            "stt": int(costs.get("stt", _DEFAULT_COSTS["stt"])),
            "speak": int(costs.get("speak", _DEFAULT_COSTS["speak"])),
        },
        children=[
            ui.Section(title="Per-action voice cost (credits)", children=[
                ui.Text("Charged per voice action. STT = transcribing an inbound voice "
                        "message; TTS = synthesizing a spoken reply. A cache hit is free. "
                        "Voice is Imperal's OpenAI cost, so it is billed even for BYOLLM "
                        "users. Applies within ~1 min.", variant="caption"),
                ui.Text("Transcription (STT) — per voice message", variant="caption"),
                ui.Input(param_name="stt", placeholder="e.g. 20"),
                ui.Text("Spoken reply (TTS) — per synthesis", variant="caption"),
                ui.Input(param_name="speak", placeholder="e.g. 15"),
            ]),
        ],
    )

    # ── Global master-switch ─────────────────────────────────────────────
    master_card = ui.Card(
        title="Global voice master-switch",
        content=ui.Stack(direction="v", gap=2, children=[
            ui.Text(f"Voice is currently **{'ON' if enabled else 'OFF'}** platform-wide. "
                    "When OFF, voice is disabled for everyone and the microphone disappears "
                    "from the panel.", variant="caption"),
            ui.Button(
                label=("Turn voice OFF (platform-wide)" if enabled else "Turn voice ON (platform-wide)"),
                variant=("danger" if enabled else "primary"),
                on_click=ui.Call("save_voice_enabled", enabled=(not enabled)),
            ),
        ]),
    )

    # ── Per-role access (voice:use) ──────────────────────────────────────
    access_children = [
        ui.Text("Grant or revoke voice (the voice:use scope) for ANY role/group — including "
                "the system roles (admin / user). For a single user, grant voice:use to them in "
                "the Users panel. To turn voice off for everyone at once, use the master-switch above.",
                variant="caption"),
    ]
    if roles:
        for r in roles:
            rid = r.get("id")
            has = VOICE_SCOPE in (r.get("default_scopes") or [])
            rname = r.get("display_name") or r.get("name") or str(rid)
            access_children.append(ui.Button(
                label=f"{rname}: {'Disable' if has else 'Enable'} voice  ({'ON' if has else 'off'})",
                variant=("danger" if has else "primary"),
                on_click=ui.Call("set_role_voice", role_id=rid, enabled=(not has)),
            ))
    else:
        access_children.append(ui.Text("No roles found.", variant="caption"))

    access_card = ui.Card(
        title="Voice access by role (group)",
        content=ui.Stack(direction="v", gap=1, children=access_children),
    )

    # ── Per-role connector access (connectors:use) ───────────────────────
    conn_children = [
        ui.Text("Grant or revoke messenger-connector access (the connectors:use scope) for any "
                "role/group. Same model as voice — the '*' wildcard does not grant it, so this "
                "toggle is authoritative for everyone, admins included.", variant="caption"),
    ]
    if roles:
        for r in roles:
            rid = r.get("id")
            has = CONNECTORS_SCOPE in (r.get("default_scopes") or [])
            rname = r.get("display_name") or r.get("name") or str(rid)
            conn_children.append(ui.Button(
                label=f"{rname}: {'Disable' if has else 'Enable'} connectors  ({'ON' if has else 'off'})",
                variant=("danger" if has else "primary"),
                on_click=ui.Call("set_role_connectors", role_id=rid, enabled=(not has)),
            ))
    else:
        conn_children.append(ui.Text("No roles found.", variant="caption"))
    conn_card = ui.Card(
        title="Connector access by role (Telegram / Discord)",
        content=ui.Stack(direction="v", gap=1, children=conn_children),
    )

    # ── Per-plan access (Plan.features voice/connectors/coding) ──────────
    plan_children = [
        ui.Text("Enable voice / connectors / Webbee Code / Connections (SSH & MCP targets) per subscription plan. Additive (OR) "
                "with the role and per-user toggles — a user gets a feature if their PLAN, role, "
                "or a personal grant allows it. (A per-user Webbee Code override, set in the Users "
                "panel, takes precedence over the plan's coding feature.)", variant="caption"),
    ]
    if plans:
        for p in plans:
            pid = p.get("id")
            pname = p.get("name") or str(pid)
            feats = p.get("features") or {}
            has_v = bool(feats.get("voice"))
            has_c = bool(feats.get("connectors"))
            has_code = bool(feats.get("coding"))
            has_conn = bool(feats.get("connections"))
            plan_children.append(ui.Button(
                label=f"{pname} · voice: {'Disable' if has_v else 'Enable'}  ({'ON' if has_v else 'off'})",
                variant=("danger" if has_v else "primary"),
                on_click=ui.Call("set_plan_feature", plan_id=pid, feature="voice", enabled=(not has_v)),
            ))
            plan_children.append(ui.Button(
                label=f"{pname} · connectors: {'Disable' if has_c else 'Enable'}  ({'ON' if has_c else 'off'})",
                variant=("danger" if has_c else "primary"),
                on_click=ui.Call("set_plan_feature", plan_id=pid, feature="connectors", enabled=(not has_c)),
            ))
            plan_children.append(ui.Button(
                label=f"{pname} · Webbee Code: {'Disable' if has_code else 'Enable'}  ({'ON' if has_code else 'off'})",
                variant=("danger" if has_code else "primary"),
                on_click=ui.Call("set_plan_feature", plan_id=pid, feature="coding", enabled=(not has_code)),
            ))
            plan_children.append(ui.Button(
                label=f"{pname} · Connections (SSH/MCP): {'Disable' if has_conn else 'Enable'}  ({'ON' if has_conn else 'off'})",
                variant=("danger" if has_conn else "primary"),
                on_click=ui.Call("set_plan_feature", plan_id=pid, feature="connections", enabled=(not has_conn)),
            ))
    else:
        plan_children.append(ui.Text("No plans found.", variant="caption"))
    plan_card = ui.Card(
        title="Access by plan (voice / connectors / Webbee Code / Connections)",
        content=ui.Stack(direction="v", gap=1, children=plan_children),
    )

    return ui.Stack(direction="v", gap=2, children=[
        ui.Header("Voice & Connectors", level=3),
        ui.Text("Control voice pricing, the global on/off, and which plans / groups / users can "
                "use voice and the messenger connectors.", variant="caption"),
        ui.Card(title="Voice Pricing (Imperal OpenAI cost — STT + TTS)", content=costs_form),
        master_card,
        plan_card,
        access_card,
        conn_card,
    ])
