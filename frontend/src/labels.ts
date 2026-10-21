export const TOOL_LABELS: Record<string, string> = {
  freee_list_companies: "freee 事業所一覧",
  freee_list_account_items: "freee 勘定科目一覧",
  freee_list_deals: "freee 取引一覧",
  freee_list_invoices: "freee 請求書一覧",
  freee_get_trial_balance: "freee 損益試算表",
  freee_create_expense_deal: "freee 支出取引を登録",
  web_search: "ウェブ検索",
  fetch_page: "ページを読む",
  browser_navigate: "ページを開く",
  browser_snapshot: "画面のテキスト",
  browser_click: "クリック",
  browser_type: "入力",
  browser_screenshot: "スクリーンショット",
  save_memory: "記憶に残す",
  gmail_search: "Gmail検索",
  gmail_read: "メールを読む",
  gmail_create_draft: "下書き作成",
  gmail_send_email: "メール送信",
  calendar_list_events: "予定を調べる",
  calendar_check_free_busy: "空き時間を確認",
  calendar_create_event: "予定を作成",
  calendar_update_event: "予定を更新",
  calendar_delete_event: "予定を削除",
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}

export function summarizeArguments(args: Record<string, unknown>): string {
  if (typeof args.query === "string") return args.query
  if (typeof args.url === "string") return args.url
  if (typeof args.selector === "string" && typeof args.text === "string") {
    return `${args.selector} ← ${args.text}`
  }
  if (typeof args.selector === "string") return args.selector
  if (typeof args.key === "string") return `${args.key}: ${String(args.value ?? "")}`
  return ""
}

export const SUGGESTIONS = [
  "今日のAIの話題を3つ、出典のURLつきで調べて",
  "https://www.python.org/ を読んで、Pythonが何のための言語か短くまとめて",
  "覚えて: goal は ZEN大学でAIエンジニアになること",
]
