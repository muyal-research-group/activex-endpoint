<template>
  <v-container fluid class="pa-6">
    <div class="d-flex mb-6" style="gap: 16px;">
      <v-card class="pa-4 stat-card" width="200">
        <div class="d-flex align-center justify-space-between">
          <span class="text-subtitle-1">Active</span>
          <span class="status-dot status-dot--active" />
        </div>
        <div class="text-h4 font-weight-bold mt-1">
          {{ store.items.length }}
        </div>
      </v-card>

      <v-card class="pa-4 stat-card" width="200">
        <div class="d-flex align-center justify-space-between">
          <span class="text-subtitle-1">Deleted</span>
          <span class="status-dot status-dot--unknown" />
        </div>
        <div class="text-h4 font-weight-bold mt-1 text-medium-emphasis">
          —
        </div>
        <div class="text-caption text-medium-emphasis">
          Not tracked by the API yet
        </div>
      </v-card>
    </div>

    <v-btn
      color="secondary"
      size="large"
      rounded="lg"
      prepend-icon="mdi-plus"
      class="text-uppercase font-weight-bold mb-6"
      @click="showCreateDialog = true"
    >
      Create
    </v-btn>

    <v-card class="pa-6">
      <h2 class="text-h6 mb-4">
        Virtual Environments
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
        item-value="virtual_environment_id"
        no-data-text="No virtual environments yet"
      >
        <template #item.name="{ item }">
          <NuxtLink :to="`/virtual-environments/${item.virtual_environment_id}`" class="d-flex align-center text-decoration-none">
            <v-avatar size="32" color="grey-lighten-2" class="mr-3">
              <v-icon icon="mdi-cube-outline" size="18" />
            </v-avatar>
            <div>
              <div>{{ item.name }}</div>
              <div class="text-caption text-medium-emphasis ve-id-text" :title="item.virtual_environment_id">
                {{ item.virtual_environment_id }}
              </div>
            </div>
          </NuxtLink>
        </template>
        <template #item.cpu="{ item }">
          {{ item.resource_quota.cpu }}
        </template>
        <template #item.ram="{ item }">
          {{ item.resource_quota.ram }}
        </template>
        <template #item.disk="{ item }">
          {{ item.resource_quota.disk }}
        </template>
        <template #item.actions="{ item }">
          <v-btn
            icon="mdi-delete-outline"
            variant="text"
            size="small"
            @click="confirmDelete(item)"
          />
        </template>
      </v-data-table>
    </v-card>

    <!-- Create dialog -->
    <v-dialog v-model="showCreateDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Create Virtual Environment
        </h3>
        <v-form @submit.prevent="onCreate">
          <v-text-field
            v-model="form.name"
            label="Name"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <v-text-field
            v-model.number="form.cpu"
            label="# Cores"
            type="number"
            step="0.5"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <v-text-field
            v-model.number="form.ram"
            label="RAM (GB)"
            type="number"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <v-text-field
            v-model.number="form.disk"
            label="Disk (GB)"
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

    <!-- Delete confirm dialog -->
    <v-dialog v-model="showDeleteDialog" max-width="420">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Delete "{{ pendingDelete?.name }}"?
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
  </v-container>
</template>

<script setup lang="ts">
import type { VirtualEnvironment } from '~/types/virtualEnvironment'

const store = useVirtualEnvironmentsStore()

const { preference } = useThemeSetting()
const isDarkTheme = computed(() => preference.value === 'axoDark')

onMounted(() => {
  store.fetchAll()
})

const search = ref('')
const filteredItems = computed(() => {
  if (!search.value.trim()) return store.items
  const q = search.value.toLowerCase()
  return store.items.filter(v =>
    v.name.toLowerCase().includes(q) || v.virtual_environment_id.toLowerCase().includes(q),
  )
})

const headers = [
  { title: 'Name', key: 'name' },
  { title: '# Cores', key: 'cpu' },
  { title: 'RAM (GB)', key: 'ram' },
  { title: 'Disk (GB)', key: 'disk' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const showCreateDialog = ref(false)
const createError = ref<string | null>(null)
const form = reactive({ name: '', cpu: 1, ram: 1, disk: 10 })

async function onCreate() {
  createError.value = null
  try {
    await store.create({ name: form.name, cpu: form.cpu, ram: form.ram, disk: form.disk })
    showCreateDialog.value = false
    form.name = ''
    form.cpu = 1
    form.ram = 1
    form.disk = 10
  } catch (err: any) {
    createError.value = err.message
  }
}

const showDeleteDialog = ref(false)
const deleteError = ref<string | null>(null)
const pendingDelete = ref<VirtualEnvironment | null>(null)

function confirmDelete(item: VirtualEnvironment) {
  pendingDelete.value = item
  deleteError.value = null
  showDeleteDialog.value = true
}

async function onDelete() {
  if (!pendingDelete.value) return
  try {
    await store.remove(pendingDelete.value.virtual_environment_id)
    showDeleteDialog.value = false
    pendingDelete.value = null
  } catch (err: any) {
    deleteError.value = err.message
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

.status-dot--unknown {
  background-color: #c7c9cf;
}

.ve-id-text {
  font-family: monospace;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
