<template>
  <v-container fluid class="pa-6">
    <!-- Top 4 stat cards: one row, forced equal height -->
    <v-row align="stretch">
      <v-col cols="12" sm="6" md="3">
        <v-card class="pa-4 stat-card h-100">
          <div class="d-flex align-center justify-space-between">
            <span class="text-subtitle-1 font-weight-medium">Virtual Environments</span>
            <v-icon icon="mdi-cube-outline" size="28" color="grey-darken-1" />
          </div>
          <div class="text-h2 font-weight-bold mt-2">
            {{ veStore.items.length }}
          </div>
          <div class="text-caption stat-caption-spacer">
            &nbsp;
          </div>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" md="3">
        <v-card class="pa-4 stat-card h-100">
          <div class="d-flex align-center justify-space-between">
            <span class="text-subtitle-1 font-weight-medium">Endpoints</span>
            <v-icon icon="mdi-server" size="28" color="grey-darken-1" />
          </div>
          <div class="text-h2 font-weight-bold mt-2">
            {{ endpoints.length }}
          </div>
          <div class="text-caption text-medium-emphasis">
            registered
          </div>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" md="3">
        <v-card class="pa-4 stat-card h-100">
          <div class="d-flex align-center justify-space-between">
            <span class="text-subtitle-1 font-weight-medium">Active Objects</span>
            <v-icon icon="mdi-shape-outline" size="28" color="grey-darken-1" />
          </div>
          <div class="text-h2 font-weight-bold mt-2 text-medium-emphasis">
            —
          </div>
          <div class="text-caption text-medium-emphasis">
            Not available yet
          </div>
        </v-card>
      </v-col>

      <v-col cols="12" sm="6" md="3">
        <v-card class="pa-4 stat-card h-100">
          <div class="d-flex align-center justify-space-between">
            <span class="text-subtitle-1 font-weight-medium">Functions</span>
            <v-icon icon="mdi-function-variant" size="28" color="grey-darken-1" />
          </div>
          <div class="text-h2 font-weight-bold mt-2">
            {{ activeFunctionsCount }}
          </div>
          <div class="text-caption stat-caption-spacer">
            &nbsp;
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Networks -->
    <v-card class="pa-6 mt-4">
      <div class="d-flex align-center justify-space-between flex-wrap" style="gap: 24px;">
        <span class="text-subtitle-1 font-weight-medium">Networks</span>
        <div class="d-flex align-center" style="gap: 8px;">
          <v-icon icon="mdi-arrow-down-bold-circle" color="primary" />
          <span class="font-weight-bold">GET</span>
          <span class="text-medium-emphasis">—</span>
        </div>
        <div class="d-flex align-center" style="gap: 8px;">
          <v-icon icon="mdi-arrow-up-bold-circle" color="error" />
          <span class="font-weight-bold">PUT</span>
          <span class="text-medium-emphasis">—</span>
        </div>
      </div>
      <div class="text-caption text-medium-emphasis mt-2">
        Not available yet — no network telemetry is emitted by any endpoint currently.
      </div>
    </v-card>

    <!-- Capacity -->
    <v-card class="pa-6 mt-4">
      <span class="text-subtitle-1 font-weight-medium">Capacity (Allocated)</span>
      <v-row class="mt-1" density="comfortable">
        <v-col cols="4">
          <div class="text-h4 font-weight-bold">
            {{ totalQuota.cpu }}
          </div>
          <div class="text-caption text-medium-emphasis">
            vCPU cores
          </div>
        </v-col>
        <v-col cols="4">
          <div class="text-h4 font-weight-bold">
            {{ totalQuota.ram }} GB
          </div>
          <div class="text-caption text-medium-emphasis">
            RAM
          </div>
        </v-col>
        <v-col cols="4">
          <div class="text-h4 font-weight-bold">
            {{ totalQuota.disk }} GB
          </div>
          <div class="text-caption text-medium-emphasis">
            Disk
          </div>
        </v-col>
      </v-row>
      <div class="text-caption text-medium-emphasis mt-2">
        Declared across {{ veStore.items.length }} virtual environment{{ veStore.items.length === 1 ? '' : 's' }} you own — not live disk usage.
      </div>
    </v-card>

    <!-- Recent-activity mini metrics (redesigned reference-plot grid) -->
    <v-row class="mt-4">
      <v-col v-for="metric in activityMetrics" :key="metric.title" cols="12" sm="4">
        <v-card class="pa-4">
          <div class="text-subtitle-1 text-medium-emphasis">
            {{ metric.title }}
          </div>
          <div class="text-h3 font-weight-bold">
            {{ metric.count }}
          </div>
          <v-sparkline
            :model-value="metric.values"
            :color="metric.color"
            height="40"
            padding="8"
            smooth
            line-width="2"
            fill
          />
        </v-card>
      </v-col>
    </v-row>

    <!-- Recent activity list (replaces the mockup's fake growth chart) -->
    <v-card class="pa-6 mt-4">
      <span class="text-subtitle-1 font-weight-medium">Recent Activity</span>
      <v-list v-if="history.length" density="compact" class="mt-2">
        <v-list-item
          v-for="event in history.slice(0, 10)"
          :key="event.event_id"
          :title="event.event_type"
          :subtitle="relativeTime(event.created_at)"
        />
      </v-list>
      <div v-else class="text-caption text-medium-emphasis mt-2">
        No recent activity yet.
      </div>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import type { ActivityEvent } from '~/types/activity'
import type { EndpointDoc } from '~/types/endpoint'
import type { FunctionRecord } from '~/types/functionRecord'

const { apiFetch } = useApi()
const authStore = useAuthStore()
const veStore = useVirtualEnvironmentsStore()

const endpoints = ref<EndpointDoc[]>([])
const functions = ref<FunctionRecord[]>([])
const history = ref<ActivityEvent[]>([])

onMounted(async () => {
  const userId = authStore.currentUser?.user_id
  await Promise.all([
    veStore.fetchAll(),
    apiFetch<EndpointDoc[]>('/endpoints').then(r => (endpoints.value = r)).catch(() => {}),
    apiFetch<FunctionRecord[]>('/functions').then(r => (functions.value = r)).catch(() => {}),
    apiFetch<ActivityEvent[]>(`/history?limit=100${userId ? `&user_id=${userId}` : ''}`)
      .then(r => (history.value = r))
      .catch(() => {}),
  ])
})

const activeFunctionsCount = computed(
  () => functions.value.filter(f => !f.deleted_at).length,
)

const totalQuota = computed(() => {
  return veStore.items.reduce(
    (acc, ve) => ({
      cpu: acc.cpu + (ve.resource_quota?.cpu ?? 0),
      ram: acc.ram + (ve.resource_quota?.ram ?? 0),
      disk: acc.disk + (ve.resource_quota?.disk ?? 0),
    }),
    { cpu: 0, ram: 0, disk: 0 },
  )
})

// Buckets real /history events by day, per event_type -- real counts, not
// fabricated sparkline data. Days come from the full fetched window so
// every metric's sparkline shares the same x-axis.
function bucketCounts(events: ActivityEvent[], eventType: string): number[] {
  if (events.length === 0) return [0, 0]
  const byDay = new Map<string, number>()
  for (const e of events) {
    const day = e.created_at.slice(0, 10)
    if (!byDay.has(day)) byDay.set(day, 0)
  }
  for (const e of events) {
    if (e.event_type === eventType) {
      const day = e.created_at.slice(0, 10)
      byDay.set(day, (byDay.get(day) ?? 0) + 1)
    }
  }
  const days = Array.from(byDay.keys()).sort()
  const values = days.map(d => byDay.get(d) ?? 0)
  return values.length >= 2 ? values : [...values, ...values]
}

const activityMetrics = computed(() => {
  const specs = [
    { title: 'Jobs Completed', type: 'JobCompleted', color: '#2F6FED' },
    { title: 'Jobs Failed', type: 'JobFailed', color: '#e5484d' },
    { title: 'Functions Registered', type: 'FunctionRegistered', color: '#22c55e' },
  ]
  return specs.map(spec => ({
    title: spec.title,
    color: spec.color,
    count: history.value.filter(e => e.event_type === spec.type).length,
    values: bucketCounts(history.value, spec.type),
  }))
})

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMin = Math.round(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.round(diffHr / 24)
  return `${diffDay}d ago`
}
</script>

<style scoped>
.stat-card {
  border-radius: 16px;
}

/* Reserves the same caption line height on cards that have no caption of
   their own, so all 4 top stat cards line up at an identical height. */
.stat-caption-spacer {
  visibility: hidden;
}
</style>
