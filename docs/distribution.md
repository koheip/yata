# ヤタを配る（Windows）

ヤタを「ボタン一つで入れられるアプリ」として配るための手順です。
配り方は2つあります。

| 配り方 | ファイル | 署名 | 入れるときの警告 |
| --- | --- | --- | --- |
| Microsoft Store | `Yata-<版>.msix` | Store が無料でしてくれる | 出ない |
| GitHub・自分のサイト | `Yata-Setup-<版>.exe` | なし | 「Windows によって PC が保護されました」が出る（「詳細情報」→「実行」で入る） |

どちらも中身は同じです。会話や設定は `%LOCALAPPDATA%\Yata` に保存され、アンインストールしても消えません。
ブラウザ操作には、Windows に最初から入っている Edge（なければ Chrome）を使います。Chromium を別に入れる必要はありません。

## 1. 配布ファイルを作る（自動）

GitHub Actions（`.github/workflows/release.yml`）が Windows の上で作ります。

1. `pyproject.toml` の `version` を上げてコミットする。
2. タグを付けて push する。
   ```
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. GitHub の Actions タブで `release` が緑になるのを待つ（15分くらい）。
   テスト → 画面のビルド → PyInstaller → 起動チェック → Setup.exe と MSIX、の順に進みます。
4. Releases に **下書き** ができるので、中身を確かめてから「Publish release」を押す。

タグなしで試したいときは、Actions タブの `release` →「Run workflow」で動かせます（ファイルは Artifacts に出ます）。

> リポジトリが非公開のままだと、Releases のファイルは他の人がダウンロードできません。
> 一般の人に配るときは、リポジトリを公開するか、Setup.exe を自分のサイトなどに置いてください。

## 2. Microsoft Store に出す（初回だけ準備がいる）

1. [Partner Center](https://partner.microsoft.com/dashboard) で開発者アカウントを作る（個人は無料）。
2. 「アプリとゲーム」→「新しい製品」→「MSIX または PWA アプリ」で、名前「ヤタ」を予約する。
3. 製品の「製品 ID」ページ（Product identity）に出る3つの値を、`packaging/msix/AppxManifest.xml` に書きこむ。
   - `Package/Identity/Name` → `Identity="..."` の `Name`
   - `Package/Identity/Publisher` → `Publisher="CN=..."`
   - `Package/Properties/PublisherDisplayName` → `<PublisherDisplayName>`
4. コミットしてタグを push し、できた `Yata-<版>.msix` を Partner Center の「パッケージ」にアップロードする。
5. ストアの説明文・スクリーンショット・年齢区分・プライバシーポリシーの URL を入れて申請する。
   - `runFullTrust`（ふつうのデスクトップアプリとして動く権限）を使うので、申請時に理由を聞かれます。
     「ローカルでサーバーを動かし、ブラウザ（Edge）で画面を表示するため」と書けば大丈夫です。
6. 審査は数日です。通ると Store に出て、利用者は「入手」ボタンだけで入れられます。

## 3. 手元で作るとき

```powershell
npm --prefix frontend run build
uv run --with pyinstaller pyinstaller packaging/yata.spec --noconfirm   # dist\Yata\Yata.exe
iscc packaging\windows\yata.iss                                         # dist\Yata-Setup-0.1.0.exe（Inno Setup 6 が必要）
```

## ファイルの場所

| ファイル | 役目 |
| --- | --- |
| `src/yata/desktop.py` | アプリの入口。データの置き場所、二重起動の防止、ログ |
| `packaging/yata_app.py` | PyInstaller の入口 |
| `packaging/yata.spec` | PyInstaller の設定（画面 `frontend/dist` も中に入れる） |
| `packaging/windows/yata.iss` | Setup.exe を作る Inno Setup の設定（管理者権限なしで入る） |
| `packaging/windows/yata.ico`, `version_info.txt` | exe のアイコンとバージョン情報 |
| `packaging/msix/AppxManifest.xml`, `Assets/` | Store 用 MSIX の設定とタイル画像 |
| `.github/workflows/release.yml` | 配布ファイルを自動で作る |

## あとでやるとよいこと

- 署名：Setup.exe の警告を消すには、コード署名証明書（OV、年5万円くらい〜）が必要です。Store だけなら不要です。
- 自動更新：今は新しい版を入れ直す方式です。Store 版は Store が自動で更新します。
- Mac 版：`desktop.py` は Mac の保存場所にも対応済みです。配るには `.app` 化と Apple の公証（年 $99）が必要です。
