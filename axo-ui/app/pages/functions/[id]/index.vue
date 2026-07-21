<template>
  <v-container fluid class="pa-6">
    <NuxtLink to="/functions" class="text-body-2 mb-4 d-inline-block">
      &larr; Functions
    </NuxtLink>

    <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
      {{ store.error }}
    </v-alert>

    <v-card class="pa-6 mb-6">
      <h2 class="text-h6 mb-1">
        {{ functionName ?? functionId }}
      </h2>
      <div v-if="functionName" class="text-caption text-medium-emphasis function-id-caption mb-4">
        {{ functionId }}
      </div>
      <div v-else class="mb-4" />
      <v-table density="comfortable">
        <thead>
          <tr>
            <th>Version</th>
            <th>Runtime</th>
            <th>State</th>
            <th>Parameters</th>
            <th />
            <th />
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="version in store.versions" :key="version.version">
            <td>{{ version.version }}</td>
            <td>{{ version.runtime_spec?.type ?? 'process' }}</td>
            <td>
              {{ version.state ?? '—' }}
              <v-chip v-if="version.deleted_at" size="small" variant="tonal" class="ml-2">
                Deleted
              </v-chip>
            </td>
            <td>
              <span v-if="!version.params_schema || version.params_schema.length === 0" class="text-medium-emphasis">
                —
              </span>
              <v-chip
                v-for="param in version.params_schema"
                :key="param.name"
                size="small"
                variant="tonal"
                :color="param.required ? 'secondary' : undefined"
                class="mr-1 mb-1"
              >
                {{ param.name }}: {{ param.type }}{{ param.required ? ' *' : '' }}
              </v-chip>
            </td>
            <td class="text-right">
              <v-btn
                :to="`/functions/${functionId}/run/${version.version}`"
                icon="mdi-play-circle-outline"
                variant="text"
                size="small"
                title="Run"
              />
            </td>
            <td class="text-right">
              <v-btn
                icon="mdi-delete-outline"
                variant="text"
                size="small"
                title="Delete"
                :disabled="!!version.deleted_at"
                @click="confirmDelete(version)"
              />
            </td>
            <td class="text-right">
              <span :title="version.deleted_at ? '' : 'Delete this version first'">
                <v-btn
                  icon="mdi-delete-forever"
                  variant="text"
                  size="small"
                  title="Purge"
                  :disabled="!version.deleted_at"
                  @click="confirmPurge(version)"
                />
              </span>
            </td>
          </tr>
        </tbody>
      </v-table>
    </v-card>

    <v-card class="pa-6 mb-6">
      <h3 class="text-h6 mb-4">
        Jobs
      </h3>
      <v-data-table
        :headers="jobHeaders"
        :items="jobsStore.history"
        item-value="job_id"
        no-data-text="No jobs run yet"
      >
        <template #item.job_id="{ item }">
          <NuxtLink
            :to="`/functions/${functionId}/run/${item.function_version}?job=${item.job_id}&endpoint=${item.endpoint_id}`"
            class="text-decoration-none"
          >
            {{ item.job_id }}
          </NuxtLink>
        </template>
        <template #item.status="{ item }">
          <v-chip :color="item.status === 'FAILED' ? 'error' : (item.status === 'COMPLETED' ? 'success' : 'default')" size="small" variant="tonal">
            {{ item.status }}
          </v-chip>
        </template>
        <template #item.duration_ms="{ item }">
          {{ item.duration_ms != null ? `${item.duration_ms.toFixed(0)} ms` : '—' }}
        </template>
        <template #item.created_at="{ item }">
          {{ item.created_at ?? '—' }}
        </template>
      </v-data-table>
    </v-card>

    <v-card class="pa-6">
      <h3 class="text-h6 mb-4">
        Activity
      </h3>
      <ActivityTimeline :events="store.history" />
    </v-card>

    <!-- Delete confirm dialog -->
    <v-dialog v-model="showDeleteDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Delete "{{ functionId }}" v{{ pendingDelete?.version }}?
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
          <v-btn color="error" :loading="store.loading" @click="onDelete">
            Delete
          </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- Purge confirm dialog -->
    <v-dialog v-model="showPurgeDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Purge "{{ functionId }}" v{{ pendingPurge?.version }}?
        </h3>
        <p class="text-body-2 mb-4">
          This permanently removes this version and its activity history.
          Cannot be undone.
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
import type { FunctionRecord } from '~/types/functionRecord'

const route = useRoute()
const store = useFunctionsStore()
const jobsStore = useJobsStore()

const functionId = route.params.id as string
// Same across every version (function_id is derived from the name), so any
// version carrying it works -- older functions registered before name
// forwarding existed will have none, and just fall back to showing the id.
const functionName = computed(() => store.versions.find(v => v.name)?.name ?? null)

onMounted(() => {
  store.fetchOne(functionId)
  store.fetchHistory(functionId)
  jobsStore.fetchHistory(functionId)
})

const jobHeaders = [
  { title: 'Job', key: 'job_id' },
  { title: 'Version', key: 'function_version' },
  { title: 'Status', key: 'status' },
  { title: 'Duration', key: 'duration_ms' },
  { title: 'Submitted', key: 'created_at' },
]

const showDeleteDialog = ref(false)
const deleteError = ref<string | null>(null)
const pendingDelete = ref<FunctionRecord | null>(null)

function confirmDelete(item: FunctionRecord) {
  pendingDelete.value = item
  deleteError.value = null
  showDeleteDialog.value = true
}

async function onDelete() {
  if (!pendingDelete.value) return
  try {
    await store.remove(functionId, pendingDelete.value.version)
    await store.fetchOne(functionId)
    showDeleteDialog.value = false
    pendingDelete.value = null
  } catch (err: any) {
    deleteError.value = err.message
  }
}

const showPurgeDialog = ref(false)
const purgeError = ref<string | null>(null)
const pendingPurge = ref<FunctionRecord | null>(null)

function confirmPurge(item: FunctionRecord) {
  pendingPurge.value = item
  purgeError.value = null
  showPurgeDialog.value = true
}

async function onPurge() {
  if (!pendingPurge.value) return
  try {
    await store.purgeVersion(functionId, pendingPurge.value.version)
    showPurgeDialog.value = false
    pendingPurge.value = null
  } catch (err: any) {
    purgeError.value = err.message
  }
}
</script>

<style scoped>
.function-id-caption {
  font-family: monospace;
  word-break: break-all;
}
</style>
