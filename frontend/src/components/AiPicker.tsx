import { useState } from "react"
import { AiKeyCard } from "./AiKeyCard"
import { CustomServerForm, LocalServerCard, OfflineToggle } from "./LocalAi"
import type { AiSetup, LocalServer, LocalSetup, ModelInfo } from "../types"

type AiPickerProps = {
  models: ModelInfo[]
  modelId: string
  modelLocked: boolean
  onModel: (id: string) => void
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

type Choice = { id: string; label: string; ready: boolean }

/**
 * 使う AI を1つ選ぶ。選んだものの設定（キーの入力や、起動のしかた）だけを下に出す。
 * まだ使えないものも一覧に出し、選ぶとつなぎ方を案内する。
 */
export function AiPicker(props: AiPickerProps) {
  const { models, modelId, modelLocked, onModel, aiSetup, localSetup } = props
  const [picked, setPicked] = useState(modelId)
  const [seenModel, setSeenModel] = useState(modelId)
  if (seenModel !== modelId) {
    // ほかの場所（キーを入れたあとなど）で使う AI が変わったら、表示もそれに合わせる。
    setSeenModel(modelId)
    setPicked(modelId)
  }
  const ready = new Set(models.filter((model) => model.ready).map((model) => model.id))
  const offline = Boolean(localSetup?.offline)

  const cloud: Choice[] = (aiSetup?.providers ?? []).map((provider) => ({
    id: provider.id,
    label: provider.label,
    ready: ready.has(provider.id),
  }))
  const localServers: LocalServer[] = localSetup
    ? [
        {
          id: "ollama",
          label: "Ollama",
          url: localSetup.ollama.url,
          running: localSetup.ollama.running,
          site: "https://ollama.com/",
          how: "Ollama を入れて起動すると、ここからモデルを入れられます。",
          models: localSetup.ollama.models,
          model: localSetup.ollama.model,
        },
        ...localSetup.servers,
      ]
    : []
  const local: Choice[] = [
    ...localServers.map((server) => ({ id: server.id, label: server.label, ready: ready.has(server.id) })),
    { id: "custom", label: "その他の OpenAI 互換サーバー", ready: ready.has("custom") },
  ]

  function choose(id: string) {
    setPicked(id)
    if (ready.has(id)) onModel(id)
  }

  const provider = aiSetup?.providers.find((item) => item.id === picked)
  const server = localServers.find((item) => item.id === picked)
  const note = models.find((model) => model.id === picked)?.note

  const suffix = (choice: Choice, kind: "cloud" | "local") => {
    if (choice.ready) return ""
    if (offline && kind === "cloud") return "（オフライン中）"
    return kind === "cloud" ? "（キーが必要）" : "（起動していません）"
  }

  return (
    <div className="flex flex-col gap-3">
      <select
        id="settings-model-select"
        aria-labelledby="settings-ai"
        className="h-11 w-full rounded-xl border border-input bg-card px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
        value={picked}
        onChange={(event) => choose(event.target.value)}
      >
        <optgroup label="ネットの AI">
          {cloud.map((choice) => (
            <option key={choice.id} value={choice.id}>
              {choice.label}
              {suffix(choice, "cloud")}
            </option>
          ))}
        </optgroup>
        <optgroup label="パソコンの中の AI（キー不要）">
          {local.map((choice) => (
            <option key={choice.id} value={choice.id}>
              {choice.label}
              {suffix(choice, "local")}
            </option>
          ))}
        </optgroup>
        <optgroup label="お試し">
          <option value="demo">デモ（キー不要・回答の品質はありません）</option>
        </optgroup>
      </select>
      {modelLocked ? (
        <p className="text-[0.8rem] text-muted-foreground">いま返事を作っています。切りかえた AI は、次に送るメッセージから使います。</p>
      ) : null}
      {picked !== modelId && ready.has(picked) === false ? (
        <p className="text-[0.8rem] text-muted-foreground">下の手順でつなぐと、この AI に切りかわります。</p>
      ) : null}

      {provider && !(offline && !ready.has(provider.id)) ? (
        <AiKeyCard
          key={`${provider.id}-${provider.configured}`}
          provider={provider}
          featured={!provider.configured}
          onConnect={props.onConnectAi}
          onDisconnect={props.onDisconnectAi}
        />
      ) : null}
      {server && localSetup ? (
        <LocalServerCard
          key={server.id}
          server={server}
          onRefresh={() => props.onRefreshLocal(server.id)}
          onChoose={(model) => props.onChooseModel(server.id, model)}
          ollama={
            server.id === "ollama"
              ? {
                  recommended: localSetup.ollama.recommended,
                  sizes: localSetup.ollama.sizes,
                  pull: localSetup.ollama.pull,
                  onPull: props.onPullModel,
                }
              : undefined
          }
        />
      ) : null}
      {picked === "custom" && localSetup ? (
        <CustomServerForm key="custom" setup={localSetup} onSave={props.onSaveCustomServer} onRemove={props.onRemoveCustomServer} />
      ) : null}
      {offline && provider && !ready.has(provider.id) ? (
        <p className="text-[0.8rem] text-muted-foreground">オフラインモードの間は、ネットの AI は使えません。</p>
      ) : null}
      {picked === "demo" && note ? <p className="text-[0.8rem] text-muted-foreground">{note}</p> : null}

      {localSetup ? <OfflineToggle offline={offline} onChange={props.onOffline} /> : null}
    </div>
  )
}
