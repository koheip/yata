import { ExternalLink } from "lucide-react"
import { useId, useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "cn"
import type { Connector, ConnectorSetup, ConnectorSetupList } from "../types"

type ConnectorsProps = {
  connectors: Connector[]
  setups: ConnectorSetupList | null
  onConnect: (connector: Connector) => void
  onDisconnect: (connector: Connector) => Promise<void>
  onSave: (setupId: string, values: Record<string, string>) => Promise<{ message: string }>
  onRemove: (setupId: string) => Promise<void>
}

const STATUS: Record<Connector["status"], { label: string; className: string }> = {
  connected: { label: "接続済み", className: "bg-[#E4F1EA] text-[#1F5A3D]" },
  not_connected: { label: "未接続", className: "bg-[#FDF0D5] text-[#6B4A06]" },
  not_configured: { label: "未設定", className: "bg-muted text-muted-foreground" },
}

function overall(items: Connector[]): Connector["status"] {
  if (items.length > 0 && items.every((item) => item.status === "connected")) return "connected"
  if (items.some((item) => item.status !== "not_configured")) return "not_connected"
  return "not_configured"
}

/** 設定パネルの「連携」。サービスごとに状態を見せ、その場でトークンを貼って設定できる。 */
export function ConnectorsSection({ connectors, setups, onConnect, onDisconnect, onSave, onRemove }: ConnectorsProps) {
  if (!setups) return <p className="text-sm text-muted-foreground">読み込んでいます…</p>
  const groups = setups.setups.map((setup) => ({
    setup,
    items: connectors.filter((connector) => setups.connector_to_setup[connector.id] === setup.id),
  }))
  return (
    <div className="flex flex-col gap-2.5">
      {groups.map((group) => (
        <ConnectorCard key={`${group.setup.id}-${group.setup.configured}`} {...group} onConnect={onConnect} onDisconnect={onDisconnect} onSave={onSave} onRemove={onRemove} />
      ))}
    </div>
  )
}

type CardProps = {
  setup: ConnectorSetup
  items: Connector[]
  onConnect: (connector: Connector) => void
  onDisconnect: (connector: Connector) => Promise<void>
  onSave: (setupId: string, values: Record<string, string>) => Promise<{ message: string }>
  onRemove: (setupId: string) => Promise<void>
}

function ConnectorCard({ setup, items, onConnect, onDisconnect, onSave, onRemove }: CardProps) {
  const [open, setOpen] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const baseId = useId()
  const status = STATUS[overall(items)]
  const oauth = items.filter((item) => item.auth_kind === "oauth")

  async function save() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await onSave(setup.id, values)
      setValues({})
      setOpen(false)
      setNotice(result.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存できませんでした。")
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await onRemove(setup.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "外せませんでした。")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-card px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="font-bold">{setup.label}</p>
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", status.className)}>{status.label}</span>
      </div>
      {items.map((item) => (item.note ? <p key={item.id} className="mt-1 text-[0.8rem] text-muted-foreground">{item.note}</p> : null))}

      {setup.configured && oauth.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1.5">
          {oauth.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-2 text-sm">
              <span>{item.label}</span>
              {item.status === "connected" ? (
                <Button type="button" variant="outline" className="h-10 rounded-xl px-4" onClick={() => void onDisconnect(item)}>
                  接続を外す
                </Button>
              ) : (
                <Button type="button" className="h-10 rounded-xl px-4 font-bold" onClick={() => onConnect(item)}>
                  接続する
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {notice ? (
        <p role="status" className="mt-2 text-sm text-[#1F5A3D]">
          {notice}
        </p>
      ) : null}

      {open ? (
        <form
          className="mt-3 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <ol className="flex flex-col gap-1.5 text-sm leading-6">
            {setup.steps.map((step, index) => (
              <li key={step} className="flex gap-2">
                <span aria-hidden="true" className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-bold">
                  {index + 1}
                </span>
                <span className="break-all">{step}</span>
              </li>
            ))}
          </ol>
          <a
            href={setup.key_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center justify-center gap-2 self-start rounded-xl border border-input bg-background px-4 text-sm font-bold text-foreground no-underline hover:bg-muted"
          >
            設定のページを開く
            <ExternalLink className="size-4" aria-hidden="true" />
          </a>
          {setup.fields.map((field) => {
            const id = `${baseId}-${field.name}`
            return (
              <div key={field.name} className="flex flex-col gap-1.5">
                <label htmlFor={id} className="text-sm font-bold">
                  {field.label}
                </label>
                <input
                  id={id}
                  type={field.secret ? "password" : "text"}
                  autoComplete="off"
                  spellCheck={false}
                  value={values[field.name] ?? ""}
                  onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                  placeholder={field.configured ? "設定済み（変えるときだけ入れてください）" : "ここに貼り付け"}
                  className="h-11 rounded-xl border border-input bg-background px-3.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
                />
              </div>
            )
          })}
          <p className="text-xs text-muted-foreground">入れた値はこの PC の中だけに保存し、画面には表示しません。</p>
          <div className="flex gap-2">
            <Button type="submit" className="h-11 rounded-xl px-5 font-bold" disabled={busy}>
              {busy ? "確かめています…" : "保存する"}
            </Button>
            <Button type="button" variant="ghost" className="h-11 rounded-xl" disabled={busy} onClick={() => setOpen(false)}>
              やめる
            </Button>
          </div>
        </form>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={setup.configured ? "outline" : "default"}
            className={cn("h-10 rounded-xl px-4", setup.configured ? "" : "font-bold")}
            onClick={() => setOpen(true)}
          >
            {setup.configured ? "設定を変える" : "設定する"}
          </Button>
          {setup.from_app ? (
            <Button type="button" variant="ghost" className="h-10 rounded-xl px-4 text-destructive" disabled={busy} onClick={() => void remove()}>
              外す
            </Button>
          ) : null}
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
