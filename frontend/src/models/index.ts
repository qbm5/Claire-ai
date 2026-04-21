// ── Enums ──────────────────────────────────────────────────────────

export enum ToolType {
  LLM = 0,
  Endpoint = 1,
  Pause = 2,
  Agent = 3,
  Pipeline = 4,
  If = 5,
  Parallel = 6,
  End = 7,
  Wait = 8,
  Start = 9,
  LoopCounter = 10,
  AskUser = 11,
  FileUpload = 12,
  FileDownload = 13,
  ClaudeCode = 15,
}

export enum EndpointMethod {
  GET = 0,
  POST = 1,
  PUT = 2,
  DELETE = 3,
}

export enum PropertyType {
  TEXT = 0,
  NUMBER = 1,
  BOOLEAN = 2,
  FILE = 3,
  DATE = 4,
  PASSWORD = 5,
  SELECT = 6,
}

export enum PipelineStatusType {
  Pending = 0,
  Running = 1,
  Completed = 2,
  Failed = 3,
  Paused = 4,
  WaitingForInput = 5,
}

// ── Shared ─────────────────────────────────────────────────────────

export interface Property {
  name: string
  value: any
  description?: string
  type?: PropertyType
  is_required?: boolean
  locked?: boolean
  index?: number
  is_default?: boolean
  data?: any
}

// ── Tools ──────────────────────────────────────────────────────────

export interface EnvVariable {
  name: string
  description: string
  type: PropertyType
}

export interface CustomSettingsGroup {
  resource_type: 'tool' | 'trigger'
  resource_id: string
  resource_name: string
  variables: { name: string; description: string; type: PropertyType; value: string }[]
}

export enum McpTransport { STDIO = 0, HTTP = 1 }

export interface McpServer {
  uid: string
  name: string
  transport: McpTransport
  command: string
  args: string[]
  url: string
  headers: { key: string; value: string }[]
  is_enabled: boolean
  allowed_tools: string[]
  discovered_tools: { name: string; description: string }[]
}

export interface ResponseField {
  key: string
  type: 'string' | 'number' | 'boolean' | 'object'
  children?: ResponseField[]
}

export interface AgentFunction {
  uid: string
  name: string
  description: string
  is_enabled: boolean
  is_deleted: boolean
  function_string: string
}

export interface AiTool {
  id: string
  name: string
  type: ToolType
  tag: string
  sort_index: number
  is_enabled: boolean
  description: string
  prompt: string
  system_prompt: string
  model: string
  chatbot_id: string
  endpoint_url: string
  endpoint_method: EndpointMethod
  endpoint_headers: string
  endpoint_body: string
  endpoint_query: string
  endpoint_timeout: number
  agent_functions: AgentFunction[]
  pip_dependencies: string[]
  env_variables: EnvVariable[]
  mcp_servers: McpServer[]
  // Claude Code Agent fields
  claude_code_allowed_tools: string[]
  claude_code_permission_mode: string
  claude_code_working_dir: string
  claude_code_bare: boolean
  claude_code_mcp_config: string
  claude_code_max_turns: number
  claude_code_timeout: number
  claude_code_json_schema: string
  claude_code_system_prompt_mode: string
  pipeline_id: string
  max_passes: number
  image_url: string
  response_structure: ResponseField[]
  request_inputs: Property[]
  export_uid?: string
  export_version?: number
  created_at?: string
  updated_at?: string
}

// ── Chatbots ───────────────────────────────────────────────────────

export interface ChatBot {
  id: string
  name: string
  description: string
  tag: string
  sort_index: number
  is_enabled: boolean
  is_deleted: boolean
  source_type: string
  source_folder: string
  source_texts: string[]
  github_owner: string
  github_repo: string
  github_branch: string
  github_folder: string
  model: string
  created_at?: string
  updated_at?: string
}

export interface ChatMessage {
  id: string
  role: string
  content: string
  sources: string[]
  timestamp: string
}

export interface ChatHistory {
  id: string
  chatbot_id: string
  user_id: string
  title: string
  messages: ChatMessage[]
  created_at?: string
  updated_at?: string
}

// ── Pipeline Memory ───────────────────────────────────────────────

export interface MemoryMessage {
  role: 'user' | 'assistant'
  content: string
  step_name: string
  timestamp: string
}

export interface AiPipelineMemory {
  id: string
  name: string
  type: 'short_term' | 'long_term'
  pos_x: number
  pos_y: number
  max_messages: number  // 0 = unlimited, otherwise max message pairs
  messages: MemoryMessage[]  // runtime state
}

// ── Pipelines ──────────────────────────────────────────────────────

export interface NodeEdge {
  id: string
  source: string
  target: string
  source_handle: string
  target_handle: string
}

export interface AICost {
  detail: string
  model: string
  input_token_count: number
  output_token_count: number
  input_cost: number
  output_cost: number
  total_cost: number
}

export interface AiPipelineStep {
  id: string
  name: string
  description: string
  next_steps: string[]
  next_steps_true: string[]
  next_steps_false: string[]
  is_start: boolean
  tool_id: string
  tool?: AiTool
  status: PipelineStatusType
  inputs: Property[]
  outputs: Property[]
  call_cost: AICost[]
  status_text: string
  pre_process: string
  post_process: string
  disabled: boolean
  tool_outputs: string[]
  pause_after: boolean
  retry_enabled: boolean
  max_retries: number
  validation_enabled: boolean
  validation_model: string
  memory_id: string
  pos_x: number
  pos_y: number
  split_count?: number
  iteration_outputs?: { input: string; output: string; agent_output?: string; cost?: AICost[] }[]
  prompt_used?: { system: string; user: string }
  resolved_inputs?: { name: string; value: string }[]
  execution_history?: {
    outputs: Property[]
    call_cost: AICost[]
    iteration_outputs?: { input: string; output: string; agent_output?: string; cost?: AICost[] }[]
    split_count?: number
    status_text: string
    prompt_used?: { system: string; user: string }
    resolved_inputs?: { name: string; value: string }[]
  }[]
}

export interface AiPipeline {
  id: string
  name: string
  description: string
  tag: string
  sort_index: number
  image_url: string
  steps: AiPipelineStep[]
  inputs: Property[]
  edges: NodeEdge[]
  memories: AiPipelineMemory[]
  guidance: string
  validation_model: string
  export_uid?: string
  export_version?: number
  created_at?: string
  updated_at?: string
}

export interface AiPipelineRun {
  id: string
  pipeline_id: string
  pipeline_snapshot?: AiPipeline
  steps: AiPipelineStep[]
  inputs: Property[]
  outputs: Property[]
  memories: AiPipelineMemory[]
  status: PipelineStatusType
  current_step: number
  guidance?: string
  total_cost?: number
  total_input_tokens?: number
  total_output_tokens?: number
  log_entries?: RunLogEntry[]
  created_at?: string
  completed_at?: string
}

// ── Triggers ──────────────────────────────────────────────────────

export enum TriggerType {
  Cron = 0,
  FileWatcher = 1,
  Webhook = 2,
  RSS = 3,
  Custom = 4,
}

export interface InputMapping {
  pipeline_input: string
  expression: string
}

export interface TriggerConnection {
  id: string
  pipeline_id: string
  pipeline_name: string
  is_enabled: boolean
  input_mappings: InputMapping[]
}

export interface AiTrigger {
  id: string
  name: string
  description: string
  tag: string
  sort_index: number
  is_enabled: boolean
  image_url: string
  trigger_type: TriggerType

  cron_expression: string
  watch_path: string
  watch_patterns: string
  watch_events: string[]
  rss_url: string
  rss_poll_minutes: number

  code: string
  pip_dependencies: string[]
  env_variables: EnvVariable[]

  outputs: Property[]
  connections: TriggerConnection[]

  last_fired_at: string
  last_status: string
  fire_count: number
  export_uid?: string
  export_version?: number
  created_at?: string
  updated_at?: string
}

export const TriggerTypeLabels: Record<TriggerType, string> = {
  [TriggerType.Cron]: 'Cron',
  [TriggerType.FileWatcher]: 'File Watcher',
  [TriggerType.Webhook]: 'Webhook',
  [TriggerType.RSS]: 'RSS',
  [TriggerType.Custom]: 'Custom',
}

// ── Models ────────────────────────────────────────────────────────

export interface Model {
  id: string
  model_id: string
  name: string
  provider: 'anthropic' | 'openai' | 'google' | 'xai' | 'local'
  input_cost: number
  output_cost: number
  sort_order?: number
  created_at?: string
  updated_at?: string
}

// ── Settings ───────────────────────────────────────────────────────

export interface Settings {
  ANTHROPIC_API_KEY: string
  OPENAI_API_KEY: string
  GOOGLE_API_KEY: string
  XAI_API_KEY: string
  LOCAL_LLM_URL: string
  LOCAL_LLM_API_KEY: string
  GITHUB_TOKEN: string
  DEFAULT_MODEL: string
  DB_TYPE: string
  MSSQL_CONNECTION_STRING: string
  POSTGRES_CONNECTION_STRING: string
  COSMOS_ENDPOINT: string
  COSMOS_KEY: string
  COSMOS_DATABASE: string
  AUTH_ENABLED: string
  GOOGLE_CLIENT_ID: string
  GOOGLE_CLIENT_SECRET: string
  MICROSOFT_CLIENT_ID: string
  MICROSOFT_CLIENT_SECRET: string
  TOOL_SAFE_MODE: string
  COMMUNITY_URL: string
  AZURE_STORAGE_CONNECTION_STRING: string
  AZURE_STORAGE_CONTAINER: string
  models: { id: string; name: string; provider: 'anthropic' | 'openai' | 'google' | 'xai' | 'local'; input_cost: number; output_cost: number }[]
}

// ── Auth ────────────────────────────────────────────────────────

export interface User {
  id: string
  username: string
  email: string
  role: string
  is_active?: boolean
  display_name?: string
  must_change_password?: boolean
  created_at?: string
}

export interface RolePermission {
  id: string
  resource_type: string
  can_create: boolean
  can_edit: boolean
  can_delete: boolean
  can_use: boolean
}

export interface UserPermission {
  id: string
  user_id: string
  resource_type: string
  can_create: boolean
  can_edit: boolean
  can_delete: boolean
}

export interface UserResourceAccess {
  [resource_type: string]: string[]
}

// ── Run Log ────────────────────────────────────────────────────────

export interface RunLogEntry {
  run_id: string
  step_id?: string
  timestamp: string
  level: 'info' | 'debug' | 'warn' | 'error'
  source: 'pipeline' | 'llm' | 'agent' | 'tool' | 'endpoint' | 'condition'
  message: string
  detail?: Record<string, any>
}

// ── Pip Result ─────────────────────────────────────────────────────

export interface PipResult {
  package: string
  success: boolean
  output: string
  error: string
}

// ── Helpers ────────────────────────────────────────────────────────

let _counter = 0
export function getUid(len = 8): string {
  _counter++
  return Math.random().toString(36).substring(2, 2 + len) + _counter.toString(36)
}

export function createTool(): AiTool {
  const uid = getUid()
  return {
    id: uid,
    name: `Tool ${uid}`,
    type: ToolType.LLM,
    tag: '',
    sort_index: 0,
    is_enabled: true,
    description: '',
    prompt: '',
    system_prompt: '',
    model: '',
    chatbot_id: '',
    endpoint_url: '',
    endpoint_method: EndpointMethod.GET,
    endpoint_headers: '',
    endpoint_body: '',
    endpoint_query: '',
    endpoint_timeout: 60,
    agent_functions: [],
    pip_dependencies: [],
    env_variables: [],
    mcp_servers: [],
    claude_code_allowed_tools: [],
    claude_code_permission_mode: 'default',
    claude_code_working_dir: '',
    claude_code_bare: true,
    claude_code_mcp_config: '',
    claude_code_max_turns: 0,
    claude_code_timeout: 600,
    claude_code_json_schema: '',
    claude_code_system_prompt_mode: 'append',
    pipeline_id: '',
    max_passes: 5,
    image_url: '',
    response_structure: [],
    request_inputs: [{ name: 'Input', value: '', is_required: true, locked: true, type: PropertyType.TEXT, is_default: true }],
    export_uid: getUid(),
    export_version: 1,
  }
}

export function createChatBot(): ChatBot {
  const uid = getUid()
  return {
    id: uid,
    name: `Bot ${uid}`,
    description: '',
    tag: '',
    sort_index: 0,
    is_enabled: true,
    is_deleted: false,
    source_type: 'text',
    source_folder: '',
    source_texts: [''],
    github_owner: '',
    github_repo: '',
    github_branch: 'main',
    github_folder: '',
    model: '',
  }
}

export function createPipeline(): AiPipeline {
  const uid = getUid()
  return {
    id: uid,
    name: `Pipeline ${uid}`,
    description: '',
    tag: '',
    sort_index: 0,
    image_url: '',
    steps: [],
    inputs: [{ name: 'Start', value: '', is_required: false, is_default: true, type: PropertyType.TEXT }],
    edges: [],
    memories: [],
    guidance: '',
    validation_model: '',
    export_uid: getUid(),
    export_version: 1,
  }
}

export function createPipelineStep(): AiPipelineStep {
  const uid = getUid()
  return {
    id: uid,
    name: `Step ${uid}`,
    description: '',
    next_steps: [],
    next_steps_true: [],
    next_steps_false: [],
    is_start: false,
    tool_id: '',
    status: PipelineStatusType.Pending,
    inputs: [{ name: 'Input', value: '', is_required: false, locked: true, type: PropertyType.TEXT, is_default: true }],
    outputs: [],
    call_cost: [],
    status_text: '',
    pre_process: `function process(input) {\n    return [input];\n}`,
    post_process: `function process(output) {\n    return output;\n}`,
    disabled: false,
    tool_outputs: [],
    pause_after: false,
    retry_enabled: false,
    max_retries: 1,
    validation_enabled: false,
    validation_model: '',
    memory_id: '',
    pos_x: 0,
    pos_y: 0,
  }
}

export function createPipelineRun(pipeline: AiPipeline): AiPipelineRun {
  const uid = getUid()
  return {
    id: uid,
    pipeline_id: pipeline.id,
    pipeline_snapshot: pipeline,
    steps: pipeline.steps.map(s => ({ ...s, status: PipelineStatusType.Pending, outputs: [], call_cost: [], tool_outputs: [] })),
    inputs: pipeline.inputs,
    outputs: [],
    memories: (pipeline.memories || []).map(m => ({ ...m, messages: [] })),
    status: PipelineStatusType.Pending,
    current_step: 0,
    guidance: pipeline.guidance,
    created_at: new Date().toISOString(),
  }
}

export function createPipelineMemory(type: 'short_term' | 'long_term' = 'short_term'): AiPipelineMemory {
  const uid = getUid()
  return {
    id: uid,
    name: type === 'short_term' ? 'Short Term Memory' : 'Long Term Memory',
    type,
    pos_x: 0,
    pos_y: 0,
    max_messages: 0,
    messages: [],
  }
}

export function createTrigger(): AiTrigger {
  const uid = getUid()
  return {
    id: uid,
    name: `Trigger ${uid}`,
    description: '',
    tag: '',
    sort_index: 0,
    is_enabled: false,
    image_url: '',
    trigger_type: TriggerType.Cron,
    cron_expression: '0 * * * *',
    watch_path: '',
    watch_patterns: '',
    watch_events: [],
    rss_url: '',
    rss_poll_minutes: 60,
    code: `def on_trigger(context: dict) -> dict:
    """Called when the trigger fires. Return a dict of outputs."""
    print(f"Trigger fired: {context.get('trigger_name')}")
    return context
`,
    pip_dependencies: [],
    env_variables: [],
    outputs: [],
    connections: [],
    last_fired_at: '',
    last_status: '',
    fire_count: 0,
    export_uid: getUid(),
    export_version: 1,
  }
}

export const StatusLabels: Record<PipelineStatusType, string> = {
  [PipelineStatusType.Pending]: 'Pending',
  [PipelineStatusType.Running]: 'Running',
  [PipelineStatusType.Completed]: 'Completed',
  [PipelineStatusType.Failed]: 'Failed',
  [PipelineStatusType.Paused]: 'Paused',
  [PipelineStatusType.WaitingForInput]: 'Waiting for Input',
}

export const StatusColors: Record<PipelineStatusType, string> = {
  [PipelineStatusType.Pending]: 'text-gray-400',
  [PipelineStatusType.Running]: 'text-blue-400',
  [PipelineStatusType.Completed]: 'text-green-400',
  [PipelineStatusType.Failed]: 'text-red-400',
  [PipelineStatusType.Paused]: 'text-yellow-400',
  [PipelineStatusType.WaitingForInput]: 'text-indigo-400',
}

export const ToolTypeLabels: Record<ToolType, string> = {
  [ToolType.LLM]: 'LLM',
  [ToolType.Endpoint]: 'Endpoint',
  [ToolType.Pause]: 'Pause',
  [ToolType.Agent]: 'Agent',
  [ToolType.Pipeline]: 'Pipeline',
  [ToolType.If]: 'If',
  [ToolType.Parallel]: 'Parallel',
  [ToolType.End]: 'End',
  [ToolType.Wait]: 'Wait',
  [ToolType.Start]: 'Start',
  [ToolType.LoopCounter]: 'Loop Counter',
  [ToolType.AskUser]: 'Ask User',
  [ToolType.FileUpload]: 'File Upload',
  [ToolType.FileDownload]: 'File Download',
  [ToolType.ClaudeCode]: 'Claude Code',
}

/** Magic IDs used for built-in pipeline step types (not saved tools). */
export const BASE_TOOL_ID = {
  LLM: '-1',
  ENDPOINT: '-2',
  IF: '-3',
  LOOP_COUNTER: '-4',
  END: '-5',
  WAIT: '-6',
  ASK_USER: '-7',
  FILE_UPLOAD: '-8',
  START: '-9',
  AI_TOOL: '-10',
  CLAUDE_CODE: '-11',
} as const

export type BaseToolId = typeof BASE_TOOL_ID[keyof typeof BASE_TOOL_ID]

/** Tool defaults for each built-in step type. Returns partial overrides to apply on a fresh createTool(). */
export function getBaseToolDefaults(typeId: string): { type: ToolType; name: string; prompt?: string; system_prompt?: string; max_passes?: number } | null {
  switch (typeId) {
    case BASE_TOOL_ID.LLM: return { type: ToolType.LLM, name: 'Base LLM', prompt: '{{Input}}' }
    case BASE_TOOL_ID.ENDPOINT: return { type: ToolType.Endpoint, name: 'Base Endpoint' }
    case BASE_TOOL_ID.IF: return { type: ToolType.If, name: 'If', system_prompt: 'You are a condition evaluator. Assess whether the described condition is true or false.', prompt: '{{Input}}' }
    case BASE_TOOL_ID.LOOP_COUNTER: return { type: ToolType.LoopCounter, name: 'Loop Counter', max_passes: 5 }
    case BASE_TOOL_ID.WAIT: return { type: ToolType.Wait, name: 'Wait' }
    case BASE_TOOL_ID.END: return { type: ToolType.End, name: 'End' }
    case BASE_TOOL_ID.ASK_USER: return { type: ToolType.AskUser, name: 'Ask User', prompt: '{{Input}}' }
    case BASE_TOOL_ID.FILE_UPLOAD: return { type: ToolType.FileUpload, name: 'File Upload', prompt: 'Upload your files' }
    case BASE_TOOL_ID.CLAUDE_CODE: return { type: ToolType.ClaudeCode, name: 'Claude Code', prompt: '{{Input}}' }
    case BASE_TOOL_ID.AI_TOOL: return { type: ToolType.LLM, name: 'Step' }
    case BASE_TOOL_ID.START: return { type: ToolType.Start, name: 'Start' }
    default: return null
  }
}

/** Short prefix for auto-naming steps. */
export function getBaseToolPrefix(typeId: string): string {
  switch (typeId) {
    case BASE_TOOL_ID.LLM: return 'LLM'
    case BASE_TOOL_ID.ENDPOINT: return 'EP'
    case BASE_TOOL_ID.IF: return 'If'
    case BASE_TOOL_ID.LOOP_COUNTER: return 'Loop'
    case BASE_TOOL_ID.WAIT: return 'Wait'
    case BASE_TOOL_ID.END: return 'End'
    case BASE_TOOL_ID.ASK_USER: return 'Ask'
    case BASE_TOOL_ID.FILE_UPLOAD: return 'Upload'
    case BASE_TOOL_ID.CLAUDE_CODE: return 'CC'
    case BASE_TOOL_ID.AI_TOOL: return 'Step'
    default: return 'Step'
  }
}
