import { ExternalLink, RefreshCw, WifiOff } from "lucide-react"
import { useId, useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "cn"
import type { LocalServer, LocalSetup, OllamaPull } from "../types"

const inputClass =
  "h-11 min-w-0 w-full rounded-xl border border-input bg-background px-3.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"

async function attempt(action: () => Promise<void>, setBusy: (v: boolean) => void, setError: (v: string | null) => void) {
  setBusy(true)
  setError(null)
  try {
    await action()
  } catch (err) {
    setError(err instanceof Error ? err.message : "うまくいきませんでした。")
  } finally {
    setBusy(false)
  }
}

function Status({ running }: { running: boolean }) {
  return running ? (
    <span className="shrink-0 rounded-full bg-[#E4F1EA] px-2.5 py-0.5 text-xs font-bold text-[#1F5A3D]">動いています</span>
  ) : (
    <span className="shrink-0 rounded-full bg-secondary px-2.5 py-0.5 text-xs font-bold text-muted-foreground">止まっています</span>
  )
}

type ServerCardProps = {
  server: LocalServer
  onRefresh: () => Promise<void>
  onChoose: (model: string) => Promise<void>
  /** Ollama のときだけ。モデルを画面から入れる。 */
  ollama?: {
    recommended: { name: string; note: string }[]
    sizes: Record<string, number | null>
    pull: OllamaPull
    onPull: (model: string) => Promise<void>
  }
}

/** パソコンの中の AI（Ollama・LM Studio など）1つぶんの案内と、使うモデルの選択。 */
export function LocalServerCard({ server, onRefresh, onChoose, ollama }: ServerCardProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState("")
  const selectId = useId()
  const chosen = server.model && server.models.includes(server.model) ? server.model : ""
  const missing = server.model && !server.models.includes(server.model) ? server.model : null
  const pulling = ollama?.pull.state === "running"
  const percent =
    ollama?.pull.total && ollama.pull.completed ? Math.min(100, Math.round((ollama.pull.completed / ollama.pull.total) * 100)) : null
  const label = (model: string) => {
    const size = ollama?.sizes[model]
    return size ? `${model}（${size} GB）` : model
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="font-bold">{server.label}</p>
        <Status running={server.running} />
      </div>
      {server.running ? null : (
        <p className="text-[0.8rem] leading-5 text-muted-foreground">キーもお金もいりません。会話がパソコンの外に出ません。{server.how}</p>
      )}

      {server.running && server.models.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={selectId} className="text-sm font-bold">
            使うモデル
          </label>
          <select
            id={selectId}
            className="h-11 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
            value={chosen}
            disabled={busy}
            onChange={(event) => void attempt(() => onChoose(event.target.value), setBusy, setError)}
          >
            <option value="">おまかせ（{server.id === "ollama" ? "入っている最初のモデル" : "いま読み込まれているモデル"}）</option>
            {server.models.map((model) => (
              <option key={model} value={model}>
                {label(model)}
              </option>
            ))}
          </select>
          {missing ? (
            <p className="text-[0.8rem] text-muted-foreground">設定にある「{missing}」は入っていないので、選び直してください。</p>
          ) : null}
        </div>
      ) : null}
      {server.running && server.models.length === 0 ? (
        <p className="text-[0.8rem] text-muted-foreground">まだモデルが入っていません。{ollama ? "下から入れられます。" : "アプリでモデルを読み込んでください。"}</p>
      ) : null}

      {ollama && server.running ? (
        <div className="flex flex-col gap-2 rounded-xl bg-secondary/60 px-3 py-3">
          <p className="text-sm font-bold">モデルを入れる</p>
          <p className="text-[0.8rem] leading-5 text-muted-foreground">
            どれも検索や連携を使えるモデルです。数 GB をダウンロードするので、時間がかかります。
          </p>
          <ul className="flex flex-col gap-1.5">
            {ollama.recommended.map((item) => {
              const installed = server.models.includes(item.name)
              return (
                <li key={item.name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="min-w-0">
                    <span className="font-bold">{item.name}</span>
                    <span className="block text-xs text-muted-foreground">{item.note}</span>
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    variant={installed ? "ghost" : "outline"}
                    className="shrink-0 rounded-lg"
                    disabled={busy || pulling || installed}
                    onClick={() => void attempt(() => ollama.onPull(item.name), setBusy, setError)}
                  >
                    {installed ? "入っています" : "入れる"}
                  </Button>
                </li>
              )
            })}
          </ul>
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              if (name.trim()) void attempt(() => ollama.onPull(name.trim()), setBusy, setError)
            }}
          >
            <input
              aria-label="ほかのモデルの名前"
              className={inputClass}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="ほかのモデル（例: gemma3:12b）"
              spellCheck={false}
            />
            <Button type="submit" variant="outline" className="h-11 shrink-0 rounded-xl" disabled={busy || pulling || !name.trim()}>
              入れる
            </Button>
          </form>
          {pulling ? (
            <div role="status" className="flex flex-col gap-1">
              <p className="text-[0.8rem]">
                {ollama.pull.model}：{ollama.pull.message}
                {percent !== null ? `（${percent}%）` : ""}
              </p>
              <div className="h-2 overflow-hidden rounded-full bg-background">
                <div className="h-full rounded-full bg-[#3B2560] transition-[width]" style={{ width: `${percent ?? 5}%` }} />
              </div>
            </div>
          ) : null}
          {ollama.pull.state === "done" && !pulling ? <p className="text-[0.8rem] text-[#1F5A3D]">{ollama.pull.message}</p> : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" className="h-10 gap-1.5 rounded-xl" disabled={busy} onClick={() => void attempt(onRefresh, setBusy, setError)}>
          <RefreshCw className="size-4" />
          確かめ直す
        </Button>
        {server.running ? null : (
          <a
            href={server.site}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-input bg-background px-4 text-sm font-bold text-foreground no-underline hover:bg-muted"
          >
            入手する
            <ExternalLink className="size-4" aria-hidden="true" />
          </a>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        つなぐ先：<code className="break-all">{server.url}</code>
      </p>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  )
}

type CustomProps = {
  setup: LocalSetup
  onSave: (body: { base_url: string; model: string; api_key: string }) => Promise<void>
  onRemove: () => Promise<void>
}

/** その他の OpenAI 互換サーバーの URL などを入れる。 */
export function CustomServerForm({ setup, onSave, onRemove }: CustomProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [url, setUrl] = useState(setup.custom.base_url)
  const [model, setModel] = useState(setup.custom.model)
  const [key, setKey] = useState("")
  const ids = useId()
  return (
    <form
      className="flex flex-col gap-3 rounded-2xl border border-border bg-card px-4 py-3"
      onSubmit={(event) => {
        event.preventDefault()
        void attempt(async () => {
          await onSave({ base_url: url, model, api_key: key })
          setKey("")
        }, setBusy, setError)
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-bold">その他の OpenAI 互換サーバー</p>
        {setup.custom.base_url ? <Status running={setup.custom.running} /> : null}
      </div>
      <p className="text-[0.8rem] leading-5 text-muted-foreground">text-generation-webui、KoboldCpp、別のパソコンのサーバーなども使えます。</p>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${ids}-url`} className="text-sm font-bold">URL</label>
        <input id={`${ids}-url`} className={inputClass} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:5000/v1" spellCheck={false} />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${ids}-model`} className="text-sm font-bold">モデル名（空なら読み込まれているもの）</label>
        <input id={`${ids}-model`} className={inputClass} value={model} onChange={(e) => setModel(e.target.value)} spellCheck={false} />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${ids}-key`} className="text-sm font-bold">
          API キー（いる場合だけ）{setup.custom.has_key ? "：保存済み" : ""}
        </label>
        <input id={`${ids}-key`} type="password" autoComplete="off" className={inputClass} value={key} onChange={(e) => setKey(e.target.value)} spellCheck={false} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" className="h-10 rounded-xl px-5 font-bold" disabled={busy || !url.trim()}>
          保存する
        </Button>
        {setup.custom.base_url ? (
          <Button
            type="button"
            variant="ghost"
            className="h-10 rounded-xl"
            disabled={busy}
            onClick={() =>
              void attempt(async () => {
                await onRemove()
                setUrl("")
                setModel("")
              }, setBusy, setError)
            }
          >
            外す
          </Button>
        ) : null}
      </div>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </form>
  )
}

/** 完全オフラインモードの切り替え。 */
export function OfflineToggle({ offline, onChange }: { offline: boolean; onChange: (enabled: boolean) => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div className={cn("rounded-2xl border px-4 py-3", offline ? "border-[#3B2560] bg-[#F1ECF8]" : "border-border bg-card")}>
      <label className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 size-5 shrink-0 accent-[#3B2560]"
          checked={offline}
          disabled={busy}
          onChange={(event) => void attempt(() => onChange(event.target.checked), setBusy, setError)}
        />
        <span className="flex flex-col gap-0.5">
          <span className="flex items-center gap-1.5 text-sm font-bold">
            <WifiOff className="size-4" aria-hidden="true" />
            完全オフラインモード
          </span>
          <span className="text-[0.8rem] leading-5 text-muted-foreground">
            パソコンの中の AI だけを使い、ネット検索・ブラウザ操作・外部の連携・LINE への通知を止めます。
          </span>
        </span>
      </label>
      {error ? <p role="alert" className="mt-2 text-sm text-destructive">{error}</p> : null}
    </div>
  )
}
