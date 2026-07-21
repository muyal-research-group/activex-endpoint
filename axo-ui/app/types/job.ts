export interface JobSubmitRequest {
  function_name: string
  function_version: number
  params: Record<string, unknown>
}

// Mirrors JobSubmitHandler/JobResultHandler's CommandResult.metadata shape,
// relayed verbatim by POST/GET /endpoints/{endpointId}/jobs[/​{jobId}].
export interface JobResult {
  job_id: string
  endpoint_id?: string
  status?: 'QUEUED' | 'PENDING' | 'COMPLETED' | 'FAILED'
  result_ok?: boolean
  values?: unknown
  error?: string | null
}

// Mirrors domain/execution/job.py's Job.to_dict() -- the jobs read-model
// list-view shape, sourced from GET /functions/{functionId}/jobs.
export interface JobHistoryEntry {
  job_id: string
  function_id: string
  status: 'QUEUED' | 'STARTED' | 'COMPLETED' | 'FAILED'
  function_version?: number | null
  duration_ms?: number | null
  params?: Record<string, unknown> | null
  endpoint_id?: string | null
  created_at?: string | null
}
