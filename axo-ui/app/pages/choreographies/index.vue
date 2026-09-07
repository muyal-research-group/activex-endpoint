<template>
  <v-container fluid class="pa-6">
    <v-btn
      color="secondary"
      size="large"
      rounded="lg"
      prepend-icon="mdi-plus"
      class="text-uppercase font-weight-bold mb-6"
      to="/choreographies/new"
    >
      New Choreography
    </v-btn>

    <v-card class="pa-6">
      <h2 class="text-h6 mb-4">
        Choreographies
      </h2>

      <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
        {{ store.error }}
      </v-alert>

      <v-data-table
        :headers="headers"
        :items="store.items"
        :loading="store.loading"
        item-value="choreography_id"
        no-data-text="No choreographies yet"
      >
        <template #item.name="{ item }">
          <NuxtLink :to="`/choreographies/${item.choreography_id}`" class="text-decoration-none">
            {{ item.name }}
          </NuxtLink>
        </template>
        <template #item.updated_at="{ item }">
          {{ new Date(item.updated_at).toLocaleString() }}
        </template>
        <template #item.actions="{ item }">
          <v-btn icon="mdi-delete-outline" variant="text" size="small" @click="confirmDelete(item)" />
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="showDeleteDialog" max-width="480">
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
          <v-btn color="error" :loading="store.loading" @click="onDelete">
            Delete
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import type { Choreography } from '~/types/choreography'

const store = useChoreographiesStore()

onMounted(() => {
  store.fetchAll()
})

const headers = [
  { title: 'Name', key: 'name' },
  { title: 'Updated', key: 'updated_at' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const showDeleteDialog = ref(false)
const deleteError = ref<string | null>(null)
const pendingDelete = ref<Choreography | null>(null)

function confirmDelete(item: Choreography) {
  pendingDelete.value = item
  deleteError.value = null
  showDeleteDialog.value = true
}

async function onDelete() {
  if (!pendingDelete.value) return
  try {
    await store.remove(pendingDelete.value.choreography_id)
    showDeleteDialog.value = false
    pendingDelete.value = null
  } catch (err: any) {
    deleteError.value = err.message
  }
}
</script>
