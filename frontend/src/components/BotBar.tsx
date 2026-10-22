import { Plus } from "lucide-react"
import { cn } from "cn"
import { crowColor } from "../crow"
import { Crow } from "./Crow"
import type { Bot } from "../types"

type BotBarProps = {
  bots: Bot[]
  selectedId: string | null
  waiting: Record<string, number>
  disabled?: boolean
  onSelect: (id: string) => void
  onCreate: () => void
}

export function BotBar({ bots, selectedId, waiting, disabled, onSelect, onCreate }: BotBarProps) {
  return (
    <nav aria-label="ボット" className="flex flex-wrap justify-center gap-2 px-4 pt-2">
      {bots.map((bot) => {
        const on = bot.id === selectedId
        const count = waiting[bot.id] ?? 0
        const color = crowColor(bot.color)
        return (
          <button
            key={bot.id}
            type="button"
            disabled={disabled}
            aria-pressed={on}
            aria-label={count ? `${bot.name}（許可待ち ${count}件）` : bot.name}
            onClick={() => onSelect(bot.id)}
            className={cn(
              "flex min-w-[4.5rem] flex-col items-center gap-1 rounded-2xl p-1.5 transition-opacity disabled:cursor-not-allowed",
              on ? "opacity-100" : "opacity-75 hover:opacity-100",
            )}
          >
            <span
              className="relative block rounded-[1.3rem] p-1"
              style={on ? { backgroundColor: color.soft, boxShadow: `0 0 0 3px ${color.body}` } : undefined}
            >
              <Crow color={bot.color} accessory={bot.accessory} size={52} />
              {count > 0 ? (
                <span
                  aria-hidden="true"
                  className="absolute -top-1 -right-1 flex h-5 min-w-5 items-center justify-center rounded-full border-2 border-background bg-[#E39B12] px-1 text-xs font-bold text-[#2A1A00]"
                >
                  {count}
                </span>
              ) : null}
            </span>
            <span className="max-w-24 truncate text-[0.8rem] font-bold">{bot.name}</span>
          </button>
        )
      })}
      <button
        type="button"
        disabled={disabled}
        onClick={onCreate}
        className="flex min-w-[4.5rem] flex-col items-center gap-1 rounded-2xl p-1.5 text-muted-foreground hover:text-foreground disabled:cursor-not-allowed"
      >
        <span className="flex size-[60px] items-center justify-center rounded-[1.3rem] border-2 border-dashed border-[#B9ACCB]">
          <Plus className="size-5" aria-hidden="true" />
        </span>
        <span className="text-[0.8rem]">新しく作る</span>
      </button>
    </nav>
  )
}
