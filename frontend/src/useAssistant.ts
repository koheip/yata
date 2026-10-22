import { useCallback, useEffect, useRef, useState } from "react"
import {
  connectConnector,
  createBot,
  createConversation,
  deleteBot,
  listBots,
  updateBot,
  createRoutine,
  deleteConversation,
  deleteFact,
  deleteRoutine,
  disconnectConnector,
  fetchModels,
  getAiSetup,
  chooseLocalModel,
  getLocalSetup,
  pullOllamaModel,
  removeCustomLlm,
  saveCustomLlm,
  setOffline,
  getConnectorSetups,
  getConversation,
  removeConnectorSetup,
  saveConnectorSetup,
  removeAiKey,
  saveAiKey,
  listConnectors,
  listConversations,
  listFacts,
  listRoutines,
  pauseRoutine,
  resolveConfirmation,
  resumeRoutine,
  setRoutineNotifyLine,
  streamMessage,
} from "./api"
import type {
  AiSetup,
  LocalSetup,
  Bot,
  ConnectorSetupList,
  BotInput,
  ChatMessage,
  LookOption,
  RoutineConfirmation,
  ConfirmRequest,
  Connector,
  Conversation,
  Fact,
  ModelInfo,
  Routine,
  RoutinePreset,
  ServerEvent,
  Step,
  ToolStep,
} from "./types"

function looksLikeRoutine(text: string): boolean {
  const normalized = text.trim().replace(/[０-９]/g, (digit) => String.fromCharCode(digit.charCodeAt(0) - 0xfee0))
  return /^(?:ルーティン[:：]\s*)?(?:毎朝\s*\d{1,2}\s*時|毎週\s*月曜(?:日)?\s*\d{1,2}\s*時|毎時|1時間ごと)/.test(normalized)
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return {}
}

const BOT_KEY = "yata.selectedBot"

function loadSelectedBot(): string {
  try {
    return window.localStorage.getItem(BOT_KEY) ?? "yata"
  } catch {
    return "yata"
  }
}

function saveSelectedBot(id: string) {
  try {
    window.localStorage.setItem(BOT_KEY, id)
  } catch {
    // 保存できなくても、この画面の中では選んだボットのまま動く。
  }
}

export function useAssistant() {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [modelId, setModelId] = useState("demo")
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [facts, setFacts] = useState<Fact[]>([])
  const [routines, setRoutines] = useState<Routine[]>([])
  const [presets, setPresets] = useState<RoutinePreset[]>([])
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [bots, setBots] = useState<Bot[]>([])
  const [aiSetup, setAiSetup] = useState<AiSetup | null>(null)
  const [localSetup, setLocalSetup] = useState<LocalSetup | null>(null)
  const [connectorSetups, setConnectorSetups] = useState<ConnectorSetupList | null>(null)
  const [botColors, setBotColors] = useState<LookOption[]>([])
  const [botAccessories, setBotAccessories] = useState<LookOption[]>([])
  const [botId, setBotIdState] = useState<string>(loadSelectedBot)
  const [draft, setDraft] = useState("")
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  useEffect(() => {
    // 設定を開いたら、連携の状態（LINE の入り口など、裏で変わるもの）を読み直す。
    if (!settingsOpen) return
    let alive = true
    const load = () =>
      listConnectors().then(
        (data) => {
          if (alive) setConnectors(data.connectors)
        },
        () => undefined,
      )
    void load()
    const timer = window.setInterval(load, 5000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [settingsOpen])
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)
  const confirmResolver = useRef<((approved: boolean) => void) | null>(null)
  const sendingRef = useRef(false)
  const activeIdRef = useRef<string | null>(null)
  const streamingRef = useRef(false)
  const seenRuns = useRef<Record<string, string | null>>({})

  const selected = models.find((model) => model.id === modelId) ?? null
  const bot = bots.find((item) => item.id === botId) ?? bots.find((item) => item.is_default) ?? null

  function setBotId(id: string) {
    setBotIdState(id)
    saveSelectedBot(id)
  }
  activeIdRef.current = activeId
  streamingRef.current = streaming

  const refreshLists = useCallback(async () => {
    const [conversationData, factData, routineData, connectorData, botData, setupData, connectorSetupData] =
      await Promise.all([
        listConversations(),
        listFacts(),
        listRoutines(),
        listConnectors(),
        listBots(),
        getAiSetup(),
        getConnectorSetups(),
      ])
    setAiSetup(setupData)
    void getLocalSetup().then(setLocalSetup, () => undefined)
    setConnectorSetups(connectorSetupData)
    setBots(botData.bots)
    setBotColors(botData.colors)
    setBotAccessories(botData.accessories)
    setConversations(conversationData.conversations)
    setFacts(factData.facts)
    setRoutines(routineData.routines)
    setPresets(routineData.presets)
    setConnectors(connectorData.connectors)
    // ルーティンの確認待ちは、机の「許可待ち」に並べて利用者が開くのを待つ。
    for (const routine of routineData.routines) {
      const previous = seenRuns.current[routine.id]
      seenRuns.current[routine.id] = routine.last_run
      if (
        previous !== undefined &&
        previous !== routine.last_run &&
        routine.conversation_id === activeIdRef.current &&
        !streamingRef.current
      ) {
        const detail = await getConversation(routine.conversation_id)
        setActiveId(detail.id)
        setMessages(detail.messages)
      }
    }
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshLists().catch(() => {
        // A missed poll should not cover the transcript with an error.
      })
    }, 15000)
    const onFocus = () => {
      void refreshLists().catch(() => {})
    }
    window.addEventListener("focus", onFocus)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener("focus", onFocus)
    }
  }, [refreshLists])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const modelData = await fetchModels()
        if (cancelled) return
        setModels(modelData.models)
        const preferred =
          modelData.models.find((model) => model.id === modelData.default_model_id && model.ready) ??
          modelData.models.find((model) => model.ready)
        setModelId(preferred?.id ?? "demo")
        await refreshLists()
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "読み込みに失敗しました。")
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshLists])

  const askConfirm = useCallback((request: ConfirmRequest) => {
    setConfirm(request)
    return new Promise<boolean>((resolve) => {
      confirmResolver.current = resolve
    })
  }, [])

  const decide = useCallback((approved: boolean) => {
    const resolve = confirmResolver.current
    if (!resolve) return
    confirmResolver.current = null
    setConfirm(null)
    resolve(approved)
  }, [])

  function patchAssistant(id: string, updater: (message: ChatMessage) => ChatMessage) {
    setMessages((current) => current.map((message) => (message.id === id ? updater(message) : message)))
  }

  async function handleEvent(assistantId: string, event: ServerEvent) {
    if (event.type === "delta") {
      // できた文字から順に見せる。ツールを呼ぶ前の前置きだった場合は、あとの note で置きかわる。
      const text = String(event.text ?? "")
      patchAssistant(assistantId, (message) => ({ ...message, content: message.content + text }))
      return
    }
    if (event.type === "note") {
      const step: Step = { type: "note", text: String(event.text ?? "") }
      patchAssistant(assistantId, (message) => ({ ...message, content: "", steps: [...message.steps, step] }))
      return
    }
    if (event.type === "tool_call") {
      const step: ToolStep = {
        type: "tool",
        id: String(event.id ?? ""),
        name: String(event.name ?? ""),
        arguments: asRecord(event.arguments),
        ok: true,
        content: "",
      }
      patchAssistant(assistantId, (message) => ({ ...message, content: "", steps: [...message.steps, step] }))
      return
    }
    if (event.type === "tool_result") {
      const toolId = String(event.id ?? "")
      patchAssistant(assistantId, (message) => ({
        ...message,
        steps: message.steps.map((step) => {
          if (step.type !== "tool" || step.id !== toolId) return step
          return {
            ...step,
            ok: Boolean(event.ok),
            content: String(event.content ?? ""),
            image_url: typeof event.image_url === "string" ? event.image_url : null,
          }
        }),
      }))
      return
    }
    if (event.type === "confirmation_required") {
      const requestId = String(event.request_id ?? "")
      const approved = await askConfirm({
        requestId,
        tool: String(event.tool ?? ""),
        risk: String(event.risk ?? ""),
        summary: String(event.summary ?? ""),
        arguments: asRecord(event.arguments),
      })
      await resolveConfirmation(requestId, approved)
      return
    }
    if (event.type === "answer") {
      patchAssistant(assistantId, (message) => ({ ...message, content: String(event.content ?? "") }))
      return
    }
    if (event.type === "error") {
      const message = String(event.message ?? "エージェントが失敗しました。")
      setError(message)
      patchAssistant(assistantId, (current) => ({
        ...current,
        content: current.content || message,
      }))
    }
  }

  async function openConversation(id: string) {
    if (streaming) return
    setError(null)
    setSidebarOpen(false)
    try {
      const detail = await getConversation(id)
      setActiveId(detail.id)
      setMessages(detail.messages)
      if (detail.bot_id) setBotId(detail.bot_id)
      if (models.some((model) => model.id === detail.model_id)) setModelId(detail.model_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "会話を開けませんでした。")
    }
  }

  async function answerRoutineConfirmation(pending: RoutineConfirmation, approved: boolean) {
    try {
      await resolveConfirmation(pending.request_id, approved)
    } catch (err) {
      setError(err instanceof Error ? err.message : "許可を送れませんでした。")
    } finally {
      await refreshLists().catch(() => {})
    }
  }

  function reviewRoutineConfirmation(pending: RoutineConfirmation) {
    if (confirmResolver.current) return
    setConfirm({
      requestId: pending.request_id,
      tool: pending.tool,
      risk: pending.risk,
      summary: pending.summary,
      arguments: pending.arguments,
    })
    confirmResolver.current = (approved: boolean) => {
      void answerRoutineConfirmation(pending, approved)
    }
  }

  async function reloadModels(prefer?: string) {
    const modelData = await fetchModels()
    setModels(modelData.models)
    const preferred = prefer ? modelData.models.find((model) => model.id === prefer && model.ready) : undefined
    if (preferred) setModelId(preferred.id)
  }

  /** 画面で入れた API キーを保存し、その AI をすぐ使えるようにする。 */
  async function connectAi(providerId: string, key: string) {
    const result = await saveAiKey(providerId, key)
    await reloadModels(providerId)
    setAiSetup(await getAiSetup())
    return result
  }

  /** 連携のトークンなどを画面から保存し、すぐ使えるようにする。 */
  async function saveConnector(setupId: string, values: Record<string, string>) {
    const result = await saveConnectorSetup(setupId, values)
    await refreshLists()
    return result
  }

  async function removeConnector(setupId: string) {
    await removeConnectorSetup(setupId)
    await refreshLists()
  }

  /** パソコンの中の AI（LM Studio など）が動いているかを確かめ直す。 */
  async function refreshLocal(prefer?: string) {
    setLocalSetup(await getLocalSetup())
    await reloadModels(prefer)
  }

  /** パソコンの中の AI で使うモデルを選ぶ（空なら読み込まれているもの）。 */
  async function chooseModel(serverId: string, model: string) {
    setLocalSetup(await chooseLocalModel(serverId, model))
    await reloadModels(serverId)
  }

  /** Ollama にモデルを入れる。終わるまで進み具合を見に行き、終わったらそのモデルを使う。 */
  async function pullModel(model: string) {
    await pullOllamaModel(model)
    for (;;) {
      const setup = await getLocalSetup()
      setLocalSetup(setup)
      if (setup.ollama.pull.state !== "running") {
        if (setup.ollama.pull.state === "done") await chooseModel("ollama", model)
        else throw new Error(setup.ollama.pull.message ?? "モデルを入れられませんでした。")
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 1500))
    }
  }

  async function saveCustomServer(body: { base_url: string; model: string; api_key: string }) {
    setLocalSetup(await saveCustomLlm(body))
    await reloadModels("custom")
  }

  async function removeCustomServer() {
    setLocalSetup(await removeCustomLlm())
    await reloadModels()
  }

  async function changeOffline(enabled: boolean) {
    setLocalSetup(await setOffline(enabled))
    await reloadModels()
  }

  async function disconnectAi(providerId: string) {
    await removeAiKey(providerId)
    await reloadModels()
    setAiSetup(await getAiSetup())
  }

  function selectBot(id: string) {
    if (streaming) return
    setBotId(id)
    setActiveId(null)
    setMessages([])
    setError(null)
  }

  async function addBot(input: BotInput) {
    const created = await createBot(input)
    await refreshLists()
    selectBot(created.id)
    return created
  }

  async function editBot(id: string, input: Partial<BotInput>) {
    await updateBot(id, input)
    await refreshLists()
  }

  async function removeBot(id: string) {
    await deleteBot(id)
    setBotId("yata")
    await refreshLists()
  }

  /** 返事を待つのをやめる（パソコンの中の AI が重くて返事が来ないときなど）。 */
  function stop() {
    abortRef.current?.abort()
  }

  function startNewChat() {
    if (streaming) return
    setActiveId(null)
    setMessages([])
    setError(null)
    setSidebarOpen(false)
  }

  async function send(text?: string) {
    const content = (text ?? draft).trim()
    if (!content || streaming || sendingRef.current) return
    if (selected && !selected.ready && !looksLikeRoutine(content)) {
      setError(selected.note ?? "このモデルはまだ使えません。")
      return
    }
    setError(null)
    sendingRef.current = true
    setStreaming(true)
    let conversationId = activeId
    try {
      if (!conversationId) {
        const created = await createConversation(modelId, bot?.id ?? "yata")
        conversationId = created.id
        setActiveId(created.id)
        setConversations((current) => [created, ...current])
      }
      const assistantId = crypto.randomUUID()
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "user", content, steps: [] },
        { id: assistantId, role: "assistant", content: "", steps: [] },
      ])
      setDraft("")
      const controller = new AbortController()
      abortRef.current = controller
      await streamMessage(conversationId, content, modelId, (event) => handleEvent(assistantId, event), controller.signal)
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError("返事を止めました。")
      } else {
        setError(err instanceof Error ? err.message : "送信に失敗しました。")
      }
    } finally {
      abortRef.current = null
      sendingRef.current = false
      setStreaming(false)
      if (conversationId) {
        try {
          const detail = await getConversation(conversationId)
          setMessages(detail.messages)
          await refreshLists()
        } catch {
          // Keep the optimistic transcript if the reload fails.
        }
      }
    }
  }

  async function removeConversation() {
    if (!pendingDelete) return
    const target = pendingDelete
    setPendingDelete(null)
    await deleteConversation(target.id)
    if (activeId === target.id) {
      setActiveId(null)
      setMessages([])
    }
    await refreshLists()
  }

  async function removeFact(key: string) {
    await deleteFact(key)
    setFacts((current) => current.filter((fact) => fact.key !== key))
  }

  async function addRoutine(input: { name: string; prompt: string; preset?: string; schedule?: string }) {
    await createRoutine({ ...input, model_id: modelId, bot_id: bot?.id ?? "yata" })
    await refreshLists()
  }

  async function toggleRoutine(routine: Routine) {
    if (routine.enabled) await pauseRoutine(routine.id)
    else await resumeRoutine(routine.id)
    await refreshLists()
  }

  async function toggleRoutineLine(routine: Routine) {
    await setRoutineNotifyLine(routine.id, !routine.notify_line)
    await refreshLists()
  }

  async function removeRoutine(routine: Routine) {
    await deleteRoutine(routine.id)
    await refreshLists()
  }

  async function connectToConnector(connector: Connector) {
    try {
      const { authorize_url: authorizeUrl } = await connectConnector(connector.id)
      window.location.href = authorizeUrl
    } catch (err) {
      setError(err instanceof Error ? err.message : "連携の接続に失敗しました。")
    }
  }

  async function disconnectFromConnector(connector: Connector) {
    await disconnectConnector(connector.id)
    await refreshLists()
  }

  return {
    models,
    modelId,
    setModelId,
    selected,
    conversations,
    activeId,
    messages,
    facts,
    routines,
    presets,
    draft,
    setDraft,
    streaming,
    loading,
    error,
    confirm,
    decide,
    sidebarOpen,
    setSidebarOpen,
    settingsOpen,
    setSettingsOpen,
    pendingDelete,
    setPendingDelete,
    openConversation,
    startNewChat,
    send,
    stop,
    removeConversation,
    removeFact,
    addRoutine,
    toggleRoutine,
    toggleRoutineLine,
    removeRoutine,
    connectors,
    connectToConnector,
    disconnectFromConnector,
    answerRoutineConfirmation,
    reviewRoutineConfirmation,
    aiSetup,
    localSetup,
    refreshLocal,
    chooseModel,
    pullModel,
    saveCustomServer,
    removeCustomServer,
    changeOffline,
    connectorSetups,
    saveConnector,
    removeConnector,
    connectAi,
    disconnectAi,
    bots,
    bot,
    botColors,
    botAccessories,
    selectBot,
    addBot,
    editBot,
    removeBot,
  }
}
