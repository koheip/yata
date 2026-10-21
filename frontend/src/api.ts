import type { ChatMessage, Conversation, Fact, ModelInfo, Routine, RoutinePreset, ServerEvent } from "./types"

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

export function createConversation(modelId: string) {
  return request<Conversation>("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  })
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
}) {
  return request<Routine>("/api/routines", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
): Promise<void> {
  const response = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
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
