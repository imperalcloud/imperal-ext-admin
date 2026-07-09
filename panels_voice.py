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

    return ui.Stack(direction="v", gap=2, children=[
        ui.Header("Voice", level=3),
        ui.Text("Control voice pricing, the global on/off, and which roles / users can use voice. "
                "Connector & Connections access per role moved to the Roles tab; per-plan features "
                "to the Plans tab.", variant="caption"),
        ui.Card(title="Voice Pricing (Imperal OpenAI cost — STT + TTS)", content=costs_form),
        master_card,
        access_card,
    ])
