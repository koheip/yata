"""連携を画面から設定するための説明と、入力欄の定義。

一般の人が .env を開かなくても済むように、どの値をどこで取ってくるかを
手順として書いておく。値そのものは SecretStore に保存し、画面には出さない。
"""

from __future__ import annotations

from typing import Any

import httpx

# 連携 id（/api/connectors の id）から、設定のまとまり id へ。Gmail とカレンダーは同じ設定を使う。
CONNECTOR_TO_SETUP = {
    "gmail": "google",
    "google_calendar": "google",
    "chatwork": "chatwork",
    "rakuten": "rakuten",
    "freee": "freee",
    "line": "line",
    "backlog": "backlog",
    "kintone": "kintone",
    "moneyforward": "moneyforward",
}


def connector_setups(port: int) -> list[dict[str, Any]]:
    return [
        {
            "id": "chatwork",
            "label": "Chatwork",
            "advanced": False,
            "restart_required": False,
            "key_url": "https://www.chatwork.com/service/packages/chatwork/subpackages/api/token.php",
            "steps": [
                "下のボタンで Chatwork の「API トークン」のページを開きます（Chatwork にログインしておきます）。",
                "パスワードを入れて「表示」を押します。",
                "表示されたトークンをコピーして、この下に貼り付けます。",
            ],
            "fields": [
                {"name": "chatwork_api_token", "label": "API トークン", "secret": True, "optional": False},
            ],
        },
        {
            "id": "line",
            "label": "LINE",
            "advanced": False,
            "restart_required": True,
            "key_url": "https://developers.line.biz/console/",
            "steps": [
                "下のボタンで LINE Developers を開き、公式アカウントと Messaging API チャネルを作ります。",
                "「チャネル基本設定」で、チャネルシークレットと「あなたのユーザーID」をコピーします。",
                "「Messaging API設定」で、チャネルアクセストークン（長期）を発行してコピーします。",
                "3つを下に貼り付けて保存し、ヤタを起動し直します。",
            ],
            "fields": [
                {"name": "line_channel_access_token", "label": "チャネルアクセストークン（長期）", "secret": True, "optional": False},
                {"name": "line_channel_secret", "label": "チャネルシークレット", "secret": True, "optional": False},
                {"name": "line_allowed_user_ids", "label": "あなたのユーザーID（U から始まります）", "secret": False, "optional": False},
            ],
        },
        {
            "id": "backlog",
            "label": "Backlog",
            "advanced": False,
            "restart_required": False,
            "key_url": "https://support-ja.backlog.com/hc/ja/articles/360035641754",
            "steps": [
                "Backlog にログインし、右上のアイコン →「個人設定」→「API」を開きます（下のボタンで手順のページを開けます）。",
                "「メモ」に「ヤタ」と入れて「登録」を押し、表示された API キーをコピーします。",
                "スペースの URL（例: https://example.backlog.jp）と API キーを、この下に貼り付けます。",
            ],
            "fields": [
                {"name": "backlog_space", "label": "スペースの URL", "secret": False, "optional": False},
                {"name": "backlog_api_key", "label": "API キー", "secret": True, "optional": False},
            ],
        },
        {
            "id": "kintone",
            "label": "kintone",
            "advanced": False,
            "restart_required": False,
            "key_url": "https://jp.cybozu.help/k/ja/app/api/api_token.html",
            "steps": [
                "使いたい kintone アプリを開き、⚙（アプリの設定）→「設定」→「APIトークン」を開きます。",
                "「生成する」を押し、ヤタにさせたいこと（レコード閲覧・追加・編集）に印を付けて保存し、「アプリを更新」を押します。",
                "kintone の URL（例: https://example.cybozu.com）と API トークンを、この下に貼り付けます。アプリが複数あるときは、トークンをカンマ（,）で区切って並べます。",
            ],
            "fields": [
                {"name": "kintone_domain", "label": "kintone の URL", "secret": False, "optional": False},
                {"name": "kintone_api_tokens", "label": "API トークン（複数はカンマ区切り）", "secret": True, "optional": False},
            ],
        },
        {
            "id": "rakuten",
            "label": "楽天市場",
            "advanced": False,
            "restart_required": False,
            "key_url": "https://webservice.rakuten.co.jp/app/list",
            "steps": [
                "下のボタンで楽天ウェブサービスを開き、楽天会員でログインして「+アプリID発行」を押します。",
                "アプリの種類は「バックエンドサービス」を選び、許可 IP アドレスにこの PC のグローバル IP を登録します。",
                "表示された「アプリケーションID」と「アクセスキー（pk_ から始まります）」を、この下に貼り付けます。",
            ],
            "fields": [
                {"name": "rakuten_application_id", "label": "アプリケーションID", "secret": False, "optional": False},
                {"name": "rakuten_access_key", "label": "アクセスキー", "secret": True, "optional": False},
                {"name": "rakuten_affiliate_id", "label": "アフィリエイトID（なくても使えます）", "secret": False, "optional": True},
            ],
        },
        {
            "id": "freee",
            "label": "freee 会計",
            "advanced": True,
            "restart_required": False,
            "key_url": "https://app.secure.freee.co.jp/developers",
            "steps": [
                "下のボタンで freee アプリストアの開発者ページを開き、アプリを登録します。",
                f"コールバック URL に http://127.0.0.1:{port}/api/connectors/freee/oauth/callback を登録します。",
                "表示された Client ID と Client Secret を貼り付けて保存し、「接続する」を押します。",
            ],
            "fields": [
                {"name": "freee_client_id", "label": "Client ID", "secret": False, "optional": False},
                {"name": "freee_client_secret", "label": "Client Secret", "secret": True, "optional": False},
            ],
        },
        {
            "id": "moneyforward",
            "label": "マネーフォワード クラウド請求書",
            "advanced": True,
            "restart_required": False,
            "key_url": "https://app-portal.moneyforward.com/",
            "steps": [
                "下のボタンでマネーフォワードの「アプリポータル」を開き、新しいアプリを作ります。",
                f"リダイレクト URI に http://127.0.0.1:{port}/api/connectors/moneyforward/oauth/callback を登録します。",
                "使う API に「クラウド請求書」を選びます。",
                "表示された Client ID と Client Secret を貼り付けて保存し、「接続する」を押します。",
            ],
            "fields": [
                {"name": "moneyforward_client_id", "label": "Client ID", "secret": False, "optional": False},
                {"name": "moneyforward_client_secret", "label": "Client Secret", "secret": True, "optional": False},
            ],
        },
        {
            "id": "google",
            "label": "Gmail・Google カレンダー",
            "advanced": True,
            "restart_required": False,
            "key_url": "https://console.cloud.google.com/apis/credentials",
            "steps": [
                "Google Cloud Console でプロジェクトを作り、Gmail API と Google Calendar API を有効にします。",
                "「OAuth 同意画面」を「外部」で作り、自分の Google アカウントをテストユーザーに追加します。",
                "「認証情報」→「OAuth クライアント ID」で、種類に「デスクトップアプリ」を選んで作ります。",
                "表示されたクライアント ID とクライアント シークレットを貼り付けて保存し、「接続する」を押します。",
            ],
            "fields": [
                {"name": "google_oauth_client_id", "label": "クライアント ID", "secret": False, "optional": False},
                {"name": "google_oauth_client_secret", "label": "クライアント シークレット", "secret": True, "optional": False},
            ],
        },
    ]


def check_line_token(token: str, transport: httpx.BaseTransport | None = None) -> bool | None:
    """LINE のチャネルアクセストークンを確かめる。True: 使える / False: 使えない / None: 確かめられない。"""
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            response = client.get("https://api.line.me/v2/bot/info", headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return True
    if response.status_code in (400, 401, 403):
        return False
    return None
