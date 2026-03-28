/**
 * Artifact-aware markdown renderer.
 *
 * Extends `marked` to detect /api/artifacts/ URLs and render them as
 * appropriate HTML elements (video, audio, image, download card) based
 * on file extension / MIME type.
 *
 * Also renders link artifacts (external URLs) as clickable cards.
 *
 * Usage:
 *   import { renderMarkdown } from '@/composables/useArtifactRenderer'
 *   const html = renderMarkdown(text)
 */

import { marked, type Tokens } from 'marked'

const ARTIFACT_URL_RE = /\/api\/artifacts\/[^"'\s)\\&]+/

/** Map file extensions to content categories */
function classifyUrl(url: string): 'video' | 'audio' | 'image' | 'pdf' | 'download' {
  const ext = url.split('.').pop()?.toLowerCase().split('?')[0] ?? ''
  if (['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogv'].includes(ext)) return 'video'
  if (['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'wma'].includes(ext)) return 'audio'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico'].includes(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  return 'download'
}

/** Extract filename from artifact URL */
function filenameFromUrl(url: string): string {
  const parts = url.split('/')
  return decodeURIComponent(parts[parts.length - 1] || 'file')
}

/** Detect service from URL for icon hints */
function detectService(url: string): { name: string; color: string } {
  if (url.includes('github.com')) return { name: 'GitHub', color: 'text-gray-200' }
  if (url.includes('atlassian.net') || url.includes('jira')) return { name: 'Jira', color: 'text-blue-400' }
  if (url.includes('slack.com')) return { name: 'Slack', color: 'text-purple-400' }
  if (url.includes('drive.google.com') || url.includes('docs.google.com')) return { name: 'Google', color: 'text-green-400' }
  if (url.includes('discord.com') || url.includes('discord.gg')) return { name: 'Discord', color: 'text-indigo-400' }
  if (url.includes('notion.so')) return { name: 'Notion', color: 'text-gray-200' }
  if (url.includes('figma.com')) return { name: 'Figma', color: 'text-pink-400' }
  return { name: '', color: 'text-sky-400' }
}

/** Render an artifact URL as rich HTML */
function renderArtifactHtml(url: string, altText?: string): string {
  const kind = classifyUrl(url)
  const filename = altText || filenameFromUrl(url)

  switch (kind) {
    case 'video':
      return `<div class="artifact artifact-video my-3 not-prose">
        <video controls preload="metadata" class="max-w-full max-h-[500px] rounded-lg bg-black">
          <source src="${url}">
          Your browser does not support video playback.
        </video>
        <div class="flex items-center justify-between mt-1 text-xs text-gray-500">
          <span>${filename}</span>
          <a href="${url}" download="${filename}" class="hover:text-gray-300 underline">Download</a>
        </div>
      </div>`

    case 'audio':
      return `<div class="artifact artifact-audio my-3 not-prose">
        <audio controls preload="metadata" class="w-full">
          <source src="${url}">
          Your browser does not support audio playback.
        </audio>
        <div class="flex items-center justify-between mt-1 text-xs text-gray-500">
          <span>${filename}</span>
          <a href="${url}" download="${filename}" class="hover:text-gray-300 underline">Download</a>
        </div>
      </div>`

    case 'image':
      return `<div class="artifact artifact-image my-3 not-prose">
        <img src="${url}" alt="${filename}" class="max-w-full max-h-[500px] rounded-lg" loading="lazy" />
        <div class="flex items-center justify-between mt-1 text-xs text-gray-500">
          <span>${filename}</span>
          <a href="${url}" download="${filename}" class="hover:text-gray-300 underline">Download</a>
        </div>
      </div>`

    case 'pdf':
      return `<div class="artifact artifact-pdf my-3 not-prose">
        <iframe src="${url}" class="w-full h-[600px] rounded-lg border border-gray-700" title="${filename}"></iframe>
        <div class="flex items-center justify-between mt-1 text-xs text-gray-500">
          <span>${filename}</span>
          <a href="${url}" download="${filename}" class="hover:text-gray-300 underline">Download</a>
        </div>
      </div>`

    default:
      return `<div class="artifact artifact-download my-3 bg-sky-500/10 border border-sky-500/30 rounded-lg p-3 flex items-center gap-3">
        <svg class="w-6 h-6 text-sky-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <span class="flex-1 min-w-0 text-sm text-gray-200 truncate">${filename}</span>
        <a href="${url}" download="${filename}" class="px-3 py-1.5 bg-sky-600 hover:bg-sky-700 rounded text-xs font-medium text-white no-underline transition-colors">Download</a>
      </div>`
  }
}

/** Render an external link artifact as a card */
function renderLinkHtml(url: string, title: string, description?: string): string {
  const service = detectService(url)
  const badge = service.name
    ? `<span class="text-[10px] font-semibold uppercase ${service.color} opacity-70">${service.name}</span>`
    : ''

  return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="artifact artifact-link my-2 bg-gray-800/80 border border-gray-700 hover:border-gray-500 rounded-lg p-3 flex items-center gap-3 no-underline transition-colors block">
    <svg class="w-5 h-5 ${service.color} shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
    </svg>
    <div class="flex-1 min-w-0">
      <div class="text-sm text-gray-200 truncate">${title}</div>
      ${description ? `<div class="text-xs text-gray-500 truncate mt-0.5">${description}</div>` : ''}
    </div>
    ${badge}
  </a>`
}

/**
 * Custom marked renderer that intercepts artifact URLs.
 */
const renderer = {
  // Links: if href is an artifact URL, render as rich media
  link({ href, text }: Tokens.Link): string | false {
    if (href && ARTIFACT_URL_RE.test(href)) {
      return renderArtifactHtml(href, text !== href ? text : undefined)
    }
    // Default rendering for non-artifact links
    return false
  },

  // Images: if src is an artifact URL, use our renderer (handles non-image types too)
  image({ href, text }: Tokens.Image): string | false {
    if (href && ARTIFACT_URL_RE.test(href)) {
      return renderArtifactHtml(href, text || undefined)
    }
    return false
  },
}

/**
 * Post-process: find bare artifact URLs in text (not already in HTML tags)
 * and convert them to rich elements.
 */
function postProcessBareUrls(html: string): string {
  // Match bare artifact URLs that aren't inside href="", src="", or already processed
  // Exclude & to avoid gobbling HTML entities like &quot;
  return html.replace(
    /(?<!["=])(\/api\/artifacts\/[^\s<"'&\\]+)/g,
    (match) => {
      return renderArtifactHtml(match)
    }
  )
}

/** Extract artifact URLs from raw text (before HTML encoding) */
function extractArtifactUrls(text: string): string[] {
  const re = /\/api\/artifacts\/[^\s"'<>&\\]+/g
  const urls: string[] = []
  let m
  while ((m = re.exec(text)) !== null) {
    urls.push(m[0])
  }
  return [...new Set(urls)]
}

// Configure marked with our custom renderer
marked.use({ renderer })

/**
 * Render markdown text with artifact-aware extensions.
 * Drop-in replacement for `marked.parse(text)`.
 */
export function renderMarkdown(text: string): string {
  let html = marked.parse(text, { async: false }) as string
  // Catch any bare artifact URLs that weren't in markdown link/image syntax
  if (html.includes('/api/artifacts/')) {
    html = postProcessBareUrls(html)
  }
  return html
}

/**
 * Render markdown for tool results: show the full text as-is, then append
 * artifact download cards as a tray below (instead of replacing URLs inline).
 */
export function renderMarkdownToolResult(text: string): string {
  // Render markdown without bare-URL replacement so JSON stays intact
  let html = marked.parse(text, { async: false }) as string
  // Extract artifact URLs from the original text and show as a tray below
  const urls = extractArtifactUrls(text)
  if (urls.length > 0) {
    const items = urls.map(url => renderArtifactHtml(url)).join('\n')
    html += `<div class="artifact-tray mt-3 pt-3 border-t border-gray-700/50 not-prose">
      <div class="text-xs text-gray-500 mb-2 font-semibold uppercase">Artifacts</div>
      ${items}
    </div>`
  }
  return html
}

/** Artifact type from backend */
export interface Artifact {
  type?: 'file' | 'link'
  // File artifacts
  filename?: string
  url: string
  mime?: string
  size?: number
  // Link artifacts
  title?: string
  description?: string
}

/** Render an artifact tray for artifacts not referenced in the output text */
export function renderArtifactTray(artifacts: Artifact[], outputText: string): string {
  // Filter to artifacts not already referenced in the output
  const unreferenced = artifacts.filter(a => !outputText.includes(a.url))
  if (unreferenced.length === 0) return ''

  const items = unreferenced.map(a => {
    if (a.type === 'link') {
      return renderLinkHtml(a.url, a.title || a.url, a.description)
    }
    // File artifact (default for backwards compatibility)
    return renderArtifactHtml(a.url, a.filename)
  }).join('\n')

  return `<div class="artifact-tray mt-3 pt-3 border-t border-gray-700/50 not-prose">
    <div class="text-xs text-gray-500 mb-2 font-semibold uppercase">Artifacts</div>
    ${items}
  </div>`
}
