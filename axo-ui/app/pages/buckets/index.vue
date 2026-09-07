<template>
  <v-container fluid class="pa-6">
    <div class="d-flex mb-6" style="gap: 16px;">
      <v-card class="pa-4 stat-card" width="200">
        <div class="d-flex align-center justify-space-between">
          <span class="text-subtitle-1">Buckets</span>
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
      @click="openCreateDialog"
    >
      Create Bucket
    </v-btn>

    <v-card class="pa-6">
      <h2 class="text-h6 mb-4">
        Buckets
      </h2>

      <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
        {{ store.error }}
      </v-alert>

      <v-data-table
        :headers="headers"
        :items="store.items"
        :loading="store.loading"
        item-value="name"
        no-data-text="No buckets registered yet"
      >
        <template #item.name="{ item }">
          <NuxtLink :to="`/buckets/${item.name}`" class="d-flex align-center text-decoration-none">
            <v-avatar size="32" color="grey-lighten-2" class="mr-3">
              <v-icon icon="mdi-database-outline" size="18" />
            </v-avatar>
            {{ item.name }}
          </NuxtLink>
        </template>
        <template #item.usage="{ item }">
          <div style="max-width: 220px;">
            <v-progress-linear
              :model-value="usagePercent(item)"
              :color="usagePercent(item) >= 90 ? 'error' : 'secondary'"
              height="8"
              rounded
              class="mb-1"
            />
            <span class="text-caption text-medium-emphasis">
              {{ formatBytes(item.used_bytes) }} / {{ formatBytes(item.quota_bytes) }}
            </span>
          </div>
        </template>
      </v-data-table>
    </v-card>

    <!-- Create dialog -->
    <v-dialog v-model="showCreateDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Create Bucket
        </h3>
        <v-form @submit.prevent="onCreate">
          <v-select
            v-model="form.endpoint_id"
            :items="endpointsStore.items"
            item-title="endpoint_id"
            item-value="endpoint_id"
            label="Endpoint"
            variant="outlined"
            density="comfortable"
            class="mb-3"
            :rules="[v => !!v || 'Select an endpoint to register the bucket on']"
          />
          <v-text-field
            v-model="form.name"
            label="Name"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <v-text-field
            v-model.number="quotaMb"
            label="Quota (MB)"
            type="number"
            variant="outlined"
            density="comfortable"
            class="mb-4"
          />
          <v-alert v-if="createError" type="error" variant="tonal" density="compact" class="mb-4">
            {{ createError }}
          </v-alert>
          <div class="d-flex justify-end" style="gap: 8px;">
            <v-btn variant="text" @click="showCreateDialog = false">
              Cancel
            </v-btn>
            <v-btn color="secondary" type="submit" :loading="store.loading">
              Create
            </v-btn>
          </div>
        </v-form>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import type { DataBucket } from '~/types/bucket'

const store = useBucketsStore()
const endpointsStore = useEndpointsStore()

onMounted(() => {
  store.fetchAll()
  endpointsStore.fetchAll()
})

const headers = [
  { title: 'Name', key: 'name' },
  { title: 'Usage', key: 'usage', sortable: false },
]

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function usagePercent(item: DataBucket): number {
  if (item.quota_bytes <= 0) return 0
  return Math.min(100, (item.used_bytes / item.quota_bytes) * 100)
}

const showCreateDialog = ref(false)
const createError = ref<string | null>(null)
const quotaMb = ref(100)
const form = reactive({ endpoint_id: null as string | null, name: '' })

function openCreateDialog() {
  createError.value = null
  form.endpoint_id = null
  form.name = ''
  quotaMb.value = 100
  showCreateDialog.value = true
}

async function onCreate() {
  createError.value = null
  if (!form.endpoint_id) {
    createError.value = 'Select an endpoint to register the bucket on'
    return
  }
  try {
    await store.create(form.endpoint_id, { name: form.name, quota_bytes: Math.round(quotaMb.value * 1024 * 1024) })
    showCreateDialog.value = false
  } catch (err: any) {
    createError.value = err.message
  }
}
</script>

<style scoped>
.stat-card {
  border-radius: 16px;
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
