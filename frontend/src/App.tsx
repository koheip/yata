import { ScrollArea } from "@/components/ui/scroll-area"
import { Composer } from "./components/Composer"
import { ConfirmDialog, DeleteDialog } from "./components/ConfirmDialog"
import { MenuButton, Sidebar } from "./components/Sidebar"
import { Transcript } from "./components/Transcript"
import { useAssistant } from "./useAssistant"

export default function App() {
  const assistant = useAssistant()

  return (
    <div className="flex h-svh overflow-hidden bg-background text-foreground">
      <Sidebar
        conversations={assistant.conversations}
        facts={assistant.facts}
        activeId={assistant.activeId}
        open={assistant.sidebarOpen}
        onOpenChange={assistant.setSidebarOpen}
        onSelect={(id) => {
          void assistant.openConversation(id)
        }}
        onNew={assistant.startNewChat}
        onDelete={assistant.setPendingDelete}
        onDeleteFact={(key) => {
          void assistant.removeFact(key)
        }}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border px-3 py-3 md:px-5">
          <MenuButton onClick={() => assistant.setSidebarOpen(true)} />
          <label className="min-w-0 flex-1 text-sm">
            <span className="sr-only">モデル</span>
            <select
              className="h-9 w-full max-w-xs rounded-lg border border-input bg-card px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
              value={assistant.modelId}
              onChange={(event) => assistant.setModelId(event.target.value)}
              disabled={assistant.streaming}
              aria-label="モデル"
            >
              {assistant.models.map((model) => (
                <option key={model.id} value={model.id} disabled={!model.ready}>
                  {model.provider} / {model.label}
                  {model.ready ? "" : "（利用不可）"}
                </option>
              ))}
            </select>
          </label>
          <p className="hidden text-xs text-muted-foreground sm:block">
            {assistant.selected?.upstream_model}
          </p>
        </header>
        {assistant.error ? (
          <p className="border-b border-border bg-destructive/10 px-4 py-2 text-sm text-destructive" role="alert">
            {assistant.error}
          </p>
        ) : null}
        <ScrollArea className="min-h-0 flex-1">
          {assistant.loading ? (
            <p className="px-6 py-10 text-sm text-muted-foreground">読み込んでいます…</p>
          ) : (
            <Transcript
              messages={assistant.messages}
              streaming={assistant.streaming}
              onSuggest={(text) => {
                void assistant.send(text)
              }}
            />
          )}
        </ScrollArea>
        <Composer
          draft={assistant.draft}
          streaming={assistant.streaming}
          selected={assistant.selected}
          onDraft={assistant.setDraft}
          onSend={() => {
            void assistant.send()
          }}
        />
      </main>
      <ConfirmDialog request={assistant.confirm} onDecide={assistant.decide} />
      <DeleteDialog
        conversation={assistant.pendingDelete}
        onCancel={() => assistant.setPendingDelete(null)}
        onConfirm={() => {
          void assistant.removeConversation()
        }}
      />
    </div>
  )
}
