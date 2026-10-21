"""楽天市場コネクタとツール。HTTP と待機はすべて差し替える。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

import httpx
import pytest

from yata.config import Settings
from yata.connectors.base import ConnectorRegistry, ConnectorState
from yata.connectors.catalog import build_connector_registry
from yata.connectors.rakuten import RakutenConnector
from yata.tools.base import Risk, ToolContext
from yata.tools.catalog import build_registry, visible_registry
from yata.tools.policy import ToolPolicy
from yata.tools.rakuten import (
    RAKUTEN_BASE, RANKING_PATH, SEARCH_PATH,
    RakutenItemRankingTool, RakutenSearchItemsTool, rakuten_request,
)

APPLICATION_ID = "test-rakuten-application-secret"
ACCESS_KEY = "pk_test-rakuten-access-secret"
AFFILIATE_ID = "test-rakuten-affiliate-secret"
ORIGIN = "https://example.test"
SECRETS = (APPLICATION_ID, ACCESS_KEY, AFFILIATE_ID)
TOOL_TYPES = (RakutenSearchItemsTool, RakutenItemRankingTool)


def context(application_id=APPLICATION_ID, access_key=ACCESS_KEY, affiliate_id=None, origin=None):
    connectors = ConnectorRegistry()
    connectors.register(RakutenConnector(application_id, access_key, affiliate_id, origin))
    return ToolContext("conv", None, None, None, True, connectors=connectors)


@pytest.fixture(autouse=True)
def mock_rate_limit(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("yata.tools.rakuten._last_request", None)
    monkeypatch.setattr("yata.tools.rakuten._request_lock", asyncio.Lock())
    monkeypatch.setattr("yata.tools.rakuten.asyncio.sleep", sleep)
    return sleep


@pytest.fixture
def mock_http(monkeypatch):
    client_type = httpx.AsyncClient

    def install(handler):
        transport = httpx.MockTransport(handler)

        def client(**kwargs):
            assert kwargs["timeout"] == 15
            return client_type(transport=transport, **kwargs)

        monkeypatch.setattr("yata.tools.rakuten.httpx.AsyncClient", client)

    return install


def assert_safe(value):
    text = str(value)
    for secret in SECRETS:
        assert secret not in text
        assert quote(secret, safe="") not in text


@pytest.mark.parametrize("application_id, access_key, connected", [
    (None, None, False), (APPLICATION_ID, None, False), (None, ACCESS_KEY, False),
    ("", ACCESS_KEY, False), (APPLICATION_ID, "  ", False),
    (APPLICATION_ID, ACCESS_KEY, True),
])
def test_connector_and_visibility(application_id, access_key, connected):
    ctx = context(application_id, access_key, AFFILIATE_ID, ORIGIN)
    connector = ctx.connectors.get("rakuten")
    assert connector.status() is (ConnectorState.CONNECTED if connected else ConnectorState.NOT_CONFIGURED)
    assert connector.id == "rakuten"
    assert connector.label == "楽天市場"
    assert connector.auth_kind == "token"
    assert connector.disconnect() is False
    assert_safe(repr(connector))
    assert_safe(str(connector))
    names = {tool_type().name for tool_type in TOOL_TYPES}
    base = build_registry()
    visible = set(visible_registry(base, ctx.connectors).names())
    assert visible & names == (names if connected else set())
    assert not set(visible_registry(base, None).names()) & names


def test_credentials_and_catalog(tmp_path):
    settings = Settings(
        _env_file=None, yata_db=str(tmp_path / "yata.db"),
        rakuten_application_id=APPLICATION_ID, rakuten_access_key=ACCESS_KEY,
        rakuten_affiliate_id=AFFILIATE_ID, rakuten_origin=ORIGIN,
    )
    connector = build_connector_registry(settings).get("rakuten")
    assert connector.credentials() == {
        "applicationId": APPLICATION_ID, "accessKey": ACCESS_KEY,
        "affiliateId": AFFILIATE_ID, "Origin": ORIGIN,
    }
    assert RakutenConnector("  " + APPLICATION_ID, ACCESS_KEY + "  ").status() is ConnectorState.CONNECTED


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
def test_read_only(tool_type):
    tool = tool_type()
    assert tool.risk is Risk.READ
    assert tool.required_connector == "rakuten"
    assert ToolPolicy().needs_confirmation(tool, {}) is False


@pytest.mark.parametrize("affiliate_id, origin", [(None, None), (AFFILIATE_ID, ORIGIN), ("  ", "")])
@pytest.mark.parametrize("tool_type, arguments, path, query", [
    (RakutenSearchItemsTool, {"keyword": "日本茶"}, SEARCH_PATH, {"keyword": "日本茶", "hits": "10"}),
    (RakutenSearchItemsTool, {"keyword": "茶", "min_price": 0, "max_price": 5000, "sort": "+itemPrice", "hits": 99},
     SEARCH_PATH, {"keyword": "茶", "minPrice": "0", "maxPrice": "5000", "sort": "+itemPrice", "hits": "30"}),
    (RakutenSearchItemsTool, {"keyword": "茶", "hits": -1}, SEARCH_PATH, {"keyword": "茶", "hits": "1"}),
    (RakutenItemRankingTool, {}, RANKING_PATH, {}),
    (RakutenItemRankingTool, {"genre_id": 100316}, RANKING_PATH, {"genreId": "100316"}),
])
async def test_request_shape(mock_http, tool_type, arguments, path, query, affiliate_id, origin):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url.copy_with(query=None)) == RAKUTEN_BASE + path
        expected = {**query, "applicationId": APPLICATION_ID, "format": "json", "formatVersion": "2"}
        if affiliate_id and affiliate_id.strip():
            expected["affiliateId"] = affiliate_id
        assert dict(request.url.params) == expected
        assert "accessKey" not in request.url.params
        assert ACCESS_KEY not in str(request.url)
        assert request.headers["accessKey"] == ACCESS_KEY
        assert request.headers.get("Origin") == (origin or None)
        return httpx.Response(200, json={"Items": [], "count": 0})

    mock_http(handler)
    result = await tool_type().run(arguments, context(affiliate_id=affiliate_id, origin=origin))
    assert len(requests) == 1
    assert result.ok
    assert json.loads(result.content) == []
    assert_safe(result)


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
async def test_flat_response_and_url_preference(mock_http, tool_type):
    item = {"rank": 2, "itemName": "お茶", "itemPrice": 1500, "shopName": "茶店",
            "reviewAverage": 4.5, "reviewCount": 12, "itemUrl": "https://example.test/item/2",
            "affiliateUrl": "https://example.test/affiliate/2"}
    second = {**item, "rank": 1, "itemName": "紅茶", "affiliateUrl": ""}
    mock_http(lambda request: httpx.Response(200, json={"Items": [item, second], "count": 2}))
    result = await tool_type().run({"keyword": "茶"}, context())
    assert result.ok
    rows = json.loads(result.content)
    expected = {"name": "お茶", "price": 1500, "shop": "茶店", "review_average": 4.5,
                "review_count": 12, "url": item["affiliateUrl"]}
    if tool_type is RakutenItemRankingTool:
        assert [row["rank"] for row in rows] == [1, 2]
        assert rows[1] == {"rank": 2, **expected}
        assert rows[0]["url"] == item["itemUrl"]
    else:
        assert rows[0] == expected
        assert rows[1]["url"] == item["itemUrl"]
    assert_safe(result)


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
async def test_404_is_empty(mock_http, tool_type):
    mock_http(lambda request: httpx.Response(404, json={"error": "not_found"}))
    result = await tool_type().run({"keyword": "茶"}, context())
    assert result.ok
    assert json.loads(result.content) == []


@pytest.mark.parametrize("status, expected", [
    (400, "400"), (401, "認証に失敗"), (403, "認証に失敗"),
    (429, "1秒以上"), (500, "500"), (503, "503"),
])
@pytest.mark.parametrize("nested", [True, False])
@pytest.mark.parametrize("tool_type", TOOL_TYPES)
async def test_errors_are_safe(mock_http, tool_type, status, expected, nested):
    detail = "CLIENT_IP_NOT_ALLOWED " + " ".join(SECRETS) + " https://example.test/private?key=" + ACCESS_KEY
    body = ({"errors": {"errorCode": status, "errorMessage": detail}} if nested else
            {"error": "wrong_parameter", "error_description": detail})
    mock_http(lambda request: httpx.Response(status, json=body))
    result = await tool_type().run({"keyword": "茶"}, context(affiliate_id=AFFILIATE_ID))
    assert not result.ok
    assert expected in result.content
    assert "楽天市場" in result.content
    if status in (401, 403):
        assert "IP/Origin" in result.content
        assert ".env" in result.content
    if status in (400, 500, 503):
        assert "CLIENT_IP_NOT_ALLOWED" in result.content
    assert "https://" not in result.content
    assert_safe(result)


async def test_communication_failure(mock_http):
    def handler(request):
        raise httpx.ConnectError(" ".join(SECRETS) + str(request.url), request=request)

    mock_http(handler)
    data, error = await rakuten_request(context(), "GET", SEARCH_PATH)
    assert data is None
    assert not error.ok
    assert "通信に失敗" in error.content
    assert "https://" not in error.content
    assert_safe(error)


@pytest.mark.parametrize("application_id, access_key", [(None, None), (APPLICATION_ID, None), (None, ACCESS_KEY)])
async def test_not_configured_never_requests(mock_http, application_id, access_key):
    def handler(request):
        pytest.fail("未設定時は HTTP を呼ばない")

    mock_http(handler)
    data, error = await rakuten_request(context(application_id, access_key), "GET", SEARCH_PATH)
    assert data is None
    assert not error.ok
    assert "接続されていません" in error.content
    assert_safe(error)


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
async def test_output_redacts_echoed_credentials(mock_http, tool_type):
    affiliate_url = "https://example.test/" + AFFILIATE_ID
    mock_http(lambda request: httpx.Response(200, json={"Items": [{
        "itemName": " ".join(SECRETS), "itemUrl": "https://example.test/" + APPLICATION_ID,
        "affiliateUrl": affiliate_url,
    }]}))
    result = await tool_type().run({"keyword": "茶"}, context(affiliate_id=AFFILIATE_ID))
    assert result.ok
    row = json.loads(result.content)[0]
    assert row["name"] == f"[非表示] [非表示] {AFFILIATE_ID}"
    assert row["url"] == affiliate_url
    for secret in (APPLICATION_ID, ACCESS_KEY):
        assert secret not in result.content
        assert quote(secret, safe="") not in result.content


@pytest.mark.parametrize("hits, expected", [
    ("5", 5), (None, 10), ("abc", 10), ([], 10),
    ("0", 1), ("31", 30), (-1, 1), (99, 30),
])
async def test_search_normalizes_hits(hits, expected):
    request = AsyncMock(return_value=({"Items": []}, None))
    result = await RakutenSearchItemsTool(request_fn=request).run(
        {"keyword": "茶", "hits": hits}, context(),
    )
    assert result.ok
    assert request.await_args.kwargs["params"]["hits"] == expected


@pytest.mark.parametrize("source, target", [("min_price", "minPrice"), ("max_price", "maxPrice")])
@pytest.mark.parametrize("value, expected", [("500", 500), (0, 0), (None, None)])
async def test_search_normalizes_prices(source, target, value, expected):
    request = AsyncMock(return_value=({"Items": []}, None))
    result = await RakutenSearchItemsTool(request_fn=request).run(
        {"keyword": "茶", source: value}, context(),
    )
    assert result.ok
    params = request.await_args.kwargs["params"]
    if expected is None:
        assert target not in params
    else:
        assert params[target] == expected


@pytest.mark.parametrize("source, label", [("min_price", "最低価格"), ("max_price", "最高価格")])
@pytest.mark.parametrize("value", ["abc", "", [], {}, float("inf")])
async def test_search_rejects_invalid_prices(source, label, value):
    request = AsyncMock(return_value=({"Items": []}, None))
    result = await RakutenSearchItemsTool(request_fn=request).run(
        {"keyword": "茶", source: value}, context(),
    )
    assert not result.ok
    assert result.content == f"{label}は整数で指定してください。"
    request.assert_not_awaited()


async def test_request_fn_injection():
    request = AsyncMock(return_value=({"Items": []}, None))
    result = await RakutenSearchItemsTool(request_fn=request).run({"keyword": "茶"}, context())
    assert result.ok
    assert request.await_args.args[1:] == ("GET", SEARCH_PATH)
    assert request.await_args.kwargs["params"] == {"keyword": "茶", "hits": 10}


@pytest.mark.parametrize("elapsed, expected_delay", [(0.25, 0.75), (1.5, None)])
async def test_shared_rate_limit(mock_http, mock_rate_limit, monkeypatch, elapsed, expected_delay):
    mock_http(lambda request: httpx.Response(200, json={"Items": []}))
    clock = iter([10.0, 10.0 + elapsed, 10.0 + max(1, elapsed)])
    monkeypatch.setattr("yata.tools.rakuten.time", SimpleNamespace(monotonic=lambda: next(clock)))
    await RakutenSearchItemsTool().run({"keyword": "茶"}, context())
    await RakutenItemRankingTool().run({}, context())
    if expected_delay is None:
        mock_rate_limit.assert_not_awaited()
    else:
        mock_rate_limit.assert_awaited_once_with(expected_delay)
