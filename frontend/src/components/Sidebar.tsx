import { House, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "cn"
import { Drawer } from "./Drawer"
import { RoutinesSection } from "./Routines"
import type { Conversation, Routine, RoutinePreset } from "../types"

type HistoryProps = {
  botName: string
  conversations: Conversation[]
  activeId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (conversation: Conversation) => void
  routines: Routine[]
  presets: RoutinePreset[]
  onCreateRoutine: (input: { name: string; prompt: string; preset?: string; schedule?: string }) => Promise<void>
  onToggleRoutine: (routine: Routine) => Promise<void>
  onToggleRoutineLine: (routine: Routine) => Promise<void>
  onDeleteRoutine: (routine: Routine) => Promise<void>
}

/** 「記録」パネル。選んでいるボットとの会話と、ルーティンの管理。 */
export function Sidebar({
  botName,
  conversations,
  activeId,
  open,
  onOpenChange,
  onSelect,
  onNew,
  onDelete,
  routines,
  presets,
  onCreateRoutine,
  onToggleRoutine,
  onToggleRoutineLine,
  onDeleteRoutine,
}: HistoryProps) {
  return (
    <Drawer title={`${botName}の記録`} open={open} onClose={() => onOpenChange(false)}>
      <div className="flex flex-col gap-6">
        <Button className="h-11 w-full justify-start gap-2 rounded-xl" onClick={onNew}>
          <House />
          机にもどる
        </Button>

        <section aria-labelledby="history-chats" className="flex flex-col gap-2">
          <h3 id="history-chats" className="text-base font-bold">
            会話
          </h3>
          {conversations.length === 0 ? (
            <p className="text-sm text-muted-foreground">会話はまだありません。</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {conversations.map((conversation) => (
                <li key={conversation.id}>
                  <div
                    className={cn(
                      "group flex items-center gap-1 rounded-xl pr-1",
                      conversation.id === activeId ? "bg-sidebar-accent" : "hover:bg-sidebar-accent/70",
                    )}
                  >
                    <button
                      type="button"
                      className="min-h-10 min-w-0 flex-1 truncate px-3 py-2 text-left text-sm"
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
        </section>

        <RoutinesSection
          routines={routines}
          presets={presets}
          onCreate={onCreateRoutine}
          onToggle={onToggleRoutine}
          onToggleLine={onToggleRoutineLine}
          onDelete={onDeleteRoutine}
          onOpen={(id) => onSelect(id)}
        />
      </div>
    </Drawer>
  )
}
