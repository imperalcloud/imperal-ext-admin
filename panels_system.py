"""Admin · System panel builder — platform topology graph, health, temporal cluster, and services.
"""
from __future__ import annotations

import asyncio
from imperal_sdk import ui

from app import AUTH_GW, REGISTRY_URL, TEMPORAL_HOST, TEMPORAL_PORT, TEMPORAL_NAMESPACE
from panels_sections import _check_health


async def build_system(ctx, **kwargs):
    """System info — platform topology graph, health, temporal cluster, and services."""
    gw, reg = await asyncio.gather(
        _check_health("auth_gateway", f"{AUTH_GW}/healthz"),
        _check_health("registry", f"{REGISTRY_URL}/health"),
    )

    gw_color = "green" if gw == "Operational" else "red"
    reg_color = "green" if reg == "Operational" else "red"

    # Core node services
    temporal_status = "Operational" if TEMPORAL_HOST else "Unconfigured"
    temporal_color = "green" if temporal_status == "Operational" else "amber"

    # 1. Interactive Cluster Topology Graph (Cytoscape / react-cytoscapejs)
    graph_nodes = [
        {"id": "auth_gw", "label": "Auth Gateway\n(104.224.88.155:8085)", "type": "gateway", "size": 48},
        {"id": "worker", "label": "Platform Worker\n(104.224.88.156)", "type": "worker", "size": 56},
        {"id": "temporal", "label": "Temporal Cluster\n(port: 7233)", "type": "orchestrator", "size": 44},
        {"id": "registry", "label": "Registry Service\n(66.78.41.10:8098)", "type": "registry", "size": 40},
        {"id": "redis", "label": "Config Store & Redis\n(cache & routing)", "type": "database", "size": 36},
    ]
    graph_edges = [
        {"source": "auth_gw", "target": "worker", "label": "HTTP / gRPC", "type": "control"},
        {"source": "worker", "target": "temporal", "label": "Workflows", "type": "state"},
        {"source": "worker", "target": "registry", "label": "Sync API", "type": "meta"},
        {"source": "worker", "target": "redis", "label": "Routing Cache", "type": "fast"},
        {"source": "auth_gw", "target": "redis", "label": "Token Ledger", "type": "auth"},
    ]

    return ui.Stack(children=[
        ui.Header("System Architecture & Cluster Topology", level=3),
        ui.Stats(children=[
            ui.Stat(label="Auth Gateway", value=gw, color=gw_color),
            ui.Stat(label="Registry", value=reg, color=reg_color),
            ui.Stat(label="Temporal Cluster", value=temporal_status, color=temporal_color),
            ui.Stat(label="Decentralized OS", value="Active", color="blue"),
        ], columns=2),
        ui.Card(
            title="Interactive Cluster Topology (Cytoscape Graph)",
            content=ui.Graph(
                nodes=graph_nodes,
                edges=graph_edges,
                layout="cose-bilkent",
                height=320,
                edge_label_visible=True,
                color_by="type",
            ),
        ),
        ui.Card(
            title="Cluster & Core Services",
            content=ui.KeyValue(items=[
                {"key": "OS Architecture", "value": "Imperal Cloud ICNLI AI Cloud OS (Decentralized)"},
                {"key": "Auth Gateway", "value": f"auth.imperal.io ({AUTH_GW})"},
                {"key": "Registry API", "value": f"api-server:8098 ({REGISTRY_URL})"},
                {"key": "Temporal Host", "value": f"{TEMPORAL_HOST}:{TEMPORAL_PORT} (ns: {TEMPORAL_NAMESPACE})"},
            ])
        ),
        ui.Alert(
            title="Context & LLM Tunables",
            message="LLM provider configurations and neural routing are managed under the LLM Config section.",
            type="info",
        ),
    ])
