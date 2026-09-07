import type {
  Choreography,
  ChoreographyGraph,
  ChoreographyRun,
  ChoreographyRunMessage,
  ValidationResult,
} from '~/types/choreography'

export const useChoreographiesStore = defineStore('choreographies', () => {
  const { apiFetch, wsUrl } = useApi()

  const items = ref<Choreography[]>([])
  const current = ref<Choreography | null>(null)
  const runs = ref<ChoreographyRun[]>([])
  const currentRun = ref<ChoreographyRun | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let runSocket: WebSocket | null = null

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      items.value = await apiFetch<Choreography[]>('/choreographies')
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function fetchOne(choreographyId: string) {
    loading.value = true
    error.value = null
    try {
      current.value = await apiFetch<Choreography>(`/choreographies/${choreographyId}`)
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function create(name: string, graph: ChoreographyGraph): Promise<Choreography> {
    loading.value = true
    error.value = null
    try {
      const created = await apiFetch<Choreography>('/choreographies', { method: 'POST', body: { name, graph } })
      await fetchAll()
      return created
    } catch (err: any) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  // Rejected with a 409 (surfaced via err.message) while a run is active --
  // the caller must stop the run first.
  async function update(choreographyId: string, name: string, graph: ChoreographyGraph) {
    loading.value = true
    error.value = null
    try {
      current.value = await apiFetch<Choreography>(`/choreographies/${choreographyId}`, {
        method: 'PUT', body: { name, graph },
      })
    } catch (err: any) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  async function remove(choreographyId: string) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/choreographies/${choreographyId}`, { method: 'DELETE' })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  async function validate(choreographyId: string): Promise<ValidationResult> {
    return apiFetch<ValidationResult>(`/choreographies/${choreographyId}/validate`, { method: 'POST' })
  }

  async function run(choreographyId: string): Promise<ChoreographyRun> {
    error.value = null
    try {
      const started = await apiFetch<ChoreographyRun>(`/choreographies/${choreographyId}/run`, { method: 'POST' })
      currentRun.value = started
      return started
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  async function fetchRuns(choreographyId: string) {
    runs.value = await apiFetch<ChoreographyRun[]>(`/choreographies/${choreographyId}/runs`)
  }

  async function fetchRun(choreographyId: string, runId: string) {
    currentRun.value = await apiFetch<ChoreographyRun>(`/choreographies/${choreographyId}/runs/${runId}`)
  }

  async function cancelRun(choreographyId: string, runId: string) {
    currentRun.value = await apiFetch<ChoreographyRun>(
      `/choreographies/${choreographyId}/runs/${runId}/cancel`, { method: 'POST' },
    )
  }

  // Applies one live node_status/run_status push directly onto currentRun,
  // same "upsert in place" shape stores/buckets.ts's _upsertItem uses.
  function _applyMessage(message: ChoreographyRunMessage) {
    if (!currentRun.value) return
    if (message.type === 'run_status') {
      currentRun.value.status = message.status
      return
    }
    currentRun.value.node_states[message.node_id] = {
      node_id: message.node_id, status: message.status, job_id: message.job_id,
      endpoint_id: message.endpoint_id, attempt: message.attempt, error: message.error,
      warnings: message.warnings, duration_ms: message.duration_ms,
    }
  }

  function connectRunSocket(runId: string) {
    if (runSocket) return
    runSocket = new WebSocket(wsUrl(`/ws/choreographies/${runId}`))
    runSocket.addEventListener('message', (event) => {
      _applyMessage(JSON.parse(event.data) as ChoreographyRunMessage)
    })
  }

  function disconnectRunSocket() {
    runSocket?.close()
    runSocket = null
  }

  return {
    items, current, runs, currentRun, loading, error,
    fetchAll, fetchOne, create, update, remove, validate, run, fetchRuns, fetchRun, cancelRun,
    connectRunSocket, disconnectRunSocket,
  }
})
