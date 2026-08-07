from types import SimpleNamespace

import pytest

import handlers_repo_contract_graph as h


def _ctx(uid="imp_test"):
    return SimpleNamespace(user=SimpleNamespace(imperal_id=uid))


@pytest.mark.asyncio
async def test_contract_graph_links_schema_refs_across_repos(monkeypatch):
    maps = [
        {
            "_repo_key": "producer", "repo_root": "/src/producer", "git_ref": "abc123",
            "updated_at": 100, "endpoint_count": 1, "schema_count": 0,
            "contract_evidence_complete": True,
            "endpoints": [{"method": "POST", "route": "/v1/orders", "handler": "create_order",
                           "path": "api.py", "line": 10, "schema_refs": ["OrderIn", "OrderOut"]}],
            "schemas": [],
        },
        {
            "_repo_key": "consumer", "repo_root": "/src/consumer", "git_ref": "def456",
            "updated_at": 90, "endpoint_count": 0, "schema_count": 1, "endpoints": [],
            "contract_evidence_complete": True,
            "schemas": [{"name": "OrderIn", "schema_kind": "model", "path": "models.py",
                         "line": 3, "fields": ["sku"]}],
        },
    ]
    monkeypatch.setattr(h, "_load_all", lambda uid: _async_value(maps))
    result = await h.fn_get_cross_repo_contract_graph(_ctx(), h.ContractGraphParam(query="order"))
    data = result.data
    assert data["repo_count"] == 2
    assert data["endpoint_count"] == 1
    assert data["schema_count"] == 1
    assert data["contracts_complete"] is True
    assert any(x["relation"] == "endpoint_schema_ref" and x["identity"] == "OrderIn"
               for x in data["links"])
    assert all("repo_key" in x and "path" in x and "line" in x
               for x in data["endpoints"] + data["schemas"])


@pytest.mark.asyncio
async def test_contract_graph_is_user_scoped_and_bounded(monkeypatch):
    seen = []
    async def load(uid):
        seen.append(uid)
        return [{"_repo_key": "r", "endpoints": [], "schemas": [], "updated_at": 1}]
    monkeypatch.setattr(h, "_load_all", load)
    result = await h.fn_get_cross_repo_contract_graph(
        _ctx("imp_owner"), h.ContractGraphParam(query="", limit=200))
    assert seen == ["imp_owner"]
    assert result.data["repo_count"] == 1
    assert len(result.data["links"]) <= 200


async def _async_value(value):
    return value
