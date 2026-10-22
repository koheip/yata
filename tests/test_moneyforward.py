"""マネーフォワード クラウド請求書の連携とツール。通信はすべてモック。"""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from yata.connectors.base import ConnectorRegistry, ConnectorState
from yata.connectors.moneyforward import MoneyForwardConnector, MoneyForwardOAuthError
from yata.connectors.token_store import TokenSet, TokenStore
from yata.tools.base import Risk, ToolContext
from yata.tools.moneyforward import MfCreateBillingTool, MfListBillingsTool, MfListPartnersTool
from yata.tools.policy import describe_action

CLIENT_ID = "mf-client-id-test"
SECRET = "mf-client-secret-test"
REDIRECT = "http://127.0.0.1:8741/api/connectors/moneyforward/oauth/callback"


def connector(tmp_path, handler=None):
    factory = None
    if handler is not None:
        client_type = httpx.AsyncClient
        factory = lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw)  # noqa: E731
    return MoneyForwardConnector(CLIENT_ID, SECRET, REDIRECT, TokenStore(tmp_path), http_client_factory=factory)


def test_authorize_url_has_scopes_and_pkce(tmp_path):
    mf = connector(tmp_path)
    assert mf.status() is ConnectorState.NOT_CONNECTED
    query = parse_qs(urlparse(mf.authorize_url("st", "ch")).query)
    assert query["scope"] == ["mfc/invoice/data.read mfc/invoice/data.write"]
    assert query["code_challenge_method"] == ["S256"] and query["redirect_uri"] == [REDIRECT]
    assert MoneyForwardConnector(None, None, REDIRECT, TokenStore(tmp_path)).status() is ConnectorState.NOT_CONFIGURED


async def test_exchange_uses_basic_auth_and_refreshes_once(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"access_token": f"at-{len(seen)}", "refresh_token": f"rt-{len(seen)}", "expires_in": 3600})

    mf = connector(tmp_path, handler)
    await mf.complete_authorization("code-1", "verifier-1")
    auth = seen[0].headers["Authorization"]
    assert auth == "Basic " + base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
    assert parse_qs(seen[0].content.decode())["code_verifier"] == ["verifier-1"]
    assert mf.status() is ConnectorState.CONNECTED and await mf.access_token() == "at-1"

    store = TokenStore(tmp_path)
    store.save("moneyforward", TokenSet("old", "rt-1", time.time() - 10, ""))
    assert await mf.access_token() == "at-2"
    assert parse_qs(seen[-1].content.decode()) == {"grant_type": ["refresh_token"], "refresh_token": ["rt-1"]}


async def test_failed_refresh_disconnects(tmp_path):
    mf = connector(tmp_path, lambda request: httpx.Response(400, json={"error": "invalid_grant"}))
    TokenStore(tmp_path).save("moneyforward", TokenSet("old", "rt", time.time() - 10, ""))
    with pytest.raises(MoneyForwardOAuthError):
        await mf.access_token()
    assert mf.status() is ConnectorState.NOT_CONNECTED


def ctx(tmp_path):
    TokenStore(tmp_path).save("moneyforward", TokenSet("access-x", "refresh-x", time.time() + 3600, ""))
    registry = ConnectorRegistry()
    registry.register(connector(tmp_path))
    return ToolContext("conv", None, None, None, True, connectors=registry)


@pytest.fixture
def mock_http(monkeypatch):
    client_type = httpx.AsyncClient
    requests = []

    def install(handler):
        def wrapped(request):
            requests.append(request)
            return handler(request)

        monkeypatch.setattr("yata.tools.moneyforward.httpx.AsyncClient",
                            lambda **kw: client_type(transport=httpx.MockTransport(wrapped), **kw))
        return requests

    return install


async def test_list_partners_and_billings(tmp_path, mock_http):
    def handler(request):
        if request.url.path.endswith("/partners"):
            return httpx.Response(200, json={"data": [{"id": "p1", "name": "A社", "departments": [{"id": "d1", "name": "経理部"}]}]})
        return httpx.Response(200, json={"data": [{"id": "b1", "title": "10月分", "total_price": "11000"}]})

    requests = mock_http(handler)
    partners = await MfListPartnersTool().run({}, ctx(tmp_path))
    assert json.loads(partners.content)[0]["departments"] == [{"id": "d1", "name": "経理部"}]
    assert requests[-1].headers["Authorization"] == "Bearer access-x"
    billings = await MfListBillingsTool().run({"from": "2026-10-01", "to": "2026-10-31"}, ctx(tmp_path))
    assert "10月分" in billings.content
    assert parse_qs(requests[-1].url.query.decode())["range_key"] == ["billing_date"]
    bad = await MfListBillingsTool().run({"from": "10/1", "to": "2026-10-31"}, ctx(tmp_path))
    assert not bad.ok


async def test_create_billing_maps_tax_and_stays_draft(tmp_path, mock_http):
    requests = mock_http(lambda r: httpx.Response(201, json={"id": "b9", "billing_number": "0009", "total_price": "10800"}))
    args = {"department_id": "d1", "title": "10月分", "billing_date": "2026-10-31", "due_date": "2026-11-30",
            "items": [{"name": "制作費", "price": 10000, "quantity": 1, "tax": "8%（軽減）"}]}
    result = await MfCreateBillingTool().run(args, ctx(tmp_path))
    assert result.ok and "下書き" in result.content
    body = json.loads(requests[-1].content)
    assert body["items"][0]["excise"] == "eight_percent_as_reduced_tax_rate"
    assert requests[-1].url.path.endswith("/invoice_template_billings")
    assert MfCreateBillingTool.risk is Risk.EXTERNAL and MfListBillingsTool.risk is Risk.READ
    text = describe_action(MfCreateBillingTool(), args)
    assert "制作費" in text and "10000 円" in text


async def test_errors_hide_secrets(tmp_path, mock_http):
    mock_http(lambda r: httpx.Response(500, text=f"oops {SECRET} access-x"))
    result = await MfListPartnersTool().run({}, ctx(tmp_path))
    assert not result.ok and SECRET not in result.content and "access-x" not in result.content
