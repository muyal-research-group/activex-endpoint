// Endpoint docs are genuinely polymorphic: they're built from whichever of
// EndpointStarted/EndpointMetricsReported/EndpointStopped events have
// landed for that node so far (plain $set upserts), so most fields are
// optional and the shape is intentionally open-ended.
export interface EndpointDoc {
  endpoint_id: string
  // Derived by the projector from which of EndpointStarted/EndpointStopped/
  // EndpointUnreachable/EndpointRecovered landed most recently -- absent
  // until the first of any of these arrives. `unreachable` is set by
  // EndpointLivenessWorker when a running node goes stale and a direct
  // PING to it fails; it auto-recovers back to `running` on the next
  // successful ping, with no user action.
  status?: 'running' | 'stopped' | 'unreachable'
  router_bind?: string
  pub_bind?: string
  metrics?: Record<string, unknown>
  uptime_ms?: number
  created_at?: string
  // Computed, viewer-scoped: true immediately for `stopped`; for
  // `unreachable`, true once unreachable_since is older than the caller's
  // own endpoint_purge_eligible_after_minutes preference. Purely a
  // UI-surfacing signal -- the backend purge route allows stopped/unreachable
  // regardless of this flag.
  purge_eligible?: boolean
  // Set only while status is `unreachable` -- the timestamp the node was
  // first found unreachable (mirrors the doc's own created_at at that
  // moment). Null otherwise.
  unreachable_since?: string | null
  // Live Docker container resource usage, pushed over /ws/endpoints --
  // distinct from `metrics` above (the node's own self-reported heartbeat
  // metric, fetched once on page load, never pushed). Absent until the
  // first EndpointStatsPoller tick arrives after page load.
  container_stats?: EndpointContainerStats
  [key: string]: unknown
}

export interface EndpointContainerStats {
  endpoint_id: string
  available: boolean
  cpu_percent?: number
  memory_usage?: number
  memory_limit?: number
  network_rx?: number
  network_tx?: number
}

// Mirrors LaunchEndpointNodeUseCase.execute()'s params on the API side
// (axo_vem/application/nodes/launch_endpoint_node.py) --
// env_overrides is always seeded from GET /endpoints/deployment-defaults
// then sent back in full, since the backend merges {...defaults, ...overrides}
// and silently ignores mesh-identity keys regardless of what's sent.
// AXO_ENDPOINT_SUB_CONNECT is derived server-side from the target VE's
// existing running endpoints -- there is no client-supplied peer list.
export interface EndpointDeployRequest {
  virtual_environment_id?: string | null
  env_overrides: Record<string, string>
  router_port: number
  pub_port: number
  results_port: number
}

export interface DeployedEndpoint {
  endpoint_id: string
  container_name: string
  router_bind: string
}
