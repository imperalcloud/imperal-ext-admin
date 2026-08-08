# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL records for the model-governance READ/WRITE tools.

Field names mirror the ACTUAL runtime payloads built in
`handlers_model_governance.py` verbatim — federal
I-EXT-RECORD-FIELD-NAMING-SYMMETRIC. The runtime rows are produced by
`model_dump()` of the pure models in `models_llm_routing` /
`models_ext_model_policy`, so these records intentionally repeat those field
names rather than re-deriving them.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import model_validator

from imperal_sdk import sdl


# ── 1. llm_routing_report ────────────────────────────────────────────────── #

class LlmRoutingSlotRecord(sdl.Entity):
    """One resolved purpose slot: which model runs, its tier, what it costs."""

    purpose: Optional[str] = None
    label: Optional[str] = None
    effective_model: Optional[str] = None
    provider: Optional[str] = None
    source: Optional[str] = None
    tier: Optional[str] = None
    platform_fee: Optional[int] = None
    is_priced: Optional[bool] = None
    is_available: Optional[bool] = None
    estimated_run_credits: Optional[int] = None
    warnings: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("purpose") or d.get("id") or ""
            d.setdefault("title", d.get("label") or d.get("purpose") or "")
            d.setdefault("kind", "llmroutingslot")
        return d


class LlmRoutingReportResponse(sdl.EntityList[LlmRoutingSlotRecord]):
    """Slots + the fee table used, so the credit maths can be checked."""

    substitutions: list[dict] = []
    tier_fees: dict[str, int] = {}
    fees_are_live: Optional[bool] = None
    category_prices: dict[str, int] = {}
    actions_costed: Optional[int] = None
    warnings: list[str] = []


# ── 2. audit_extension_models ────────────────────────────────────────────── #

class ExtensionModelPolicyRecord(sdl.Entity):
    """One extension's AI Models settings vs the system defaults."""

    app_id: Optional[str] = None
    display_name: Optional[str] = None
    uses_system_defaults: Optional[bool] = None
    pinned_models: list[dict] = []
    pinned_params: dict[str, Any] = {}
    forced_params: dict[str, Any] = {}
    forced_params_are_form_defaults: Optional[bool] = None
    thinking_mode: Optional[str] = None
    findings: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("app_id") or d.get("id") or ""
            d.setdefault("title", d.get("display_name") or d.get("app_id") or "")
            d.setdefault("kind", "extensionmodelpolicy")
        return d


class ExtensionModelAuditResponse(sdl.EntityList[ExtensionModelPolicyRecord]):
    """Audit result. `unreadable_app_ids` is reported, never silently skipped."""

    deviating_count: Optional[int] = None
    unreadable_app_ids: list[str] = []


# ── 3. reset_extension_models ────────────────────────────────────────────── #

class ExtensionModelResetReceipt(sdl.Entity):
    """Receipt for a reset run. `applied=False` means it was a preview."""

    applied: Optional[bool] = None
    changed: list[dict] = []
    unchanged: list[str] = []
    failed: list[dict] = []
    inherit_value: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d.setdefault("id", "extension_models_reset")
            n = len(d.get("changed") or [])
            verb = "reset" if d.get("applied") else "preview"
            d.setdefault("title", f"{n} extension(s) — {verb}")
            d.setdefault("kind", "extensionmodelreset")
        return d
