import type { BucketCreateRequest, BucketStatusMessage, BucketWithItems, DataBucket } from '~/types/bucket'

export const useBucketsStore = defineStore('buckets', () => {
  const { apiFetch, wsUrl } = useApi()

  const items = ref<DataBucket[]>([])
  const current = ref<BucketWithItems | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let socket: WebSocket | null = null

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      items.value = await apiFetch<DataBucket[]>('/buckets')
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function fetchOne(name: string) {
    loading.value = true
    error.value = null
    try {
      current.value = await apiFetch<BucketWithItems>(`/buckets/${name}`)
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  async function create(endpointId: string, payload: BucketCreateRequest) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/endpoints/${endpointId}/buckets`, { method: 'POST', body: payload })
      await fetchAll()
    } catch (err: any) {
      error.value = err.message
      loading.value = false
      throw err
    }
  }

  // `file` is sent as multipart/form-data, mirroring stores/functions.ts::register's
  // code upload -- the browser reads the file into memory and proxies it
  // through axo_vem, which relays DATA_REGISTER + chunked
  // DATA_CHUNK_PUT calls to the cluster on the caller's behalf. Deliberately
  // does NOT refetch the bucket afterward -- that used to race the async
  // node-event -> Kurrent -> projector -> Mongo pipeline the read model
  // depends on (the bug this whole pending/ready + WS design fixes). The
  // new row appears via the "buckets" WS push instead, see connectSocket().
  async function uploadData(
    endpointId: string,
    bucket: string,
    key: string,
    version: number,
    file: File,
    format = 'raw',
    kind = 'fs',
  ) {
    loading.value = true
    error.value = null
    try {
      const formData = new FormData()
      formData.append('key', key)
      formData.append('version', String(version))
      formData.append('format', format)
      formData.append('kind', kind)
      formData.append('file', file)

      await apiFetch(`/endpoints/${endpointId}/buckets/${bucket}/data`, { method: 'POST', body: formData })
    } catch (err: any) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deleteData(endpointId: string, bucket: string, key: string, version: number) {
    loading.value = true
    error.value = null
    try {
      await apiFetch(`/endpoints/${endpointId}/buckets/${bucket}/data/${key}/${version}`, { method: 'DELETE' })
      // No local splice here either -- the row disappears via the same WS
      // push's status: "deleted" message, once the deletion has actually
      // replicated, not merely been accepted by one node.
    } catch (err: any) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  // Downloads still go through apiFetch's auth headers (unlike the WS
  // connection) since GET /endpoints/.../download is a normal authenticated
  // REST route, just one whose response body is a raw byte stream instead
  // of JSON -- $fetch's default responseType would try to parse it as JSON,
  // so this asks for a Blob instead and drives the browser's own
  // save-file-as flow via a throwaway <a>.
  async function downloadData(endpointId: string, bucket: string, key: string, version: number) {
    error.value = null
    try {
      const blob = await apiFetch<Blob>(
        `/endpoints/${endpointId}/buckets/${bucket}/data/${key}/${version}/download`,
        { responseType: 'blob' },
      )
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = key.split('/').pop() || key
      link.click()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      error.value = err.message
      throw err
    }
  }

  function _upsertItem(message: BucketStatusMessage) {
    if (!current.value || message.bucket !== current.value.name) return

    if (message.status === 'deleted') {
      current.value.items = current.value.items.filter(
        item => !(item.name === message.name && item.version === message.version),
      )
      return
    }

    const existing = current.value.items.find(
      item => item.name === message.name && item.version === message.version,
    )
    if (existing) {
      existing.status = message.status
      return
    }
    // Only a "pending" message (the first one for any given item) carries
    // the full shape -- "ready" can only ever be flipping a row that
    // already exists, since pending always lands first. See
    // bucket_handler.py's broadcast payload for why.
    if (message.status === 'pending' && message.format !== undefined) {
      current.value.items.push({
        name: message.name, version: message.version, format: message.format,
        kind: message.kind!, total_size: message.total_size!, total_chunks: message.total_chunks!,
        status: 'pending',
      })
    }
  }

  function connectSocket() {
    if (socket) return
    socket = new WebSocket(wsUrl('/ws/buckets'))
    socket.addEventListener('message', (event) => {
      _upsertItem(JSON.parse(event.data) as BucketStatusMessage)
    })
  }

  function disconnectSocket() {
    socket?.close()
    socket = null
  }

  return {
    items, current, loading, error,
    fetchAll, fetchOne, create, uploadData, deleteData, downloadData,
    connectSocket, disconnectSocket,
  }
})
