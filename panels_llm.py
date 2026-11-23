"""Admin · LLM Config panel.

Structure: Config Form + Extension Overrides + Platform Usage.
Test Connection shows inline Alert (no chat messages).
Config from Auth GW /v1/internal/config/llm (canonical source).
"""
from __future__ import annotations

import asyncio
import logging

from imperal_sdk import ui
from app import _gw_request
from panels_sections import (
    _cached, _fetch_llm_usage, _fetch_extensions, _fmt_tokens, _fmt_latency,
)
from panels_llm_form import build_llm_form
from panels_llm_models import fetch_model_catalog, catalog_to_options

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


def _keyed_providers(keys: dict | None) -> list[str] | None:
    """The providers whose key is typed in Secrets; the form marks every other
    one "(no API key)". "custom" is always in: a local endpoint may need no
    key. None when the secret store did not answer - then nothing is marked,
    because "unknown" is not "no key"."""
    if keys is None:
        return None
    avail = [p for p, is_set in keys.items() if is_set and p != "openai_compatible"]
    avail.append("custom")
    return avail


# ── Inline test ───────────────────────────────────────────────────────

# A test result is kept for a short while: the panel re-renders with its last
# parameters after every save, and each render must not call the provider again.
_TEST_KEEP_S = 120.0
_test_seen: dict[tuple, tuple[float, dict]] = {}


async def _run_test_once(ctx, cfg: dict, target: str) -> dict:
    import time
    prefix = "failover_" if "failover" in target else ""
    key = (target, cfg.get(f"{prefix}provider"), cfg.get(f"{prefix}model"), cfg.get(f"{prefix}base_url"))
    hit = _test_seen.get(key)
    if hit and time.monotonic() - hit[0] < _TEST_KEEP_S:
        return hit[1]
    result = await _run_test(ctx, cfg, target)
    _test_seen.clear()
    _test_seen[key] = (time.monotonic(), result)
    return result


async def _run_test(ctx, cfg: dict, target: str) -> dict:
    """Make the call the pressed Test button names; ``{ok, message}``.

    target: "main" | "main_compat" | "failover" | "failover_compat". The slot's
    provider, model and base URL are the saved ones and the key is the
    provider's secret - what the kernel would use - so the test answers "does
    the saved configuration work"."""
    from llm_keys import secret_name
    from llm_probe import key_for_test, may_send_key_to, probe   # local: keeps the panel import light
    failover = "failover" in target
    prefix = "failover_" if failover else ""
    provider = str(cfg.get(f"{prefix}provider") or ("" if failover else "anthropic"))
    base_url = str(cfg.get(f"{prefix}base_url") or "")
    try:
        if provider and not may_send_key_to(provider, base_url):
            return {"ok": False, "message": (
                f"Nothing was called: the {provider} key is sent only to {provider}'s own address, "
                f"and this slot's Base URL is another one ({base_url}). Clear the Base URL, or "
                "choose the provider Custom for an address of your own.")}
        key = await key_for_test(ctx, provider, base_url)
        if not key and provider and provider != "custom":
            return {"ok": False, "message": (
                f"No API key for {provider}: set the secret {secret_name(provider)} in Admin > Secrets. "
                "Nothing was called.")}
        return await probe(
            provider, str(cfg.get(f"{prefix}model") or ""), key, base_url,
            tools="compat" in target,
        )
    except Exception as e:
        return {"ok": False, "message": f"The test itself failed: {type(e).__name__}: {e}"}


def _build_keys_view(keys: dict | None) -> list:
    """Every provider, whether its key is typed, and the way to type it."""
    from llm_keys import PROVIDERS, secret_name, secrets_path
    nodes: list = [ui.Text(
        "One API key per provider. A key is a secret of the Admin extension, kept in Imperal Vault: "
        "it is typed in the Secrets manager and is never shown again. Every model of a provider, "
        "in any task, runs on that provider's key; a provider without a key is not called.",
        variant="caption",
    )]
    if keys is None:
        nodes.append(ui.Alert(
            title="Key status unknown",
            message="The secret store did not answer, so this page cannot say which keys are set.",
            type="warning",
        ))
    for prov, label in PROVIDERS.items():
        state = "unknown" if keys is None else ("set" if keys.get(prov) else "NOT SET")
        is_set = bool(keys and keys.get(prov))
        nodes.append(ui.Stack([
            ui.Stack([
                ui.Text(f"{label}  ·  {state}", variant="body"),
                ui.Text(secret_name(prov), variant="caption"),
            ]),
            ui.Button(label="Change the key" if is_set else "Set the key",
                      variant="secondary" if is_set else "primary", size="sm",
                      on_click=ui.Navigate(path=secrets_path(prov))),
        ], direction="h", justify="between", align="center"))
    return nodes


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
                on_click=ui.Call(
                    "save_llm_config", reset_extension_override=ext_id,
                    confirm=(f"Reset '{display}' back to the system default "
                             "model? Its per-extension override is cleared "
                             "immediately — you can set a new one via Save "
                             "any time."),
                ),
            ),
        ], direction="h", gap=3, justify="between", align="center"))
    return nodes


def _build_add_override_form(
    overrides: dict, extensions: list[dict], model_catalog: dict,
) -> list:
    """Form to CREATE a new per-extension override (was Reset-only).

    handlers_llm.py::fn_save_llm_config has always accepted
    set_extension_override + override_model (+ optional override_provider,
    auto-inferred from the model id when left blank) — this panel just had
    no control that could ever POST them, so the write path was unreachable
    from the UI. Only extensions WITHOUT an existing override are offered;
    to change one, Reset it first.
    """
    candidates = [
        e for e in extensions
        if e.get("app_id") and e.get("app_id") not in overrides
    ]
    if not candidates:
        return [ui.Text(
            "Every extension already has an override, or none are installed.",
            variant="caption",
        )]
    ext_options = [
        {"value": e["app_id"], "label": e.get("display_name", e["app_id"])}
        for e in sorted(candidates, key=lambda e: e.get("display_name", e["app_id"]))
    ]
    _, model_options = catalog_to_options(model_catalog)
    return [
        ui.Form(
            action="save_llm_config",
            submit_label="Add Override",
            defaults={"set_extension_override": "", "override_model": ""},
            children=[
                ui.Text(
                    "Pin one extension to a specific model, independent of "
                    "the platform default and every per-purpose slot above. "
                    "Provider is inferred from the model id.",
                    variant="caption",
                ),
                ui.Select(
                    options=ext_options,
                    param_name="set_extension_override",
                    placeholder="Choose extension",
                ),
                ui.Select(
                    options=model_options,
                    param_name="override_model",
                    placeholder="Choose model",
                ),
            ],
        ),
    ]


# ── Main builder ──────────────────────────────────────────────────────

EXTRA_VIEWS = (("provider-keys", "Provider keys"), ("extension-overrides", "Extension overrides"),
               ("usage-today", "Usage today"))


async def build_llm(ctx, run_test: str = "", llm_view: str = "", **kwargs):
    """Build LLM Config panel. run_test='main'|'failover' triggers inline test."""
    from llm_keys import keys_set
    cfg = await _fetch_llm_config()
    usage, extensions, tenant_defaults, model_catalog, llm_keys_set = await asyncio.gather(
        _fetch_llm_usage(),
        _fetch_extensions(),
        _fetch_tenant_defaults(),
        fetch_model_catalog(ctx, cfg),
        keys_set(ctx),
    )

    provider = cfg.get("provider", "anthropic")
    model = cfg.get("model", "")
    code = cfg.get("code_model", "")
    # G2 (2026-07-16): Webbee Code fallback pair read-through (blank = off).
    code_fallback = cfg.get("code_fallback_model", "")
    routing = cfg.get("routing_model", "")
    routing_fallback = cfg.get("routing_fallback_model", "")
    execution = cfg.get("execution_model", "")
    navigate = cfg.get("navigate_model", "")
    chain_narrative = cfg.get("chain_narrative_model", "")
    judge = cfg.get("judge_model", "")
    # Federalization 2026-05-19 — new per-purpose model overrides
    conversational = cfg.get("conversational_model", "")
    step_reclassify = cfg.get("step_reclassify_model", "")
    tool_picker = cfg.get("tool_picker_model", "")
    action_narrator = cfg.get("action_narrator_model", "")
    # Webbee Code model tiers (2026-07-30): Webbee Smart/SuperSmart/UltraSmart,
    # each a full admin-owned (primary, fallback) pair. Read-through from the
    # SAME flat Config Store keys save_llm_config writes -- no separate store.
    # "webbeesmart" matches MODEL_TIERS in the kernel's llm/model_tiers.py --
    # the read side keys off that tuple, so the flat Config Store prefix must
    # agree exactly (this panel previously read/wrote "smart_*", a key nothing
    # on the kernel side ever looked at).
    webbeesmart_model = cfg.get("webbeesmart_model", "")
    webbeesmart_fallback = cfg.get("webbeesmart_fallback_model", "")
    # Universal Brain reasoning tier (purpose="resolve") -- configurable via
    # this flat key all along, but with no field in the form until now.
    resolve_model = cfg.get("resolve_model", "")
    resolve_fallback = cfg.get("resolve_fallback_model", "")
    supersmart_model = cfg.get("supersmart_model", "")
    supersmart_fallback = cfg.get("supersmart_fallback_model", "")
    ultrasmart_model = cfg.get("ultrasmart_model", "")
    ultrasmart_fallback = cfg.get("ultrasmart_fallback_model", "")
    failover_on = cfg.get("failover_enabled", False)
    fo_provider = cfg.get("failover_provider", "")
    fo_model = cfg.get("failover_model", "")
    fo_base_url = cfg.get("failover_base_url", "")
    base_url = cfg.get("base_url", "")
    ext_overrides = cfg.get("extension_overrides", {})
    available = _keyed_providers(llm_keys_set)
    override_count = len(ext_overrides)

    children: list = [
        ui.Header("LLM Configuration", level=3),
    ]

    # Inline test result (shown when user clicked Test)
    if run_test:
        result = await _run_test_once(ctx, cfg, run_test)
        label = "Failover" if "failover" in run_test else "Default Provider"
        test_type = "Tool-Use Compatibility" if "compat" in run_test else "Connection"
        children.append(ui.Alert(
            title=f"Test {label} · {test_type}",
            message=result["message"],
            type="success" if result["ok"] else "error",
        ))

    children.extend([
        build_llm_form(
            provider=provider, model=model, base_url=base_url,
            code_model=code,
            code_fallback_model=code_fallback,
            routing_model=routing,
            routing_fallback_model=routing_fallback,
            execution_model=execution,
            navigate_model=navigate,
            chain_narrative_model=chain_narrative,
            judge_model=judge,
            failover_enabled=bool(failover_on),
            failover_provider=fo_provider, failover_model=fo_model,
            failover_base_url=fo_base_url,
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
            # Webbee Code model tiers (2026-07-30)
            webbeesmart_model=webbeesmart_model,
            webbeesmart_fallback_model=webbeesmart_fallback,
            resolve_model=resolve_model,
            resolve_fallback_model=resolve_fallback,
            supersmart_model=supersmart_model,
            supersmart_fallback_model=supersmart_fallback,
            ultrasmart_model=ultrasmart_model,
            ultrasmart_fallback_model=ultrasmart_fallback,
            # Live model catalogue from the provider APIs (no hardcoded list).
            model_catalog=model_catalog,
            # I-CODING-THREAD-COMPACTION-ADMIN-TUNABLE (2026-07-31): these 6
            # knobs live in cfg (imperal:config:llm) directly -- NOT
            # tenant_defaults -- same store the kernel's get_admin_llm_config_field
            # cascade reads.
            coding_thread_config=cfg,
            # ORPHAN READER FIX (2026-08-18): knowledge_pick_max_tokens is read
            # by the kernel from THIS store (imperal:config:llm) via
            # get_admin_llm_config_field -- so the form must read/write cfg, not
            # tenant_defaults, or the control would save somewhere nothing reads.
            knowledge_config=cfg,
            # ORPHAN READER FIXES (2026-08-18): the kernel feature flags
            # (hub_brain_first_enabled, panel_diet_enabled, frame_v2_enabled)
            # live in cfg (imperal:config:llm) -- the SAME store the kernel's
            # get_admin_llm_config_field cascade reads and fn_save_llm_config
            # writes -- NOT tenant_defaults.
            kernel_flags_config=cfg,
            # BUG FIX (2026-08-28): the 11 per-purpose max_tokens caps
            # (routing/execution/navigate/chain_narrative/judge/conversational/
            # step_reclassify/tool_picker/chain_arg_refs/semantic_verifier/
            # action_narrator) + the new code_max_tokens row are ALL saved
            # into cfg (imperal:config:llm) by the generic save loop -- same
            # store config_resolver.py's cascade reads via
            # _extract_per_purpose_admin. The form used to read their
            # "current value" from tenant_defaults (a different store), so a
            # save looked like it silently reverted. See build_llm_form's
            # purpose_max_tokens_config docstring.
            purpose_max_tokens_config=cfg,
            view=str(llm_view or ""),
            extra_views=EXTRA_VIEWS,
            keys_set=llm_keys_set,
        ),
    ])
    if llm_view == "provider-keys":
        children.append(ui.Section(title="Provider keys", children=_build_keys_view(llm_keys_set)))
    if llm_view == "extension-overrides":
        children.append(ui.Section(
            title=f"Extension Overrides ({override_count})",
            collapsible=True,
            children=[
                *_build_overrides(ext_overrides, extensions),
                ui.Divider(),
                *_build_add_override_form(ext_overrides, extensions, model_catalog),
            ],
        ))
    if llm_view == "usage-today":
        children.append(ui.Section(title="Platform Usage Today", children=[
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
                ui.Stat(label="BYOLLM Calls",
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
        ]))

    return ui.Stack(children=children)
