import type {
  AiProvider,
  AiSetup,
  LocalSetup,
  Bot,
  BotInput,
  ConnectorSetup,
  ConnectorSetupList,
  ChatMessage,
  LookOption,
  Connector,
  Conversation,
  Fact,
  ModelInfo,
  Routine,
  RoutinePreset,
  ServerEvent,
} from "./types"

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === "string" && body.detail) return body.detail
  } catch {
    // The body was not JSON.
  }
  return "通信に失敗しました。"
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) throw new Error(await errorMessage(response))
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function fetchModels() {
  return request<{ default_model_id: string; models: ModelInfo[] }>("/api/models")
}

export function listConversations() {
  return request<{ conversations: Conversation[] }>("/api/conversations")
}

export function createConversation(modelId: string, botId: string) {
  return request<Conversation>("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, bot_id: botId }),
  })
}

export function getAiSetup() {
  return request<AiSetup>("/api/setup/ai")
}

export function saveAiKey(providerId: string, key: string) {
  return request<AiProvider & { verified: boolean | null; message: string }>(`/api/setup/ai/${providerId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  })
}

export function removeAiKey(providerId: string) {
  return request<AiProvider>(`/api/setup/ai/${providerId}`, { method: "DELETE" })
}

export function getLocalSetup() {
  return request<LocalSetup>("/api/setup/local")
}

export function saveCustomLlm(body: { base_url: string; model: string; api_key: string }) {
  return request<LocalSetup>("/api/setup/local/custom", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function removeCustomLlm() {
  return request<LocalSetup>("/api/setup/local/custom", { method: "DELETE" })
}

export function chooseLocalModel(serverId: string, model: string) {
  return request<LocalSetup>(`/api/setup/local/${serverId}/model`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  })
}

export function pullOllamaModel(model: string) {
  return request<unknown>("/api/setup/local/ollama/pull", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  })
}

export function setOffline(enabled: boolean) {
  return request<LocalSetup>("/api/setup/offline", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  })
}

export function getConnectorSetups() {
  return request<ConnectorSetupList>("/api/setup/connectors")
}

export function saveConnectorSetup(setupId: string, values: Record<string, string>) {
  return request<ConnectorSetup & { message: string }>(`/api/setup/connectors/${setupId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  })
}

export function removeConnectorSetup(setupId: string) {
  return request<ConnectorSetup>(`/api/setup/connectors/${setupId}`, { method: "DELETE" })
}

export function quitApp() {
  return request<{ ok: boolean }>("/api/app/quit", { method: "POST" })
}

export function listBots() {
  return request<{ bots: Bot[]; colors: LookOption[]; accessories: LookOption[] }>("/api/bots")
}

export function createBot(body: BotInput) {
  return request<Bot>("/api/bots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function updateBot(id: string, body: Partial<BotInput>) {
  return request<Bot>(`/api/bots/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function deleteBot(id: string) {
  return request<void>(`/api/bots/${encodeURIComponent(id)}`, { method: "DELETE" })
}

export function getConversation(id: string) {
  return request<Conversation & { messages: ChatMessage[] }>(`/api/conversations/${id}`)
}

export function deleteConversation(id: string) {
  return request<void>(`/api/conversations/${id}`, { method: "DELETE" })
}

export function listFacts() {
  return request<{ facts: Fact[] }>("/api/facts")
}

export function deleteFact(key: string) {
  return request<void>(`/api/facts/${encodeURIComponent(key)}`, { method: "DELETE" })
}

export function listRoutines() {
  return request<{ presets: RoutinePreset[]; routines: Routine[] }>("/api/routines")
}

export function createRoutine(body: {
  name: string
  prompt: string
  preset?: string
  schedule?: string
  schedule_kind?: string
  model_id?: string
  bot_id?: string
}) {
  return request<Routine>("/api/routines", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function setRoutineNotifyLine(id: string, enabled: boolean) {
  return request<Routine>(`/api/routines/${id}/notify_line`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  })
}

export function pauseRoutine(id: string) {
  return request<Routine>(`/api/routines/${id}/pause`, { method: "POST" })
}

export function resumeRoutine(id: string) {
  return request<Routine>(`/api/routines/${id}/resume`, { method: "POST" })
}

export function deleteRoutine(id: string) {
  return request<void>(`/api/routines/${id}`, { method: "DELETE" })
}

export function listConnectors() {
  return request<{ connectors: Connector[] }>("/api/connectors")
}

export function connectConnector(id: string) {
  return request<{ authorize_url: string }>(`/api/connectors/${id}/connect`, { method: "POST" })
}

export function disconnectConnector(id: string) {
  return request<Connector>(`/api/connectors/${id}/disconnect`, { method: "POST" })
}

export function resolveConfirmation(requestId: string, approved: boolean) {
  return request<{ ok: boolean }>(`/api/confirmations/${requestId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  })
}

export async function streamMessage(
  conversationId: string,
  content: string,
  modelId: string,
  onEvent: (event: ServerEvent) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, model_id: modelId }),
  })
  if (!response.ok || !response.body) throw new Error(await errorMessage(response))

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split("\n\n")
    buffer = chunks.pop() ?? ""
    for (const chunk of chunks) {
      const data = chunk
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("")
      if (!data) continue
      await onEvent(JSON.parse(data) as ServerEvent)
    }
  }
}
