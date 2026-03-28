<script setup lang="ts">
import { computed } from 'vue'
import VueApexCharts from 'vue3-apexcharts'

interface Run {
  id: string
  pipeline_name: string
  pipeline_id: string
  status: number
  created_at: string
  completed_at: string
  duration_s: number | null
  cost: number
  tool_id?: string
}

const props = defineProps<{
  runs: Run[]
  sinceFilter: string
}>()

const statusLabel: Record<number, string> = {
  0: 'Pending', 1: 'Running', 2: 'Completed', 3: 'Failed', 4: 'Paused', 5: 'Waiting',
}
const statusColors: Record<number, string> = {
  0: '#6b7280', 1: '#3b82f6', 2: '#22c55e', 3: '#ef4444', 4: '#eab308', 5: '#6366f1',
}

// --- Granularity ---
const granularity = computed<'hour' | 'day' | 'month'>(() => {
  const f = props.sinceFilter
  if (f === '1h' || f === 'today' || f === '24h') return 'hour'
  if (f === '7d' || f === '30d') return 'day'
  return 'month' // 365d, all, or ''
})

function bucketKey(iso: string): string {
  const d = new Date(iso)
  const g = granularity.value
  if (g === 'hour') return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:00`
  if (g === 'day') return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function formatBucketLabel(key: string): string {
  const g = granularity.value
  if (g === 'hour') {
    // "2026-03-01 14:00" -> "14:00"
    return key.split(' ')[1] || key
  }
  if (g === 'day') {
    // "2026-03-01" -> "Mar 1"
    const [, m, d] = key.split('-')
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return `${months[parseInt(m) - 1]} ${parseInt(d)}`
  }
  // month: "2026-03" -> "Mar 2026"
  const [y, m] = key.split('-')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[parseInt(m) - 1]} ${y}`
}

// --- Chart 1: Runs & Cost Over Time ---
const timeSeriesData = computed(() => {
  const buckets = new Map<string, { count: number; cost: number }>()
  for (const run of props.runs) {
    if (!run.created_at) continue
    const key = bucketKey(run.created_at)
    const b = buckets.get(key) || { count: 0, cost: 0 }
    b.count++
    b.cost += run.cost || 0
    buckets.set(key, b)
  }
  // Sort by key (chronological)
  const sorted = [...buckets.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  return {
    categories: sorted.map(([k]) => formatBucketLabel(k)),
    counts: sorted.map(([, v]) => v.count),
    costs: sorted.map(([, v]) => parseFloat(v.cost.toFixed(4))),
  }
})

const timeSeriesOptions = computed(() => ({
  chart: {
    type: 'bar' as const,
    background: 'transparent',
    toolbar: { show: false },
    fontFamily: 'inherit',
  },
  theme: { mode: 'dark' as const },
  colors: ['#3b82f6', '#22c55e'],
  plotOptions: {
    bar: { borderRadius: 3, columnWidth: '60%' },
  },
  stroke: { width: [0, 3], curve: 'smooth' as const },
  xaxis: {
    categories: timeSeriesData.value.categories,
    labels: { style: { colors: '#9ca3af', fontSize: '11px' } },
    axisBorder: { color: '#374151' },
    axisTicks: { color: '#374151' },
  },
  yaxis: [
    {
      title: { text: 'Runs', style: { color: '#9ca3af', fontSize: '11px' } },
      labels: { style: { colors: '#9ca3af' }, formatter: (v: number) => Math.round(v).toString() },
      forceNiceScale: true,
      min: 0,
    },
    {
      opposite: true,
      title: { text: 'Cost ($)', style: { color: '#9ca3af', fontSize: '11px' } },
      labels: { style: { colors: '#9ca3af' }, formatter: (v: number) => `$${v.toFixed(4)}` },
      min: 0,
    },
  ],
  grid: { borderColor: '#374151', strokeDashArray: 3 },
  tooltip: {
    theme: 'dark',
    y: {
      formatter: (v: number, { seriesIndex }: { seriesIndex: number }) =>
        seriesIndex === 1 ? `$${v.toFixed(4)}` : `${v} runs`,
    },
  },
  legend: { labels: { colors: '#9ca3af' } },
  dataLabels: { enabled: false },
}))

const timeSeriesSeries = computed(() => [
  { name: 'Runs', type: 'bar', data: timeSeriesData.value.counts },
  { name: 'Cost', type: 'line', data: timeSeriesData.value.costs },
])

// --- Chart 2: Status Distribution ---
const statusDistribution = computed(() => {
  const counts = new Map<number, number>()
  for (const run of props.runs) {
    counts.set(run.status, (counts.get(run.status) || 0) + 1)
  }
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1])
  return {
    labels: entries.map(([s]) => statusLabel[s] || `Status ${s}`),
    series: entries.map(([, c]) => c),
    colors: entries.map(([s]) => statusColors[s] || '#6b7280'),
  }
})

const donutOptions = computed(() => ({
  chart: {
    type: 'donut' as const,
    background: 'transparent',
    fontFamily: 'inherit',
  },
  theme: { mode: 'dark' as const },
  colors: statusDistribution.value.colors,
  labels: statusDistribution.value.labels,
  plotOptions: {
    pie: {
      donut: {
        size: '60%',
        labels: {
          show: true,
          total: {
            show: true,
            label: 'Total',
            color: '#9ca3af',
            formatter: (w: { globals: { seriesTotals: number[] } }) =>
              w.globals.seriesTotals.reduce((a: number, b: number) => a + b, 0).toString(),
          },
        },
      },
    },
  },
  legend: { position: 'bottom' as const, labels: { colors: '#9ca3af' }, fontSize: '11px' },
  dataLabels: { enabled: false },
  stroke: { show: false },
  tooltip: { theme: 'dark' },
}))

// --- Chart 3: Cost by Pipeline/Tool ---
const costByName = computed(() => {
  const costs = new Map<string, number>()
  for (const run of props.runs) {
    if (!run.cost) continue
    const name = run.pipeline_name || 'Unknown'
    costs.set(name, (costs.get(name) || 0) + run.cost)
  }
  const sorted = [...costs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)
  return {
    categories: sorted.map(([n]) => n),
    data: sorted.map(([, c]) => parseFloat(c.toFixed(4))),
  }
})

const costBarOptions = computed(() => ({
  chart: {
    type: 'bar' as const,
    background: 'transparent',
    toolbar: { show: false },
    fontFamily: 'inherit',
  },
  theme: { mode: 'dark' as const },
  colors: ['#a855f7'],
  plotOptions: {
    bar: { horizontal: true, borderRadius: 3, barHeight: '60%' },
  },
  xaxis: {
    labels: { style: { colors: '#9ca3af', fontSize: '11px' }, formatter: (v: number) => `$${v.toFixed(4)}` },
    axisBorder: { color: '#374151' },
  },
  yaxis: {
    labels: { style: { colors: '#9ca3af', fontSize: '11px' }, maxWidth: 140 },
  },
  grid: { borderColor: '#374151', strokeDashArray: 3 },
  tooltip: {
    theme: 'dark',
    y: { formatter: (v: number) => `$${v.toFixed(4)}` },
  },
  dataLabels: { enabled: false },
}))

const costBarSeries = computed(() => [
  { name: 'Cost', data: costByName.value.data },
])

const hasRuns = computed(() => props.runs.length > 0)
const hasCostData = computed(() => costByName.value.data.length > 0)
</script>

<template>
  <div v-if="!hasRuns" class="text-sm text-gray-600 py-12 text-center">No run data to chart</div>
  <div v-else class="flex flex-col gap-4 p-4 overflow-y-auto">
    <!-- Chart 1: Runs & Cost Over Time -->
    <div>
      <h3 class="text-xs font-medium text-gray-400 mb-1">Runs & Cost Over Time</h3>
      <VueApexCharts
        type="line"
        height="200"
        :options="timeSeriesOptions"
        :series="timeSeriesSeries"
      />
    </div>

    <!-- Bottom row: Status + Cost by name -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <!-- Chart 2: Status Distribution -->
      <div>
        <h3 class="text-xs font-medium text-gray-400 mb-1">Status Distribution</h3>
        <VueApexCharts
          type="donut"
          height="180"
          :options="donutOptions"
          :series="statusDistribution.series"
        />
      </div>

      <!-- Chart 3: Cost by Pipeline/Tool -->
      <div>
        <h3 class="text-xs font-medium text-gray-400 mb-1">Cost by Pipeline / Tool</h3>
        <div v-if="!hasCostData" class="text-sm text-gray-600 py-8 text-center">No cost data</div>
        <VueApexCharts
          v-else
          type="bar"
          height="180"
          :options="{ ...costBarOptions, xaxis: { ...costBarOptions.xaxis, categories: costByName.categories } }"
          :series="costBarSeries"
        />
      </div>
    </div>
  </div>
</template>
