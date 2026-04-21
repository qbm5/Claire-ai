<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const sections = [
  { id: 'overview', label: 'Overview' },
  { id: 'tools', label: 'Tools', children: [
    { id: 'tools-types', label: 'Tool Types' },
    { id: 'tools-inputs', label: 'Request Inputs' },
    { id: 'tools-templates', label: 'Template Variables' },
    { id: 'tools-response', label: 'Response Structures' },
    { id: 'tools-agent', label: 'Agent Functions' },
    { id: 'tools-env', label: 'Environment Variables' },
    { id: 'tools-pip', label: 'Pip Dependencies' },
    { id: 'tools-mcp', label: 'MCP Servers' },
    { id: 'tools-sandbox', label: 'Safe Mode & Sandbox' },
  ]},
  { id: 'pipelines', label: 'Pipelines', children: [
    { id: 'pipelines-overview', label: 'How Pipelines Work' },
    { id: 'pipelines-steps', label: 'Step Types' },
    { id: 'pipelines-flow', label: 'Flow Control' },
    { id: 'pipelines-context', label: 'Context & Variables' },
    { id: 'pipelines-interactive', label: 'Interactive Steps' },
  ]},
  { id: 'triggers', label: 'Triggers', children: [
    { id: 'triggers-types', label: 'Trigger Types' },
    { id: 'triggers-code', label: 'Trigger Code' },
    { id: 'triggers-connections', label: 'Pipeline Connections' },
  ]},
  { id: 'claude-code', label: 'Claude Code Agent', children: [
    { id: 'claude-code-overview', label: 'How It Works' },
    { id: 'claude-code-config', label: 'Configuration' },
  ]},
  { id: 'settings', label: 'Settings', children: [
    { id: 'settings-general', label: 'General Settings' },
    { id: 'settings-models', label: 'Models' },
    { id: 'settings-custom', label: 'Custom Variables' },
  ]},
]

const activeSection = ref('overview')
const expandedSections = ref<Set<string>>(new Set(['tools']))

function toggleSection(id: string) {
  if (expandedSections.value.has(id)) {
    expandedSections.value.delete(id)
  } else {
    expandedSections.value.add(id)
  }
}

function scrollTo(id: string) {
  activeSection.value = id
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  // Expand parent if clicking a child
  for (const s of sections) {
    if (s.children?.some(c => c.id === id)) {
      expandedSections.value.add(s.id)
    }
  }
}

let scrollContainer: HTMLElement | null = null

function handleScroll() {
  if (!scrollContainer) return
  const containerRect = scrollContainer.getBoundingClientRect()
  const threshold = containerRect.top + 80
  const allIds = sections.flatMap(s => [s.id, ...(s.children?.map(c => c.id) || [])])
  for (let i = allIds.length - 1; i >= 0; i--) {
    const el = document.getElementById(allIds[i])
    if (el && el.getBoundingClientRect().top <= threshold) {
      activeSection.value = allIds[i]
      break
    }
  }
}

onMounted(() => {
  // Find the parent scroll container (App.vue's <main>)
  scrollContainer = document.querySelector('main.overflow-auto') as HTMLElement
  if (scrollContainer) {
    scrollContainer.addEventListener('scroll', handleScroll)
  }
  if (route.hash) {
    nextTick(() => scrollTo(route.hash.slice(1)))
  }
})

onUnmounted(() => {
  if (scrollContainer) {
    scrollContainer.removeEventListener('scroll', handleScroll)
  }
})

watch(() => route.hash, (hash) => {
  if (hash) nextTick(() => scrollTo(hash.slice(1)))
})
</script>

<template>
  <div class="flex min-h-full">
    <!-- Sidebar Navigation -->
    <nav class="w-56 shrink-0 border-r border-gray-800 overflow-y-auto py-4 px-3 bg-gray-950/50 sticky top-0 h-[calc(100vh-3rem)]">
      <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider px-2 mb-3">Documentation</div>
      <ul class="space-y-0.5">
        <template v-for="section in sections" :key="section.id">
          <li>
            <button
              v-if="section.children"
              @click="toggleSection(section.id); scrollTo(section.id)"
              class="w-full flex items-center justify-between px-2 py-1.5 rounded text-sm transition-colors"
              :class="activeSection === section.id ? 'bg-blue-600/20 text-blue-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'"
            >
              <span>{{ section.label }}</span>
              <svg class="w-3.5 h-3.5 transition-transform" :class="expandedSections.has(section.id) ? 'rotate-90' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7" /></svg>
            </button>
            <button
              v-else
              @click="scrollTo(section.id)"
              class="w-full text-left px-2 py-1.5 rounded text-sm transition-colors"
              :class="activeSection === section.id ? 'bg-blue-600/20 text-blue-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'"
            >
              {{ section.label }}
            </button>
            <ul v-if="section.children && expandedSections.has(section.id)" class="ml-3 mt-0.5 space-y-0.5 border-l border-gray-800 pl-2">
              <li v-for="child in section.children" :key="child.id">
                <button
                  @click="scrollTo(child.id)"
                  class="w-full text-left px-2 py-1 rounded text-xs transition-colors"
                  :class="activeSection === child.id ? 'text-blue-400 bg-blue-600/10' : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/50'"
                >
                  {{ child.label }}
                </button>
              </li>
            </ul>
          </li>
        </template>
      </ul>
    </nav>

    <!-- Content -->
    <main class="flex-1 px-8 py-6">
      <div class="max-w-3xl mx-auto">

        <!-- OVERVIEW -->
        <section id="overview" class="mb-16">
          <h1 class="text-2xl font-bold text-gray-50 mb-2">Claire Documentation</h1>
          <p class="text-gray-400 mb-6">An AI orchestration platform for building tools, pipelines, and triggers powered by Claude.</p>

          <div class="grid grid-cols-2 gap-3 mb-6">
            <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div class="text-sm font-semibold text-blue-400 mb-1">Tools</div>
              <p class="text-xs text-gray-500">Reusable building blocks: LLM prompts, API endpoints, and agentic Python functions that Claude can call.</p>
            </div>
            <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div class="text-sm font-semibold text-purple-400 mb-1">Pipelines</div>
              <p class="text-xs text-gray-500">Visual workflows that chain tools together with branching, loops, and user interaction steps.</p>
            </div>
            <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div class="text-sm font-semibold text-amber-400 mb-1">Triggers</div>
              <p class="text-xs text-gray-500">Event sources &mdash; cron schedules, webhooks, file watchers, RSS feeds &mdash; that automatically fire pipelines.</p>
            </div>
            <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div class="text-sm font-semibold text-cyan-400 mb-1">Claude Code Agent</div>
              <p class="text-xs text-gray-500">Run Claude Code CLI in headless mode to perform coding tasks: file editing, code generation, analysis, and more with real-time streaming.</p>
            </div>
          </div>

          <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-4 text-xs text-gray-500">
            <span class="text-gray-400 font-medium">How it fits together:</span> You create <strong class="text-gray-300">Tools</strong> as individual capabilities (including Claude Code agents). You wire them into <strong class="text-gray-300">Pipelines</strong> for repeatable workflows. <strong class="text-gray-300">Triggers</strong> automate when those pipelines run.
          </div>

          <div class="mt-6 rounded-lg overflow-hidden border border-gray-800">
            <img src="/docs/dashboard.png" alt="Dashboard overview" class="w-full" />
            <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">The Dashboard shows real-time stats, active runs, processes, and cost tracking.</div>
          </div>
        </section>

        <!-- TOOLS -->
        <section id="tools" class="mb-16">
          <h2 class="text-xl font-bold text-gray-50 mb-1">Tools</h2>
          <p class="text-gray-400 text-sm mb-4">Tools are the fundamental building blocks of the platform. Each tool is a self-contained unit that takes inputs, does work, and produces output.</p>

          <div class="mb-6 rounded-lg overflow-hidden border border-gray-800">
            <img src="/docs/tools.png" alt="Tools list view" class="w-full" />
            <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">The Tools list shows all your tools with type badges, descriptions, and quick actions.</div>
          </div>

          <!-- Tool Types -->
          <div id="tools-types" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Tool Types</h3>

            <div class="space-y-4">
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-blue-900/40 text-blue-400 border border-blue-800">LLM</span>
                  <span class="text-sm font-medium text-gray-50">Prompt-based tool</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">Sends a prompt to Claude (or another model) and returns the response. Best for text generation, analysis, summarization, and content transformation.</p>
                <div class="text-xs text-gray-600">Configure: prompt, system prompt, model selection, optional response structure for JSON output.</div>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-green-900/40 text-green-400 border border-green-800">Endpoint</span>
                  <span class="text-sm font-medium text-gray-50">HTTP request tool</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">Makes HTTP requests to external APIs or services. Supports GET, POST, PUT, DELETE methods with template variable substitution in URLs, headers, query params, and body.</p>
                <div class="text-xs text-gray-600">Configure: URL, method, headers, query parameters, request body, response structure.</div>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-purple-900/40 text-purple-400 border border-purple-800">Agent</span>
                  <span class="text-sm font-medium text-gray-50">Agentic tool with Python functions</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">The most powerful tool type. Claude runs in an agentic loop, calling your custom Python functions as tools. The loop continues until Claude returns a final text response.</p>
                <div class="text-xs text-gray-600">Configure: system prompt, Python functions, environment variables, pip dependencies, MCP servers.</div>
              </div>
            </div>
          </div>

          <!-- Request Inputs -->
          <div id="tools-inputs" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Request Inputs</h3>
            <p class="text-xs text-gray-400 mb-3">Request inputs are the parameters a user provides each time they run a tool. Each input becomes a template variable available in your tool's configuration.</p>

            <div class="bg-gray-950 border border-gray-800 rounded-lg overflow-hidden mb-3">
              <table class="w-full text-xs">
                <thead><tr class="border-b border-gray-800 text-gray-500">
                  <th class="text-left px-3 py-2 font-medium">Property</th>
                  <th class="text-left px-3 py-2 font-medium">Description</th>
                </tr></thead>
                <tbody class="text-gray-400">
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300 font-mono">name</td><td class="px-3 py-1.5">Display name and template variable key</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300 font-mono">description</td><td class="px-3 py-1.5">Help text shown to the user</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300 font-mono">type</td><td class="px-3 py-1.5">Text, Number, Boolean, File, Date, Password, or Select</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300 font-mono">is_required</td><td class="px-3 py-1.5">Whether the input must be provided</td></tr>
                  <tr><td class="px-3 py-1.5 text-gray-300 font-mono">is_default</td><td class="px-3 py-1.5">Marks the primary input (one per tool)</td></tr>
                </tbody>
              </table>
            </div>
            <p class="text-xs text-gray-500">An input named <code class="text-gray-400 bg-gray-800 px-1 rounded">Query</code> becomes available as <code class="text-gray-400 bg-gray-800 px-1 rounded" v-pre>{{Query}}</code> in prompts, URLs, headers, and request bodies.</p>
          </div>

          <!-- Template Variables -->
          <div id="tools-templates" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Template Variables</h3>
            <p class="text-xs text-gray-400 mb-3">Template variables use double-brace syntax and are resolved at runtime. They work in prompts, URLs, headers, query params, and request bodies.</p>

            <div class="bg-gray-950 border border-gray-800 rounded-lg p-3 font-mono text-xs space-y-1.5 mb-3">
              <div><span class="text-blue-400" v-pre>{{InputName}}</span> <span class="text-gray-600">&mdash; value of a request input</span></div>
              <div><span class="text-blue-400" v-pre>{{StepName}}</span> <span class="text-gray-600">&mdash; output of a previous pipeline step</span></div>
              <div><span class="text-blue-400" v-pre>{{StepName.field}}</span> <span class="text-gray-600">&mdash; dot notation into JSON output</span></div>
              <div><span class="text-blue-400" v-pre>{{ArrayName[0]}}</span> <span class="text-gray-600">&mdash; first element of an array</span></div>
              <div><span class="text-blue-400" v-pre>{{ArrayName[-1]}}</span> <span class="text-gray-600">&mdash; last element of an array</span></div>
              <div><span class="text-blue-400" v-pre>{{ArrayName[@]}}</span> <span class="text-gray-600">&mdash; current item (in loop context)</span></div>
            </div>

            <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-3 text-xs text-gray-500">
              <span class="text-amber-400 font-medium">Note:</span> Template variables are case-sensitive. The name must exactly match the input or step name as defined.
            </div>
          </div>

          <!-- Response Structures -->
          <div id="tools-response" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Response Structures</h3>
            <p class="text-xs text-gray-400 mb-3">Response structures define the expected shape of a tool's output. They're optional but powerful.</p>

            <ul class="text-xs text-gray-400 space-y-1.5 mb-3 ml-4 list-disc">
              <li><strong class="text-gray-300">LLM &amp; Agent tools:</strong> Claude is forced to return structured JSON matching the schema via <code class="text-gray-400 bg-gray-800 px-1 rounded">tool_use</code>. This guarantees you get the exact fields you need.</li>
              <li><strong class="text-gray-300">Endpoint tools:</strong> Defines the expected API response shape so downstream pipeline steps know what fields are available.</li>
            </ul>

            <p class="text-xs text-gray-400 mb-2">Each field in a response structure has:</p>
            <div class="bg-gray-950 border border-gray-800 rounded-lg p-3 font-mono text-xs space-y-1 mb-3">
              <div><span class="text-green-400">key</span>: <span class="text-gray-500">field name (e.g. "summary", "items")</span></div>
              <div><span class="text-green-400">type</span>: <span class="text-gray-500">string | number | boolean | object</span></div>
              <div><span class="text-green-400">description</span>: <span class="text-gray-500">guides the LLM on what to put here</span></div>
              <div><span class="text-green-400">children</span>: <span class="text-gray-500">nested fields (for object type)</span></div>
            </div>
            <p class="text-xs text-gray-500">Downstream pipeline steps can access individual fields with dot notation: <code class="text-gray-400 bg-gray-800 px-1 rounded" v-pre>{{ToolStep.summary}}</code></p>
          </div>

          <!-- Agent Functions -->
          <div id="tools-agent" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Agent Functions</h3>
            <p class="text-xs text-gray-400 mb-3">Agent tools expose Python functions that Claude can call in a loop. Each function file is saved to disk and loaded at runtime. Function signatures are inspected to generate tool schemas automatically.</p>

            <div class="mb-4 rounded-lg overflow-hidden border border-gray-800">
              <img src="/docs/tool-editor.png" alt="Agent tool editor" class="w-full" />
              <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">The Agent tool editor: system prompt, user prompt with template variables, functions list, model selection, and pip dependencies.</div>
            </div>

            <div class="bg-gray-950 border border-gray-800 rounded-lg p-4 mb-3">
              <div class="text-[10px] text-gray-600 mb-2 font-mono">example: search_web.py</div>
              <pre class="text-xs text-gray-300 font-mono whitespace-pre leading-relaxed"><span class="text-blue-400">def</span> <span class="text-green-400">search_web</span>(query: <span class="text-amber-400">str</span>, limit: <span class="text-amber-400">int</span> = 10) -> <span class="text-amber-400">str</span>:
    <span class="text-gray-500">"""Search the web and return results.

    Args:
        query: What to search for
        limit: Maximum number of results
    """</span>
    <span class="text-blue-400">import</span> requests
    resp = requests.get(<span class="text-amber-300">"https://api.example.com/search"</span>,
                        params={<span class="text-amber-300">"q"</span>: query, <span class="text-amber-300">"limit"</span>: limit})
    <span class="text-blue-400">return</span> resp.text</pre>
            </div>

            <div class="space-y-2 text-xs text-gray-400">
              <p><strong class="text-gray-300">Type hints matter:</strong> <code class="bg-gray-800 px-1 rounded">str</code> &rarr; string, <code class="bg-gray-800 px-1 rounded">int</code> &rarr; integer, <code class="bg-gray-800 px-1 rounded">float</code> &rarr; number, <code class="bg-gray-800 px-1 rounded">bool</code> &rarr; boolean, <code class="bg-gray-800 px-1 rounded">list</code> &rarr; array. These generate the JSON schema Claude sees.</p>
              <p><strong class="text-gray-300">Docstrings matter:</strong> The docstring becomes the tool description Claude reads. <code class="bg-gray-800 px-1 rounded">Args:</code> lines become parameter descriptions.</p>
              <p><strong class="text-gray-300">Return type:</strong> Functions must return strings. Wrap structured data with <code class="bg-gray-800 px-1 rounded">json.dumps()</code>.</p>
              <p><strong class="text-gray-300">Timeout:</strong> Each function call has a 15-minute default timeout.</p>
            </div>
          </div>

          <!-- Environment Variables -->
          <div id="tools-env" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Environment Variables</h3>
            <p class="text-xs text-gray-400 mb-3">Environment variables are persistent secrets or configuration values defined per tool. Unlike request inputs (which change per run), env vars are set once in Settings and available every time the tool runs.</p>

            <div class="bg-gray-950 border border-gray-800 rounded-lg p-4 mb-3">
              <div class="text-[10px] text-gray-600 mb-2 font-mono">Declaring in tool config:</div>
              <pre class="text-xs text-gray-300 font-mono whitespace-pre leading-relaxed">env_variables: [
  { name: <span class="text-amber-300">"JIRA_TOKEN"</span>, description: <span class="text-amber-300">"API token"</span>, type: <span class="text-amber-300">"password"</span> },
  { name: <span class="text-amber-300">"JIRA_URL"</span>, description: <span class="text-amber-300">"Instance URL"</span>, type: <span class="text-amber-300">"text"</span> }
]</pre>
            </div>

            <div class="bg-gray-950 border border-gray-800 rounded-lg p-4 mb-3">
              <div class="text-[10px] text-gray-600 mb-2 font-mono">Using in agent functions:</div>
              <pre class="text-xs text-gray-300 font-mono whitespace-pre leading-relaxed"><span class="text-blue-400">def</span> <span class="text-green-400">list_issues</span>() -> <span class="text-amber-400">str</span>:
    <span class="text-gray-500">"""List JIRA issues."""</span>
    <span class="text-gray-500"># Env vars are injected as module-level globals</span>
    headers = {<span class="text-amber-300">"Authorization"</span>: <span class="text-amber-300">f"Bearer <span class="text-blue-300">{JIRA_TOKEN}</span>"</span>}
    <span class="text-gray-500"># ...</span></pre>
            </div>

            <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-3 text-xs space-y-1.5">
              <p class="text-amber-400 font-medium">Important:</p>
              <ul class="text-gray-500 ml-3 list-disc space-y-1">
                <li>In <strong class="text-gray-400">agent functions</strong>, env vars are available as bare globals (e.g. <code class="bg-gray-800 px-1 rounded">JIRA_TOKEN</code>)</li>
                <li>In <strong class="text-gray-400">endpoint tools</strong>, use template syntax: <code class="bg-gray-800 px-1 rounded" v-pre>{{JIRA_TOKEN}}</code> in headers/body</li>
                <li>Do <strong class="text-gray-400">NOT</strong> use <code class="bg-gray-800 px-1 rounded">os.environ</code> or <code class="bg-gray-800 px-1 rounded">dotenv</code> &mdash; env access is sandboxed</li>
                <li>Set values in <strong class="text-gray-400">Settings &gt; Custom Variables</strong> after saving the tool</li>
              </ul>
            </div>
          </div>

          <!-- Pip Dependencies -->
          <div id="tools-pip" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Pip Dependencies</h3>
            <p class="text-xs text-gray-400 mb-3">Agent tools can declare Python package dependencies. When the tool is saved, packages are automatically installed via pip.</p>

            <div class="bg-gray-950 border border-gray-800 rounded-lg p-3 font-mono text-xs space-y-1 mb-3">
              <div><span class="text-green-400">"requests"</span> <span class="text-gray-600">&mdash; latest version</span></div>
              <div><span class="text-green-400">"jira==3.1.0"</span> <span class="text-gray-600">&mdash; exact version</span></div>
              <div><span class="text-green-400">"pandas>=2.0"</span> <span class="text-gray-600">&mdash; minimum version</span></div>
            </div>
            <p class="text-xs text-gray-500">Already-installed packages are skipped. Install results (success/failure per package) are returned when saving.</p>
          </div>

          <!-- MCP Servers -->
          <div id="tools-mcp" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">MCP Servers</h3>
            <p class="text-xs text-gray-400 mb-3">Model Context Protocol (MCP) servers provide additional tools that Claude can call alongside your Python functions. They allow integration with external systems without writing code.</p>

            <div class="space-y-3 mb-3">
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <div class="text-xs font-medium text-gray-300 mb-1">Stdio Transport</div>
                <p class="text-xs text-gray-500">Spawns a local subprocess. Configure a command and arguments.</p>
                <div class="bg-gray-950 rounded p-2 mt-2 font-mono text-xs text-gray-400">
                  command: <span class="text-green-400">"npx"</span> &nbsp; args: <span class="text-green-400">["-y", "@modelcontextprotocol/server-brave-search"]</span>
                </div>
              </div>
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <div class="text-xs font-medium text-gray-300 mb-1">HTTP/SSE Transport</div>
                <p class="text-xs text-gray-500">Connects to a remote MCP server via HTTP. Configure URL and optional headers.</p>
                <div class="bg-gray-950 rounded p-2 mt-2 font-mono text-xs text-gray-400">
                  url: <span class="text-green-400">"https://mcp.example.com/sse"</span> &nbsp; headers: <span class="text-green-400" v-pre>{"Authorization": "Bearer {{API_TOKEN}}"}</span>
                </div>
              </div>
            </div>

            <p class="text-xs text-gray-500">Use <strong class="text-gray-400">Test Connection</strong> to discover available tools, then select which ones the agent can use via the <strong class="text-gray-400">allowed_tools</strong> list.</p>
          </div>

          <!-- Safe Mode & Sandbox -->
          <div id="tools-sandbox" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Safe Mode &amp; Sandbox</h3>
            <p class="text-xs text-gray-400 mb-3">Safe Mode restricts what tool and trigger code can access on the system. It's enabled by default and can be toggled in Settings.</p>

            <div class="grid grid-cols-2 gap-3 mb-4">
              <div class="bg-gray-900 border border-green-900/50 rounded-lg p-3">
                <div class="text-xs font-semibold text-green-400 mb-2">Safe Mode ON (default)</div>
                <ul class="text-xs text-gray-500 space-y-1 ml-3 list-disc">
                  <li>Filesystem restricted to workspace directory</li>
                  <li>Environment variables sandboxed</li>
                  <li>Path traversal blocked</li>
                  <li>Symlink escape prevented</li>
                </ul>
              </div>
              <div class="bg-gray-900 border border-amber-900/50 rounded-lg p-3">
                <div class="text-xs font-semibold text-amber-400 mb-2">Safe Mode OFF</div>
                <ul class="text-xs text-gray-500 space-y-1 ml-3 list-disc">
                  <li>Unrestricted filesystem access</li>
                  <li>Environment variables still sandboxed</li>
                  <li>Use for trusted tools that need system access</li>
                  <li>Toggle in Settings (takes effect immediately)</li>
                </ul>
              </div>
            </div>

            <div class="bg-gray-950 border border-gray-800 rounded-lg p-4 mb-3">
              <div class="text-xs font-medium text-gray-300 mb-2">Workspace Directory</div>
              <p class="text-xs text-gray-500 mb-2">Each tool and trigger gets its own isolated workspace:</p>
              <div class="font-mono text-xs space-y-1">
                <div><span class="text-gray-500">Tools:</span> <span class="text-blue-400">data/agents/{tool_name}_{tool_id}/workspace/</span></div>
                <div><span class="text-gray-500">Triggers:</span> <span class="text-blue-400">data/triggers/{trigger_id}/workspace/</span></div>
              </div>
              <p class="text-xs text-gray-500 mt-2">Access via the <code class="bg-gray-800 px-1 rounded text-gray-400">WORKSPACE_DIR</code> global variable in your code. Files persist between runs.</p>
            </div>

            <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-3 text-xs text-gray-500">
              <span class="text-gray-400 font-medium">What's always sandboxed (regardless of Safe Mode):</span> Environment variables are always isolated. Tool code can only see its own declared env vars, never system secrets like API keys or database credentials.
            </div>
          </div>
        </section>

        <!-- PIPELINES -->
        <section id="pipelines" class="mb-16">
          <h2 class="text-xl font-bold text-gray-50 mb-1">Pipelines</h2>
          <p class="text-gray-400 text-sm mb-4">Pipelines are visual workflows that chain tools together into directed graphs. Steps execute in topological order, with data flowing from one step to the next.</p>

          <div class="mb-6 rounded-lg overflow-hidden border border-gray-800">
            <img src="/docs/pipelines.png" alt="Pipelines list view" class="w-full" />
            <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">The Pipelines list with tags, step counts, and quick actions.</div>
          </div>

          <div id="pipelines-overview" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">How Pipelines Work</h3>

            <div class="mb-4 rounded-lg overflow-hidden border border-gray-800">
              <img src="/docs/pipeline-editor.png" alt="Pipeline visual editor" class="w-full" />
              <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">The visual pipeline editor: drag-and-drop steps connected by edges, with settings and inputs on the left.</div>
            </div>

            <ol class="text-xs text-gray-400 space-y-2 ml-4 list-decimal">
              <li><strong class="text-gray-300">Define steps:</strong> Each step wraps a tool (LLM, Endpoint, or Agent) or is a flow control node (If, Wait, Loop, End).</li>
              <li><strong class="text-gray-300">Connect edges:</strong> Draw connections between steps in the visual editor. Edges define execution order and data flow.</li>
              <li><strong class="text-gray-300">Configure inputs:</strong> Pipeline inputs are provided at run time and available to all steps as template variables.</li>
              <li><strong class="text-gray-300">Run:</strong> Steps execute in topological order. Each step's output is added to a shared context, available to all downstream steps.</li>
            </ol>
          </div>

          <div id="pipelines-steps" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Step Types</h3>

            <div class="space-y-3 mb-4">
              <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider">Processing Steps</div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-blue-900/40 text-blue-400 border border-blue-800">LLM</span>
                <span class="text-xs text-gray-300 ml-2">Send a prompt to Claude and get a response. Supports system prompt, model selection, and response structures.</span>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-green-900/40 text-green-400 border border-green-800">Endpoint</span>
                <span class="text-xs text-gray-300 ml-2">Make an HTTP request. URL, headers, body, and query params all support template variables.</span>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-purple-900/40 text-purple-400 border border-purple-800">Agent</span>
                <span class="text-xs text-gray-300 ml-2">Run Claude in an agentic loop with Python functions and MCP tools.</span>
              </div>
            </div>

            <div class="space-y-3 mb-4">
              <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider">Flow Control</div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-amber-900/40 text-amber-400 border border-amber-800">If</span>
                <span class="text-xs text-gray-300 ml-2">Conditional branching. An LLM evaluates a condition and routes to true or false branches.</span>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-gray-700/40 text-gray-400 border border-gray-700">Wait</span>
                <span class="text-xs text-gray-300 ml-2">Synchronization barrier. Waits for all incoming edges to complete before proceeding.</span>
                <div class="text-[10px] text-amber-500 mt-1">Warning: Do not place directly after an If step &mdash; only one branch executes, causing a deadlock.</div>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-gray-700/40 text-gray-400 border border-gray-700">LoopCounter</span>
                <span class="text-xs text-gray-300 ml-2">Tracks iterations up to a max count. Use with If to create retry/loop patterns without infinite loops.</span>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-red-900/40 text-red-400 border border-red-800">End</span>
                <span class="text-xs text-gray-300 ml-2">Terminal node. Stops execution on that branch.</span>
              </div>
            </div>
          </div>

          <div id="pipelines-flow" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Flow Control Patterns</h3>

            <div class="space-y-4">
              <div class="bg-gray-950 border border-gray-800 rounded-lg p-4">
                <div class="text-xs font-medium text-gray-300 mb-2">Conditional Branching</div>
                <div class="font-mono text-xs text-gray-500 mb-1">Step &rarr; If &rarr; [true branch] / [false branch]</div>
                <p class="text-xs text-gray-500">The If step evaluates a condition using an LLM. Connect true and false outputs to different downstream steps.</p>
              </div>

              <div class="bg-gray-950 border border-gray-800 rounded-lg p-4">
                <div class="text-xs font-medium text-gray-300 mb-2">Parallel Fan-out &amp; Rejoin</div>
                <div class="font-mono text-xs text-gray-500 mb-1">Step &rarr; [A, B, C] &rarr; Wait &rarr; Next</div>
                <p class="text-xs text-gray-500">One step can have multiple outgoing edges. Use a Wait step to synchronize before continuing.</p>
              </div>

              <div class="bg-gray-950 border border-gray-800 rounded-lg p-4">
                <div class="text-xs font-medium text-gray-300 mb-2">Retry Loop</div>
                <div class="font-mono text-xs text-gray-500 mb-1">Step &rarr; LoopCounter &rarr; If (check result) &rarr; [false: back to Step] / [true: continue]</div>
                <p class="text-xs text-gray-500">LoopCounter prevents infinite loops by capping iterations at <code class="bg-gray-800 px-1 rounded">max_passes</code> (default 5).</p>
              </div>
            </div>
          </div>

          <div id="pipelines-context" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Context &amp; Variables</h3>
            <p class="text-xs text-gray-400 mb-3">As a pipeline runs, each step's output is added to a shared context. Downstream steps can reference any earlier output using template variables.</p>

            <div class="bg-gray-950 border border-gray-800 rounded-lg p-3 font-mono text-xs space-y-1.5 mb-3">
              <div><span class="text-blue-400" v-pre>{{Input}}</span> <span class="text-gray-600">&mdash; pipeline input provided at run time</span></div>
              <div><span class="text-blue-400" v-pre>{{AnalyzeStep}}</span> <span class="text-gray-600">&mdash; full output of a step named "AnalyzeStep"</span></div>
              <div><span class="text-blue-400" v-pre>{{AnalyzeStep.status}}</span> <span class="text-gray-600">&mdash; a field from JSON output</span></div>
              <div><span class="text-blue-400" v-pre>{{AnalyzeStep.items[0].name}}</span> <span class="text-gray-600">&mdash; nested array/object access</span></div>
            </div>

            <p class="text-xs text-gray-500">Variables are resolved just before each step executes. If a variable isn't found, it's left as-is (not replaced with empty string).</p>
          </div>

          <div id="pipelines-interactive" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Interactive Steps</h3>

            <div class="space-y-3">
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-cyan-900/40 text-cyan-400 border border-cyan-800">AskUser</span>
                <span class="text-xs text-gray-300 ml-2">Multi-round conversation step</span>
                <p class="text-xs text-gray-500 mt-1">An LLM generates clarifying questions. The user answers. The loop continues until the LLM has enough information and returns a summary. The summary becomes the step output.</p>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-cyan-900/40 text-cyan-400 border border-cyan-800">FileUpload</span>
                <span class="text-xs text-gray-300 ml-2">Pause for file upload</span>
                <p class="text-xs text-gray-500 mt-1">Pauses the pipeline and prompts the user to upload files. The output is a JSON array of uploaded file paths.</p>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-cyan-900/40 text-cyan-400 border border-cyan-800">Claude Code</span>
                <span class="text-xs text-gray-300 ml-2">Claude Code CLI agent step</span>
                <p class="text-xs text-gray-500 mt-1">Runs Claude Code in headless mode with a prompt. It uses its built-in tools (Bash, Read, Edit, etc.) to complete coding tasks. See the <button @click="scrollTo('claude-code')" class="text-blue-400 hover:underline">Claude Code Agent</button> section for details.</p>
              </div>
            </div>
          </div>
        </section>

        <!-- TRIGGERS -->
        <section id="triggers" class="mb-16">
          <h2 class="text-xl font-bold text-gray-50 mb-1">Triggers</h2>
          <p class="text-gray-400 text-sm mb-4">Triggers are event sources that automatically fire connected pipelines. Each trigger watches for a specific kind of event and runs your code when it occurs.</p>

          <div class="mb-6 rounded-lg overflow-hidden border border-gray-800">
            <img src="/docs/triggers.png" alt="Triggers list view" class="w-full" />
            <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">The Triggers list showing different trigger types: File Watcher, Cron, and Custom.</div>
          </div>

          <div id="triggers-types" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Trigger Types</h3>

            <div class="space-y-3">
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-blue-900/40 text-blue-400 border border-blue-800">Cron</span>
                  <span class="text-sm font-medium text-gray-50">Schedule-based</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">Fires on a cron schedule. Standard 5-field cron syntax.</p>
                <div class="bg-gray-950 rounded p-2 font-mono text-xs text-gray-500 space-y-0.5">
                  <div><span class="text-green-400">*/5 * * * *</span> &mdash; every 5 minutes</div>
                  <div><span class="text-green-400">0 9 * * MON-FRI</span> &mdash; weekdays at 9am</div>
                  <div><span class="text-green-400">0 0 1 * *</span> &mdash; first day of each month</div>
                </div>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-green-900/40 text-green-400 border border-green-800">Webhook</span>
                  <span class="text-sm font-medium text-gray-50">HTTP endpoint</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">Auto-generates a URL that accepts HTTP POST requests with JSON body. No configuration needed beyond enabling.</p>
                <div class="bg-gray-950 rounded p-2 font-mono text-[11px] text-gray-500">
                  POST <span class="text-blue-400">/api/triggers/{trigger_id}/webhook</span>
                </div>
                <p class="text-xs text-gray-500 mt-2">Context includes: <code class="bg-gray-800 px-1 rounded text-gray-400">webhook_body</code>, <code class="bg-gray-800 px-1 rounded text-gray-400">webhook_method</code>, <code class="bg-gray-800 px-1 rounded text-gray-400">webhook_headers</code>. Top-level body keys are also flattened as <code class="bg-gray-800 px-1 rounded text-gray-400">body_keyname</code>.</p>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-amber-900/40 text-amber-400 border border-amber-800">FileWatcher</span>
                  <span class="text-sm font-medium text-gray-50">Filesystem monitoring</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">Watches a local directory for file changes. Configure a path, glob patterns, and which events to watch.</p>
                <div class="bg-gray-950 rounded p-2 font-mono text-xs text-gray-500 space-y-0.5">
                  <div>watch_path: <span class="text-green-400">"/data/incoming"</span></div>
                  <div>watch_patterns: <span class="text-green-400">"*.csv, *.json"</span></div>
                  <div>watch_events: <span class="text-green-400">created, modified</span></div>
                </div>
                <p class="text-xs text-gray-500 mt-2">Context includes: <code class="bg-gray-800 px-1 rounded text-gray-400">file_path</code>, <code class="bg-gray-800 px-1 rounded text-gray-400">file_name</code>, <code class="bg-gray-800 px-1 rounded text-gray-400">event_type</code></p>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-orange-900/40 text-orange-400 border border-orange-800">RSS</span>
                  <span class="text-sm font-medium text-gray-50">Feed polling</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">Polls RSS/Atom feeds at a configurable interval. Only new entries trigger (duplicates are tracked).</p>
                <div class="bg-gray-950 rounded p-2 font-mono text-xs text-gray-500 space-y-0.5">
                  <div>rss_url: <span class="text-green-400">"https://blog.example.com/feed.xml"</span></div>
                  <div>rss_poll_minutes: <span class="text-green-400">15</span></div>
                </div>
                <p class="text-xs text-gray-500 mt-2">Context includes: <code class="bg-gray-800 px-1 rounded text-gray-400">entry_title</code>, <code class="bg-gray-800 px-1 rounded text-gray-400">entry_link</code>, <code class="bg-gray-800 px-1 rounded text-gray-400">entry_summary</code>, <code class="bg-gray-800 px-1 rounded text-gray-400">entry_published</code></p>
              </div>

              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs font-medium rounded bg-purple-900/40 text-purple-400 border border-purple-800">Custom</span>
                  <span class="text-sm font-medium text-gray-50">Long-lived subprocess</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">Runs as a separate Python process with an <code class="bg-gray-800 px-1 rounded text-gray-400">emit()</code> callback. Use for polling remote APIs, watching non-local resources, or any custom event source.</p>
                <div class="bg-gray-950 rounded p-2 font-mono text-xs text-gray-400">
                  <div><span class="text-blue-400">def</span> <span class="text-green-400">run</span>(emit):</div>
                  <div class="ml-4"><span class="text-blue-400">while</span> <span class="text-amber-400">True</span>:</div>
                  <div class="ml-8">emit({<span class="text-amber-300">"event"</span>: <span class="text-amber-300">"data"</span>})</div>
                  <div class="ml-8">time.sleep(60)</div>
                </div>
              </div>
            </div>
          </div>

          <div id="triggers-code" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Trigger Code</h3>
            <p class="text-xs text-gray-400 mb-3">Each trigger has a Python handler that processes the event and returns data to feed into connected pipelines.</p>

            <div class="mb-4 rounded-lg overflow-hidden border border-gray-800">
              <img src="/docs/trigger-editor.png" alt="Trigger editor" class="w-full" />
              <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">The Trigger editor: code editor with on_trigger handler, cron config, connections tab, and fire output panel.</div>
            </div>

            <div class="grid grid-cols-2 gap-3 mb-3">
              <div class="bg-gray-950 border border-gray-800 rounded-lg p-3">
                <div class="text-[10px] text-gray-600 mb-2 font-mono">Standard triggers (Cron, FileWatcher, Webhook, RSS)</div>
                <pre class="text-xs text-gray-400 font-mono whitespace-pre leading-relaxed"><span class="text-blue-400">def</span> <span class="text-green-400">on_trigger</span>(context: <span class="text-amber-400">dict</span>) -> <span class="text-amber-400">dict</span>:
    <span class="text-gray-500"># context has: trigger_type,
    # trigger_name, trigger_time,
    # plus type-specific fields</span>
    <span class="text-blue-400">return</span> {<span class="text-amber-300">"result"</span>: <span class="text-amber-300">"value"</span>}</pre>
                <p class="text-[10px] text-gray-600 mt-2">Env vars: use bare globals (<code class="bg-gray-800 px-0.5 rounded">API_KEY</code>)</p>
              </div>
              <div class="bg-gray-950 border border-gray-800 rounded-lg p-3">
                <div class="text-[10px] text-gray-600 mb-2 font-mono">Custom triggers</div>
                <pre class="text-xs text-gray-400 font-mono whitespace-pre leading-relaxed"><span class="text-blue-400">def</span> <span class="text-green-400">run</span>(emit):
    <span class="text-blue-400">import</span> os, time
    key = os.getenv(<span class="text-amber-300">"API_KEY"</span>)
    <span class="text-blue-400">while</span> <span class="text-amber-400">True</span>:
        emit({<span class="text-amber-300">"data"</span>: <span class="text-amber-300">"..."</span>})
        time.sleep(60)</pre>
                <p class="text-[10px] text-gray-600 mt-2">Env vars: use <code class="bg-gray-800 px-0.5 rounded">os.getenv()</code> (subprocess)</p>
              </div>
            </div>

            <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-3 text-xs text-gray-500">
              <span class="text-amber-400 font-medium">Key difference:</span> Standard triggers run <strong class="text-gray-400">in-process</strong> (env vars are globals). Custom triggers run as a <strong class="text-gray-400">separate subprocess</strong> (env vars via <code class="bg-gray-800 px-1 rounded">os.getenv()</code>).
            </div>
          </div>

          <div id="triggers-connections" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Pipeline Connections</h3>
            <p class="text-xs text-gray-400 mb-3">Each trigger can connect to one or more pipelines. When the trigger fires, the handler's return value is mapped to pipeline inputs.</p>

            <ol class="text-xs text-gray-400 space-y-1.5 ml-4 list-decimal">
              <li>Event occurs (schedule tick, webhook POST, file change, etc.)</li>
              <li>Python handler runs and returns a dict</li>
              <li>For each connected pipeline: a new pipeline run is created with the trigger's output as input variables</li>
              <li>Pipeline executes with those variables available as <code class="bg-gray-800 px-1 rounded text-gray-400" v-pre>{{variable_name}}</code></li>
            </ol>
          </div>
        </section>

        <!-- TASKS -->
        <section id="claude-code" class="mb-16">
          <h2 class="text-xl font-bold text-gray-50 mb-1">Claude Code Agent</h2>
          <p class="text-gray-400 text-sm mb-4">A tool type that runs the Claude Code CLI in headless mode. It can read, write, and execute code using Claude's built-in tools — Bash, Read, Edit, Write, Glob, Grep, and more.</p>

          <div id="claude-code-overview" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">How It Works</h3>

            <div class="space-y-3 mb-4">
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="text-xs font-semibold text-cyan-400 mb-1">1. Configuration</div>
                <p class="text-xs text-gray-500">Create a Claude Code tool, set a prompt (with template variables), choose which tools to allow, set a working directory and permission mode.</p>
              </div>
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="text-xs font-semibold text-blue-400 mb-1">2. Execution</div>
                <p class="text-xs text-gray-500">The tool spawns <code class="bg-gray-800 px-1 rounded text-gray-400">claude -p</code> as a subprocess with streaming JSON output. The CLI uses its agentic loop to complete the task, calling tools as needed.</p>
              </div>
              <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div class="text-xs font-semibold text-green-400 mb-1">3. Streaming</div>
                <p class="text-xs text-gray-500">Output streams in real-time: text responses, tool calls (Bash commands, file edits), and results are all displayed as they happen. The UI updates live.</p>
              </div>
            </div>

            <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-3 text-xs text-gray-500">
              <span class="text-gray-400 font-medium">Requirements:</span> The <code class="bg-gray-800 px-1 rounded text-gray-400">claude</code> CLI must be installed globally (<code class="bg-gray-800 px-1 rounded text-gray-400">npm install -g @anthropic-ai/claude-code</code>). An <code class="bg-gray-800 px-1 rounded text-gray-400">ANTHROPIC_API_KEY</code> must be available — either from the app settings or set as an env variable on the tool.
            </div>
          </div>

          <div id="claude-code-config" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Configuration</h3>

            <div class="bg-gray-950 border border-gray-800 rounded-lg overflow-hidden">
              <table class="w-full text-xs">
                <thead><tr class="border-b border-gray-800 text-gray-500">
                  <th class="text-left px-3 py-2 font-medium">Setting</th>
                  <th class="text-left px-3 py-2 font-medium">Description</th>
                </tr></thead>
                <tbody class="text-gray-400">
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Prompt</td><td class="px-3 py-1.5">The main instruction. Supports template variables like <code class="bg-gray-800 px-1 rounded" v-pre>{{Input}}</code></td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">System Prompt</td><td class="px-3 py-1.5">Optional. Append to or replace Claude Code's default system prompt.</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Allowed Tools</td><td class="px-3 py-1.5">Which tools Claude Code can use without prompting (Bash, Read, Edit, Write, etc.)</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Permission Mode</td><td class="px-3 py-1.5"><code class="bg-gray-800 px-1 rounded">default</code>, <code class="bg-gray-800 px-1 rounded">acceptEdits</code> (auto-approve file writes), or <code class="bg-gray-800 px-1 rounded">dontAsk</code> (deny unlisted)</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Working Directory</td><td class="px-3 py-1.5">The directory where Claude Code runs. Should point to a project/repo.</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Bare Mode</td><td class="px-3 py-1.5">Skip auto-discovery of hooks, plugins, and MCP servers. Recommended for automation.</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Max Turns</td><td class="px-3 py-1.5">Limit the number of agentic turns. 0 = unlimited.</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Timeout</td><td class="px-3 py-1.5">Maximum seconds before the process is killed.</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">MCP Config</td><td class="px-3 py-1.5">Optional JSON for additional MCP servers the CLI should connect to.</td></tr>
                  <tr><td class="px-3 py-1.5 text-gray-300">JSON Schema</td><td class="px-3 py-1.5">Optional. Forces structured output conforming to the given schema.</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- SETTINGS -->
        <section id="settings" class="mb-16">
          <h2 class="text-xl font-bold text-gray-50 mb-1">Settings</h2>
          <p class="text-gray-400 text-sm mb-4">Admin-only configuration for API keys, models, and tool/trigger variables.</p>

          <div class="mb-6 rounded-lg overflow-hidden border border-gray-800">
            <img src="/docs/settings.png" alt="Settings view" class="w-full" />
            <div class="bg-gray-900 px-3 py-1.5 text-[10px] text-gray-500">Settings page: API keys, model configuration, Safe Mode toggle, and authentication options.</div>
          </div>

          <div id="settings-general" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">General Settings</h3>
            <div class="bg-gray-950 border border-gray-800 rounded-lg overflow-hidden">
              <table class="w-full text-xs">
                <thead><tr class="border-b border-gray-800 text-gray-500">
                  <th class="text-left px-3 py-2 font-medium">Setting</th>
                  <th class="text-left px-3 py-2 font-medium">Description</th>
                </tr></thead>
                <tbody class="text-gray-400">
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Anthropic API Key</td><td class="px-3 py-1.5">Required for Claude models</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">OpenAI API Key</td><td class="px-3 py-1.5">Required for GPT models</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Google API Key</td><td class="px-3 py-1.5">Required for Gemini models</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">xAI API Key</td><td class="px-3 py-1.5">Required for Grok models</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Local LLM URL</td><td class="px-3 py-1.5">Server URL for local models (Ollama, vLLM, LM Studio, llama.cpp)</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Default Model</td><td class="px-3 py-1.5">Model used when none is specified</td></tr>
                  <tr class="border-b border-gray-800/50"><td class="px-3 py-1.5 text-gray-300">Safe Mode</td><td class="px-3 py-1.5">Toggle filesystem sandboxing for tools/triggers (takes effect immediately)</td></tr>
                  <tr><td class="px-3 py-1.5 text-gray-300">Authentication</td><td class="px-3 py-1.5">Enable/disable user login with Google or Microsoft OAuth</td></tr>
                </tbody>
              </table>
            </div>
          </div>

          <div id="settings-models" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Models</h3>
            <p class="text-xs text-gray-400 mb-3">Manage available LLM models. Add, remove, or reorder models. Each model has a provider (Anthropic, OpenAI, Google, xAI, or Local), pricing per million tokens (input and output), and a display name.</p>
            <p class="text-xs text-gray-500">Models appear in dropdowns throughout the app wherever a model can be selected (tool config, pipeline steps).</p>
          </div>

          <div id="settings-custom" class="mb-10">
            <h3 class="text-base font-semibold text-gray-50 mb-3">Custom Variables</h3>
            <p class="text-xs text-gray-400 mb-3">Set values for environment variables declared by tools and triggers. Variables are grouped by the resource that declared them.</p>

            <div class="bg-gray-900/50 border border-gray-800 rounded-lg p-3 text-xs text-gray-500">
              <span class="text-gray-400 font-medium">Workflow:</span> Declare env vars in your tool/trigger config &rarr; Save the tool &rarr; Go to Settings &gt; Custom Variables &rarr; Enter the values. Password-type variables are stored securely and displayed obfuscated.
            </div>
          </div>
        </section>

        <!-- Bottom spacer -->
        <div class="h-32"></div>
      </div>
    </main>
  </div>
</template>
