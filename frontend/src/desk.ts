// 「ヤタの机」に並べる仕事とあいさつを、ルーティンと実行履歴から組み立てる。
import { toolLabel } from "./labels"
import type { Routine, RoutineConfirmation } from "./types"

export type DeskTaskKind = "wait" | "doing" | "next" | "done" | "failed"

export type DeskTask = {
  key: string
  kind: DeskTaskKind
  title: string
  sub: string
  conversationId?: string
  confirmation?: RoutineConfirmation
}

const TIME_ZONE = "Asia/Tokyo"

function dayKey(date: Date): string {
  return new Intl.DateTimeFormat("ja-JP", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(date)
}

/** 「今日 18:00」「明日 8:00」「昨日 7:45」「10/24 9:00」のように短く表す。 */
export function formatWhen(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ""
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  const time = new Intl.DateTimeFormat("ja-JP", { timeZone: TIME_ZONE, hour: "numeric", minute: "2-digit" }).format(date)
  const oneDay = 24 * 60 * 60 * 1000
  const day = dayKey(date)
  if (day === dayKey(now)) return `今日 ${time}`
  if (day === dayKey(new Date(now.getTime() + oneDay))) return `明日 ${time}`
  if (day === dayKey(new Date(now.getTime() - oneDay))) return `昨日 ${time}`
  const md = new Intl.DateTimeFormat("ja-JP", { timeZone: TIME_ZONE, month: "numeric", day: "numeric" }).format(date)
  return `${md} ${time}`
}

export function buildDeskTasks(routines: Routine[], options: { chatBusy?: boolean; now?: Date } = {}): DeskTask[] {
  const now = options.now ?? new Date()
  const waiting: DeskTask[] = []
  const doing: DeskTask[] = []
  const upcoming: (DeskTask & { at: number })[] = []
  const finished: (DeskTask & { at: number })[] = []

  if (options.chatBusy) {
    doing.push({ key: "chat", kind: "doing", title: "頼まれたことに取りかかっています", sub: "作業中" })
  }

  for (const routine of routines) {
    const pending = routine.pending_confirmation
    if (pending) {
      waiting.push({
        key: `wait-${pending.request_id}`,
        kind: "wait",
        title: routine.name,
        sub: `${toolLabel(pending.tool)}の許可を待っています`,
        conversationId: routine.conversation_id,
        confirmation: pending,
      })
    } else if (routine.last_status === "running") {
      doing.push({
        key: `doing-${routine.id}`,
        kind: "doing",
        title: routine.name,
        sub: "作業中",
        conversationId: routine.conversation_id,
      })
    }

    if (routine.enabled && routine.next_run) {
      const at = new Date(routine.next_run).getTime()
      if (!Number.isNaN(at)) {
        upcoming.push({
          key: `next-${routine.id}`,
          kind: "next",
          title: routine.name,
          sub: `${formatWhen(routine.next_run, now)}・${routine.schedule_label}`,
          conversationId: routine.conversation_id,
          at,
        })
      }
    }

    for (const run of routine.recent_runs) {
      if (!run.finished_at || run.status === "running" || run.status === "waiting_confirmation") continue
      const at = new Date(run.finished_at).getTime()
      if (Number.isNaN(at)) continue
      const failed = run.status === "error"
      finished.push({
        key: `run-${run.id}`,
        kind: failed ? "failed" : "done",
        title: routine.name,
        sub: failed ? `うまくいきませんでした・${formatWhen(run.finished_at, now)}` : formatWhen(run.finished_at, now),
        conversationId: routine.conversation_id,
        at,
      })
    }
  }

  upcoming.sort((a, b) => a.at - b.at)
  finished.sort((a, b) => b.at - a.at)
  const strip = ({ at: _at, ...task }: DeskTask & { at: number }): DeskTask => task
  return [...waiting, ...doing, ...upcoming.slice(0, 3).map(strip), ...finished.slice(0, 3).map(strip)]
}

function hello(now: Date): string {
  const hour = Number(new Intl.DateTimeFormat("en-US", { timeZone: TIME_ZONE, hour: "numeric", hourCycle: "h23" }).format(now))
  if (hour >= 4 && hour < 11) return "おはよう。"
  if (hour >= 11 && hour < 18) return "こんにちは。"
  return "こんばんは。"
}

/** 机のいちばん上で、カラスが今の状況をひとことで伝える。 */
export function buildGreeting(tasks: DeskTask[], now: Date = new Date()): { hello: string; line: string } {
  const waiting = tasks.filter((task) => task.kind === "wait").length
  const doing = tasks.find((task) => task.kind === "doing")
  const next = tasks.find((task) => task.kind === "next")
  let line = "なにか頼んでみて。"
  if (waiting > 0) line = `${waiting}件、きみの返事を待ってるよ。`
  else if (doing) line = `いま「${doing.title}」をやってるよ。`
  else if (next) line = `次は ${next.sub.split("・")[0]} に「${next.title}」をやるね。`
  return { hello: hello(now), line }
}
