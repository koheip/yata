import { Menu, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { cn } from "cn"
import type { Conversation, Fact } from "../types"

type SidebarProps = {
  conversations: Conversation[]
  facts: Fact[]
  activeId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (conversation: Conversation) => void
  onDeleteFact: (key: string) => void
}

export function Sidebar({
  conversations,
  facts,
  activeId,
  open,
  onOpenChange,
  onSelect,
  onNew,
  onDelete,
  onDeleteFact,
}: SidebarProps) {
  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="メニューを閉じる"
          className="fixed inset-0 z-30 bg-foreground/20 md:hidden"
          onClick={() => onOpenChange(false)}
        />
      ) : null}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-transform md:static md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center gap-3 px-4 py-4">
          <LampMark />
          <div>
            <p className="font-mincho text-2xl leading-none">灯</p>
            <p className="text-xs tracking-[0.18em] text-muted-foreground">ともしび</p>
          </div>
        </div>
        <div className="px-3">
          <Button className="w-full justify-start" onClick={onNew}>
            <Plus />
            新しい会話
          </Button>
        </div>
        <ScrollArea className="mt-3 min-h-0 flex-1 px-2">
          {conversations.length === 0 ? (
            <p className="px-2 py-6 text-sm text-muted-foreground">会話はまだありません。</p>
          ) : (
            <ul className="space-y-1 pb-4">
              {conversations.map((conversation) => (
                <li key={conversation.id}>
                  <div
                    className={cn(
                      "group flex items-center gap-1 rounded-lg pr-1",
                      conversation.id === activeId ? "bg-sidebar-accent" : "hover:bg-sidebar-accent/70",
                    )}
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 truncate px-3 py-2 text-left text-sm"
                      onClick={() => onSelect(conversation.id)}
                    >
                      {conversation.title}
                    </button>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                      aria-label={`${conversation.title} を削除`}
                      onClick={() => onDelete(conversation)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
        <Separator />
        <div className="max-h-56 overflow-y-auto px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-medium tracking-wide text-muted-foreground">記憶</p>
            <Badge variant="secondary">{facts.length}</Badge>
          </div>
          {facts.length === 0 ? (
            <p className="text-sm text-muted-foreground">記憶はまだありません。</p>
          ) : (
            <ul className="space-y-2">
              {facts.map((fact) => (
                <li key={fact.key} className="flex items-start gap-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{fact.key}</p>
                    <p className="truncate text-muted-foreground">{fact.value}</p>
                  </div>
                  <Button
                    type="button"
                    size="icon-xs"
                    variant="ghost"
                    aria-label={`${fact.key} を忘れる`}
                    onClick={() => onDeleteFact(fact.key)}
                  >
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>
    </>
  )
}

export function MenuButton({ onClick }: { onClick: () => void }) {
  return (
    <Button type="button" size="icon" variant="outline" className="md:hidden" aria-label="メニューを開く" onClick={onClick}>
      <Menu />
    </Button>
  )
}

function LampMark() {
  return (
    <svg viewBox="0 0 32 32" className="size-9" aria-hidden="true">
      <rect width="32" height="32" rx="10" fill="#fbf8f1" stroke="#ddd4c3" />
      <path d="M16 5c.6 2.8 3.4 4.6 3.4 7.8 0 2.2-1.4 3.6-3.4 4.2-2-.6-3.4-2-3.4-4.2C12.6 9.6 15.4 7.8 16 5z" fill="#b8432f" />
      <path d="M11.5 21.5h9M16 17.2V26M13 26h6" stroke="#1c1915" fill="none" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}
