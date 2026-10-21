# エージェント向けルール

まず [CLAUDE.md](CLAUDE.md) を読み、従ってください（follow CLAUDE.md）。

- Yata は日本語を第一にした汎用の個人用 AI アシスタントです。
- Python/FastAPI は uv で管理し、起動は `uv run yata`、既定は `127.0.0.1:8741` です。
- UI は `frontend/` の React・TypeScript・Tailwind CSS です。
- 構成は `src/yata/`（`connectors/`、`tools/`、`routines/`）、`frontend/src/`、`tests/` です。
- 検証は `uv run pytest`、UI ビルドは `cd frontend && npm run build`（`tsc -b && vite build`）です。
- `Risk.READ` と `Risk.WRITE` は既定で確認不要、`Risk.MUTATE` と `Risk.EXTERNAL` は ConfirmationGate で実行前に確認します。
- 外部に変更や送信を行うアクションは常に確認が必要です。ルーティンもゲートを迂回してはいけません。
- 秘密情報は `.env` で管理し、`.env` と `data/` は絶対にコミットしないでください。
- リポジトリ名を変更せず、差分を小さく保ち、必要なファイルだけを読んでください。
- パスは実物で確認し、無関係な変更や利用者の変更の上書きを避けてください。
- 方向性と実装段階は [ROADMAP.md](ROADMAP.md) を参照してください。
