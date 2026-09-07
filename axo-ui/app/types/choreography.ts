// Mirrors axo_shared.events.models.ChoreographyNode's to_dict()/model_dump() shape.
export interface ChoreographyNode {
  node_id: string
  kind: 'function' | 'bucket'
  // vue-flow layout only, not semantic.
  position: { x: number, y: number }
  // kind === 'function'
  function_id?: string | null
  function_version?: number | null
  max_retries?: number
  retry_policy?: 'constant' | 'exponential_backoff' | 'jitter'
  // kind === 'bucket'
  bucket_name?: string | null
  selected_items?: { name: string, version: number }[] | null
}

// Mirrors axo_shared.events.models.ChoreographyEdge.
export interface ChoreographyEdge {
  edge_id: string
  source_node_id: string
  target_node_id: string
  kind: 'fn_to_fn' | 'fn_to_bucket' | 'bucket_to_fn'
  // kind === 'fn_to_fn': which of the target's declared params receives the source's whole result.
  target_param?: string | null
  // kind === 'bucket_to_fn': how many items to process concurrently, capped at the target's max_concurrency.
  parallelism?: number
}

export interface ChoreographyGraph {
  nodes: ChoreographyNode[]
  edges: ChoreographyEdge[]
}

// Mirrors axo_vem.domain.choreography.choreography.Choreography.to_dict().
export interface Choreography {
  choreography_id: string
  name: string
  owner_user_id: string
  graph: ChoreographyGraph
  created_at: string
  updated_at: string
  has_active_run?: boolean
}

export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

// Mirrors axo_vem.domain.choreography.run.NodeRunState.to_dict().
export interface NodeRunState {
  node_id: string
  status: NodeStatus
  job_id?: string | null
  endpoint_id?: string | null
  attempt: number
  error?: string | null
  warnings: string[]
  duration_ms?: number | null
}

// Mirrors axo_vem.domain.choreography.run.ChoreographyRun.to_dict().
export interface ChoreographyRun {
  run_id: string
  choreography_id: string
  status: RunStatus
  node_states: Record<string, NodeRunState>
  started_at?: string | null
  finished_at?: string | null
}

export interface ConcurrencyViolation {
  node_id: string
  function_id: string
  required_concurrency: number
  max_concurrency: number
}

export interface ValidationResult {
  ok: boolean
  violations: ConcurrencyViolation[]
}

// Messages pushed on /ws/choreographies/{run_id} by RunChoreographyUseCase's
// own orchestrator thread -- not event-sourced, see run_choreography.py.
export interface NodeStatusMessage extends NodeRunState {
  type: 'node_status'
}

export interface RunStatusMessage {
  type: 'run_status'
  run_id: string
  status: RunStatus
}

export type ChoreographyRunMessage = NodeStatusMessage | RunStatusMessage
