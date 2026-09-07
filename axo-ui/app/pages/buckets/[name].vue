<template>
  <v-container fluid class="pa-6">
    <NuxtLink to="/buckets" class="text-body-2 mb-4 d-inline-block">
      &larr; Buckets
    </NuxtLink>

    <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
      {{ store.error }}
    </v-alert>

    <template v-if="store.current">
      <v-card class="pa-6 mb-6">
        <div class="d-flex justify-space-between align-start flex-wrap" style="gap: 16px;">
          <div>
            <h2 class="text-h6 mb-2">
              {{ store.current.name }}
            </h2>
            <div style="max-width: 320px;">
              <v-progress-linear
                :model-value="usagePercent"
                :color="usagePercent >= 90 ? 'error' : 'secondary'"
                height="8"
                rounded
                class="mb-1"
              />
              <span class="text-caption text-medium-emphasis">
                {{ formatBytes(store.current.used_bytes) }} / {{ formatBytes(store.current.quota_bytes) }} used
              </span>
            </div>
          </div>
          <v-btn
            color="secondary"
            prepend-icon="mdi-upload"
            @click="openUploadDialog"
          >
            Upload data
          </v-btn>
        </div>
      </v-card>

      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Data
        </h3>
        <v-table density="comfortable">
          <thead>
            <tr>
              <th>Key</th>
              <th>Version</th>
              <th>Format</th>
              <th>Kind</th>
              <th>Size</th>
              <th />
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in store.current.items"
              :key="`${item.name}:${item.version}`"
              :class="{ 'opacity-60': item.status === 'pending' }"
            >
              <td>
                {{ item.name }}
                <v-progress-circular
                  v-if="item.status === 'pending'"
                  indeterminate
                  size="14"
                  width="2"
                  color="secondary"
                  class="ml-2"
                />
              </td>
              <td>{{ item.version }}</td>
              <td>{{ item.format }}</td>
              <td>{{ item.kind }}</td>
              <td>{{ formatBytes(item.total_size) }}</td>
              <td class="text-right">
                <v-btn
                  icon="mdi-download-outline"
                  variant="text"
                  size="small"
                  title="Download"
                  :disabled="item.status !== 'ready' || endpointsStore.items.length === 0"
                  @click="onDownload(item)"
                />
              </td>
              <td class="text-right">
                <v-btn
                  icon="mdi-delete-outline"
                  variant="text"
                  size="small"
                  title="Delete"
                  :disabled="item.status !== 'ready'"
                  @click="confirmDelete(item)"
                />
              </td>
            </tr>
          </tbody>
        </v-table>
        <p v-if="store.current.items.length === 0" class="text-body-2 text-medium-emphasis">
          No data registered in this bucket yet
        </p>
      </v-card>

      <!-- Delete data confirm dialog -->
      <v-dialog v-model="showDeleteDialog" max-width="480">
        <v-card class="pa-6">
          <h3 class="text-h6 mb-4">
            Delete "{{ pendingDelete?.name }}" v{{ pendingDelete?.version }}?
          </h3>
          <p class="text-body-2 mb-4">
            This cannot be undone.
          </p>
          <v-select
            v-model="deleteEndpointId"
            :items="endpointsStore.items"
            item-title="endpoint_id"
            item-value="endpoint_id"
            label="Via endpoint"
            hint="Any reachable cluster member can process this"
            persistent-hint
            variant="outlined"
            density="comfortable"
            class="mb-4"
          />
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
    </template>

    <!-- Upload data dialog -->
    <v-dialog v-model="showUploadDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Upload data
        </h3>
        <v-form @submit.prevent="onUpload">
          <v-select
            v-model="form.endpoint_id"
            :items="endpointsStore.items"
            item-title="endpoint_id"
            item-value="endpoint_id"
            label="Endpoint"
            variant="outlined"
            density="comfortable"
            class="mb-3"
            :rules="[v => !!v || 'Select an endpoint to upload through']"
          />
          <v-text-field
            v-model="form.key"
            label="Key"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <v-text-field
            v-model.number="form.version"
            label="Version"
            type="number"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <div class="d-flex mb-3" style="gap: 12px;">
            <v-select
              v-model="form.format"
              :items="['raw', 'pickle', 'csv', 'npy']"
              label="Format"
              variant="outlined"
              density="comfortable"
            />
            <v-select
              v-model="form.kind"
              :items="['fs']"
              label="Kind"
              variant="outlined"
              density="comfortable"
            />
          </div>
          <v-file-input
            v-model="uploadFile"
            label="File"
            variant="outlined"
            density="comfortable"
            prepend-icon="mdi-file-outline"
            class="mb-4"
          />
          <v-alert v-if="uploadError" type="error" variant="tonal" density="compact" class="mb-4">
            {{ uploadError }}
          </v-alert>
          <div class="d-flex justify-end" style="gap: 8px;">
            <v-btn variant="text" @click="showUploadDialog = false">
              Cancel
            </v-btn>
            <v-btn color="secondary" type="submit" :loading="store.loading">
              Upload
            </v-btn>
          </div>
        </v-form>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import type { DataItem } from '~/types/bucket'

const route = useRoute()
const store = useBucketsStore()
const endpointsStore = useEndpointsStore()

const bucketName = route.params.name as string

onMounted(() => {
  store.fetchOne(bucketName)
  endpointsStore.fetchAll()
  store.connectSocket()
})

onBeforeUnmount(() => {
  store.disconnectSocket()
})

// DataItem.name is always "{bucket}/{key}" -- the upload/download/delete
// routes take the bare key as its own path segment, so this strips the
// "{bucketName}/" prefix back off rather than re-deriving it from scratch.
function keyOf(item: DataItem): string {
  return item.name.slice(bucketName.length + 1)
}

const usagePercent = computed(() => {
  if (!store.current || store.current.quota_bytes <= 0) return 0
  return Math.min(100, (store.current.used_bytes / store.current.quota_bytes) * 100)
})

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

const showUploadDialog = ref(false)
const uploadError = ref<string | null>(null)
const uploadFile = ref<File | null>(null)
const form = reactive({
  endpoint_id: null as string | null,
  key: '',
  version: 1,
  format: 'raw',
  kind: 'fs',
})

function openUploadDialog() {
  uploadError.value = null
  uploadFile.value = null
  form.endpoint_id = null
  form.key = ''
  form.version = 1
  form.format = 'raw'
  form.kind = 'fs'
  showUploadDialog.value = true
}

async function onUpload() {
  uploadError.value = null
  if (!form.endpoint_id) {
    uploadError.value = 'Select an endpoint to upload through'
    return
  }
  if (!uploadFile.value) {
    uploadError.value = 'A file is required'
    return
  }
  try {
    await store.uploadData(
      form.endpoint_id, bucketName, form.key, form.version, uploadFile.value, form.format, form.kind,
    )
    showUploadDialog.value = false
  } catch (err: any) {
    uploadError.value = err.message
  }
}

async function onDownload(item: DataItem) {
  const endpointId = endpointsStore.items[0]?.endpoint_id
  if (!endpointId) return
  try {
    await store.downloadData(endpointId, bucketName, keyOf(item), item.version)
  } catch {
    // store.error already holds the message; the alert at the top of the
    // page surfaces it -- nothing further to do here.
  }
}

const showDeleteDialog = ref(false)
const deleteError = ref<string | null>(null)
const deleteEndpointId = ref<string | null>(null)
const pendingDelete = ref<DataItem | null>(null)

function confirmDelete(item: DataItem) {
  pendingDelete.value = item
  deleteEndpointId.value = endpointsStore.items[0]?.endpoint_id ?? null
  deleteError.value = null
  showDeleteDialog.value = true
}

async function onDelete() {
  if (!pendingDelete.value || !deleteEndpointId.value) {
    deleteError.value = 'Select an endpoint to send the delete through'
    return
  }
  try {
    await store.deleteData(deleteEndpointId.value, bucketName, keyOf(pendingDelete.value), pendingDelete.value.version)
    showDeleteDialog.value = false
    pendingDelete.value = null
  } catch (err: any) {
    deleteError.value = err.message
  }
}
</script>
