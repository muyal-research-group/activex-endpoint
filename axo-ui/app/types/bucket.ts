export interface DataBucket {
  name: string
  quota_bytes: number
  used_bytes: number
  created_at?: string
}

export interface DataItem {
  name: string
  version: number
  format: string
  kind: string
  total_size: number
  total_chunks: number
  status: 'pending' | 'ready'
}

export interface BucketStatusMessage {
  bucket: string
  name: string
  version: number
  status: 'pending' | 'ready' | 'deleted'
  format?: string
  kind?: string
  total_size?: number
  total_chunks?: number
}

export interface BucketWithItems extends DataBucket {
  items: DataItem[]
}

export interface BucketCreateRequest {
  name: string
  quota_bytes: number
}
