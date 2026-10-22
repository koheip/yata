import { X } from "lucide-react"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "cn"

type DrawerProps = {
  title: string
  open: boolean
  onClose: () => void
  children: ReactNode
}

/** 右から出るパネル。設定と記録で使う。 */
export function Drawer({ title, open, onClose, children }: DrawerProps) {
  return (
    <>
      {open ? <button type="button" aria-label={`${title}を閉じる`} className="fixed inset-0 z-30 bg-foreground/20" onClick={onClose} /> : null}
      <aside
        aria-label={title}
        aria-hidden={!open}
        inert={!open}
        className={cn(
          "fixed inset-y-0 right-0 z-40 flex w-96 max-w-[92vw] flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground shadow-xl transition-transform",
          open ? "translate-x-0" : "pointer-events-none translate-x-full",
        )}
      >
        <div className="flex items-center gap-2 px-5 py-3">
          <h2 className="flex-1 font-maru text-xl font-bold">{title}</h2>
          <Button type="button" size="icon-lg" variant="ghost" className="size-11 rounded-xl" aria-label="閉じる" onClick={onClose}>
            <X className="size-5" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8">{children}</div>
      </aside>
    </>
  )
}
