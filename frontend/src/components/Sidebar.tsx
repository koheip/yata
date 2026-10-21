import { Menu, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { cn } from "cn"
import { ConnectorsSection } from "./Connectors"
import { RoutinesSection } from "./Routines"
import type { Connector, Conversation, Fact, Routine, RoutinePreset } from "../types"

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
  routines: Routine[]
  presets: RoutinePreset[]
  onCreateRoutine: (input: { name: string; prompt: string; preset?: string; schedule?: string }) => Promise<void>
  onToggleRoutine: (routine: Routine) => Promise<void>
  onDeleteRoutine: (routine: Routine) => Promise<void>
  connectors: Connector[]
  onConnectConnector: (connector: Connector) => void
  onDisconnectConnector: (connector: Connector) => Promise<void>
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
  routines,
  presets,
  onCreateRoutine,
  onToggleRoutine,
  onDeleteRoutine,
  connectors,
  onConnectConnector,
  onDisconnectConnector,
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
          <CrowMark />
          <div>
            <p className="font-mincho text-2xl leading-none">ヤタ</p>
            <p className="text-xs tracking-[0.18em] text-muted-foreground">八咫烏</p>
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
        <RoutinesSection
          routines={routines}
          presets={presets}
          onCreate={onCreateRoutine}
          onToggle={onToggleRoutine}
          onDelete={onDeleteRoutine}
          onOpen={(id) => onSelect(id)}
        />
        <Separator />
        <ConnectorsSection connectors={connectors} onConnect={onConnectConnector} onDisconnect={onDisconnectConnector} />
        <Separator />
        <div className="max-h-40 overflow-y-auto px-4 py-3">
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

function CrowMark() {
  return (
    <svg viewBox="0 0 32 32" className="size-9" aria-hidden="true">
      <rect width="32" height="32" rx="10" fill="#fbf8f1" stroke="#ddd4c3" />
      <path
        d="M6.2 17.6c2.4-.6 4.2-2 5-3.6-.2 2.2 1.2 4.2 3.4 5.4-2.6.2-5.2-.4-6.8-1.8-.6.6-1.2 1.2-1.6 0z"
        fill="#1c1915"
      />
      <path
        d="M10.4 15.2c.6-3.2 3.2-5.6 6.6-5.8 2.2-.1 3.8.6 5.2 2l3.4-1.4c.3 1.3-.4 2.2-1.6 2.5l-1.6.5c.5 1.1.4 2.3-.4 3.3-1.5 1.8-4 3-6.8 2.9-3-.1-5.2-1.5-6-3.2.6-.4 1-.7 1.2-.8z"
        fill="#1c1915"
      />
      <path d="M23.6 12.4 28 13.1l-4.2 1.5z" fill="#b8432f" />
      <circle cx="21.2" cy="13.2" r="0.75" fill="#fbf8f1" />
      <path d="M13.2 21.6v3.2M16 22v3.4M18.8 21.6v3" stroke="#1c1915" strokeWidth="1.15" strokeLinecap="round" />
    </svg>
  )
}
