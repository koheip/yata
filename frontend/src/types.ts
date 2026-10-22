export type ModelInfo = {
  id: string
  label: string
  provider: string
  upstream_model: string
  ready: boolean
  note: string | null
  /** パソコンの中で動く AI か */
  local: boolean
}

export type Conversation = {
  id: string
  title: string
  model_id: string
  bot_id: string
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
  bot_id: string
  last_status: string | null
  last_snippet: string | null
  recent_runs: RoutineRun[]
  pending_confirmation: RoutineConfirmation | null
}

export type Bot = {
  id: string
  name: string
  job: string
  color: string
  accessory: string
  is_default: boolean
  created_at: string
}

export type BotInput = {
  name: string
  job: string
  color: string
  accessory: string
}

export type LookOption = {
  id: string
  label: string
}

export type AiProvider = {
  id: string
  label: string
  badge: string
  key_url: string
  steps: string[]
  configured: boolean
  source: "app" | "env" | null
  /** 「ほかの AI」にまとめて出すもの */
  more: boolean
  /** つないだときに選んだモデル名 */
  model: string | null
}

export type LocalServer = {
  id: string
  label: string
  url: string
  site: string
  how: string
  running: boolean
  /** サーバーに入っているモデル */
  models: string[]
  /** 選んでいるモデル。空なら読み込まれているもの */
  model: string
}

export type OllamaPull = {
  state: "idle" | "running" | "done" | "error"
  model?: string
  message?: string
  completed?: number
  total?: number
}

export type LocalSetup = {
  offline: boolean
  ollama: {
    url: string
    running: boolean
    models: string[]
    sizes: Record<string, number | null>
    model: string
    recommended: { name: string; note: string }[]
    pull: OllamaPull
  }
  servers: LocalServer[]
  custom: { base_url: string; model: string; has_key: boolean; running: boolean }
}

export type AiSetup = {
  providers: AiProvider[]
  needs_setup: boolean
}

export type ConnectorSetupField = {
  name: string
  label: string
  secret: boolean
  optional: boolean
  configured: boolean
  source: "app" | "env" | null
}

export type ConnectorSetup = {
  id: string
  label: string
  advanced: boolean
  restart_required: boolean
  key_url: string
  steps: string[]
  fields: ConnectorSetupField[]
  configured: boolean
  from_app: boolean
}

export type ConnectorSetupList = {
  setups: ConnectorSetup[]
  connector_to_setup: Record<string, string>
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
