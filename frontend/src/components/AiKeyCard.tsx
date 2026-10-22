import { ExternalLink, KeyRound } from "lucide-react"
import { useId, useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "cn"
import type { AiProvider } from "../types"

type AiKeyCardProps = {
  provider: AiProvider
  /** 机の「はじめに」で使うときは、説明を大きめに出す。 */
  featured?: boolean
  onConnect: (providerId: string, key: string) => Promise<{ message: string }>
  onDisconnect: (providerId: string) => Promise<void>
}

/** API キーを貼り付けて AI をつなぐカード。キーの取り方も、その場で案内する。 */
export function AiKeyCard({ provider, featured, onConnect, onDisconnect }: AiKeyCardProps) {
  const [editing, setEditing] = useState(Boolean(featured) && !provider.configured)
  const [key, setKey] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const inputId = `ai-key-${provider.id}-${useId()}`

  async function connect() {
    if (!key.trim()) {
      setError("キーを貼り付けてください。")
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await onConnect(provider.id, key)
      setKey("")
      setEditing(false)
      setNotice(result.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : "つなげませんでした。")
    } finally {
      setBusy(false)
    }
  }

  async function disconnect() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await onDisconnect(provider.id)
      setEditing(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "外せませんでした。")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={cn("rounded-2xl border bg-card px-4 py-3", featured ? "border-[#E3DAEE] p-5 shadow-[0_4px_16px_rgba(34,25,51,0.06)]" : "border-border")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={cn("font-bold", featured ? "text-lg" : "")}>{provider.label}</p>
        {provider.configured ? (
          <span className="rounded-full bg-[#E4F1EA] px-2.5 py-0.5 text-xs font-bold text-[#1F5A3D]">つながっています</span>
        ) : (
          <span className="rounded-full bg-[#FDF0D5] px-2.5 py-0.5 text-xs font-bold text-[#6B4A06]">{provider.badge}</span>
        )}
      </div>

      {notice ? (
        <p role="status" className="mt-2 text-sm text-[#1F5A3D]">
          {notice}
        </p>
      ) : null}

      {editing ? (
        <form
          className="mt-3 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void connect()
          }}
        >
          <ol className="flex flex-col gap-1.5 text-sm leading-6">
            {provider.steps.map((step, index) => (
              <li key={step} className="flex gap-2">
                <span aria-hidden="true" className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-bold">
                  {index + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
          <a
            href={provider.key_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center justify-center gap-2 self-start rounded-xl border border-input bg-background px-4 text-sm font-bold text-foreground no-underline hover:bg-muted"
          >
            キーを作るページを開く
            <ExternalLink className="size-4" aria-hidden="true" />
          </a>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={inputId} className="text-sm font-bold">
              コピーしたキー
            </label>
            <div className="flex gap-2">
              <input
                id={inputId}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={key}
                onChange={(event) => setKey(event.target.value)}
                placeholder="ここに貼り付け"
                className="h-11 min-w-0 flex-1 rounded-xl border border-input bg-background px-3.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
              />
              <Button type="submit" className="h-11 gap-1.5 rounded-xl px-5 font-bold" disabled={busy}>
                <KeyRound className="size-4" />
                {busy ? "確かめています…" : "つなぐ"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">キーはこの PC の中だけに保存し、画面には表示しません。</p>
          </div>
          {provider.configured || !featured ? (
            <Button type="button" variant="ghost" className="h-10 self-start rounded-xl" onClick={() => setEditing(false)}>
              やめる
            </Button>
          ) : null}
        </form>
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          {provider.configured ? (
            <Button type="button" variant="outline" className="h-10 rounded-xl px-4" onClick={() => setEditing(true)}>
              キーを入れ直す
            </Button>
          ) : (
            <Button type="button" className="h-10 rounded-xl px-4 font-bold" onClick={() => setEditing(true)}>
              キーを入れてつなぐ
            </Button>
          )}
          {provider.source === "app" ? (
            <Button type="button" variant="ghost" className="h-10 rounded-xl px-4 text-destructive" disabled={busy} onClick={() => void disconnect()}>
              外す
            </Button>
          ) : null}
          {provider.source === "env" ? <p className="self-center text-xs text-muted-foreground">.env のキーを使っています</p> : null}
        </div>
      )}

      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}
