<template>
  <v-container fluid class="pa-6">
    <div class="d-flex mb-6" style="gap: 16px;">
      <v-card class="pa-4 stat-card" width="200">
        <div class="d-flex align-center justify-space-between">
          <span class="text-subtitle-1">Nodes</span>
          <span class="status-dot status-dot--active" />
        </div>
        <div class="text-h4 font-weight-bold mt-1">
          {{ store.items.length }}
        </div>
      </v-card>
    </div>

    <v-btn
      color="secondary"
      size="large"
      rounded="lg"
      prepend-icon="mdi-plus"
      class="text-uppercase font-weight-bold mb-6"
      @click="openDeployDialog"
    >
      Deploy Endpoint
    </v-btn>

    <v-card class="pa-6">
      <h2 class="text-h6 mb-4">
        Endpoints
      </h2>

      <v-text-field
        v-model="search"
        placeholder="Search"
        variant="solo"
        flat
        rounded="pill"
        :bg-color="isDarkTheme ? '#1B1C1F' : '#f4f5f8'"
        density="comfortable"
        prepend-inner-icon="mdi-magnify"
        hide-details
        class="mb-4 search-field"
        :class="{ 'search-field--dark': isDarkTheme }"
        max-width="420"
      />

      <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
        {{ store.error }}
      </v-alert>

      <v-data-table
        :headers="headers"
        :items="filteredItems"
        :loading="store.loading"
        item-value="endpoint_id"
        no-data-text="No endpoints yet"
        :item-class="(item) => item.status === 'stopped' ? 'text-medium-emphasis' : ''"
      >
        <template #item.endpoint_id="{ item }">
          <NuxtLink :to="`/endpoints/${item.endpoint_id}`" class="d-flex align-center text-decoration-none">
            <v-avatar size="32" color="grey-lighten-2" class="mr-3">
              <v-icon icon="mdi-server" size="18" />
            </v-avatar>
            {{ item.endpoint_id }}
          </NuxtLink>
        </template>
        <template #item.status="{ item }">
          <v-chip
            :color="item.status === 'stopped' ? 'default' : item.status === 'unreachable' ? 'warning' : 'success'"
            size="small"
            variant="tonal"
          >
            {{ item.status ?? 'unknown' }}
          </v-chip>
        </template>
        <template #item.router_bind="{ item }">
          {{ item.router_bind ?? '—' }}
        </template>
        <template #item.virtual_environment_id="{ item }">
          {{ item.virtual_environment_id ?? '—' }}
        </template>
        <template #item.cpu_percent="{ item }">
          <span v-if="item.container_stats?.available" class="text-medium-emphasis">
            {{ item.container_stats.cpu_percent?.toFixed(1) }}%
          </span>
          <span v-else-if="item.container_stats" class="text-caption text-medium-emphasis">
            unavailable
          </span>
          <span v-else class="text-caption text-medium-emphasis">—</span>
        </template>
        <template #item.memory="{ item }">
          <span v-if="item.container_stats?.available" class="text-medium-emphasis">
            {{ formatBytes(item.container_stats.memory_usage ?? 0) }} / {{ formatBytes(item.container_stats.memory_limit ?? 0) }}
          </span>
          <span v-else class="text-caption text-medium-emphasis">—</span>
        </template>
        <template #item.actions="{ item }">
          <v-btn
            icon="mdi-cube-send"
            variant="text"
            size="small"
            title="Assign virtual environment"
            @click="openAssignDialog(item)"
          />
          <v-btn
            icon="mdi-restart"
            variant="text"
            size="small"
            title="Restart"
            @click="onRestart(item)"
          />
          <v-btn
            icon="mdi-stop-circle-outline"
            variant="text"
            size="small"
            title="Stop"
            @click="onStop(item)"
          />
        </template>
      </v-data-table>
    </v-card>

    <!-- Deploy dialog -->
    <v-dialog v-model="showDeployDialog" max-width="640" scrollable>
      <v-card>
        <v-card-title class="pa-6 pb-0">
          <h3 class="text-h6">
            Deploy Endpoint
          </h3>
        </v-card-title>
        <v-card-text class="pa-6">
          <v-form @submit.prevent="onDeploy">
            <v-select
              v-model="form.virtual_environment_id"
              :items="veOptions"
              item-title="name"
              item-value="virtual_environment_id"
              label="Virtual Environment"
              variant="outlined"
              density="comfortable"
              clearable
              hint="Optional -- leave unassigned to configure later"
              persistent-hint
              class="mb-4"
            />

            <div class="d-flex mb-4" style="gap: 12px;">
              <v-text-field
                v-model.number="form.router_port"
                label="Router port"
                type="number"
                variant="outlined"
                density="comfortable"
              />
              <v-text-field
                v-model.number="form.pub_port"
                label="Pub port"
                type="number"
                variant="outlined"
                density="comfortable"
              />
              <v-text-field
                v-model.number="form.results_port"
                label="Results port"
                type="number"
                variant="outlined"
                density="comfortable"
              />
            </div>

            <v-expansion-panels class="mb-4">
              <v-expansion-panel>
                <v-expansion-panel-title>
                  Advanced: environment variables ({{ envKeys.length }})
                </v-expansion-panel-title>
                <v-expansion-panel-text>
                  <p class="text-caption text-medium-emphasis mb-3">
                    Pre-filled with each node's defaults -- edit any value to override it.
                  </p>
                  <v-text-field
                    v-for="key in envKeys"
                    :key="key"
                    v-model="form.env_overrides[key]"
                    :label="key"
                    variant="outlined"
                    density="compact"
                    class="mb-2"
                  />
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>

            <v-alert v-if="deployError" type="error" variant="tonal" density="compact" class="mb-4">
              {{ deployError }}
            </v-alert>

            <div class="d-flex justify-end" style="gap: 8px;">
              <v-btn variant="text" @click="showDeployDialog = false">
                Cancel
              </v-btn>
              <v-btn color="secondary" type="submit" :loading="store.loading">
                Deploy
              </v-btn>
            </div>
          </v-form>
        </v-card-text>
      </v-card>
    </v-dialog>

    <!-- Assign virtual environment dialog -->
    <v-dialog v-model="showAssignDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Assign virtual environment to "{{ assignTarget?.endpoint_id }}"
        </h3>
        <v-select
          v-model="assignVeId"
          :items="veOptions"
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
        <v-alert v-if="assignError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ assignError }}
        </v-alert>
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
  </v-container>
</template>

<script setup lang="ts">
import type { EndpointDoc } from '~/types/endpoint'

const store = useEndpointsStore()
const veStore = useVirtualEnvironmentsStore()

const { preference } = useThemeSetting()
const isDarkTheme = computed(() => preference.value === 'axoDark')

onMounted(() => {
  store.fetchAll()
  veStore.fetchAll()
  store.connectFleetSocket()
})

onBeforeUnmount(() => {
  store.disconnectFleetSocket()
})

const search = ref('')
const filteredItems = computed(() => {
  if (!search.value.trim()) return store.items
  const q = search.value.toLowerCase()
  return store.items.filter(e => e.endpoint_id.toLowerCase().includes(q))
})

const headers = [
  { title: 'Endpoint', key: 'endpoint_id' },
  { title: 'Status', key: 'status' },
  { title: 'Router bind', key: 'router_bind' },
  { title: 'Virtual environment', key: 'virtual_environment_id' },
  { title: 'CPU', key: 'cpu_percent', sortable: false },
  { title: 'Memory', key: 'memory', sortable: false },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

const veOptions = computed(() => veStore.items)

// Backend-owned identity/addressing keys -- LaunchEndpointNodeUseCase always
// sets these itself and silently ignores anything sent here for them, so
// they're excluded from the editable list rather than shown as no-ops.
const MESH_IDENTITY_KEYS = new Set([
  'AXO_ENDPOINT_ID', 'AXO_ENDPOINT_SUB_CONNECT', 'AXO_ENDPOINT_API_URI',
  'AXO_ENDPOINT_ROUTER_BIND', 'AXO_ENDPOINT_PUB_BIND', 'AXO_ENDPOINT_VIRTUAL_ENV_ID',
])

const showDeployDialog = ref(false)
const deployError = ref<string | null>(null)

const form = reactive({
  virtual_environment_id: null as string | null,
  router_port: 5555,
  pub_port: 5556,
  results_port: 5557,
  env_overrides: {} as Record<string, string>,
})

const envKeys = computed(() => Object.keys(form.env_overrides).sort())

async function openDeployDialog() {
  deployError.value = null
  form.virtual_environment_id = null
  form.router_port = 5555
  form.pub_port = 5556
  form.results_port = 5557

  if (Object.keys(veStore.items).length === 0) await veStore.fetchAll()
  await store.fetchDeploymentDefaults()
  form.env_overrides = Object.fromEntries(
    Object.entries(store.deploymentDefaults).filter(([key]) => !MESH_IDENTITY_KEYS.has(key)),
  )

  showDeployDialog.value = true
}

async function onDeploy() {
  deployError.value = null
  try {
    await store.deploy({
      virtual_environment_id: form.virtual_environment_id,
      env_overrides: form.env_overrides,
      router_port: form.router_port,
      pub_port: form.pub_port,
      results_port: form.results_port,
    })
    showDeployDialog.value = false
  } catch (err: any) {
    deployError.value = err.message
  }
}

const showAssignDialog = ref(false)
const assignError = ref<string | null>(null)
const assignTarget = ref<EndpointDoc | null>(null)
const assignVeId = ref<string | null>(null)

function openAssignDialog(item: EndpointDoc) {
  assignTarget.value = item
  assignVeId.value = (item.virtual_environment_id as string | undefined) ?? null
  assignError.value = null
  showAssignDialog.value = true
}

async function onAssign() {
  if (!assignTarget.value) return
  try {
    await store.assignVirtualEnvironment(assignTarget.value.endpoint_id, assignVeId.value)
    showAssignDialog.value = false
  } catch (err: any) {
    assignError.value = err.message
  }
}

async function onStop(item: EndpointDoc) {
  if (!confirm(`Stop and remove "${item.endpoint_id}"? This only works for endpoints deployed via this API.`)) return
  try {
    await store.stop(item.endpoint_id)
  } catch {
    // surfaced through store.error's existing alert
  }
}

async function onRestart(item: EndpointDoc) {
  try {
    await store.restart(item.endpoint_id)
  } catch {
    // surfaced through store.error's existing alert
  }
}
</script>

<style scoped>
.stat-card {
  border-radius: 16px;
}

.search-field--dark :deep(.v-field__input) {
  color: #fff;
}

.search-field--dark :deep(input::placeholder) {
  color: rgba(255, 255, 255, 0.6);
  opacity: 1;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot--active {
  background-color: #22c55e;
}
</style>
