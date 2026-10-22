import { Shuffle } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "cn"
import { CROW_COLORS, crowColor, pickLook } from "../crow"
import { Crow } from "./Crow"
import type { Bot, BotInput, LookOption } from "../types"

type BotFormProps = {
  /** null なら新しく作る。ボットを渡すと編集する。 */
  bot: Bot | null
  bots: Bot[]
  colors: LookOption[]
  accessories: LookOption[]
  onSave: (input: BotInput) => Promise<void>
  onDelete: (bot: Bot) => Promise<void>
  onClose: () => void
}

/** ボットを作る・直すダイアログ。開くたびに作り直すので、key を付けて使う。 */
export function BotForm({ bot, bots, colors, accessories, onSave, onDelete, onClose }: BotFormProps) {
  const [look, setLook] = useState(() => (bot ? { color: bot.color, accessory: bot.accessory } : pickLook(bots)))
  const [name, setName] = useState(bot?.name ?? "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const others = bots.filter((item) => item.id !== bot?.id)

  async function submit() {
    if (!name.trim()) {
      setError("名前を入れてください。")
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onSave({ name: name.trim(), job: "", color: look.color, accessory: look.accessory })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存できませんでした。")
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!bot) return
    setBusy(true)
    setError(null)
    try {
      await onDelete(bot)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "消せませんでした。")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-maru text-xl">{bot ? `${bot.name}を編集` : "新しいボット"}</DialogTitle>
          <DialogDescription>
            {bot ? "名前と見た目を変えられます。" : "見た目は自動で決まります。好みでなければ変えられます。"}
          </DialogDescription>
        </DialogHeader>

        <form
          id="bot-form"
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
        >
          <div className="flex items-center gap-4">
            <span className="rounded-[1.6rem] p-1.5" style={{ backgroundColor: crowColor(look.color).soft }}>
              <Crow color={look.color} accessory={look.accessory} size={96} title="このボットの見た目" />
            </span>
            <Button
              type="button"
              variant="outline"
              className="h-11 gap-2 rounded-xl px-4"
              onClick={() => setLook(pickLook(others, look))}
            >
              <Shuffle className="size-4" />
              別の見た目にする
            </Button>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="bot-name" className="text-sm font-bold">
              名前
            </label>
            <input
              id="bot-name"
              value={name}
              maxLength={20}
              onChange={(event) => setName(event.target.value)}
              placeholder="例：買いもの係"
              className="h-11 rounded-xl border border-input bg-card px-3.5 text-[0.95rem] outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
            />
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-sm font-bold">体の色</legend>
            <div className="flex flex-wrap gap-2.5">
              {colors.map((option) => {
                const on = option.id === look.color
                const swatch = CROW_COLORS[option.id as keyof typeof CROW_COLORS]?.body ?? "#4B3170"
                return (
                  <button
                    key={option.id}
                    type="button"
                    aria-label={option.label}
                    aria-pressed={on}
                    onClick={() => setLook({ ...look, color: option.id })}
                    className={cn("size-11 rounded-xl border-[3px] shadow-[0_0_0_1px_var(--input)]", on ? "border-foreground" : "border-card")}
                    style={{ backgroundColor: swatch }}
                  />
                )
              })}
            </div>
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-sm font-bold">小物</legend>
            <div className="flex flex-wrap gap-2">
              {accessories.map((option) => {
                const on = option.id === look.accessory
                return (
                  <button
                    key={option.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setLook({ ...look, accessory: option.id })}
                    className={cn(
                      "h-10 rounded-full border px-3.5 text-sm",
                      on ? "border-foreground bg-foreground font-bold text-background" : "border-input bg-card",
                    )}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>
          </fieldset>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </form>

        {bot && !bot.is_default ? (
          <div className="rounded-xl border border-border p-3 text-sm">
            {confirmDelete ? (
              <div className="flex flex-col gap-2">
                <p>「{bot.name}」を消します。会話とルーティンは消えずに「ヤタ」に引き継がれます。</p>
                <div className="flex gap-2">
                  <Button type="button" variant="destructive" className="h-10 rounded-xl" disabled={busy} onClick={() => void remove()}>
                    消す
                  </Button>
                  <Button type="button" variant="outline" className="h-10 rounded-xl" disabled={busy} onClick={() => setConfirmDelete(false)}>
                    やめる
                  </Button>
                </div>
              </div>
            ) : (
              <Button type="button" variant="ghost" className="h-10 rounded-xl text-destructive" onClick={() => setConfirmDelete(true)}>
                このボットを消す
              </Button>
            )}
          </div>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" className="h-11 rounded-xl px-5" disabled={busy} onClick={onClose}>
            やめる
          </Button>
          <Button type="submit" form="bot-form" className="h-11 rounded-xl px-6 font-bold" disabled={busy}>
            {bot ? "保存する" : "作る"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
