# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL entity records — DEVELOPER PORTAL domain (app review + payout review).

Federal I-EXT-RECORD-FIELD-NAMING-SYMMETRIC: field names mirror the ACTUAL
runtime dict keys the handler returns (verified against handlers_developer.py).
100% SDL — both are real ``sdl.Entity`` receipt records.
"""
from __future__ import annotations

from typing import Optional, Any
from pydantic import model_validator

from imperal_sdk import sdl


# --- app review ---

class AppReviewReceipt(sdl.Entity):
    """Receipt entity for review_app (kind='appreview').

    Mirrors the ACTUAL handler return keys verbatim (verified vs
    handlers_developer.review_app, which was made symmetric to these keys):
    {app_id, action, status, reason, registered}. id = app_id; title = app_id."""
    app_id: Optional[str] = None
    action: Optional[str] = None
    status: Optional[Any] = None
    reason: Optional[str] = None
    registered: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("app_id") or data.get("id") or "app_review"
            data.setdefault("title", data.get("app_id") or "app_review")
            data.setdefault("kind", "appreview")
        return data


# --- payout review ---

class PayoutReviewReceipt(sdl.Entity):
    """Receipt entity for review_payout (kind='payout').

    Mirrors the ACTUAL handler return keys verbatim (verified vs
    handlers_developer.review_payout, which was made symmetric to these keys):
    {payout_id, action, note, status}. id = str(payout_id);
    title = 'payout <id>'."""
    payout_id: Optional[Any] = None
    action: Optional[str] = None
    note: Optional[str] = None
    status: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            pid = data.get("payout_id")
            data["id"] = str(pid) if pid not in (None, "") else (data.get("id") or "payout")
            data.setdefault("title", "payout " + str(pid if pid not in (None, "") else ""))
            data.setdefault("kind", "payout")
        return data
