import type { ActivityEvent } from '~/types/activity'
import type { FunctionRecord, FunctionRegisterRequest } from '~/types/functionRecord'

export const useFunctionsStore = defineStore('functions', () => {
  const { apiFetch, wsUrl } = useApi()

  const items = ref<FunctionRecord[]>([])
  // All registered versions of one function_id -- GET /functions/{id}
  // returns every version, not a single record.
  const versions = ref<FunctionRecord[]>([])
  const history = ref<ActivityEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  let fleetSocket: WebSocket | null = null

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      items.value = await apiFetch<FunctionRecord[]>('/functions')
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  // `code` is a raw .py File -- sent as multipart/form-data, not JSON, so
  // useApi's $fetch call passes a FormData body straight through untouched
  // (it detects FormData and skips JSON-encoding/sets its own boundary
  // Content-Type automatically). The API only statically validates the
  // upload (AST parse, never executed) and forwards it untouched; actual
  // execution happens only on the target endpoint node's own cold start.
  async function register(payload: FunctionRegisterRequest, code: File) {
    loading.value = true
    error.value = null
    try {
      const formData = new FormData()
      formData.append('name', payload.name)
      formData.append('virtual_environment_id', payload.virtual_environment_id)
      if (payload.runtime_spec) formData.append('runtime_spec', JSON.stringify(payload.runtime_spec))
      if (payload.params_schema && payload.params_schema.length > 0) {
        formData.append('params_schema', JSON.stringify(payload.params_schema))
      }
      formData.append('code', code)

      await apiFetch('/functions', { method: 'POST', body: formData })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  // No endpointId -- the API resolves the function's own recorded endpoint
  // (the node that actually owns it) instead of trusting a caller pick.
  async function remove(functionId: string, version: number) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/functions/${functionId}/${version}`, { method: 'DELETE' })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  // Hard-deletes this version's read-model doc + activity history --
  // only succeeds once the version is already soft-deleted via remove().
  async function purgeVersion(functionId: string, version: number) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/functions/${functionId}/${version}/purge`, { method: 'DELETE' })
      await fetchOne(functionId)
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  async function fetchOne(functionId: string) {
    loading.value = true
    error.value = null
    try {
      versions.value = await apiFetch<FunctionRecord[]>(`/functions/${functionId}`)
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function fetchHistory(functionId: string) {
    try {
      history.value = await apiFetch<ActivityEvent[]>(`/functions/${functionId}/history`)
    } catch (err: any) {
      error.value = err.message
    }
  }

  // Fleet-wide function lifecycle feed -- every FunctionRegistered/
  // Deployed/Activated/.../Deleted message, keyed by (function_id, version)
  // like the collection itself. Mirrors useEndpointsStore's
  // connectFleetSocket: an unknown (function_id, version) pair is a brand
  // new row (e.g. a function just registered elsewhere in this session),
  // otherwise it's patched into the existing row in place.
  function connectFleetSocket() {
    if (fleetSocket) return
    fleetSocket = new WebSocket(wsUrl('/ws/functions'))
    fleetSocket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data) as FunctionRecord
      const item = items.value.find(f => f.function_id === message.function_id && f.version === message.version)
      if (item) Object.assign(item, message)
      else items.value.push(message)
    })
  }

  function disconnectFleetSocket() {
    fleetSocket?.close()
    fleetSocket = null
  }

  return {
    items, versions, history, loading, error,
    fetchAll, register, remove, purgeVersion, fetchOne, fetchHistory,
    connectFleetSocket, disconnectFleetSocket,
  }
})
