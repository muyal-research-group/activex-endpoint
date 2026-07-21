export interface ActivityEvent {
  event_id: string
  event_type: string
  created_at: string
  user_id: string | null
  virtual_environment_id: string | null
  endpoint_id: string | null
  runtime_type: string | null
  meta: Record<string, unknown>
}
