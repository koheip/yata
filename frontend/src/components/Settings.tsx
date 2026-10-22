import { Power, Trash2 } from "lucide-react"
import { useState } from "react"
import { quitApp } from "../api"
import { Button } from "@/components/ui/button"
import { AiPicker } from "./AiPicker"
import { ConnectorsSection } from "./Connectors"
import { Drawer } from "./Drawer"
import type { AiSetup, Connector, ConnectorSetupList, Fact, LocalSetup, ModelInfo } from "../types"

type SettingsProps = {
  open: boolean
  onClose: () => void
  connectors: Connector[]
  onConnect: (connector: Connector) => void
  onDisconnect: (connector: Connector) => Promise<void>
  connectorSetups: ConnectorSetupList | null
  onSaveConnector: (setupId: string, values: Record<string, string>) => Promise<{ message: string }>
  onRemoveConnector: (setupId: string) => Promise<void>
  models: ModelInfo[]
  modelId: string
  modelLocked: boolean
  onModel: (id: string) => void
  facts: Fact[]
  onDeleteFact: (key: string) => void
  aiSetup: AiSetup | null
  onConnectAi: (providerId: string, key: string) => Promise<{ message: string }>
  onDisconnectAi: (providerId: string) => Promise<void>
  localSetup: LocalSetup | null
  onRefreshLocal: (prefer?: string) => Promise<void>
  onChooseModel: (serverId: string, model: string) => Promise<void>
  onPullModel: (model: string) => Promise<void>
  onSaveCustomServer: (body: { base_url: string; model: string; api_key: string }) => Promise<void>
  onRemoveCustomServer: () => Promise<void>
  onOffline: (enabled: boolean) => Promise<void>
}

export function Settings({
  open,
  onClose,
  connectors,
  onConnect,
  onDisconnect,
  connectorSetups,
  onSaveConnector,
  onRemoveConnector,
  models,
  modelId,
  modelLocked,
  onModel,
  facts,
  onDeleteFact,
  aiSetup,
  onConnectAi,
  onDisconnectAi,
  localSetup,
  onRefreshLocal,
  onChooseModel,
  onPullModel,
  onSaveCustomServer,
  onRemoveCustomServer,
  onOffline,
}: SettingsProps) {
  const [quitStep, setQuitStep] = useState<"idle" | "confirm" | "done" | "error">("idle")
  const connected = connectors.filter((connector) => connector.status === "connected").length
  return (
    <Drawer title="設定" open={open} onClose={onClose}>
      <div className="flex flex-col gap-8">
        <section aria-labelledby="settings-ai" className="flex flex-col gap-3">
          <h3 id="settings-ai" className="text-base font-bold">
            使う AI
          </h3>
          <AiPicker
            models={models}
            modelId={modelId}
            modelLocked={modelLocked}
            onModel={onModel}
            aiSetup={aiSetup}
            onConnectAi={onConnectAi}
            onDisconnectAi={onDisconnectAi}
            localSetup={localSetup}
            onRefreshLocal={onRefreshLocal}
            onChooseModel={onChooseModel}
            onPullModel={onPullModel}
            onSaveCustomServer={onSaveCustomServer}
            onRemoveCustomServer={onRemoveCustomServer}
            onOffline={onOffline}
          />
        </section>

        <section aria-labelledby="settings-links" className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between">
            <h3 id="settings-links" className="text-base font-bold">
              連携
            </h3>
            <span className="text-xs text-muted-foreground">
              {connected} / {connectors.length} 件つながっています
            </span>
          </div>
          <ConnectorsSection
            connectors={connectors}
            setups={connectorSetups}
            onConnect={onConnect}
            onDisconnect={onDisconnect}
            onSave={onSaveConnector}
            onRemove={onRemoveConnector}
          />
        </section>

        <section aria-labelledby="settings-memory" className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <h3 id="settings-memory" className="text-base font-bold">
              ヤタが覚えていること
            </h3>
            <span className="text-xs text-muted-foreground">{facts.length} 件</span>
          </div>
          {facts.length === 0 ? (
            <p className="text-sm text-muted-foreground">まだ何も覚えていません。「覚えて：〜」と頼むと、ここに並びます。</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {facts.map((fact) => (
                <li key={fact.key} className="flex items-start gap-2 rounded-xl bg-card px-3 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <p className="font-bold">{fact.key}</p>
                    <p className="break-words text-muted-foreground">{fact.value}</p>
                  </div>
                  <Button
                    type="button"
                    size="icon-lg"
                    variant="ghost"
                    className="size-10 rounded-lg"
                    aria-label={`${fact.key} を忘れる`}
                    onClick={() => onDeleteFact(fact.key)}
                  >
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="settings-quit" className="flex flex-col gap-2 border-t border-border pt-6">
          <h3 id="settings-quit" className="text-base font-bold">
            ヤタを終了する
          </h3>
          <p className="text-[0.8rem] leading-5 text-muted-foreground">
            画面を閉じても、ルーティンのためにヤタは動き続けます。完全に止めたいときだけ使ってください。
          </p>
          {quitStep === "done" ? (
            <p role="status" className="text-sm text-[#1F5A3D]">
              ヤタを終了しました。このウィンドウを閉じてください。
            </p>
          ) : quitStep === "confirm" ? (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="destructive"
                className="h-10 rounded-xl px-4"
                onClick={() => {
                  quitApp()
                    .then(() => setQuitStep("done"))
                    .catch(() => setQuitStep("error"))
                }}
              >
                終了する（ルーティンも止まります）
              </Button>
              <Button type="button" variant="ghost" className="h-10 rounded-xl" onClick={() => setQuitStep("idle")}>
                やめる
              </Button>
            </div>
          ) : (
            <Button type="button" variant="outline" className="h-10 gap-2 self-start rounded-xl px-4" onClick={() => setQuitStep("confirm")}>
              <Power className="size-4" />
              ヤタを終了する
            </Button>
          )}
          {quitStep === "error" ? (
            <p role="alert" className="text-sm text-destructive">
              終了できませんでした。もう一度試してください。
            </p>
          ) : null}
        </section>
      </div>
    </Drawer>
  )
}
