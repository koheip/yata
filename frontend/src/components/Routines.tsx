import { useState, type FormEvent } from "react"
import { Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import type { Routine, RoutinePreset } from "../types"

type RoutinesProps = {
  routines: Routine[]
  presets: RoutinePreset[]
  onCreate: (input: { name: string; prompt: string; preset?: string; schedule?: string }) => Promise<void>
  onToggle: (routine: Routine) => Promise<void>
  onToggleLine: (routine: Routine) => Promise<void>
  onDelete: (routine: Routine) => Promise<void>
  onOpen: (conversationId: string) => void
}

const FALLBACK_PRESETS: RoutinePreset[] = [
  { id: "morning", label: "毎朝 8:00", schedule: "0 8 * * *", schedule_kind: "cron" },
  { id: "hourly", label: "毎時 0分", schedule: "0 * * * *", schedule_kind: "cron" },
  { id: "monday", label: "毎週月曜 9:00", schedule: "0 9 * * 1", schedule_kind: "cron" },
  { id: "weekday", label: "平日 8:30", schedule: "30 8 * * 1-5", schedule_kind: "cron" },
  { id: "monthly25", label: "毎月25日 9:00", schedule: "0 9 25 * *", schedule_kind: "cron" },
]

/** 日本の小さな会社・個人事業でよく使う決まった仕事。押すと入力欄が埋まる。 */
const TEMPLATES = [
  {
    name: "朝の未対応まとめ",
    preset: "weekday",
    prompt: "Chatwork の未読とメンション、Backlog で自分が担当の未完了の課題、今日の予定をまとめて。急ぎのものを先に、返事が必要なものには返信の下書きもつけて。今日が祝日ならそう伝えて。",
  },
  {
    name: "今週の段取り",
    preset: "monday",
    prompt: "今週の予定と、期限が今週の課題・タスクを曜日ごとに並べて。祝日があれば jp_calendar で確かめて書いて。",
  },
  {
    name: "月末の請求書チェック",
    preset: "monthly25",
    prompt: "今月の請求書（freee・マネーフォワード クラウド請求書）を確かめて、毎月請求している取引先でまだ作っていないところがあれば教えて。支払期限は月末締め翌月末払いとして、jp_calendar で土日・祝日を確かめて書いて。",
  },
  {
    name: "業界ニュース",
    preset: "morning",
    prompt: "自分の仕事に関係するきのうからのニュースを3つ、出典の URL つきで短くまとめて。",
  },
]

function formatWhen(iso: string | null): string {
  if (!iso) return "まだ実行していません"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function statusLabel(status: string | null): string | null {
  if (status === "waiting_confirmation") return "確認待ち"
  if (status === "error") return "失敗"
  if (status === "running") return "実行中"
  return null
}

export function RoutinesSection({ routines, presets, onCreate, onToggle, onToggleLine, onDelete, onOpen }: RoutinesProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [prompt, setPrompt] = useState("")
  const [preset, setPreset] = useState("morning")
  const [cron, setCron] = useState("0 8 * * *")
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const options = presets.length > 0 ? presets : FALLBACK_PRESETS

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onCreate(
        preset === "custom"
          ? { name: name.trim(), prompt: prompt.trim(), schedule: cron.trim() }
          : { name: name.trim(), prompt: prompt.trim(), preset },
      )
      setName("")
      setPrompt("")
      setPreset("morning")
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "登録に失敗しました。")
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="flex flex-col">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-base font-bold">ルーティン</h3>
        <Button type="button" size="xs" variant="outline" onClick={() => setOpen(true)}>
          追加
        </Button>
      </div>
      {routines.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          まだありません。毎朝・平日・毎週月曜・毎月25日などに登録できます。チャットに「毎朝8時にニュースを要約して」と送っても登録されます。
        </p>
      ) : (
        <ul className="space-y-3">
          {routines.map((routine) => {
            const badge = statusLabel(routine.last_status)
            return (
              <li key={routine.id} className="text-sm">
                <div className="flex items-start gap-2">
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => onOpen(routine.conversation_id)}
                  >
                    <p className="truncate font-medium">{routine.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {routine.enabled ? routine.schedule_label : "停止中"}
                    </p>
                  </button>
                  {badge ? (
                    <Badge variant={routine.last_status === "error" ? "destructive" : "secondary"}>{badge}</Badge>
                  ) : null}
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {routine.last_snippet || "結果はまだありません。"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">前回 {formatWhen(routine.last_run)}</p>
                <div className="mt-1 flex gap-1">
                  <Button type="button" size="xs" variant="ghost" onClick={() => void onToggle(routine)}>
                    {routine.enabled ? "停止" : "再開"}
                  </Button>
                  <Button type="button" size="xs" variant="ghost" onClick={() => void onToggleLine(routine)}>
                    {routine.notify_line ? "LINE通知: オン" : "LINE通知: オフ"}
                  </Button>
                  <Button
                    type="button"
                    size="icon-xs"
                    variant="ghost"
                    aria-label={`${routine.name} を削除`}
                    onClick={() => void onDelete(routine)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={(event) => void submit(event)}>
            <DialogHeader>
              <DialogTitle>ルーティンを追加</DialogTitle>
              <DialogDescription>
                サーバーが動いていれば、ブラウザを閉じていても実行され、結果は会話に残ります。
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-3">
              <div className="flex flex-wrap gap-1.5" aria-label="よく使うルーティン">
                {TEMPLATES.map((template) => (
                  <Button
                    key={template.name}
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() => {
                      setName(template.name)
                      setPrompt(template.prompt)
                      if (options.some((option) => option.id === template.preset)) setPreset(template.preset)
                    }}
                  >
                    {template.name}
                  </Button>
                ))}
              </div>
              <label className="grid gap-1 text-sm">
                名前
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  maxLength={80}
                  placeholder="朝のニュース"
                  className="h-9 rounded-lg border border-input bg-card px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
                />
              </label>
              <label className="grid gap-1 text-sm">
                指示
                <Textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  required
                  maxLength={8000}
                  placeholder="今日のニュースを3つ、出典のURLつきで要約して"
                />
              </label>
              <label className="grid gap-1 text-sm">
                いつ
                <select
                  value={preset}
                  onChange={(event) => setPreset(event.target.value)}
                  aria-label="実行時刻"
                  className="h-9 rounded-lg border border-input bg-card px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
                >
                  {options.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                  <option value="custom">cron を自分で書く</option>
                </select>
              </label>
              {preset === "custom" ? (
                <label className="grid gap-1 text-sm">
                  cron（分 時 日 月 曜日。曜日は 0 が日曜、1 が月曜）
                  <input
                    value={cron}
                    onChange={(event) => setCron(event.target.value)}
                    required
                    placeholder="0 8 * * *"
                    className="h-9 rounded-lg border border-input bg-card px-2 font-mono text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
                  />
                </label>
              ) : null}
              {error ? (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              ) : null}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                キャンセル
              </Button>
              <Button type="submit" disabled={saving}>
                登録する
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  )
}
