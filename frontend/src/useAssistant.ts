import { useCallback, useEffect, useRef, useState } from "react"
import {
  createConversation,
  deleteConversation,
  deleteFact,
  fetchModels,
  getConversation,
  listConversations,
  listFacts,
  resolveConfirmation,
  streamMessage,
} from "./api"
import type { ChatMessage, ConfirmRequest, Conversation, Fact, ModelInfo, ServerEvent, Step, ToolStep } from "./types"

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return {}
}

export function useAssistant() {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [modelId, setModelId] = useState("demo")
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [facts, setFacts] = useState<Fact[]>([])
  const [draft, setDraft] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)
  const confirmResolver = useRef<((approved: boolean) => void) | null>(null)
  const sendingRef = useRef(false)

  const selected = models.find((model) => model.id === modelId) ?? null

  const refreshLists = useCallback(async () => {
    const [conversationData, factData] = await Promise.all([listConversations(), listFacts()])
    setConversations(conversationData.conversations)
    setFacts(factData.facts)
  }, [])

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
    if (event.type === "note") {
      const step: Step = { type: "note", text: String(event.text ?? "") }
      patchAssistant(assistantId, (message) => ({ ...message, steps: [...message.steps, step] }))
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
      patchAssistant(assistantId, (message) => ({ ...message, steps: [...message.steps, step] }))
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
      if (models.some((model) => model.id === detail.model_id)) setModelId(detail.model_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "会話を開けませんでした。")
    }
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
    if (selected && !selected.ready) {
      setError(selected.note ?? "このモデルはまだ使えません。")
      return
    }
    setError(null)
    sendingRef.current = true
    setStreaming(true)
    let conversationId = activeId
    try {
      if (!conversationId) {
        const created = await createConversation(modelId)
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
      await streamMessage(conversationId, content, modelId, (event) => handleEvent(assistantId, event))
    } catch (err) {
      setError(err instanceof Error ? err.message : "送信に失敗しました。")
    } finally {
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

  return {
    models,
    modelId,
    setModelId,
    selected,
    conversations,
    activeId,
    messages,
    facts,
    draft,
    setDraft,
    streaming,
    loading,
    error,
    confirm,
    decide,
    sidebarOpen,
    setSidebarOpen,
    pendingDelete,
    setPendingDelete,
    openConversation,
    startNewChat,
    send,
    removeConversation,
    removeFact,
  }
}
