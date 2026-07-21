export interface ResourceQuota {
  cpu: number
  ram: number
  disk: number
}

export interface VirtualEnvironment {
  virtual_environment_id: string
  name: string
  owner_user_id: string
  resource_quota: ResourceQuota
  created_at?: string
  deleted_at?: string | null
}

export interface VirtualEnvironmentCreateRequest {
  name: string
  cpu: number
  ram: number
  disk: number
}
