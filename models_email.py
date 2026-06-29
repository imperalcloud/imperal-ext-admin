# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL records for the admin Email tab — durable log + per-case templates +
write results. Field names mirror the ACTUAL gateway payloads
(/v1/internal/email/{log,templates,templates/{case},test}) — federal
I-EXT-RECORD-FIELD-NAMING-SYMMETRIC."""
from __future__ import annotations

from typing import Optional, Any

from pydantic import model_validator

from imperal_sdk import sdl


class EmailLogRecord(sdl.Entity):
    """One durable email_log row — GET /v1/internal/email/log."""
    created_at: Optional[Any] = None
    case: Optional[str] = None
    to_email: Optional[str] = None
    user_id: Optional[str] = None
    subject: Optional[str] = None
    status: Optional[str] = None          # sent | failed | skipped_disabled | skipped_dedup
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    dedup_key: Optional[str] = None
    tag: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = str(d.get("id") or "")
            d.setdefault("title", f"{d.get('case') or 'email'} → {d.get('to_email') or '?'}")
            d.setdefault("kind", "email_log")
        return d


class EmailLogResponse(sdl.EntityList[EmailLogRecord]):
    pass


class EmailTemplateRecord(sdl.Entity):
    """One case in the template list — GET /v1/internal/email/templates."""
    case: Optional[str] = None
    description: Optional[str] = None
    default_subject: Optional[str] = None
    subject: Optional[str] = None          # effective subject (override or default)
    enabled: Optional[bool] = None
    has_custom_body: Optional[bool] = None
    updated_at: Optional[Any] = None
    updated_by: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("case") or ""
            d.setdefault("title", d.get("case") or "")
            d.setdefault("kind", "email_template")
        return d


class EmailTemplatesResponse(sdl.EntityList[EmailTemplateRecord]):
    pass


class EmailTemplateFull(sdl.Entity):
    """Full editable template for ONE case — GET /v1/internal/email/templates/{case}.
    RAW override fields (empty = no override) + the built-in default preview."""
    case: Optional[str] = None
    description: Optional[str] = None
    default_subject: Optional[str] = None
    subject: Optional[str] = None
    html_body: Optional[str] = None
    text_body: Optional[str] = None
    enabled: Optional[bool] = None
    has_custom_body: Optional[bool] = None
    default_html_preview: Optional[str] = None
    default_text_preview: Optional[str] = None
    updated_at: Optional[Any] = None
    updated_by: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("case") or ""
            d.setdefault("title", f"{d.get('case') or 'template'} template")
            d.setdefault("kind", "email_template")
        return d


class EmailTemplateSaved(sdl.Entity):
    """Result of PUT /v1/internal/email/templates/{case}."""
    case: Optional[str] = None
    enabled: Optional[bool] = None
    action: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = d.get("case") or ""
            d.setdefault("title", f"{d.get('action') or 'saved'} {d.get('case') or ''}".strip())
            d.setdefault("kind", "email_template")
        return d


class EmailTestResult(sdl.Entity):
    """Result of POST /v1/internal/email/test."""
    case: Optional[str] = None
    to: Optional[str] = None
    status: Optional[str] = None
    provider_message_id: Optional[str] = None
    error: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = f"{d.get('case') or 'test'}:{d.get('to') or ''}"
            d.setdefault("title", f"test {d.get('case') or ''} → {d.get('status') or '?'}")
            d.setdefault("kind", "email_test")
        return d
