import { useEffect, useRef } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { SUGGESTIONS, summarizeArguments, toolLabel } from "../labels"
import type { ChatMessage, Step } from "../types"

type TranscriptProps = {
  messages: ChatMessage[]
  streaming: boolean
  onSuggest: (text: string) => void
}

export function Transcript({ messages, streaming, onSuggest }: TranscriptProps) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" })
  }, [messages, streaming])

  if (messages.length === 0) {
    return (
      <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center px-4 py-16">
        <p className="font-mincho text-4xl text-foreground">灯をともす</p>
        <p className="mt-3 max-w-xl text-sm leading-7 text-muted-foreground">
          調べて、ページを読んで、必要なときだけブラウザを動かします。APIキーがなくても、デモモデルでツールの流れを見られます。
        </p>
        <div className="mt-6 flex flex-col gap-2">
          {SUGGESTIONS.map((suggestion) => (
            <Button
              key={suggestion}
              type="button"
              variant="outline"
              className="h-auto justify-start px-3 py-2 text-left whitespace-normal"
              onClick={() => onSuggest(suggestion)}
            >
              {suggestion}
            </Button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
      {messages.map((message, index) => {
        const live = streaming && index === messages.length - 1 && message.role === "assistant"
        return message.role === "user" ? (
          <UserMessage key={message.id} content={message.content} />
        ) : (
          <AssistantMessage key={message.id} message={message} live={live} />
        )
      })}
      <div ref={endRef} />
    </div>
  )
}

function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl bg-foreground px-4 py-2.5 text-sm leading-7 whitespace-pre-wrap text-background">
        {content}
      </p>
    </div>
  )
}

function AssistantMessage({ message, live }: { message: ChatMessage; live: boolean }) {
  const thinking = live && !message.content && message.steps.length === 0
  return (
    <article className="space-y-3">
      {thinking ? <p className="text-sm text-muted-foreground">考えています…</p> : null}
      {message.steps.length > 0 ? <ToolTrace steps={message.steps} live={live} /> : null}
      {message.content ? (
        <p className="text-sm leading-7 whitespace-pre-wrap text-foreground">{message.content}</p>
      ) : live && message.steps.length > 0 ? (
        <p className="text-sm text-muted-foreground">結果をまとめています…</p>
      ) : null}
    </article>
  )
}

function ToolTrace({ steps, live }: { steps: Step[]; live: boolean }) {
  return (
    <ol className="space-y-2 border-l border-border pl-3">
      {steps.map((step, index) =>
        step.type === "note" ? (
          <li key={`note-${index}`} className="text-xs text-muted-foreground">
            {step.text}
          </li>
        ) : (
          <li key={step.id || index} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={step.ok ? "secondary" : "destructive"}>{toolLabel(step.name)}</Badge>
              <span className="text-xs text-muted-foreground">{summarizeArguments(step.arguments)}</span>
              {live && !step.content ? <span className="text-xs text-muted-foreground">実行しています…</span> : null}
            </div>
            {step.content ? (
              <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-card px-3 py-2 text-xs leading-5 whitespace-pre-wrap text-muted-foreground">
                {step.content}
              </pre>
            ) : null}
            {step.image_url ? (
              <img
                src={step.image_url}
                alt="ブラウザのスクリーンショット"
                className="mt-2 max-h-72 rounded-lg border border-border"
              />
            ) : null}
          </li>
        ),
      )}
    </ol>
  )
}
