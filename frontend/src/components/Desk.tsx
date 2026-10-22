import { ArrowUp, Check, Pencil, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "cn"
import { crowColor } from "../crow"
import { Crow } from "./Crow"
import type { DeskTask } from "../desk"
import type { ModelInfo } from "../types"

export type DeskBot = {
  name: string
  job: string
  color: string
  accessory: string
}

type DeskProps = {
  bot: DeskBot
  greeting: { hello: string; line: string }
  tasks: DeskTask[]
  draft: string
  streaming: boolean
  selected: ModelInfo | null
  onDraft: (value: string) => void
  onSend: () => void
  onApprove: (task: DeskTask) => void
  onReview: (task: DeskTask) => void
  onOpen: (conversationId: string) => void
  onEdit?: () => void
}

export function Desk({ bot, greeting, tasks, draft, streaming, selected, onDraft, onSend, onApprove, onReview, onOpen, onEdit }: DeskProps) {
  const blocked = streaming || !draft.trim()
  const color = crowColor(bot.color)
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-8 px-5 pt-6 pb-16">
      <section aria-label={bot.name} className="flex flex-col items-center gap-3 text-center">
        <Crow color={bot.color} accessory={bot.accessory} size={120} title={`${bot.name}（八咫烏）`} />
        {onEdit ? (
          <Button type="button" variant="ghost" className="h-9 gap-1.5 rounded-lg text-sm text-muted-foreground" onClick={onEdit}>
            <Pencil className="size-4" />
            {bot.name}を編集
          </Button>
        ) : null}
        <h1 className="font-maru text-[1.7rem] leading-snug font-bold">
          {greeting.hello}
          <br />
          {greeting.line}
        </h1>
      </section>

      <form
        className="flex flex-col gap-1"
        onSubmit={(event) => {
          event.preventDefault()
          if (!blocked) onSend()
        }}
      >
        <div className="flex items-end gap-2 rounded-3xl border border-border bg-card py-2 pr-2 pl-5 shadow-[0_4px_16px_rgba(34,25,51,0.06)]">
          <Textarea
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            placeholder={`${bot.name}に頼む`}
            rows={1}
            aria-label={`${bot.name}に頼む`}
            className="max-h-40 min-h-11 flex-1 resize-none border-0 bg-transparent px-0 py-2.5 text-base shadow-none focus-visible:ring-0"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                if (!blocked) onSend()
              }
            }}
          />
          <Button
            type="submit"
            size="icon-lg"
            disabled={blocked}
            aria-label="送る"
            className="size-11 rounded-2xl"
            style={{ backgroundColor: color.body }}
          >
            <ArrowUp className="size-5" />
          </Button>
        </div>
        {selected?.note ? <p className="px-4 text-xs text-muted-foreground">{selected.note}</p> : null}
      </form>

      <section aria-labelledby="desk-tasks" className="flex flex-col gap-2.5">
        <h2 id="desk-tasks" className="px-1 text-sm text-muted-foreground">
          {bot.name}の仕事
        </h2>
        {tasks.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-border px-4 py-5 text-center text-sm text-muted-foreground">
            まだ仕事はありません。「毎朝8時にニュースを要約して」のように頼むと、ここに並びます。
          </p>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {tasks.map((task) => (
              <li key={task.key}>
                <TaskRow task={task} accent={color.body} onApprove={onApprove} onReview={onReview} onOpen={onOpen} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function TaskMark({ kind, accent }: { kind: DeskTask["kind"]; accent: string }) {
  if (kind === "wait") return <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full bg-[#E39B12]" />
  if (kind === "doing")
    return <span aria-hidden="true" className="size-2.5 shrink-0 animate-pulse rounded-full" style={{ backgroundColor: accent }} />
  if (kind === "next") return <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full border-2 border-[#9A8FAD]" />
  if (kind === "failed") return <X aria-hidden="true" className="size-3.5 shrink-0 text-destructive" />
  return <Check aria-hidden="true" className="size-3.5 shrink-0 text-[#2F7A55]" />
}

const KIND_LABEL: Record<DeskTask["kind"], string> = {
  wait: "許可待ち",
  doing: "作業中",
  next: "予定",
  done: "完了",
  failed: "失敗",
}

function TaskRow({
  task,
  accent,
  onApprove,
  onReview,
  onOpen,
}: {
  task: DeskTask
  accent: string
  onApprove: (task: DeskTask) => void
  onReview: (task: DeskTask) => void
  onOpen: (conversationId: string) => void
}) {
  const quiet = task.kind === "done" || task.kind === "failed"
  const body = (
    <>
      <TaskMark kind={task.kind} accent={accent} />
      <span className="sr-only">{KIND_LABEL[task.kind]}：</span>
      <span className="min-w-0 flex-1 text-left">
        <span className={cn("block truncate text-[0.95rem] leading-6", quiet ? "text-muted-foreground" : "font-bold")}>
          {task.title}
        </span>
        <span className={cn("block truncate text-[0.8rem]", task.kind === "wait" ? "text-[#6B4A06]" : "text-muted-foreground")}>
          {task.sub}
        </span>
      </span>
    </>
  )

  if (task.kind === "wait") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[#F1DDB0] bg-card px-4 py-3">
        <div className="flex min-w-48 flex-1 items-center gap-3">{body}</div>
        <div className="flex gap-1.5">
          <Button type="button" className="h-10 rounded-xl px-4 font-bold" style={{ backgroundColor: accent }} onClick={() => onApprove(task)}>
            許可
          </Button>
          <Button type="button" variant="outline" className="h-10 rounded-xl px-3.5" onClick={() => onReview(task)}>
            見る
          </Button>
        </div>
      </div>
    )
  }

  return (
    <button
      type="button"
      disabled={!task.conversationId}
      onClick={() => task.conversationId && onOpen(task.conversationId)}
      className={cn(
        "flex w-full items-center gap-3 rounded-2xl border px-4 py-3 transition-colors",
        quiet ? "border-transparent hover:bg-card/70" : "border-[#ECE6F3] bg-card hover:border-border",
        "disabled:cursor-default",
      )}
    >
      {body}
    </button>
  )
}
