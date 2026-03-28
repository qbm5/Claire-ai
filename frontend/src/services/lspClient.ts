/**
 * Lightweight LSP client that bridges Monaco editors to a pylsp backend
 * over a single WebSocket connection.
 *
 * Public API (called by CodeEditor):
 *   didOpen(uri, languageId, text)
 *   didChange(uri, text)
 *   didClose(uri)
 *
 * Registers Monaco providers once for 'python' language.
 */

import * as monaco from 'monaco-editor'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PendingRequest {
  resolve: (result: any) => void
  reject: (err: Error) => void
  timer: ReturnType<typeof setTimeout>
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let ws: WebSocket | null = null
let nextId = 1
const pending = new Map<number, PendingRequest>()
const documentVersions = new Map<string, number>()   // uri → version
const documentContents = new Map<string, string>()    // uri → last-sent text
let serverReady = false
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let providersRegistered = false

// ---------------------------------------------------------------------------
// WebSocket connection
// ---------------------------------------------------------------------------

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/lsp`
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return

  ws = new WebSocket(wsUrl())

  ws.onopen = () => {
    console.log('[LSP] WebSocket connected, sending initialize...')
    // Send initialize
    sendRequest('initialize', {
      processId: null,
      capabilities: {
        textDocument: {
          completion: { completionItem: { snippetSupport: false } },
          hover: { contentFormat: ['markdown', 'plaintext'] },
          signatureHelp: { signatureInformation: { documentationFormat: ['markdown', 'plaintext'] } },
          publishDiagnostics: { relatedInformation: false },
          synchronization: { didSave: false, willSave: false },
        },
      },
      rootUri: 'file:///workspace',
      workspaceFolders: null,
    }).then(() => {
      serverReady = true
      console.log('[LSP] Server ready, re-opening', documentContents.size, 'document(s)')
      sendNotification('initialized', {})
      // Re-open any tracked documents
      for (const [uri, text] of documentContents) {
        const version = documentVersions.get(uri) ?? 1
        sendNotification('textDocument/didOpen', {
          textDocument: { uri, languageId: 'python', version, text },
        })
      }
    }).catch((err) => {
      console.error('[LSP] Initialize failed:', err)
    })
  }

  ws.onmessage = (ev) => {
    let msg: any
    try { msg = JSON.parse(ev.data) } catch { return }

    // Response to a request we sent
    if ('id' in msg && pending.has(msg.id)) {
      const p = pending.get(msg.id)!
      pending.delete(msg.id)
      clearTimeout(p.timer)
      if (msg.error) {
        p.reject(new Error(msg.error.message ?? 'LSP error'))
      } else {
        p.resolve(msg.result)
      }
      return
    }

    // Server notification
    if (msg.method === 'textDocument/publishDiagnostics') {
      handleDiagnostics(msg.params)
    }
    // Ignore other notifications (window/logMessage etc.)
  }

  ws.onclose = (ev) => {
    console.log('[LSP] WebSocket closed, code:', ev.code, 'reason:', ev.reason)
    serverReady = false
    // Reject pending requests
    for (const [id, p] of pending) {
      clearTimeout(p.timer)
      p.reject(new Error('LSP connection closed'))
      pending.delete(id)
    }
    ws = null
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (documentVersions.size > 0) {
      console.log('[LSP] Will reconnect in 3s...')
      reconnectTimer = setTimeout(connect, 3000)
    }
  }

  ws.onerror = (ev) => {
    console.error('[LSP] WebSocket error:', ev)
    // onclose will fire next
  }
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    serverReady = false
    // Send shutdown + exit gracefully
    if (ws.readyState === WebSocket.OPEN) {
      sendRequest('shutdown', null).catch(() => {})
      sendNotification('exit', null)
    }
    ws.close()
    ws = null
  }
}

// ---------------------------------------------------------------------------
// JSON-RPC helpers
// ---------------------------------------------------------------------------

function sendRequest(method: string, params: any): Promise<any> {
  return new Promise((resolve, reject) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return reject(new Error('LSP not connected'))
    }
    const id = nextId++
    const timer = setTimeout(() => {
      pending.delete(id)
      reject(new Error(`LSP request ${method} timed out`))
    }, 10_000)
    pending.set(id, { resolve, reject, timer })
    ws.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }))
  })
}

function sendNotification(method: string, params: any) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ jsonrpc: '2.0', method, params }))
}

// ---------------------------------------------------------------------------
// Document sync (public API)
// ---------------------------------------------------------------------------

export function didOpen(uri: string, languageId: string, text: string) {
  console.log('[LSP] didOpen:', uri)
  const version = 1
  documentVersions.set(uri, version)
  documentContents.set(uri, text)

  if (!providersRegistered) {
    registerProviders()
    providersRegistered = true
    console.log('[LSP] Providers registered for python')
  }

  connect()

  if (serverReady) {
    sendNotification('textDocument/didOpen', {
      textDocument: { uri, languageId, version, text },
    })
  }
  // If not ready, onopen handler will re-send didOpen for all tracked docs
}

export function didChange(uri: string, text: string) {
  const prev = documentVersions.get(uri)
  if (prev === undefined) return
  const version = prev + 1
  documentVersions.set(uri, version)
  documentContents.set(uri, text)

  if (serverReady) {
    sendNotification('textDocument/didChange', {
      textDocument: { uri, version },
      contentChanges: [{ text }],
    })
  }
}

export function didClose(uri: string) {
  if (!documentVersions.has(uri)) return

  if (serverReady) {
    sendNotification('textDocument/didClose', {
      textDocument: { uri },
    })
  }

  documentVersions.delete(uri)
  documentContents.delete(uri)

  // Clear diagnostics for closed document
  const model = monaco.editor.getModels().find(m => m.uri.toString() === uri)
  if (model) {
    monaco.editor.setModelMarkers(model, 'pylsp', [])
  }

  // Disconnect when no documents remain
  if (documentVersions.size === 0) {
    disconnect()
  }
}

// ---------------------------------------------------------------------------
// Diagnostics handler
// ---------------------------------------------------------------------------

function handleDiagnostics(params: { uri: string; diagnostics: any[] }) {
  const model = monaco.editor.getModels().find(m => m.uri.toString() === params.uri)
  if (!model) return

  const markers: monaco.editor.IMarkerData[] = params.diagnostics.map(d => ({
    severity: lspSeverityToMonaco(d.severity),
    message: d.message,
    startLineNumber: d.range.start.line + 1,
    startColumn: d.range.start.character + 1,
    endLineNumber: d.range.end.line + 1,
    endColumn: d.range.end.character + 1,
    source: d.source ?? 'pylsp',
  }))

  monaco.editor.setModelMarkers(model, 'pylsp', markers)
}

function lspSeverityToMonaco(severity?: number): monaco.MarkerSeverity {
  switch (severity) {
    case 1: return monaco.MarkerSeverity.Error
    case 2: return monaco.MarkerSeverity.Warning
    case 3: return monaco.MarkerSeverity.Info
    case 4: return monaco.MarkerSeverity.Hint
    default: return monaco.MarkerSeverity.Info
  }
}

// ---------------------------------------------------------------------------
// LSP → Monaco type converters
// ---------------------------------------------------------------------------

function lspCompletionKindToMonaco(kind?: number): monaco.languages.CompletionItemKind {
  // LSP CompletionItemKind → Monaco CompletionItemKind
  const map: Record<number, monaco.languages.CompletionItemKind> = {
    1: monaco.languages.CompletionItemKind.Text,
    2: monaco.languages.CompletionItemKind.Method,
    3: monaco.languages.CompletionItemKind.Function,
    4: monaco.languages.CompletionItemKind.Constructor,
    5: monaco.languages.CompletionItemKind.Field,
    6: monaco.languages.CompletionItemKind.Variable,
    7: monaco.languages.CompletionItemKind.Class,
    8: monaco.languages.CompletionItemKind.Interface,
    9: monaco.languages.CompletionItemKind.Module,
    10: monaco.languages.CompletionItemKind.Property,
    11: monaco.languages.CompletionItemKind.Unit,
    12: monaco.languages.CompletionItemKind.Value,
    13: monaco.languages.CompletionItemKind.Enum,
    14: monaco.languages.CompletionItemKind.Keyword,
    15: monaco.languages.CompletionItemKind.Snippet,
    16: monaco.languages.CompletionItemKind.Color,
    17: monaco.languages.CompletionItemKind.File,
    18: monaco.languages.CompletionItemKind.Reference,
    19: monaco.languages.CompletionItemKind.Folder,
    20: monaco.languages.CompletionItemKind.EnumMember,
    21: monaco.languages.CompletionItemKind.Constant,
    22: monaco.languages.CompletionItemKind.Struct,
    23: monaco.languages.CompletionItemKind.Event,
    24: monaco.languages.CompletionItemKind.Operator,
    25: monaco.languages.CompletionItemKind.TypeParameter,
  }
  return map[kind ?? 1] ?? monaco.languages.CompletionItemKind.Text
}

function markupToMarkdown(doc: any): string {
  if (!doc) return ''
  if (typeof doc === 'string') return doc
  return doc.value ?? ''
}

// ---------------------------------------------------------------------------
// Monaco provider registration (once, globally for 'python')
// ---------------------------------------------------------------------------

function registerProviders() {
  // Completion
  monaco.languages.registerCompletionItemProvider('python', {
    triggerCharacters: ['.', '(', ','],
    async provideCompletionItems(model, position) {
      const uri = model.uri.toString()
      if (!documentVersions.has(uri) || !serverReady) return { suggestions: [] }

      try {
        const result = await sendRequest('textDocument/completion', {
          textDocument: { uri },
          position: { line: position.lineNumber - 1, character: position.column - 1 },
        })

        const items: any[] = Array.isArray(result) ? result : result?.items ?? []
        const word = model.getWordUntilPosition(position)
        const range = new monaco.Range(
          position.lineNumber, word.startColumn,
          position.lineNumber, word.endColumn,
        )

        const suggestions: monaco.languages.CompletionItem[] = items.map((item, i) => ({
          label: item.label,
          kind: lspCompletionKindToMonaco(item.kind),
          insertText: item.insertText ?? item.label,
          detail: item.detail ?? '',
          documentation: markupToMarkdown(item.documentation),
          range,
          sortText: item.sortText ?? String(i).padStart(5, '0'),
        }))

        return { suggestions }
      } catch {
        return { suggestions: [] }
      }
    },
  })

  // Hover
  monaco.languages.registerHoverProvider('python', {
    async provideHover(model, position) {
      const uri = model.uri.toString()
      if (!documentVersions.has(uri) || !serverReady) return null

      try {
        const result = await sendRequest('textDocument/hover', {
          textDocument: { uri },
          position: { line: position.lineNumber - 1, character: position.column - 1 },
        })

        if (!result?.contents) return null

        const contents: monaco.IMarkdownString[] = []
        const raw = result.contents
        if (typeof raw === 'string') {
          contents.push({ value: raw })
        } else if (raw.kind === 'markdown' || raw.kind === 'plaintext') {
          contents.push({ value: raw.value })
        } else if (raw.value) {
          contents.push({ value: `\`\`\`${raw.language ?? ''}\n${raw.value}\n\`\`\`` })
        } else if (Array.isArray(raw)) {
          for (const part of raw) {
            if (typeof part === 'string') {
              contents.push({ value: part })
            } else if (part.value) {
              contents.push({ value: `\`\`\`${part.language ?? ''}\n${part.value}\n\`\`\`` })
            }
          }
        }

        let range: monaco.Range | undefined
        if (result.range) {
          range = new monaco.Range(
            result.range.start.line + 1, result.range.start.character + 1,
            result.range.end.line + 1, result.range.end.character + 1,
          )
        }

        return { contents, range }
      } catch {
        return null
      }
    },
  })

  // Signature help
  monaco.languages.registerSignatureHelpProvider('python', {
    signatureHelpTriggerCharacters: ['(', ','],
    async provideSignatureHelp(model, position) {
      const uri = model.uri.toString()
      if (!documentVersions.has(uri) || !serverReady) return null

      try {
        const result = await sendRequest('textDocument/signatureHelp', {
          textDocument: { uri },
          position: { line: position.lineNumber - 1, character: position.column - 1 },
        })

        if (!result?.signatures?.length) return null

        const signatures: monaco.languages.SignatureInformation[] = result.signatures.map((sig: any) => ({
          label: sig.label,
          documentation: markupToMarkdown(sig.documentation),
          parameters: (sig.parameters ?? []).map((p: any) => ({
            label: p.label,
            documentation: markupToMarkdown(p.documentation),
          })),
        }))

        return {
          value: {
            signatures,
            activeSignature: result.activeSignature ?? 0,
            activeParameter: result.activeParameter ?? 0,
          },
          dispose() {},
        }
      } catch {
        return null
      }
    },
  })
}
