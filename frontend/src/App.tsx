import { ArrowLeft, History, Settings as SettingsIcon, WifiOff } from "lucide-react"
import { useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Composer } from "./components/Composer"
import { BotBar } from "./components/BotBar"
import { BotForm } from "./components/BotForm"
import { ConfirmDialog, DeleteDialog } from "./components/ConfirmDialog"
import { Crow } from "./components/Crow"
import { Desk, type DeskBot } from "./components/Desk"
import { Onboarding } from "./components/Onboarding"
import { Settings } from "./components/Settings"
import { Sidebar } from "./components/Sidebar"
import { Transcript } from "./components/Transcript"
import { buildDeskTasks, buildGreeting } from "./desk"
import type { Bot } from "./types"
import { useAssistant } from "./useAssistant"

const YATA: DeskBot = { name: "ヤタ", job: "なんでも頼める相棒", color: "purple", accessory: "none" }

export default function App() {
  const assistant = useAssistant()
  // undefined: 閉じている / null: 新しく作る / Bot: 編集する
  const [formBot, setFormBot] = useState<Bot | null | undefined>(undefined)
  const [formKey, setFormKey] = useState(0)
  const onDesk = assistant.activeId === null && assistant.messages.length === 0
  const bot = assistant.bot
  const botId = bot?.id ?? "yata"
  const deskBot: DeskBot = bot ?? YATA
  const botRoutines = useMemo(
    () => assistant.routines.filter((routine) => (routine.bot_id ?? "yata") === botId),
    [assistant.routines, botId],
  )
  const tasks = useMemo(
    () => buildDeskTasks(botRoutines, { chatBusy: assistant.streaming }),
    [botRoutines, assistant.streaming],
  )
  const greeting = buildGreeting(tasks)
  const waitingByBot = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const routine of assistant.routines) {
      if (routine.pending_confirmation) counts[routine.bot_id ?? "yata"] = (counts[routine.bot_id ?? "yata"] ?? 0) + 1
    }
    return counts
  }, [assistant.routines])
  const waiting = Object.values(waitingByBot).reduce((sum, count) => sum + count, 0)
  const botConversations = assistant.conversations.filter((item) => (item.bot_id ?? "yata") === botId)
  const ollamaReady = assistant.models.some((model) => model.local && model.ready)
  const firstProvider = assistant.aiSetup?.providers[0]
  const showOnboarding = Boolean(assistant.aiSetup?.needs_setup && !ollamaReady && firstProvider)

  function openForm(target: Bot | null) {
    setFormKey((key) => key + 1)
    setFormBot(target)
  }

  return (
    <div className="flex h-svh flex-col overflow-hidden bg-background text-foreground">
      <header className="flex items-center gap-2 px-3 py-2.5 md:px-5">
        {onDesk ? (
          <p className="flex shrink-0 items-center gap-2 px-1">
            <Crow color="purple" size={30} />
            <span className="font-maru text-lg font-bold whitespace-nowrap">ヤタ</span>
          </p>
        ) : (
          <Button type="button" variant="ghost" className="h-10 gap-2 rounded-xl px-3" onClick={assistant.startNewChat} disabled={assistant.streaming}>
            <ArrowLeft className="size-4" />
            <Crow color={deskBot.color} accessory={deskBot.accessory} size={26} />
            <span className="hidden max-w-40 truncate sm:inline">{deskBot.name}の</span>机にもどる
            {waiting > 0 ? (
              <span className="rounded-full bg-[#FDF0D5] px-2 py-0.5 text-xs font-bold text-[#6B4A06]">許可待ち {waiting}</span>
            ) : null}
          </Button>
        )}
        <div className="flex-1" />
        {assistant.localSetup?.offline ? (
          <span className="flex shrink-0 items-center gap-1 rounded-full bg-[#F1ECF8] px-2.5 py-1 text-xs font-bold text-[#3B2560]" title="会話を外に出さないモードです">
            <WifiOff className="size-3.5" aria-hidden="true" />
            オフライン
          </span>
        ) : null}
        <Button
          type="button"
          variant="ghost"
          size="icon-lg"
          className="size-11 rounded-xl"
          aria-label="記録（会話とルーティン）"
          title="記録（会話とルーティン）"
          onClick={() => assistant.setSidebarOpen(true)}
        >
          <History className="size-5" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-lg"
          className="size-11 rounded-xl"
          aria-label="設定"
          title="設定"
          onClick={() => assistant.setSettingsOpen(true)}
        >
          <SettingsIcon className="size-5" />
        </Button>
      </header>

      {assistant.error ? (
        <p className="mx-auto w-full max-w-xl rounded-xl bg-destructive/10 px-4 py-2 text-sm text-destructive" role="alert">
          {assistant.error}
        </p>
      ) : null}

      {onDesk ? (
        <ScrollArea className="min-h-0 flex-1">
          {assistant.loading ? (
            <p className="px-6 py-10 text-center text-sm text-muted-foreground">読み込んでいます…</p>
          ) : (
            <>
            {showOnboarding && firstProvider ? (
              <Onboarding
                provider={firstProvider}
                onConnect={assistant.connectAi}
                onDisconnect={assistant.disconnectAi}
                onOther={() => assistant.setSettingsOpen(true)}
              />
            ) : null}
            <BotBar
              bots={assistant.bots}
              selectedId={botId}
              waiting={waitingByBot}
              disabled={assistant.streaming}
              onSelect={assistant.selectBot}
              onCreate={() => openForm(null)}
            />
            <Desk
              bot={deskBot}
              onEdit={bot ? () => openForm(bot) : undefined}
              greeting={greeting}
              tasks={tasks}
              draft={assistant.draft}
              streaming={assistant.streaming}
              selected={assistant.selected}
              onDraft={assistant.setDraft}
              onSend={() => {
                void assistant.send()
              }}
              onApprove={(task) => {
                if (task.confirmation) void assistant.answerRoutineConfirmation(task.confirmation, true)
              }}
              onReview={(task) => {
                if (task.confirmation) assistant.reviewRoutineConfirmation(task.confirmation)
              }}
              onOpen={(id) => {
                void assistant.openConversation(id)
              }}
            />
            </>
          )}
        </ScrollArea>
      ) : (
        <>
          <ScrollArea className="min-h-0 flex-1">
            <Transcript
              messages={assistant.messages}
              streaming={assistant.streaming}
              bot={deskBot}
              onSuggest={(text) => {
                void assistant.send(text)
              }}
            />
          </ScrollArea>
          <Composer
            draft={assistant.draft}
            streaming={assistant.streaming}
            selected={assistant.selected}
            onDraft={assistant.setDraft}
            onSend={() => {
              void assistant.send()
            }}
            onStop={assistant.stop}
          />
        </>
      )}

      <Sidebar
        conversations={botConversations}
        botName={deskBot.name}
        activeId={assistant.activeId}
        open={assistant.sidebarOpen}
        onOpenChange={assistant.setSidebarOpen}
        onSelect={(id) => {
          void assistant.openConversation(id)
        }}
        onNew={assistant.startNewChat}
        onDelete={assistant.setPendingDelete}
        routines={botRoutines}
        presets={assistant.presets}
        onCreateRoutine={assistant.addRoutine}
        onToggleRoutine={assistant.toggleRoutine}
        onToggleRoutineLine={assistant.toggleRoutineLine}
        onDeleteRoutine={assistant.removeRoutine}
      />
      <Settings
        open={assistant.settingsOpen}
        onClose={() => assistant.setSettingsOpen(false)}
        connectors={assistant.connectors}
        onConnect={(connector) => {
          void assistant.connectToConnector(connector)
        }}
        onDisconnect={(connector) => assistant.disconnectFromConnector(connector)}
        connectorSetups={assistant.connectorSetups}
        onSaveConnector={assistant.saveConnector}
        onRemoveConnector={assistant.removeConnector}
        models={assistant.models}
        modelId={assistant.modelId}
        modelLocked={assistant.streaming}
        onModel={assistant.setModelId}
        facts={assistant.facts}
        onDeleteFact={(key) => {
          void assistant.removeFact(key)
        }}
        aiSetup={assistant.aiSetup}
        onConnectAi={assistant.connectAi}
        onDisconnectAi={assistant.disconnectAi}
        localSetup={assistant.localSetup}
        onRefreshLocal={assistant.refreshLocal}
        onChooseModel={assistant.chooseModel}
        onPullModel={assistant.pullModel}
        onSaveCustomServer={assistant.saveCustomServer}
        onRemoveCustomServer={assistant.removeCustomServer}
        onOffline={assistant.changeOffline}
      />
      {formBot !== undefined ? (
        <BotForm
          key={formKey}
          bot={formBot}
          bots={assistant.bots}
          colors={assistant.botColors}
          accessories={assistant.botAccessories}
          onSave={async (input) => {
            if (formBot) await assistant.editBot(formBot.id, input)
            else await assistant.addBot(input)
          }}
          onDelete={(target) => assistant.removeBot(target.id)}
          onClose={() => setFormBot(undefined)}
        />
      ) : null}
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
