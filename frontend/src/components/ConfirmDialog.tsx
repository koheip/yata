import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { toolLabel } from "../labels"
import type { ConfirmRequest, Conversation } from "../types"

type ConfirmDialogProps = {
  request: ConfirmRequest | null
  onDecide: (approved: boolean) => void
}

export function ConfirmDialog({ request, onDecide }: ConfirmDialogProps) {
  return (
    <Dialog open={request !== null} onOpenChange={(open) => { if (!open) onDecide(false) }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>この操作を許可しますか？</DialogTitle>
          <DialogDescription>
            {toolLabel(request?.tool ?? "")} はページの状態を変えます。内容を確認してから許可してください。
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm leading-6">{request?.summary}</p>
        <pre className="max-h-40 overflow-auto rounded-lg bg-muted px-3 py-2 text-xs leading-5 whitespace-pre-wrap">
          {JSON.stringify(request?.arguments ?? {}, null, 2)}
        </pre>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onDecide(false)}>
            拒否する
          </Button>
          <Button type="button" onClick={() => onDecide(true)}>
            許可する
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

type DeleteDialogProps = {
  conversation: Conversation | null
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteDialog({ conversation, onCancel, onConfirm }: DeleteDialogProps) {
  return (
    <Dialog open={conversation !== null} onOpenChange={(open) => { if (!open) onCancel() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>会話を削除しますか？</DialogTitle>
          <DialogDescription>「{conversation?.title}」の履歴は元に戻せません。記憶はそのまま残ります。</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            キャンセル
          </Button>
          <Button type="button" variant="destructive" onClick={onConfirm}>
            削除する
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
