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

export type RoutinePreset = {
  id: string
  label: string
  schedule: string
  schedule_kind: string
}

export type RoutineConfirmation = {
  request_id: string
  tool: string
  risk: string
  summary: string
  arguments: Record<string, unknown>
}

export type RoutineRun = {
  id: string
  status: string
  snippet: string
  started_at: string
  finished_at: string | null
}

export type Routine = {
  id: string
  name: string
  prompt: string
  schedule_kind: string
  schedule: string
  schedule_label: string
  timezone: string
  enabled: boolean
  notify_line: boolean
  last_run: string | null
  next_run: string | null
  model_id: string
  conversation_id: string
  last_status: string | null
  last_snippet: string | null
  recent_runs: RoutineRun[]
  pending_confirmation: RoutineConfirmation | null
}

export type ConnectorStatus = "not_configured" | "not_connected" | "connected"

export type Connector = {
  id: string
  label: string
  auth_kind: "oauth" | "token"
  status: ConnectorStatus
  setup_instructions: string | null
  note?: string | null
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
