import { ArrowUp } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import type { ModelInfo } from "../types"

type ComposerProps = {
  draft: string
  streaming: boolean
  selected: ModelInfo | null
  onDraft: (value: string) => void
  onSend: () => void
}

export function Composer({ draft, streaming, selected, onDraft, onSend }: ComposerProps) {
  const blocked = streaming || !draft.trim() || (selected ? !selected.ready : false)
  return (
    <form
      className="mx-auto w-full max-w-3xl px-4 pb-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (!blocked) onSend()
      }}
    >
      {selected?.note ? <p className="mb-2 text-xs text-muted-foreground">{selected.note}</p> : null}
      <div className="rounded-2xl border border-border bg-card p-2 shadow-sm">
        <Textarea
          value={draft}
          onChange={(event) => onDraft(event.target.value)}
          placeholder="調べたいこと、読ませたいURL、覚えてほしいこと"
          rows={2}
          className="max-h-40 min-h-16 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
          aria-label="メッセージ"
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              if (!blocked) onSend()
            }
          }}
        />
        <div className="flex items-center justify-between px-1 pb-1">
          <p className="text-xs text-muted-foreground">Enter で送信、Shift+Enter で改行</p>
          <Button type="submit" size="icon" disabled={blocked} aria-label="送信">
            <ArrowUp />
          </Button>
        </div>
      </div>
    </form>
  )
}
