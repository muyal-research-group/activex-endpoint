import type { JobHistoryEntry, JobResult } from '~/types/job'

const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED'])

export const useJobsStore = defineStore('jobs', () => {
  const { apiFetch } = useApi()

  const current = ref<JobResult | null>(null)
  const history = ref<JobHistoryEntry[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // functionId is the node's actual catalog lookup key (the route param on
  // /functions/{id}/...), not a display name -- see JobSubmitHandler.handle()
  // on the node side. functionName is optional and only ever used for the
  // node's own logging.
  async function submit(
    endpointId: string,
    functionId: string,
    functionVersion: number,
    params: Record<string, unknown>,
    functionName?: string,
  ) {
    error.value = null
    try {
      return await apiFetch<JobResult>(`/endpoints/${endpointId}/jobs`, {
        method: 'POST',
        body: { function_id: functionId, function_name: functionName, function_version: functionVersion, params },
      })
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  // Caller never picks an endpoint -- the API resolves one server-side from
  // the function's own virtual_environment_id (preferring that VE's
  // currently-elected mesh leader). Returns the same JobResult shape submit()
  // does, plus which endpoint_id it actually landed on, needed for poll().
  async function submitForFunction(
    functionId: string,
    functionVersion: number,
    params: Record<string, unknown>,
  ) {
    error.value = null
    try {
      return await apiFetch<JobResult>(`/functions/${functionId}/${functionVersion}/jobs`, {
        method: 'POST',
        body: { params },
      })
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  async function poll(endpointId: string, jobId: string) {
    error.value = null
    try {
      current.value = await apiFetch<JobResult>(`/endpoints/${endpointId}/jobs/${jobId}`)
      return current.value
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  // Submit-then-poll loop until a terminal status or timeout -- mirrors
  // AxoEndpointClient.run()'s convenience wrapper on the Python client side.
  async function run(
    endpointId: string,
    functionId: string,
    functionVersion: number,
    params: Record<string, unknown>,
    { intervalMs = 800, timeoutMs = 30000 }: { intervalMs?: number, timeoutMs?: number } = {},
  ) {
    loading.value = true
    error.value = null
    try {
      const submitted = await submit(endpointId, functionId, functionVersion, params)
      const jobId = submitted.job_id
      const startedAt = Date.now()

      while (true) {
        const result = await poll(endpointId, jobId)
        if (result.status && TERMINAL_STATUSES.has(result.status)) return result
        if (Date.now() - startedAt > timeoutMs) throw new Error('Timed out waiting for the job to finish')
        await new Promise(resolve => setTimeout(resolve, intervalMs))
      }
    } catch (err: any) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchHistory(functionId: string, version?: number) {
    error.value = null
    try {
      history.value = await apiFetch<JobHistoryEntry[]>(`/functions/${functionId}/jobs`, {
        params: version !== undefined ? { version } : undefined,
      })
    } catch (err: any) {
      error.value = err.message
    }
  }

  return { current, history, loading, error, submit, submitForFunction, poll, run, fetchHistory }
})
