export interface FunctionRecord {
  function_id: string
  version: number
  // Only present once the function was registered after the name was added
  // to the FunctionRegistered event -- older functions may have no name.
  name?: string | null
  runtime_spec?: Record<string, unknown> | null
  params_schema?: ParamSpec[] | null
  owner_user_id?: string
  state?: string
  deleted_at?: string | null
  virtual_environment_id?: string
}

// Mirrors axo_shared.functions.params_schema.ParamSpec's to_dict()/from_dict() shape.
export interface ParamSpec {
  name: string
  type: 'string' | 'number' | 'boolean' | 'json' | 'data_ref'
  required: boolean
  default?: unknown
}

// Mirrors axo_shared.runtime.spec.RuntimeSpec's to_dict()/from_dict() shape.
export interface RuntimeSpec {
  type: 'process' | 'container'
  python_version: string
  requirements: string[]
  image?: string | null
  env_vars: Record<string, string>
  idle_ttl_seconds: number
  max_invocations: number
  memory_limit_bytes?: number | null
  cpu_limit?: number | null
  max_concurrency: number
  max_duration_seconds: number
}

// Everything but `code` for POST /functions -- the code blob itself travels
// as a separate multipart File the user uploads: raw .py source defining a
// top-level function named exactly `name`. axo_vem only statically
// validates that shape (parses the AST, never executes it) and forwards the
// raw source onward untouched -- a browser has no Python runtime to produce
// a cloudpickle blob itself, and actual execution is deferred to the target
// endpoint node's own cold start (forked worker or spawned container),
// never on the control plane.
//
// virtual_environment_id is the caller's chosen workspace -- axo_vem
// auto-picks which endpoint assigned to that VE to route the register onto,
// so no endpoint_id is ever supplied here.
export interface FunctionRegisterRequest {
  name: string
  virtual_environment_id: string
  runtime_spec?: RuntimeSpec
  params_schema?: ParamSpec[]
}
