<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  letter: string
  size: number
}>()

const char = computed(() => (props.letter || '?').charAt(0).toUpperCase())
const idx = computed(() => {
  const c = char.value.charCodeAt(0)
  return c >= 65 && c <= 90 ? c - 65 : c % 26
})

// Each letter gets a unique gradient pair and accent color
const palettes = [
  { g1: '#7c3aed', g2: '#4f46e5', accent: '#a78bfa' }, // A - violet→indigo
  { g1: '#2563eb', g2: '#0891b2', accent: '#67e8f9' }, // B - blue→cyan
  { g1: '#0d9488', g2: '#059669', accent: '#6ee7b7' }, // C - teal→emerald
  { g1: '#d97706', g2: '#dc2626', accent: '#fbbf24' }, // D - amber→red
  { g1: '#7c3aed', g2: '#db2777', accent: '#f0abfc' }, // E - violet→pink
  { g1: '#059669', g2: '#2563eb', accent: '#34d399' }, // F - emerald→blue
  { g1: '#e11d48', g2: '#9333ea', accent: '#fb7185' }, // G - rose→purple
  { g1: '#0891b2', g2: '#7c3aed', accent: '#22d3ee' }, // H - cyan→violet
  { g1: '#ea580c', g2: '#d97706', accent: '#fb923c' }, // I - orange→amber
  { g1: '#4f46e5', g2: '#0d9488', accent: '#818cf8' }, // J - indigo→teal
  { g1: '#db2777', g2: '#ea580c', accent: '#f472b6' }, // K - pink→orange
  { g1: '#2563eb', g2: '#7c3aed', accent: '#93c5fd' }, // L - blue→violet
  { g1: '#dc2626', g2: '#ea580c', accent: '#f87171' }, // M - red→orange
  { g1: '#0d9488', g2: '#4f46e5', accent: '#5eead4' }, // N - teal→indigo
  { g1: '#9333ea', g2: '#2563eb', accent: '#c084fc' }, // O - purple→blue
  { g1: '#059669', g2: '#0891b2', accent: '#34d399' }, // P - emerald→cyan
  { g1: '#d97706', g2: '#e11d48', accent: '#fcd34d' }, // Q - amber→rose
  { g1: '#e11d48', g2: '#7c3aed', accent: '#fda4af' }, // R - rose→violet
  { g1: '#4f46e5', g2: '#db2777', accent: '#a5b4fc' }, // S - indigo→pink
  { g1: '#0891b2', g2: '#059669', accent: '#67e8f9' }, // T - cyan→emerald
  { g1: '#9333ea', g2: '#e11d48', accent: '#d8b4fe' }, // U - purple→rose
  { g1: '#ea580c', g2: '#9333ea', accent: '#fdba74' }, // V - orange→purple
  { g1: '#2563eb', g2: '#059669', accent: '#60a5fa' }, // W - blue→emerald
  { g1: '#dc2626', g2: '#d97706', accent: '#fca5a5' }, // X - red→amber
  { g1: '#7c3aed', g2: '#0891b2', accent: '#c4b5fd' }, // Y - violet→cyan
  { g1: '#db2777', g2: '#4f46e5', accent: '#f9a8d4' }, // Z - pink→indigo
]

const pal = computed(() => palettes[idx.value])

// Pattern type: 0=circuit dots, 1=concentric arcs, 2=grid dots, 3=diagonal lines, 4=hex nodes, 5=radial burst
const pattern = computed(() => idx.value % 6)
</script>

<template>
  <svg :width="size" :height="size" :viewBox="`0 0 200 200`" class="rounded shrink-0" style="display: block">
    <defs>
      <linearGradient :id="`lg-${char}`" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" :stop-color="pal.g1" />
        <stop offset="100%" :stop-color="pal.g2" />
      </linearGradient>
      <radialGradient :id="`rg-${char}`" cx="30%" cy="30%" r="70%">
        <stop offset="0%" stop-color="rgba(255,255,255,0.15)" />
        <stop offset="100%" stop-color="rgba(0,0,0,0.1)" />
      </radialGradient>
    </defs>

    <!-- Background -->
    <rect width="200" height="200" rx="24" :fill="`url(#lg-${char})`" />
    <rect width="200" height="200" rx="24" :fill="`url(#rg-${char})`" />

    <!-- Pattern 0: Circuit dots + lines -->
    <g v-if="pattern === 0" :stroke="pal.accent" stroke-width="1" fill="none" opacity="0.3">
      <circle cx="30" cy="30" r="3" :fill="pal.accent" />
      <circle cx="170" cy="40" r="2" :fill="pal.accent" />
      <circle cx="40" cy="170" r="2" :fill="pal.accent" />
      <circle cx="160" cy="160" r="3" :fill="pal.accent" />
      <line x1="30" y1="30" x2="80" y2="30" />
      <line x1="80" y1="30" x2="80" y2="60" />
      <line x1="160" y1="160" x2="120" y2="160" />
      <line x1="120" y1="160" x2="120" y2="140" />
      <line x1="170" y1="40" x2="170" y2="70" />
      <line x1="40" y1="170" x2="40" y2="140" />
    </g>

    <!-- Pattern 1: Concentric arcs -->
    <g v-else-if="pattern === 1" :stroke="pal.accent" stroke-width="1.5" fill="none" opacity="0.2">
      <path d="M 20 180 A 160 160 0 0 1 180 20" />
      <path d="M 40 180 A 140 140 0 0 1 180 40" />
      <path d="M 60 180 A 120 120 0 0 1 180 60" />
      <circle cx="170" cy="30" r="3" :fill="pal.accent" opacity="0.5" />
      <circle cx="30" cy="170" r="3" :fill="pal.accent" opacity="0.5" />
    </g>

    <!-- Pattern 2: Grid dots -->
    <g v-else-if="pattern === 2" :fill="pal.accent" opacity="0.15">
      <circle cx="20" cy="20" r="2.5" /><circle cx="60" cy="20" r="2.5" /><circle cx="100" cy="20" r="2.5" /><circle cx="140" cy="20" r="2.5" /><circle cx="180" cy="20" r="2.5" />
      <circle cx="20" cy="60" r="2.5" /><circle cx="60" cy="60" r="2.5" />
      <circle cx="140" cy="60" r="2.5" /><circle cx="180" cy="60" r="2.5" />
      <circle cx="20" cy="140" r="2.5" /><circle cx="60" cy="140" r="2.5" />
      <circle cx="140" cy="140" r="2.5" /><circle cx="180" cy="140" r="2.5" />
      <circle cx="20" cy="180" r="2.5" /><circle cx="60" cy="180" r="2.5" /><circle cx="100" cy="180" r="2.5" /><circle cx="140" cy="180" r="2.5" /><circle cx="180" cy="180" r="2.5" />
    </g>

    <!-- Pattern 3: Diagonal lines -->
    <g v-else-if="pattern === 3" :stroke="pal.accent" stroke-width="1" opacity="0.15">
      <line x1="0" y1="40" x2="40" y2="0" />
      <line x1="0" y1="80" x2="80" y2="0" />
      <line x1="120" y1="200" x2="200" y2="120" />
      <line x1="160" y1="200" x2="200" y2="160" />
      <circle cx="20" cy="20" r="2" :fill="pal.accent" opacity="0.4" />
      <circle cx="180" cy="180" r="2" :fill="pal.accent" opacity="0.4" />
    </g>

    <!-- Pattern 4: Hexagonal network -->
    <g v-else-if="pattern === 4" :stroke="pal.accent" stroke-width="1" fill="none" opacity="0.2">
      <polygon points="30,15 45,25 45,40 30,50 15,40 15,25" />
      <polygon points="165,150 180,160 180,175 165,185 150,175 150,160" />
      <line x1="45" y1="32" x2="80" y2="50" />
      <line x1="150" y1="167" x2="120" y2="150" />
      <circle cx="30" cy="32" r="2" :fill="pal.accent" opacity="0.5" />
      <circle cx="165" cy="167" r="2" :fill="pal.accent" opacity="0.5" />
    </g>

    <!-- Pattern 5: Radial burst -->
    <g v-else :stroke="pal.accent" stroke-width="1" opacity="0.15">
      <line x1="100" y1="100" x2="20" y2="20" />
      <line x1="100" y1="100" x2="180" y2="20" />
      <line x1="100" y1="100" x2="20" y2="180" />
      <line x1="100" y1="100" x2="180" y2="180" />
      <line x1="100" y1="100" x2="100" y2="15" />
      <line x1="100" y1="100" x2="100" y2="185" />
      <line x1="100" y1="100" x2="15" y2="100" />
      <line x1="100" y1="100" x2="185" y2="100" />
      <circle cx="100" cy="100" r="25" fill="none" :stroke="pal.accent" opacity="0.2" />
    </g>

    <!-- Letter -->
    <text
      x="100" y="100"
      text-anchor="middle"
      dominant-baseline="central"
      fill="white"
      font-family="ui-sans-serif, system-ui, sans-serif"
      font-weight="700"
      font-size="90"
      opacity="0.95"
      style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3))"
    >{{ char }}</text>
  </svg>
</template>
