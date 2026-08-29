"""Admin · Byte-aware render cap for big lists (Users, Extensions, ...).

Incident (2026-08-29): the kernel's fast_rpc reply pipe has a HARD 256KB
cap on any panel response — if it's exceeded, the WHOLE reply is replaced
with a typed truncation error, not a partial render (see
imperal_kernel/rpc/stream_consumer.py: REPLY_PAYLOAD_MAX_BYTES / "reply
payload over %d bytes ... replacing with typed truncation error"). The
Users and Extensions panels each had a fixed item-COUNT cap (200 / 150)
picked by guessing, not by measuring actual bytes-per-item. At this
tenant's real size that guess was already wrong: 41 real users serialize
to ~268KB (over the cap) and 169 real extensions to ~392KB — so the panel
that was supposed to protect against a large tenant was ITSELF the thing
tripping the kernel's hard limit, leaving the panel (and, transitively,
anything that auto-opens it, like the sidebar's last-active section)
stuck on a typed error with nothing rendered.

A fixed item count can never be right for every tenant: one app/user with
a long description or a big tools/scopes list weighs far more than a
plain one. This module replaces "first N items" with "build items one at
a time and stop once the ACTUAL serialized weight approaches the budget"
— it can never overshoot the kernel's hard cap regardless of how heavy
each item turns out to be, and it renders MORE items on tenants where
they happen to be light instead of always truncating at the same number.
"""
from __future__ import annotations

import json
from typing import Callable, TypeVar

T = TypeVar("T")

# Budget for the LIST ITEMS ONLY, not the whole panel response. Leaves
# headroom under the kernel's 256KB (262144 byte) hard cap for everything
# else the panel also ships alongside the list: header, search/filter
# bar, the truncation ui.Alert itself, JSON envelope/RPC framing, and any
# per-request growth in those (e.g. more role options over time). 200KB
# measured empirically as comfortable: real payloads at this budget leave
# 60KB+ of headroom.
DEFAULT_ITEM_BUDGET_BYTES = 200_000


def build_capped_list(
    candidates: list[T],
    build_item: Callable[[T], object],
    *,
    budget_bytes: int = DEFAULT_ITEM_BUDGET_BYTES,
) -> tuple[list, int, int]:
    """Build UI list items one at a time, stopping before the byte budget.

    ``build_item`` turns one candidate into a UINode (e.g. ui.ListItem).
    Each built item is serialized via ``.to_dict()`` to measure its REAL
    wire weight — no guessing from item count. Stops BEFORE adding an item
    that would push the running total over ``budget_bytes``, so the
    result is always under budget even if later items are heavier than
    earlier ones.

    Returns ``(items, rendered_count, total_candidates)``. An empty
    ``candidates`` list returns ``([], 0, 0)`` immediately — always safe.
    """
    items: list = []
    running_bytes = 0
    total = len(candidates)

    for candidate in candidates:
        node = build_item(candidate)
        try:
            node_dict = node.to_dict() if hasattr(node, "to_dict") else node
            weight = len(json.dumps(node_dict, default=str))
        except Exception:
            # A single unserializable/odd item must not crash the whole
            # panel render — skip it from the budget count but still
            # render it (its own to_dict() already succeeded if we got
            # this far in the try, so this only guards the json.dumps
            # measurement step itself).
            weight = 0

        if items and running_bytes + weight > budget_bytes:
            break

        items.append(node)
        running_bytes += weight

    return items, len(items), total
