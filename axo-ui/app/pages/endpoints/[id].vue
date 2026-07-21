<template>
  <v-container fluid class="pa-6">
    <NuxtLink to="/endpoints" class="text-body-2 mb-4 d-inline-block">
      &larr; Endpoints
    </NuxtLink>

    <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
      {{ store.error }}
    </v-alert>

    <template v-if="store.current">
      <v-card class="pa-6 mb-6">
        <div class="d-flex justify-space-between align-start">
          <div>
            <div class="d-flex align-center mb-4" style="gap: 12px;">
              <h2 class="text-h6">
                {{ store.current.endpoint_id }}
              </h2>
              <v-chip
                :color="store.current.status === 'stopped' ? 'default' : store.current.status === 'unreachable' ? 'warning' : 'success'"
                size="small"
                variant="tonal"
              >
                {{ store.current.status ?? 'unknown' }}
              </v-chip>
            </div>
            <div class="text-caption text-medium-emphasis">
              Router bind
            </div>
            <div class="text-body-1 mb-3">
              {{ store.current.router_bind ?? '—' }}
            </div>
            <div class="text-caption text-medium-emphasis">
              Virtual environment
            </div>
            <div class="text-body-1 mb-3">
              {{ store.current.virtual_environment_id ?? '—' }}
            </div>
            <template v-if="store.current.status === 'unreachable'">
              <div class="text-caption text-medium-emphasis">
                Unreachable since
              </div>
              <div class="text-body-1">
                {{ store.current.unreachable_since ?? '—' }}
              </div>
            </template>
          </div>
          <div class="d-flex" style="gap: 8px;">
            <v-btn variant="tonal" prepend-icon="mdi-cube-send" @click="openAssignDialog">
              Assign VE
            </v-btn>
            <v-btn variant="tonal" prepend-icon="mdi-restart" @click="onRestart">
              Restart
            </v-btn>
            <v-btn variant="tonal" color="error" prepend-icon="mdi-stop-circle-outline" @click="onStop">
              Stop
            </v-btn>
            <span :title="['stopped', 'unreachable'].includes(store.current.status ?? '') ? '' : 'Stop the endpoint first'">
              <v-btn
                :variant="store.current.purge_eligible ? 'flat' : 'tonal'"
                color="error"
                prepend-icon="mdi-delete-forever"
                :disabled="!['stopped', 'unreachable'].includes(store.current.status ?? '')"
                @click="showPurgeDialog = true"
              >
                {{ store.current.purge_eligible ? 'Purge recommended' : 'Purge' }}
              </v-btn>
            </span>
          </div>
        </div>
      </v-card>

      <v-card class="pa-6 mb-6">
        <h3 class="text-h6 mb-4">
          Resource usage
        </h3>
        <div v-if="store.current.container_stats?.available" class="d-flex" style="gap: 48px;">
          <div>
            <div class="text-caption text-medium-emphasis">
              CPU
            </div>
            <div class="text-h5 font-weight-bold">
              {{ store.current.container_stats.cpu_percent?.toFixed(1) }}%
            </div>
          </div>
          <div>
            <div class="text-caption text-medium-emphasis">
              Memory
            </div>
            <div class="text-h5 font-weight-bold">
              {{ formatBytes(store.current.container_stats.memory_usage ?? 0) }}
              <span class="text-body-2 text-medium-emphasis">
                / {{ formatBytes(store.current.container_stats.memory_limit ?? 0) }}
              </span>
            </div>
          </div>
          <div>
            <div class="text-caption text-medium-emphasis">
              Network RX / TX
            </div>
            <div class="text-h5 font-weight-bold">
              {{ formatBytes(store.current.container_stats.network_rx ?? 0) }} / {{ formatBytes(store.current.container_stats.network_tx ?? 0) }}
            </div>
          </div>
        </div>
        <p v-else-if="store.current.container_stats" class="text-body-2 text-medium-emphasis">
          Stats unavailable -- this endpoint isn't a container managed by this API (e.g. a docker-compose-managed node).
        </p>
        <p v-else class="text-body-2 text-medium-emphasis">
          Waiting for the first stats update…
        </p>
      </v-card>

      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Activity
        </h3>
        <ActivityTimeline :events="store.history" />
      </v-card>
    </template>

    <!-- Assign virtual environment dialog -->
    <v-dialog v-model="showAssignDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Assign virtual environment
        </h3>
        <v-select
          v-model="assignVeId"
          :items="veStore.items"
          item-title="name"
          item-value="virtual_environment_id"
          label="Virtual Environment"
          variant="outlined"
          density="comfortable"
          clearable
          hint="Leave empty to detach"
          persistent-hint
          class="mb-4"
        />
        <div class="d-flex justify-end" style="gap: 8px;">
          <v-btn variant="text" @click="showAssignDialog = false">
            Cancel
          </v-btn>
          <v-btn color="secondary" :loading="store.loading" @click="onAssign">
            Save
          </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- Purge confirm dialog -->
    <v-dialog v-model="showPurgeDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Purge "{{ endpointId }}"?
        </h3>
        <p class="text-body-2 mb-4">
          This permanently removes this endpoint's record and its activity
          history. Cannot be undone.
        </p>
        <v-alert v-if="purgeError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ purgeError }}
        </v-alert>
        <div class="d-flex justify-end" style="gap: 8px;">
          <v-btn variant="text" @click="showPurgeDialog = false">
            Cancel
          </v-btn>
          <v-btn color="error" :loading="store.loading" @click="onPurge">
            Purge
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
const route = useRoute()
const store = useEndpointsStore()
const veStore = useVirtualEnvironmentsStore()

const endpointId = route.params.id as string

onMounted(() => {
  store.fetchOne(endpointId)
  store.fetchHistory(endpointId)
  veStore.fetchAll()
  store.connectScopedSocket(endpointId)
})

onBeforeUnmount(() => {
  store.disconnectScopedSocket()
})

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

const showAssignDialog = ref(false)
const assignVeId = ref<string | null>(null)

function openAssignDialog() {
  assignVeId.value = (store.current?.virtual_environment_id as string | undefined) ?? null
  showAssignDialog.value = true
}

async function onAssign() {
  try {
    await store.assignVirtualEnvironment(endpointId, assignVeId.value)
    await store.fetchOne(endpointId)
    showAssignDialog.value = false
  } catch {
    // surfaced through store.error's existing alert
  }
}

async function onStop() {
  if (!confirm(`Stop and remove "${endpointId}"? This only works for endpoints deployed via this API.`)) return
  await store.stop(endpointId).catch(() => {})
  await store.fetchOne(endpointId)
}

async function onRestart() {
  await store.restart(endpointId).catch(() => {})
  await store.fetchOne(endpointId)
}

const showPurgeDialog = ref(false)
const purgeError = ref<string | null>(null)

async function onPurge() {
  purgeError.value = null
  try {
    await store.purge(endpointId)
    showPurgeDialog.value = false
    await navigateTo('/endpoints')
  } catch (err: any) {
    purgeError.value = err.message
  }
}
</script>
