/**
 * Import JSON Schema Validator
 *
 * Validates imported tool, trigger, and pipeline JSON files against
 * expected schemas before allowing import. Returns structured errors
 * so the UI can show exactly what's wrong.
 */

// ── Schema Definition Types ─────────────────────────────────────

type FieldType = 'string' | 'number' | 'boolean' | 'array' | 'object'

interface FieldSchema {
  type: FieldType | FieldType[]
  required?: boolean
  /** For arrays: schema of each item */
  items?: FieldSchema | Record<string, FieldSchema>
  /** For objects: schema of properties */
  properties?: Record<string, FieldSchema>
  /** Allowed values (enum) */
  enum?: (string | number | boolean)[]
  /** Minimum array length */
  minItems?: number
  /** Allow null in addition to declared type */
  nullable?: boolean
}

export interface ValidationError {
  path: string
  message: string
}

export interface ValidationResult {
  valid: boolean
  errors: ValidationError[]
}

// ── Core Validator ──────────────────────────────────────────────

function typeOf(val: unknown): FieldType {
  if (Array.isArray(val)) return 'array'
  if (val === null) return 'object' // null is typeof object
  return typeof val as FieldType
}

function validateValue(val: unknown, schema: FieldSchema, path: string, errors: ValidationError[]) {
  // Handle null
  if (val === null || val === undefined) {
    if (schema.required) {
      errors.push({ path, message: 'Required field is missing' })
    }
    return
  }

  // Type check
  const actualType = typeOf(val)
  const allowedTypes = Array.isArray(schema.type) ? schema.type : [schema.type]
  if (!allowedTypes.includes(actualType) && !(schema.nullable && val === null)) {
    errors.push({ path, message: `Expected ${allowedTypes.join(' | ')}, got ${actualType}` })
    return
  }

  // Enum check
  if (schema.enum && !schema.enum.includes(val as string | number | boolean)) {
    errors.push({ path, message: `Value ${JSON.stringify(val)} not in allowed values: ${schema.enum.join(', ')}` })
    return
  }

  // Array validation
  if (actualType === 'array' && Array.isArray(val)) {
    if (schema.minItems && val.length < schema.minItems) {
      errors.push({ path, message: `Array must have at least ${schema.minItems} item(s), got ${val.length}` })
    }
    if (schema.items) {
      // Distinguish FieldSchema (has type as string/array) from Record<string, FieldSchema>
      const isFieldSchema = 'type' in schema.items &&
        (typeof (schema.items as FieldSchema).type === 'string' || Array.isArray((schema.items as FieldSchema).type))
      for (let i = 0; i < val.length; i++) {
        if (isFieldSchema) {
          validateValue(val[i], schema.items as FieldSchema, `${path}[${i}]`, errors)
        } else {
          validateObject(val[i] as Record<string, unknown>, schema.items as Record<string, FieldSchema>, `${path}[${i}]`, errors)
        }
      }
    }
  }

  // Object validation
  if (actualType === 'object' && schema.properties && typeof val === 'object' && val !== null) {
    validateObject(val as Record<string, unknown>, schema.properties, path, errors)
  }
}

function validateObject(obj: Record<string, unknown>, schema: Record<string, FieldSchema>, basePath: string, errors: ValidationError[]) {
  if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) {
    errors.push({ path: basePath, message: `Expected object, got ${typeOf(obj)}` })
    return
  }

  for (const [key, fieldSchema] of Object.entries(schema)) {
    const path = basePath ? `${basePath}.${key}` : key
    const val = obj[key]

    if ((val === undefined || val === null) && fieldSchema.required) {
      errors.push({ path, message: 'Required field is missing' })
      continue
    }

    if (val !== undefined && val !== null) {
      validateValue(val, fieldSchema, path, errors)
    }
  }
}

function validate(data: unknown, schema: Record<string, FieldSchema>): ValidationResult {
  const errors: ValidationError[] = []

  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return { valid: false, errors: [{ path: '', message: 'Import data must be a JSON object' }] }
  }

  validateObject(data as Record<string, unknown>, schema, '', errors)
  return { valid: errors.length === 0, errors }
}

// ── Shared Sub-Schemas ──────────────────────────────────────────

const propertySchema: Record<string, FieldSchema> = {
  name: { type: 'string', required: true },
  value: { type: ['string', 'number', 'boolean'], required: false },
  type: { type: 'number', required: false },
}

const envVariableSchema: Record<string, FieldSchema> = {
  name: { type: 'string', required: true },
  description: { type: 'string', required: false },
  type: { type: 'number', required: false },
}

const mcpServerSchema: Record<string, FieldSchema> = {
  uid: { type: 'string', required: true },
  name: { type: 'string', required: true },
  transport: { type: 'number', required: true, enum: [0, 1] },
  command: { type: 'string', required: false },
  args: { type: 'array', required: false },
  url: { type: 'string', required: false },
  is_enabled: { type: 'boolean', required: false },
}

const agentFunctionSchema: Record<string, FieldSchema> = {
  uid: { type: 'string', required: true },
  name: { type: 'string', required: true },
  description: { type: 'string', required: false },
  is_enabled: { type: 'boolean', required: false },
  function_string: { type: 'string', required: true },
}

const responseFieldSchema: Record<string, FieldSchema> = {
  key: { type: 'string', required: true },
  type: { type: 'string', required: false, enum: ['string', 'number', 'boolean', 'object'] },
}

// ── Tool Schema ─────────────────────────────────────────────────

const toolSchema: Record<string, FieldSchema> = {
  _export_type: { type: 'string', required: true, enum: ['tool'] },
  name: { type: 'string', required: true },
  type: { type: 'number', required: true, enum: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] },
  is_enabled: { type: 'boolean', required: false },
  description: { type: 'string', required: false },
  prompt: { type: 'string', required: false },
  system_prompt: { type: 'string', required: false },
  model: { type: 'string', required: false },
  // Endpoint fields
  endpoint_url: { type: 'string', required: false },
  endpoint_method: { type: 'number', required: false, enum: [0, 1, 2, 3] },
  endpoint_timeout: { type: 'number', required: false },
  // Agent fields
  agent_functions: { type: 'array', required: false, items: agentFunctionSchema },
  pip_dependencies: { type: 'array', required: false, items: { type: 'string' } },
  env_variables: { type: 'array', required: false, items: envVariableSchema },
  mcp_servers: { type: 'array', required: false, items: mcpServerSchema },
  // Structure
  response_structure: { type: 'array', required: false, items: responseFieldSchema },
  request_inputs: { type: 'array', required: false, items: propertySchema },
  // Misc
  max_passes: { type: 'number', required: false },
  image_url: { type: 'string', required: false },
  export_uid: { type: 'string', required: false },
  export_version: { type: 'number', required: false },
}

// ── Trigger Schema ──────────────────────────────────────────────

const triggerConnectionSchema: Record<string, FieldSchema> = {
  id: { type: 'string', required: true },
  pipeline_id: { type: 'string', required: true },
  pipeline_name: { type: 'string', required: false },
  is_enabled: { type: 'boolean', required: false },
}

const triggerSchema: Record<string, FieldSchema> = {
  _export_type: { type: 'string', required: true, enum: ['trigger'] },
  name: { type: 'string', required: true },
  trigger_type: { type: 'number', required: true, enum: [0, 1, 2, 3, 4] },
  is_enabled: { type: 'boolean', required: false },
  description: { type: 'string', required: false },
  // Cron
  cron_expression: { type: 'string', required: false },
  // File watcher
  watch_path: { type: 'string', required: false },
  watch_patterns: { type: 'string', required: false },
  watch_events: { type: 'array', required: false, items: { type: 'string' } },
  // RSS
  rss_url: { type: 'string', required: false },
  rss_poll_minutes: { type: 'number', required: false },
  // Code
  code: { type: 'string', required: false },
  pip_dependencies: { type: 'array', required: false, items: { type: 'string' } },
  env_variables: { type: 'array', required: false, items: envVariableSchema },
  // Outputs & connections
  outputs: { type: 'array', required: false, items: propertySchema },
  connections: { type: 'array', required: false, items: triggerConnectionSchema },
  // Export
  export_uid: { type: 'string', required: false },
  export_version: { type: 'number', required: false },
}

// ── Pipeline Schema ─────────────────────────────────────────────

const edgeSchema: Record<string, FieldSchema> = {
  id: { type: 'string', required: true },
  source: { type: 'string', required: true },
  target: { type: 'string', required: true },
}

const stepToolSchema: Record<string, FieldSchema> = {
  type: { type: 'number', required: true, enum: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] },
  name: { type: 'string', required: false },
}

const pipelineStepSchema: Record<string, FieldSchema> = {
  id: { type: 'string', required: true },
  name: { type: 'string', required: true },
  tool_id: { type: 'string', required: false },
  tool: { type: 'object', required: false, properties: stepToolSchema },
  next_steps: { type: 'array', required: false, items: { type: 'string' } },
  next_steps_true: { type: 'array', required: false, items: { type: 'string' } },
  next_steps_false: { type: 'array', required: false, items: { type: 'string' } },
  inputs: { type: 'array', required: false, items: propertySchema },
  disabled: { type: 'boolean', required: false },
  pos_x: { type: 'number', required: false },
  pos_y: { type: 'number', required: false },
}

const memorySchema: Record<string, FieldSchema> = {
  id: { type: 'string', required: true },
  name: { type: 'string', required: true },
  type: { type: 'string', required: true, enum: ['short_term', 'long_term'] },
}

const pipelineSchema: Record<string, FieldSchema> = {
  _export_type: { type: 'string', required: true, enum: ['pipeline'] },
  name: { type: 'string', required: true },
  description: { type: 'string', required: false },
  steps: { type: 'array', required: true, minItems: 1, items: pipelineStepSchema },
  edges: { type: 'array', required: false, items: edgeSchema },
  inputs: { type: 'array', required: false, items: propertySchema },
  memories: { type: 'array', required: false, items: memorySchema },
  guidance: { type: 'string', required: false },
  // Embedded tools (optional)
  _tools: { type: 'array', required: false, items: {
    type: 'object',
    properties: {
      name: { type: 'string', required: true },
      type: { type: 'number', required: true },
    },
  }},
  // Export
  export_uid: { type: 'string', required: false },
  export_version: { type: 'number', required: false },
}

// ── Public API ──────────────────────────────────────────────────

export function validateToolImport(data: unknown): ValidationResult {
  return validate(data, toolSchema)
}

export function validateTriggerImport(data: unknown): ValidationResult {
  return validate(data, triggerSchema)
}

export function validatePipelineImport(data: unknown): ValidationResult {
  return validate(data, pipelineSchema)
}

/**
 * Compute resource status for import (new, update, or exists).
 */
export function computeResourceStatus(uid: string | undefined, version: number, existingList: { export_uid?: string; export_version?: number; id: string }[]) {
  if (!uid) return { status: 'new' as const }
  const existing = existingList.find(r => r.export_uid === uid)
  if (!existing) return { status: 'new' as const }
  if (version > (existing.export_version || 0)) {
    return { status: 'update' as const, existingVersion: existing.export_version || 0, existingId: existing.id }
  }
  return { status: 'exists' as const, existingVersion: existing.export_version || 0, existingId: existing.id }
}

/**
 * Auto-detect export type and validate accordingly.
 * Returns the detected type alongside the validation result.
 */
export function validateImport(data: unknown): ValidationResult & { detectedType?: string } {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return { valid: false, errors: [{ path: '', message: 'Import data must be a JSON object' }] }
  }

  const obj = data as Record<string, unknown>
  const exportType = obj._export_type

  if (!exportType || typeof exportType !== 'string') {
    return {
      valid: false,
      errors: [{ path: '_export_type', message: 'Missing _export_type field. This file may not be a valid export.' }],
    }
  }

  switch (exportType) {
    case 'tool':
      return { ...validateToolImport(data), detectedType: 'tool' }
    case 'trigger':
      return { ...validateTriggerImport(data), detectedType: 'trigger' }
    case 'pipeline':
      return { ...validatePipelineImport(data), detectedType: 'pipeline' }
    default:
      return {
        valid: false,
        errors: [{ path: '_export_type', message: `Unknown export type "${exportType}". Expected: tool, trigger, or pipeline.` }],
        detectedType: exportType,
      }
  }
}
