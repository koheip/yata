export type ModelInfo = {
  id: string
  label: string
  provider: string
  upstream_model: string
  ready: boolean
  note: string | null
}

export type Conversation = {
  id: string
  title: string
  model_id: string
  created_at: string
  updated_at: string
}

export type NoteStep = {
  type: "note"
  text: string
}

export type ToolStep = {
  type: "tool"
  id: string
  name: string
  arguments: Record<string, unknown>
  ok: boolean
  content: string
  image_url?: string | null
}

export type Step = NoteStep | ToolStep

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  steps: Step[]
}

export type Fact = {
  key: string
  value: string
  updated_at: string
}

export type ServerEvent = {
  type: string
  [key: string]: unknown
}

export type ConfirmRequest = {
  requestId: string
  tool: string
  risk: string
  summary: string
  arguments: Record<string, unknown>
}
