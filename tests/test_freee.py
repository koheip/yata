"""freee OAuth and tools; no real HTTP requests."""
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from yata.api.app import create_app
from yata.config import Settings
from yata.connectors.base import ConnectorRegistry, ConnectorState
from yata.connectors.freee import FreeeConnector, FreeeOAuthError, TOKEN_ENDPOINT
from yata.connectors.token_store import TokenSet, TokenStore
from yata.tools.base import ToolContext
from yata.tools.catalog import build_registry, visible_registry
from yata.tools.freee import (
    FREEE_BASE, INVOICES_URL, FreeeListCompaniesTool, FreeeListAccountItemsTool,
    FreeeListDealsTool, FreeeListInvoicesTool, FreeeGetTrialBalanceTool,
    FreeeCreateExpenseDealTool, freee_request,
)
from yata.tools.policy import ToolPolicy, describe_action

SECRET = "private-client-secret"
ACCESS = "private-access-token"
REFRESH = "private-refresh-token"
CALLBACK = "http://127.0.0.1:8741/api/connectors/freee/oauth/callback"


def connector(tmp_path, handler=None):
    factory = None if handler is None else lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    return FreeeConnector("client-id", SECRET, CALLBACK, TokenStore(tmp_path), factory)


def context(c):
    registry = ConnectorRegistry()
    registry.register(c)
    return ToolContext("conv", None, None, None, True, registry)


def save(c, expires=3600):
    c._tokens.save("freee", TokenSet(ACCESS, REFRESH, time.time() + expires, "read write"))


def test_status_authorize_visibility(tmp_path):
    c = connector(tmp_path)
    assert c.status() == ConnectorState.NOT_CONNECTED
    for value in (None, "", " ", "your-client"):
        assert FreeeConnector(value, SECRET, CALLBACK, c._tokens).status() == ConnectorState.NOT_CONFIGURED
        assert FreeeConnector("client", value, CALLBACK, c._tokens).status() == ConnectorState.NOT_CONFIGURED
    query = parse_qs(urlparse(c.authorize_url("state", "challenge")).query)
    for key, value in {"state": "state", "code_challenge": "challenge", "code_challenge_method": "S256",
                       "redirect_uri": CALLBACK, "prompt": "select_company", "response_type": "code"}.items():
        assert query[key] == [value]
    base = build_registry()
    names = {n for n in base.names() if n.startswith("freee_")}
    assert len(names) == 6
    assert names.isdisjoint(visible_registry(base, context(c).connectors).names())
    save(c)
    assert c.status() == ConnectorState.CONNECTED
    assert names <= set(visible_registry(base, context(c).connectors).names())
    assert c.disconnect()
    assert c.status() == ConnectorState.NOT_CONNECTED


async def test_exchange_and_refresh_rotation(tmp_path):
    forms = []

    def handler(request):
        assert str(request.url) == TOKEN_ENDPOINT
        assert request.method == "POST"
        form = parse_qs(request.content.decode())
        forms.append(form)
        assert form["client_secret"] == [SECRET]
        assert form["client_id"] == ["client-id"]
        return httpx.Response(200, json={"access_token": ACCESS, "refresh_token": f"rotated-{len(forms)}", "expires_in": 0})

    c = connector(tmp_path, handler)
    await c.complete_authorization("code", "verifier")
    assert forms[0]["code_verifier"] == ["verifier"]
    assert forms[0]["redirect_uri"] == [CALLBACK]
    assert forms[0]["grant_type"] == ["authorization_code"]
    assert await c.access_token() == ACCESS
    assert c._tokens.load("freee").refresh_token == "rotated-2"
    assert await c.access_token() == ACCESS
    assert forms[1]["refresh_token"] == ["rotated-1"]
    assert forms[2]["refresh_token"] == ["rotated-2"]
    assert c._tokens.load("freee").refresh_token == "rotated-3"


@pytest.mark.parametrize("status", [400, 401])
async def test_invalid_grant_disconnects(tmp_path, status):
    c = connector(tmp_path, lambda r: httpx.Response(status, json={"error": "invalid_grant", "message": SECRET}))
    save(c, -1)
    with pytest.raises(FreeeOAuthError, match="再接続") as error:
        await c.access_token()
    assert SECRET not in str(error.value)
    assert c.status() == ConnectorState.NOT_CONNECTED


def test_callback_and_status_do_not_leak(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, yata_db=str(tmp_path / "app.db"), yata_model="demo",
                        yata_scheduler_enabled=False, freee_client_id="client-id", freee_client_secret=SECRET)
    calls = []

    async def complete(self, code, code_verifier):
        calls.append((code, code_verifier))
        save(self)

    monkeypatch.setattr(FreeeConnector, "complete_authorization", complete)
    with TestClient(create_app(settings)) as client:
        path = "/api/connectors/freee/oauth/callback"
        assert "connector_error" in client.get(path, params={"code": "code", "state": "bad"}, follow_redirects=False).headers["location"]
        url = client.post("/api/connectors/freee/connect").json()["authorize_url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        response = client.get(path, params={"code": "code", "state": state}, follow_redirects=False)
        assert "connector_connected=freee" in response.headers["location"]
        assert calls[0][0] == "code" and calls[0][1]
        assert "connector_error" in client.get(path, params={"code": "code", "state": state}, follow_redirects=False).headers["location"]
        text = client.get("/api/connectors").text
        for value in (SECRET, ACCESS, REFRESH):
            assert value not in text


@pytest.mark.parametrize("tool,args,path,params,body", [
    (FreeeListCompaniesTool, {}, "/companies", None, {"companies": [{"id": 1}]}),
    (FreeeListAccountItemsTool, {"company_id": 1}, "/account_items", {"company_id": 1}, {"account_items": [{"id": 2, "name": "旅費", "default_tax_code": 3, "account_category": "expense", "extra": 9}]}),
    (FreeeListDealsTool, {"company_id": 1, "start_date": "2026-01-01", "end_date": "2026-12-31", "type": "expense", "limit": 100}, "/deals", {"company_id": 1, "start_issue_date": "2026-01-01", "end_issue_date": "2026-12-31", "type": "expense", "limit": 100}, {"deals": []}),
    (FreeeListInvoicesTool, {"company_id": 1, "start_date": "2026-01-01", "end_date": "2026-12-31"}, INVOICES_URL, {"company_id": 1, "billing_date_start": "2026-01-01", "billing_date_end": "2026-12-31", "limit": 50}, {"invoices": []}),
    (FreeeGetTrialBalanceTool, {"company_id": 1, "fiscal_year": 2026}, "/reports/trial_pl", {"company_id": 1, "fiscal_year": 2026}, {"trial_pl": {"balances": [{"account_category_name": "費用", "closing_balance": 123}]}}),
])
async def test_read_tools(tool, args, path, params, body):
    async def request(ctx, method, url, **kw):
        assert method == "GET" and url == path
        assert kw.get("params") == params
        assert kw.get("json") is None
        return body, None
    result = await tool(request).run(args, None)
    assert result.ok
    assert "extra" not in result.content
    if tool is FreeeGetTrialBalanceTool:
        assert json.loads(result.content) == [{"name": "費用", "closing_balance": 123}]


@pytest.mark.parametrize("partner", [None, 9])
async def test_create_and_confirmation(partner):
    args = dict(company_id=1, issue_date="2026-10-22", amount=12345, account_item_id=2, tax_code=3, description="交通費")
    if partner is not None:
        args["partner_id"] = partner

    async def request(ctx, method, path, **kw):
        assert method == "POST" and path == "/deals"
        expected = {"company_id": 1, "issue_date": args["issue_date"], "type": "expense",
                    "details": [{k: args[k] for k in ("account_item_id", "tax_code", "amount", "description")}]}
        if partner is not None:
            expected["partner_id"] = partner
        assert kw["json"] == expected
        return {"deal": {"id": 1}}, None
    tool = FreeeCreateExpenseDealTool(request)
    assert ToolPolicy().needs_confirmation(tool, args)
    text = describe_action(tool, args)
    for label in ("事業所 ID", "発生日", "¥12,345", "勘定科目 ID", "税区分コード", "取引先 ID", "交通費"):
        assert label in text
    if partner is None:
        assert "未指定" in text
    assert (await tool.run(args, None)).ok
    assert not (await tool.run({**args, "amount": 0}, None)).ok
    assert not (await tool.run({**args, "issue_date": "2026-02-30"}, None)).ok


@pytest.mark.parametrize("status,word", [(401, "再接続"), (403, "権限"), (429, "上限"), (400, "エラー"), (200, "非表示")])
async def test_http_errors_and_redaction(tmp_path, monkeypatch, status, word):
    c = connector(tmp_path)
    save(c)
    client_type = httpx.AsyncClient

    def handler(request):
        assert str(request.url) == FREEE_BASE + "/companies?company_id=1"
        assert request.headers["Authorization"] == f"Bearer {ACCESS}"
        return httpx.Response(status, json={"message": f"{SECRET} {ACCESS} {REFRESH}", "access_token": ACCESS})

    monkeypatch.setattr("yata.tools.freee.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    data, error = await freee_request(context(c), "GET", "/companies", params={"company_id": 1})
    text = error.content if error else json.dumps(data, ensure_ascii=False)
    assert word in text
    for value in (SECRET, ACCESS, REFRESH):
        assert value not in text


async def test_http_error_with_list_body(tmp_path, monkeypatch):
    c = connector(tmp_path)
    save(c)
    client_type = httpx.AsyncClient

    def handler(request):
        return httpx.Response(400, json=[{"message": "invalid request"}])

    monkeypatch.setattr("yata.tools.freee.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    data, error = await freee_request(context(c), "GET", "/companies")
    assert data is None
    assert error is not None and not error.ok
    assert error.content == "freee API エラー（400）: 処理に失敗しました。"


async def test_network_error(tmp_path, monkeypatch):
    c = connector(tmp_path)
    save(c)
    client_type = httpx.AsyncClient

    def handler(request):
        raise httpx.ConnectError(ACCESS, request=request)

    monkeypatch.setattr("yata.tools.freee.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    _, error = await freee_request(context(c), "GET", "/companies")
    assert not error.ok and "通信" in error.content and ACCESS not in error.content


async def test_invoice_http_url_and_tool_output(tmp_path, monkeypatch):
    c = connector(tmp_path)
    save(c)
    client_type = httpx.AsyncClient

    def handler(request):
        assert str(request.url) == INVOICES_URL + "?company_id=1&limit=50"
        return httpx.Response(200, json={"invoices": [{"id": 1, "description": ACCESS + SECRET + REFRESH}]})

    monkeypatch.setattr("yata.tools.freee.httpx.AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    result = await FreeeListInvoicesTool().run({"company_id": 1}, context(c))
    assert result.ok
    for value in (ACCESS, SECRET, REFRESH):
        assert value not in result.content


async def test_default_deal_limit_and_invalid_inputs():
    async def request(ctx, method, path, **kw):
        assert kw["params"] == {"company_id": 1, "limit": 50}
        return {"deals": []}, None

    tool = FreeeListDealsTool(request)
    assert (await tool.run({"company_id": 1}, None)).ok
    assert not (await tool.run({"company_id": 1, "limit": 101}, None)).ok
    assert not (await tool.run({"company_id": 1, "type": "invalid"}, None)).ok
