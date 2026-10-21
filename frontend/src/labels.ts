export const TOOL_LABELS: Record<string, string> = {
  web_search: "ウェブ検索",
  fetch_page: "ページを読む",
  browser_navigate: "ページを開く",
  browser_snapshot: "画面のテキスト",
  browser_click: "クリック",
  browser_type: "入力",
  browser_screenshot: "スクリーンショット",
  save_memory: "記憶に残す",
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
