import type { ActivityEvent } from '~/types/activity'
import type { VirtualEnvironment, VirtualEnvironmentCreateRequest } from '~/types/virtualEnvironment'

export const useVirtualEnvironmentsStore = defineStore('virtualEnvironments', () => {
  const { apiFetch } = useApi()

  const items = ref<VirtualEnvironment[]>([])
  const current = ref<VirtualEnvironment | null>(null)
  const history = ref<ActivityEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      items.value = await apiFetch<VirtualEnvironment[]>('/virtual-environments')
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function create(payload: VirtualEnvironmentCreateRequest) {
    loading.value = true
    error.value = null
    try {
      await apiFetch('/virtual-environments', { method: 'POST', body: payload })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  async function update(id: string, payload: VirtualEnvironmentCreateRequest) {
    error.value = null
    try {
      await apiFetch(`/virtual-environments/${id}`, { method: 'PUT', body: payload })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  // Local splice instead of a refetch -- DELETE returns 204 with no body to
  // reconcile against, and this is cheaper than another round trip.
  async function remove(id: string) {
    error.value = null
    try {
      await apiFetch(`/virtual-environments/${id}`, { method: 'DELETE' })
      items.value = items.value.filter(v => v.virtual_environment_id !== id)
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  // Hard-deletes this VE's read-model doc + activity history -- only
  // succeeds once it's already soft-deleted via remove().
  async function purge(id: string) {
    error.value = null
    try {
      await apiFetch(`/virtual-environments/${id}/purge`, { method: 'DELETE' })
      items.value = items.value.filter(v => v.virtual_environment_id !== id)
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  async function fetchOne(id: string) {
    loading.value = true
    error.value = null
    try {
      current.value = await apiFetch<VirtualEnvironment>(`/virtual-environments/${id}`)
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function fetchHistory(id: string) {
    try {
      history.value = await apiFetch<ActivityEvent[]>(`/virtual-environments/${id}/history`)
    } catch (err: any) {
      error.value = err.message
    }
  }

  return { items, current, history, loading, error, fetchAll, create, update, remove, purge, fetchOne, fetchHistory }
})
