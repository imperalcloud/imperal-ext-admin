"""Admin · Scopes panel section builder.

Displays the full list of platform scopes with:
- Backend filtering by resource and source
- Expandable ListItems with KeyValue detail + description
- Filter bar with two Select dropdowns (resource, source)
- Inline accordion form for creating a new scope
- Direct Call-based delete for non-system scopes
"""
from __future__ import annotations

import logging

from imperal_sdk import ui
from imperal_sdk.ui.base import UINode

from panels_sections import _fetch_scopes

log = logging.getLogger("admin")


# ── Data fetcher ───────────────────────────────────────────────────────





# ── Helpers ────────────────────────────────────────────────────────────


def _unique_sorted(scopes: list[dict], field: str) -> list[str]:
    """Collect unique non-empty values for a field across all scopes."""
    return sorted({s.get(field, "") for s in scopes if s.get(field)})


def _source_badge(source: str) -> UINode:
    color = "blue" if source == "platform" else "green"
    return ui.Badge(label=source or "unknown", color=color)


def _build_expanded(s: dict) -> list[UINode]:
    """Expanded content: KeyValue detail grid + optional description + delete button."""
    kv_items = [
        {"key": "Resource",   "value": s.get("resource", "—")},
        {"key": "Action",     "value": s.get("action", "—")},
        {"key": "Source",     "value": s.get("source", "—")},
        {"key": "Source ID",  "value": s.get("source_id", "—") or "—"},
        {"key": "System",     "value": "Yes" if s.get("is_system") else "No"},
        {"key": "Scope",      "value": s.get("name", "—")},
    ]
    nodes: list[UINode] = [ui.KeyValue(items=kv_items, columns=2)]

    description = s.get("description", "").strip()
    if description:
        nodes.append(ui.Text(description, variant="body"))

    # Only show Delete for non-system scopes
    if not s.get("is_system"):
        scope_name = s.get("name", "")
        nodes.append(
            ui.Button(
                label="Delete",
                variant="danger",
                on_click=ui.Call("delete_scope", scope_name=scope_name),
            )
        )

    return nodes


def _build_scope_item(s: dict) -> UINode:
    """Single scope ListItem (collapsed + expanded)."""
    name = s.get("name", "")
    display_name = s.get("display_name", "") or name
    source = s.get("source", "")
    is_system = s.get("is_system", False)

    return ui.ListItem(
        id=name,
        title=name,
        subtitle=display_name if display_name != name else "",
        badge=_source_badge(source),
        meta="system" if is_system else "",
        expandable=True,
        expanded_content=_build_expanded(s),
    )


def _build_filter_options(values: list[str], all_label: str) -> list[dict]:
    opts = [{"value": "", "label": all_label}]
    opts += [{"value": v, "label": v} for v in values]
    return opts


def _build_create_accordion() -> UINode:
    """Inline accordion with a form for creating a new scope."""
    return ui.Accordion(sections=[{
        "id": "create",
        "title": "Create New Scope",
        "children": [
            ui.Form(
                action="create_scope",
                submit_label="Create Scope",
                children=[
                    ui.Input(placeholder="Resource (e.g. billing)", param_name="resource"),
                    ui.Input(placeholder="Action (e.g. read)", param_name="action"),
                    ui.Input(placeholder="Display name", param_name="display_name"),
                    ui.Input(placeholder="Description", param_name="description"),
                ],
            ),
        ],
    }])


# ── Builder ────────────────────────────────────────────────────────────


async def build_scopes(ctx, resource: str = "", source: str = "", **kwargs) -> UINode:
    """Scopes section: filterable, expandable scope list.

    resource / source — backend filter params propagated via Select.on_change.
    """
    all_scopes = await _fetch_scopes()

    # Build filter options from ALL scopes (before filtering)
    resource_values = _unique_sorted(all_scopes, "resource")
    source_values = _unique_sorted(all_scopes, "source")

    resource_opts = _build_filter_options(resource_values, "All Resources")
    source_opts = _build_filter_options(source_values, "All Sources")

    # Apply filters
    filtered = all_scopes
    if resource:
        filtered = [s for s in filtered if s.get("resource") == resource]
    if source:
        filtered = [s for s in filtered if s.get("source") == source]

    # Filter bar — each Select preserves the OTHER filter's current value
    filter_bar = ui.Stack(
        children=[
            ui.Select(
                options=resource_opts,
                value=resource,
                param_name="resource",
                placeholder="All Resources",
                on_change=ui.Call("__panel__tools", section="scopes", source=source),
            ),
            ui.Select(
                options=source_opts,
                value=source,
                param_name="source",
                placeholder="All Sources",
                on_change=ui.Call("__panel__tools", section="scopes", resource=resource),
            ),
        ],
        direction="h",
        gap=2,
    )

    count_label = ui.Text(f"{len(filtered)} scope{'s' if len(filtered) != 1 else ''}", variant="caption")

    if not filtered:
        content = ui.Empty(
            message="No scopes match the current filters." if (resource or source) else "No scopes found.",
            icon="Key",
        )
    else:
        items = [_build_scope_item(s) for s in filtered]
        content = ui.List(items=items, searchable=True)

    return ui.Stack(
        children=[
            ui.Header("Scopes", level=3),
            filter_bar,
            _build_create_accordion(),
            count_label,
            content,
        ]
    )
