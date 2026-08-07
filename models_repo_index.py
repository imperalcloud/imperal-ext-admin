# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors.
# Licensed under the AGPL-3.0 License.
"""SDL records for the repo-index READ tools.

Field names mirror the ACTUAL payload the kernel persists into
``imperal:repo_index_map:{user_id}:{repo_key}`` and
``imperal:repo_memory:{user_id}:{repo_key}`` -- federal
I-EXT-RECORD-FIELD-NAMING-SYMMETRIC. Nothing here is re-shaped for display:
the handlers hand the stored map through as-is (minus private ``_`` keys), so
these models describe what is really on the wire, which is what makes $REF
paths verifiable instead of aspirational.

SDK V23: read tools must declare a typed return shape. These are those types.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import model_validator

from imperal_sdk import sdl


class IndexedRepoRecord(sdl.Entity):
    """One indexed repository, as summarised for the list view."""

    repo_key: Optional[str] = None
    repo_root: Optional[str] = None
    file_count: Optional[int] = None
    languages: Optional[dict] = None
    symbol_kinds: Optional[dict] = None
    endpoint_count: Optional[int] = None
    schema_count: Optional[int] = None
    contract_evidence_complete: Optional[bool] = None
    vectors_ready: Optional[bool] = None
    embedded_chunks: Optional[int] = None
    git_ref: Optional[str] = None
    branch: Optional[str] = None
    indexed: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            key = d.get("repo_key") or ""
            d["id"] = key or (d.get("repo_root") or "")
            root = (d.get("repo_root") or "").rstrip("/")
            name = root.rsplit("/", 1)[-1] if root else (key[:12] or "repo")
            files = d.get("file_count") or 0
            d.setdefault("title", f"{name} — {files} files")
            d.setdefault("kind", "repo_index")
        return d


class IndexedReposResponse(sdl.EntityList[IndexedRepoRecord]):
    pass


class RepoIndexMapRecord(sdl.Entity):
    """The full structural map of ONE repo, exactly as the kernel stored it."""

    repo_key: Optional[str] = None
    repo_root: Optional[str] = None
    evidence_version: Optional[int] = None
    content_digest: Optional[str] = None
    file_count: Optional[int] = None
    languages: Optional[dict] = None
    symbol_kinds: Optional[dict] = None
    top_symbols: Optional[list] = None
    test_hint_files: Optional[list] = None
    endpoint_count: Optional[int] = None
    schema_count: Optional[int] = None
    contract_evidence_limit: Optional[int] = None
    contract_evidence_complete: Optional[bool] = None
    endpoints: Optional[list] = None
    schemas: Optional[list] = None
    vectors_ready: Optional[bool] = None
    embedded_chunks: Optional[int] = None
    git_ref: Optional[str] = None
    branch: Optional[str] = None
    updated_at: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            root = (d.get("repo_root") or "").rstrip("/")
            name = root.rsplit("/", 1)[-1] if root else (d.get("repo_key") or "repo")
            d["id"] = d.get("repo_key") or root or name
            ref = (d.get("git_ref") or "")[:12]
            d.setdefault("title", f"{name} @ {ref}" if ref else str(name))
            d.setdefault("kind", "repo_index_map")
        return d


class CrossRepoContractGraphRecord(sdl.Entity):
    """Bounded endpoint/schema evidence graph across the caller's repos."""

    repo_count: Optional[int] = None
    endpoint_count: Optional[int] = None
    schema_count: Optional[int] = None
    link_count: Optional[int] = None
    evidence_origin: Optional[str] = None
    contracts_complete: Optional[bool] = None
    repositories: Optional[list] = None
    endpoints: Optional[list] = None
    schemas: Optional[list] = None
    links: Optional[list] = None
    freshness: Optional[list] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            d["id"] = "cross-repo-contract-graph"
            d.setdefault("title", f"Cross-repo contracts — {d.get('repo_count', 0)} repos")
            d.setdefault("kind", "cross_repo_contract_graph")
        return d


class RepoKnowledgeRecord(sdl.Entity):
    """One durable note the coding agent distilled about a repo."""

    text: Optional[str] = None
    source: Optional[str] = None
    repo_key: Optional[str] = None
    updated_at: Optional[Any] = None

    @model_validator(mode="before")
    @classmethod
    def _c(cls, d):
        if isinstance(d, dict):
            txt = (d.get("text") or d.get("note") or "").strip()
            d["id"] = d.get("id") or f"{d.get('repo_key', '')}:{hash(txt) & 0xFFFFFF:06x}"
            d.setdefault("title", (txt[:80] + "…") if len(txt) > 80 else (txt or "note"))
            d.setdefault("kind", "repo_note")
        return d


class RepoKnowledgeResponse(sdl.EntityList[RepoKnowledgeRecord]):
    pass
