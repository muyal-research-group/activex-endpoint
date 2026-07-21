<template>
  <v-container fluid class="pa-6">
    <NuxtLink to="/virtual-environments" class="text-body-2 mb-4 d-inline-block">
      &larr; Virtual Environments
    </NuxtLink>

    <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
      {{ store.error }}
    </v-alert>

    <template v-if="store.current">
      <v-card class="pa-6 mb-6">
        <div class="d-flex justify-space-between align-start flex-wrap" style="gap: 16px;">
          <div>
            <div class="d-flex align-center mb-1" style="gap: 12px;">
              <h2 class="text-h6">
                {{ store.current.name }}
              </h2>
              <v-chip v-if="store.current.deleted_at" size="small" variant="tonal">
                Deleted
              </v-chip>
            </div>
            <div class="text-caption text-medium-emphasis ve-id-caption mb-4">
              {{ store.current.virtual_environment_id }}
            </div>
            <div class="d-flex" style="gap: 32px;">
              <div>
                <div class="text-caption text-medium-emphasis">
                  # Cores
                </div>
                <div class="text-h6">
                  {{ store.current.resource_quota.cpu }}
                </div>
              </div>
              <div>
                <div class="text-caption text-medium-emphasis">
                  RAM (GB)
                </div>
                <div class="text-h6">
                  {{ store.current.resource_quota.ram }}
                </div>
              </div>
              <div>
                <div class="text-caption text-medium-emphasis">
                  Disk (GB)
                </div>
                <div class="text-h6">
                  {{ store.current.resource_quota.disk }}
                </div>
              </div>
            </div>
          </div>
          <div class="d-flex" style="gap: 8px;">
            <span :title="deleteDisabledReason">
              <v-btn
                variant="tonal"
                color="error"
                prepend-icon="mdi-delete-outline"
                :disabled="!!deleteDisabledReason"
                @click="showDeleteDialog = true"
              >
                Delete
              </v-btn>
            </span>
            <span :title="store.current.deleted_at ? '' : 'Delete the virtual environment first'">
              <v-btn
                variant="tonal"
                color="error"
                prepend-icon="mdi-delete-forever"
                :disabled="!store.current.deleted_at"
                @click="showPurgeDialog = true"
              >
                Purge
              </v-btn>
            </span>
          </div>
        </div>
      </v-card>

      <v-row align="stretch" class="mb-2">
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 stat-card h-100">
            <div class="d-flex align-center justify-space-between">
              <span class="text-subtitle-1 font-weight-medium">Endpoints</span>
              <v-icon icon="mdi-server" size="24" color="grey-darken-1" />
            </div>
            <div class="text-h4 font-weight-bold mt-1">
              {{ assignedEndpoints.length }}
            </div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 stat-card h-100">
            <div class="d-flex align-center justify-space-between">
              <span class="text-subtitle-1 font-weight-medium">Functions</span>
              <v-icon icon="mdi-function-variant" size="24" color="grey-darken-1" />
            </div>
            <div class="text-h4 font-weight-bold mt-1">
              {{ activeFunctionCount }}
            </div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 stat-card h-100">
            <div class="d-flex align-center justify-space-between">
              <span class="text-subtitle-1 font-weight-medium">Jobs</span>
              <v-icon icon="mdi-briefcase-outline" size="24" color="grey-darken-1" />
            </div>
            <div class="text-h4 font-weight-bold mt-1">
              {{ jobStats.completed + jobStats.failed }}
            </div>
            <div class="text-caption text-medium-emphasis">
              {{ jobStats.completed }} completed · {{ jobStats.failed }} failed
            </div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 stat-card h-100">
            <div class="d-flex align-center justify-space-between">
              <span class="text-subtitle-1 font-weight-medium">Active Objects</span>
              <v-icon icon="mdi-shape-outline" size="24" color="grey-darken-1" />
            </div>
            <div class="text-h4 font-weight-bold mt-1 text-medium-emphasis">
              —
            </div>
            <div class="text-caption text-medium-emphasis">
              Not available yet
            </div>
          </v-card>
        </v-col>
      </v-row>

      <v-card class="pa-6 mb-6">
        <h3 class="text-h6 mb-4">
          Endpoints
        </h3>
        <p v-if="assignedEndpoints.length === 0" class="text-body-2 text-medium-emphasis">
          No endpoints assigned
        </p>
        <v-row v-else>
          <v-col v-for="endpoint in assignedEndpoints" :key="endpoint.endpoint_id" cols="12" sm="6" md="4">
            <NuxtLink :to="`/endpoints/${endpoint.endpoint_id}`" class="text-decoration-none">
              <v-card class="pa-4 endpoint-card" variant="tonal">
                <div class="d-flex align-center justify-space-between">
                  <div class="d-flex align-center" style="gap: 8px;">
                    <v-icon icon="mdi-server" size="18" />
                    <span class="text-body-1 font-weight-medium">{{ endpoint.endpoint_id }}</span>
                  </div>
                  <v-chip :color="endpoint.status === 'running' ? 'success' : 'default'" size="small" variant="tonal">
                    {{ endpoint.status ?? 'unknown' }}
                  </v-chip>
                </div>
                <div class="text-caption text-medium-emphasis mt-1">
                  {{ endpoint.router_bind ?? '—' }}
                </div>
              </v-card>
            </NuxtLink>
          </v-col>
        </v-row>
      </v-card>

      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Activity
        </h3>
        <ActivityTimeline :events="store.history" />
      </v-card>
    </template>

    <!-- Delete confirm dialog -->
    <v-dialog v-model="showDeleteDialog" max-width="420">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Delete "{{ store.current?.name }}"?
        </h3>
        <p class="text-body-2 mb-4">
          This cannot be undone.
        </p>
        <v-alert v-if="deleteError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ deleteError }}
        </v-alert>
        <div class="d-flex justify-end" style="gap: 8px;">
          <v-btn variant="text" @click="showDeleteDialog = false">
            Cancel
          </v-btn>
          <v-btn color="error" @click="onDelete">
            Delete
          </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- Purge confirm dialog -->
    <v-dialog v-model="showPurgeDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Purge "{{ store.current?.name }}"?
        </h3>
        <p class="text-body-2 mb-4">
          This permanently removes this virtual environment's record and its
          activity history. Cannot be undone.
        </p>
        <v-alert v-if="purgeError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ purgeError }}
        </v-alert>
        <div class="d-flex justify-end" style="gap: 8px;">
          <v-btn variant="text" @click="showPurgeDialog = false">
            Cancel
          </v-btn>
          <v-btn color="error" @click="onPurge">
            Purge
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
const route = useRoute()
const store = useVirtualEnvironmentsStore()
const endpointsStore = useEndpointsStore()
const functionsStore = useFunctionsStore()

const id = route.params.id as string

onMounted(() => {
  store.fetchOne(id)
  store.fetchHistory(id)
  endpointsStore.fetchAll()
  functionsStore.fetchAll()
})

const assignedEndpoints = computed(
  () => endpointsStore.items.filter(e => e.virtual_environment_id === id),
)

const deleteDisabledReason = computed(() => {
  if (store.current?.deleted_at) return 'Already deleted'
  if (assignedEndpoints.value.length > 0) return 'Unassign all endpoints first'
  return ''
})

const activeFunctionCount = computed(
  () => functionsStore.items.filter(f => f.virtual_environment_id === id && !f.deleted_at).length,
)

const jobStats = computed(() => ({
  completed: store.history.filter(e => e.event_type === 'JobCompleted').length,
  failed: store.history.filter(e => e.event_type === 'JobFailed').length,
}))

const showDeleteDialog = ref(false)
const deleteError = ref<string | null>(null)

async function onDelete() {
  deleteError.value = null
  try {
    await store.remove(id)
    showDeleteDialog.value = false
    await navigateTo('/virtual-environments')
  } catch (err: any) {
    deleteError.value = err.message
  }
}

const showPurgeDialog = ref(false)
const purgeError = ref<string | null>(null)

async function onPurge() {
  purgeError.value = null
  try {
    await store.purge(id)
    showPurgeDialog.value = false
    await navigateTo('/virtual-environments')
  } catch (err: any) {
    purgeError.value = err.message
  }
}
</script>

<style scoped>
.stat-card {
  border-radius: 16px;
}

.endpoint-card {
  transition: transform 0.1s ease;
}

.endpoint-card:hover {
  transform: translateY(-2px);
}

.ve-id-caption {
  font-family: monospace;
  word-break: break-all;
}
</style>
