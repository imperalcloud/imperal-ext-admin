"""Repo index map — the code map, readable from EVERY surface.

The terminal coding agent builds a rich map of a repository (file counts,
languages, symbol kinds, key symbols, semantic-chunk count, the exact commit it
was indexed at) and the kernel now persists it per (user, repo) under
``imperal:repo_index_map:{user_id}:{repo_key}``.

Before this handler that map was write-only from the panel's point of view: it
shaped the coding prompt and nothing else. So the same question -- "what does
Webbee actually know about my repo?" -- was answerable in the terminal and
nowhere else. These read handlers close that gap: panel chat and Telegram now
read the SAME map the coding session wrote.

Discipline:
  * READ-ONLY. Nothing here mutates a map; only the coding turn writes one.
  * OWN DATA ONLY. The key is built from ``ctx.user.imperal_id``, which is
    kernel-authoritative and cannot be spoofed, so a caller can only ever read
    their own repos. No admin scope is required precisely because there is no
    cross-user surface.
  * STALENESS-HONEST. Every answer states the commit and how long ago the map
    was indexed, so a reader is never misled into treating it as live truth.
  * FAIL-SOFT. A Redis outage yields a clear "no map yet" answer, never an
    exception into the chat turn.
"""
from __future__ import annotations

import json
import logging
import os
import time

import redis.asyncio as aioredis
from pydantic import BaseModel, Field

# `chat` is the ChatExtension INSTANCE built in app.py -- it must come from
# there, exactly like every other handler module in this extension. Importing
# `chat` from imperal_sdk instead yields the SDK's chat MODULE, which has no
# `.function` attribute, so main.py dies at import with
# `AttributeError: module 'imperal_sdk.chat' has no attribute 'function'`
# and the whole extension fails to load (deploy check "main.py loads").
from app import ActionResult, chat

log = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_KEY_PREFIX = "imperal:repo_index_map:"
_SCAN_CAP = 200          # never walk an unbounded keyspace


class _EmptyParams(BaseModel):
    """No input: the caller is always the authenticated user."""


class _RepoParam(BaseModel):
    repo: str = Field(
        default="",
        description=("Which repo to describe — its repo_key, or any fragment of "
                     "its path/name. Empty = the most recently indexed one."),
    )


def _caller(ctx) -> str:
    return ctx.user.imperal_id if getattr(ctx, "user", None) else ""


async def _redis() -> aioredis.Redis:
    return aioredis.from_url(REDIS_URL, decode_responses=True)


def _age(ts) -> str:
    """Human staleness. Unknown timestamps say so rather than implying 'now'."""
    if not isinstance(ts, int) or ts <= 0:
        return "unknown"
    mins = max(0, int((time.time() - ts) // 60))
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    if mins < 1440:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"


async def _load_all(uid: str) -> list[dict]:
    """Every index map belonging to THIS user, newest first. Fail-soft: any
    Redis or decode problem yields [] rather than breaking the turn."""
    out: list[dict] = []
    try:
        r = await _redis()
        try:
            pattern = f"{_KEY_PREFIX}{uid}:*"
            seen = 0
            async for key in r.scan_iter(match=pattern, count=100):
                seen += 1
                if seen > _SCAN_CAP:
                    break
                try:
                    raw = await r.get(key)
                    if not raw:
                        continue
                    d = json.loads(raw)
                    if isinstance(d, dict) and d:
                        d["_repo_key"] = str(key).rsplit(":", 1)[-1]
                        out.append(d)
                except Exception:
                    continue
        finally:
            await r.aclose()
    except Exception:
        log.warning("repo index map read failed (fail-soft)", exc_info=True)
        return []
    out.sort(key=lambda d: d.get("updated_at") or 0, reverse=True)
    return out


def _summarise(d: dict) -> str:
    langs = ", ".join(f"{k}={v}" for k, v in (d.get("languages") or {}).items())
    kinds = ", ".join(f"{k}={v}" for k, v in (d.get("symbol_kinds") or {}).items())
    name = os.path.basename((d.get("repo_root") or "").rstrip("/")) or d.get("_repo_key", "repo")
    sem = (f"{d.get('embedded_chunks', 0)} semantic chunks"
           if d.get("vectors_ready") else "semantic search off")
    return (f"{name}: {d.get('file_count', '?')} files"
            + (f" ({langs})" if langs else "")
            + f" · {kinds or 'no symbols indexed'} · {sem}"
            + f" · commit {str(d.get('git_ref') or '?')[:12]}"
            + (f" [{d['branch']}]" if d.get("branch") else "")
            + f" · indexed {_age(d.get('updated_at'))}")


@chat.function(
    "list_indexed_repos",
    action_type="read",
    description=("List the repositories Webbee has a code index for, newest first — "
                 "file counts, languages, symbol counts and how fresh each index is. "
                 "Works on every surface (panel, Telegram, terminal)."),
)
async def fn_list_indexed_repos(ctx, params: _EmptyParams) -> ActionResult:
    uid = _caller(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    maps = await _load_all(uid)
    if not maps:
        return ActionResult.success(
            data={"items": [], "total": 0},
            summary=("No code index yet. Open a repo in the Webbee terminal agent — "
                     "it builds the index and it becomes readable here."))
    items = [{
        "repo_key": d.get("_repo_key", ""),
        "repo_root": d.get("repo_root", ""),
        "file_count": d.get("file_count", 0),
        "languages": d.get("languages") or {},
        "symbol_kinds": d.get("symbol_kinds") or {},
        "vectors_ready": bool(d.get("vectors_ready")),
        "embedded_chunks": d.get("embedded_chunks", 0),
        "git_ref": d.get("git_ref", ""),
        "branch": d.get("branch", ""),
        "indexed": _age(d.get("updated_at")),
    } for d in maps]
    lines = "\n".join(f"• {_summarise(d)}" for d in maps[:10])
    more = f"\n(+{len(maps) - 10} more)" if len(maps) > 10 else ""
    return ActionResult.success(
        data={"items": items, "total": len(items)},
        summary=f"{len(items)} indexed repo(s):\n{lines}{more}")


@chat.function(
    "get_repo_index_map",
    action_type="read",
    description=("Show what Webbee knows about ONE repository's code: file and language "
                 "breakdown, how many functions/classes are indexed, key symbols with "
                 "file:line, semantic-search status, and the exact commit the index was "
                 "built at. Readable from any surface."),
)
async def fn_get_repo_index_map(ctx, params: _RepoParam) -> ActionResult:
    uid = _caller(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    maps = await _load_all(uid)
    if not maps:
        return ActionResult.success(
            data={},
            summary=("No code index yet. Open the repo in the Webbee terminal agent — "
                     "the index it builds becomes readable here."))

    want = (params.repo or "").strip().lower()
    chosen = maps[0]
    if want:
        hit = next((d for d in maps
                    if want == str(d.get("_repo_key", "")).lower()
                    or want in str(d.get("repo_root", "")).lower()), None)
        if hit is None:
            names = ", ".join(os.path.basename((d.get("repo_root") or "").rstrip("/"))
                              or d.get("_repo_key", "?") for d in maps[:8])
            return ActionResult.error(
                f"No indexed repo matches '{params.repo}'. Known: {names}")
        chosen = hit

    syms = chosen.get("top_symbols") or []
    detail = [_summarise(chosen)]
    hints = chosen.get("test_hint_files") or []
    if hints:
        detail.append("Test hints: " + ", ".join(hints[:8]))
    if syms:
        detail.append("Key symbols:")
        detail += [f"  · {s}" for s in syms[:15]]
        if len(syms) > 15:
            detail.append(f"  (+{len(syms) - 15} more)")
    if not chosen.get("symbol_kinds"):
        detail.append("⚠ No symbols indexed — the parsers may be missing on that "
                      "machine; upgrading the terminal agent to 0.3.51+ fixes it.")
    return ActionResult.success(
        data={k: v for k, v in chosen.items() if not k.startswith("_")},
        summary="\n".join(detail))


# ── The cloud WEBBEE.md: durable per-repo knowledge, readable anywhere ────────
#
# The coding agent distils facts about a repo as it works ("the symbol graph is
# empty", "every edit is auto-committed to a shadow git") and the kernel stores
# them per (user, repo) under imperal:repo_memory:{user_id}:{repo_key}. That is
# effectively a WEBBEE.md living in the cloud instead of in one checkout: it is
# not tied to a machine, a clone, or a session, so context survives losing the
# laptop. It was, however, only ever read back INTO a coding turn -- so from the
# panel the knowledge was invisible. This handler surfaces it read-only.

_MEM_PREFIX = "imperal:repo_memory:"


async def _load_memories(uid: str) -> list[dict]:
    """All durable repo-note sets for this user. Fail-soft: [] on any error."""
    out: list[dict] = []
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            n = 0
            async for key in r.scan_iter(match=f"{_MEM_PREFIX}{uid}:*", count=200):
                raw = await r.get(key)
                if not raw:
                    continue
                try:
                    d = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(d, dict) and d.get("entries"):
                    d["_repo_key"] = key.split(":")[-1]
                    out.append(d)
                n += 1
                if n >= _SCAN_CAP:
                    break
        finally:
            await r.aclose()
    except Exception:
        log.warning("repo memory scan failed (fail-soft empty)", exc_info=True)
    return out


@chat.function(
    "get_repo_knowledge",
    action_type="read",
    description=("Show the durable notes Webbee has learned about your repositories — the "
                 "cloud-side WEBBEE.md. These are facts distilled while coding (conventions, "
                 "gotchas, where things live), kept per repo and independent of any single "
                 "machine or checkout, so context is never lost. Readable from any surface."),
)
async def fn_get_repo_knowledge(ctx, params: _RepoParam) -> ActionResult:
    uid = _caller(ctx)
    if not uid:
        return ActionResult.error("Could not identify the calling user.")
    mems = await _load_memories(uid)
    if not mems:
        return ActionResult.success(
            data={},
            summary=("No repo knowledge stored yet. It builds up automatically as the "
                     "Webbee terminal agent works in a repository."))

    want = (params.repo or "").strip().lower()
    chosen = mems[0]
    if want:
        hit = next((m for m in mems if want in str(m.get("_repo_key", "")).lower()), None)
        if hit is None:
            known = ", ".join(str(m.get("_repo_key", "?"))[:16] for m in mems[:8])
            return ActionResult.error(
                f"No stored knowledge matches '{params.repo}'. Known repos: {known}")
        chosen = hit

    entries = chosen.get("entries") or []
    lines = []
    # Newest last in storage (LRU tail) -> show freshest first for a reader.
    for e in reversed(entries[-20:]):
        if not isinstance(e, dict):
            continue
        note = str(e.get("note") or "").strip()
        if not note:
            continue
        cites = e.get("citations") or []
        where = f"  [{cites[0]}]" if cites else ""
        lines.append(f"• {note}{where}")

    more = f"\n(+{len(entries) - 20} older)" if len(entries) > 20 else ""
    head = f"{len(entries)} durable note(s) for repo {chosen.get('_repo_key', '?')[:16]}:"
    return ActionResult.success(
        data={"repo_key": chosen.get("_repo_key", ""), "entries": entries,
              "total": len(entries)},
        summary=head + "\n" + "\n".join(lines) + more)
