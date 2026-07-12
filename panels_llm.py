"""Admin · LLM Config panel.

Structure: Config Form + Extension Overrides + Platform Usage.
Test Connection shows inline Alert (no chat messages).
Config from Auth GW /v1/internal/config/llm (canonical source).
"""
from __future__ import annotations

import asyncio
import logging
import os

from imperal_sdk import ui
from app import _gw_request
from panels_sections import (
    _cached, _fetch_llm_usage, _fetch_extensions, _fmt_tokens, _fmt_latency,
)
from panels_llm_form import build_llm_form
from panels_llm_models import fetch_model_catalog

log = logging.getLogger("admin")


# ── Data fetchers ─────────────────────────────────────────────────────

async def _fetch_llm_config_raw() -> dict:
    try:
        return await _gw_request("GET", "/v1/internal/config/llm")
    except Exception as e:
        log.warning("Panel: fetch LLM config failed: %s", e)
        return {}


async def _fetch_llm_config() -> dict:
    return await _cached("llm_config", _fetch_llm_config_raw)


async def _fetch_tenant_defaults_raw() -> dict:
    """Fetch admin-set tenant defaults (Token Budget Controls 2026-04-27).

    Endpoint: GET /v1/admin/tenant-defaults?tenant_id=default. Returns the
    current tenant-default settings dict (10+ knobs). UI uses this to
    populate initial form values for the Token Budget Controls section.
    """
    try:
        resp = await _gw_request(
            "GET", "/v1/admin/tenant-defaults?tenant_id=default"
        )
        if isinstance(resp, dict):
            return resp.get("settings", {}) or {}
        return {}
    except Exception as e:
        log.warning("Panel: fetch tenant-defaults failed: %s", e)
        return {}


async def _fetch_tenant_defaults() -> dict:
    return await _cached("tenant_defaults", _fetch_tenant_defaults_raw)


def _env_providers() -> list[str]:
    avail = []
    if os.getenv("ANTHROPIC_API_KEY"):
        avail.append("anthropic")
    if os.getenv("OPENAI_API_KEY"):
        avail.append("openai")
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        avail.append("google")
    avail.append("custom")
    return avail or ["anthropic", "custom"]


# ── Inline test ───────────────────────────────────────────────────────

async def _run_test(cfg: dict, target: str) -> dict:
    """Run connection test, return {ok, message}."""
    try:
        if target == "failover":
            provider = cfg.get("failover_provider", "")
            model = cfg.get("failover_model", "")
        else:
            provider = cfg.get("provider", "anthropic")
            model = cfg.get("model", "")
        if not provider:
            return {"ok": False, "message": "No provider configured"}
        # Check if API key exists for provider
        key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        env_key = key_map.get(provider)
        if env_key and not os.getenv(env_key):
            return {"ok": False, "message": f"No API key for {provider}"}
        return {"ok": True, "message": f"{provider}/{model} \u2014 configured OK"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ── Override cards ────────────────────────────────────────────────────

def _build_overrides(overrides: dict, extensions: list[dict]) -> list:
    if not overrides:
        return [ui.Text(
            "No per-extension overrides. All extensions use the default.",
            variant="caption",
        )]
    ext_names = {e.get("app_id", ""): e.get("display_name", e.get("app_id", ""))
                 for e in extensions}
    nodes: list = []
    for ext_id, cfg in overrides.items():
        model = cfg.get("model", "\u2014") if isinstance(cfg, dict) else str(cfg)
        provider = cfg.get("provider", "") if isinstance(cfg, dict) else ""
        display = ext_names.get(ext_id, ext_id)
        label = f"{model} ({provider})" if provider else model
        nodes.append(ui.Stack([
            ui.Stack([
                ui.Text(display, variant="body"),
                ui.Text(label, variant="caption"),
            ]),
            ui.Button(
                label="Reset", variant="danger", size="sm",
                on_click=ui.Call("save_llm_config",
                                 reset_extension_override=ext_id),
            ),
        ], direction="h", gap=3, justify="between", align="center"))
    return nodes


# ── Main builder ──────────────────────────────────────────────────────

async def build_llm(ctx, run_test: str = "", **kwargs):
    """Build LLM Config panel. run_test='main'|'failover' triggers inline test."""
    cfg, usage, extensions, tenant_defaults, model_catalog = await asyncio.gather(
        _fetch_llm_config(),
        _fetch_llm_usage(),
        _fetch_extensions(),
        _fetch_tenant_defaults(),
        fetch_model_catalog(),
    )

    provider = cfg.get("provider", "anthropic")
    model = cfg.get("model", "")
    code = cfg.get("code_model", "")
    routing = cfg.get("routing_model", "")
    execution = cfg.get("execution_model", "")
    navigate = cfg.get("navigate_model", "")
    chain_narrative = cfg.get("chain_narrative_model", "")
    judge = cfg.get("judge_model", "")
    # Federalization 2026-05-19 — new per-purpose model overrides
    conversational = cfg.get("conversational_model", "")
    step_reclassify = cfg.get("step_reclassify_model", "")
    tool_picker = cfg.get("tool_picker_model", "")
    action_narrator = cfg.get("action_narrator_model", "")
    failover_on = cfg.get("failover_enabled", False)
    fo_provider = cfg.get("failover_provider", "")
    fo_model = cfg.get("failover_model", "")
    base_url = cfg.get("base_url", "")
    ext_overrides = cfg.get("extension_overrides", {})
    available = _env_providers()
    override_count = len(ext_overrides)

    children: list = [
        ui.Header("LLM Configuration", level=3),
    ]

    # Inline test result (shown when user clicked Test)
    if run_test:
        result = await _run_test(cfg, run_test)
        label = "Failover" if run_test == "failover" else "Default Provider"
        children.append(ui.Alert(
            title=f"Test {label}",
            message=result["message"],
            type="success" if result["ok"] else "error",
        ))

    children.extend([
        build_llm_form(
            provider=provider, model=model, base_url=base_url,
            code_model=code,
            routing_model=routing, execution_model=execution,
            navigate_model=navigate,
            chain_narrative_model=chain_narrative,
            judge_model=judge,
            failover_enabled=bool(failover_on),
            failover_provider=fo_provider, failover_model=fo_model,
            available_providers=available,
            tenant_defaults=tenant_defaults,
            # LCU-4 (2026-04-30): cfg["purpose"] is the kernel cascade
            # nested format `{purpose_name: {temperature, top_p, ...}}`.
            purpose_ai_params=cfg.get("purpose") if isinstance(cfg.get("purpose"), dict) else None,
            # Federalization 2026-05-19 — new per-purpose model overrides
            conversational_model=conversational,
            step_reclassify_model=step_reclassify,
            tool_picker_model=tool_picker,
            action_narrator_model=action_narrator,
            # Live model catalogue from the provider APIs (no hardcoded list).
            model_catalog=model_catalog,
        ),
        ui.Divider(),
        ui.Section(
            title=f"Extension Overrides ({override_count})",
            collapsible=True,
            children=_build_overrides(ext_overrides, extensions),
        ),
        ui.Divider(),
        ui.Section(title="Platform Usage Today", children=[
            ui.Stats(children=[
                ui.Stat(label="Total Calls",
                        value=str(usage.get("total_calls", 0)), color="blue"),
                ui.Stat(label="Tokens In",
                        value=_fmt_tokens(usage.get("total_tokens_in")),
                        color="cyan"),
                ui.Stat(label="Tokens Out",
                        value=_fmt_tokens(usage.get("total_tokens_out")),
                        color="cyan"),
            ], columns=3),
            ui.Stats(children=[
                ui.Stat(label="BYOLLM Users",
                        value=str(usage.get("byollm_users", 0)),
                        color="purple"),
                ui.Stat(label="Avg Latency",
                        value=_fmt_latency(usage.get("avg_latency_ms")),
                        color="orange"),
                ui.Stat(label="Failover Events",
                        value=str(usage.get("failover_events", 0)),
                        color="yellow" if usage.get("failover_events", 0) > 0
                        else "gray"),
            ], columns=3),
        ]),
    ])

    return ui.Stack(children=children)
