import type { ActivityEvent } from '~/types/activity'
import type { DeployedEndpoint, EndpointContainerStats, EndpointDeployRequest, EndpointDoc } from '~/types/endpoint'

export const useEndpointsStore = defineStore('endpoints', () => {
  const { apiFetch, wsUrl } = useApi()

  const items = ref<EndpointDoc[]>([])
  const current = ref<EndpointDoc | null>(null)
  const history = ref<ActivityEvent[]>([])
  const deploymentDefaults = ref<Record<string, string>>({})
  const loading = ref(false)
  const error = ref<string | null>(null)
  let fleetSocket: WebSocket | null = null
  let scopedSocket: WebSocket | null = null

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      items.value = await apiFetch<EndpointDoc[]>('/endpoints')
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function fetchDeploymentDefaults() {
    error.value = null
    try {
      deploymentDefaults.value = await apiFetch<Record<string, string>>('/endpoints/deployment-defaults')
    } catch (err: any) {
      error.value = err.message
    }
  }

  async function deploy(payload: EndpointDeployRequest): Promise<DeployedEndpoint> {
    loading.value = true
    error.value = null
    try {
      const launched = await apiFetch<DeployedEndpoint>('/endpoints', { method: 'POST', body: payload })
      await fetchAll()
      return launched
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  async function assignVirtualEnvironment(endpointId: string, virtualEnvironmentId: string | null) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/endpoints/${endpointId}/virtual-environment`, {
        method: 'POST',
        body: { virtual_environment_id: virtualEnvironmentId },
      })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  // Only succeeds for endpoints this API itself deployed (POST /endpoints)
  // -- a docker-compose-managed node has no container/service known to
  // this API under its endpoint_id, so the backend 404s for those.
  async function stop(endpointId: string) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/endpoints/${endpointId}/stop`, { method: 'POST' })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  async function restart(endpointId: string) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/endpoints/${endpointId}/restart`, { method: 'POST' })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  // Hard-deletes this endpoint's read-model doc + activity history --
  // only succeeds once status is already "stopped".
  async function purge(endpointId: string) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/endpoints/${endpointId}/purge`, { method: 'DELETE' })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  async function fetchOne(endpointId: string) {
    loading.value = true
    error.value = null
    try {
      current.value = await apiFetch<EndpointDoc>(`/endpoints/${endpointId}`)
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function fetchHistory(endpointId: string) {
    try {
      history.value = await apiFetch<ActivityEvent[]>(`/endpoints/${endpointId}/history`)
    } catch (err: any) {
      error.value = err.message
    }
  }

  // Fleet-wide live feed over one topic, two message shapes: most ticks are
  // EndpointStatsPoller's per-container stats (no `status` field -- patched
  // into an existing row's container_stats only, never enough on their own
  // to safely construct a new row); a `status`-bearing message is a
  // lifecycle broadcast (compute_handler.py's ENDPOINT_STARTED/STOPPED/
  // UNREACHABLE/RECOVERED branch) carrying a full EndpointDoc-shaped
  // payload, so an unknown endpoint_id there gets inserted as a new row --
  // this is what makes a freshly-deployed endpoint appear on this page
  // without a manual reload.
  function connectFleetSocket() {
    if (fleetSocket) return
    fleetSocket = new WebSocket(wsUrl('/ws/endpoints'))
    fleetSocket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data) as EndpointContainerStats | EndpointDoc
      const item = items.value.find(e => e.endpoint_id === message.endpoint_id)
      if ('status' in message) {
        if (item) Object.assign(item, message)
        else items.value.push(message as EndpointDoc)
      } else if (item) {
        item.container_stats = message as EndpointContainerStats
      }
    })
  }

  function disconnectFleetSocket() {
    fleetSocket?.close()
    fleetSocket = null
  }

  // Same feed, pre-filtered server-side to one endpoint -- used by the
  // endpoint detail page instead of connectFleetSocket() so it isn't
  // paying for (or filtering out) every other endpoint's messages.
  function connectScopedSocket(endpointId: string) {
    if (scopedSocket) return
    scopedSocket = new WebSocket(wsUrl(`/ws/endpoints/${endpointId}`))
    scopedSocket.addEventListener('message', (event) => {
      if (current.value) current.value.container_stats = JSON.parse(event.data) as EndpointContainerStats
    })
  }

  function disconnectScopedSocket() {
    scopedSocket?.close()
    scopedSocket = null
  }

  return {
    items, current, history, deploymentDefaults, loading, error,
    fetchAll, fetchDeploymentDefaults, deploy, assignVirtualEnvironment, stop, restart, purge, fetchOne, fetchHistory,
    connectFleetSocket, disconnectFleetSocket, connectScopedSocket, disconnectScopedSocket,
  }
})
