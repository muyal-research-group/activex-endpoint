export function useApi() {
  const config = useRuntimeConfig()
  const session = useAuthSession()

  async function apiFetch<T>(path: string, opts: Record<string, any> = {}): Promise<T> {
    const headers: Record<string, string> = { ...(opts.headers || {}) }
    if (session.value) {
      headers['Authorization'] = `Bearer ${session.value.access_token}`
      headers['Temporal-Secret-Key'] = session.value.temporal_secret
    }

    try {
      return await $fetch<T>(path, {
        baseURL: config.public.apiBase as string,
        ...opts,
        headers,
      })
    } catch (err: any) {
      // A 401 means the session token expired (default /login expiration is
      // 15min) or was never valid -- drop it and bounce to /login instead of
      // leaving the caller stuck silently failing every subsequent request.
      if (err?.response?.status === 401 || err?.status === 401) {
        session.value = null
        await navigateTo('/login')
      }
      const detail = err?.data?.detail
      throw new Error(typeof detail === 'string' ? detail : (err?.message || 'Request failed'))
    }
  }

  // WS routes are unauthenticated (a browser WebSocket handshake can't
  // attach the Authorization/Temporal-Secret-Key headers apiFetch does --
  // see infrastructure/transport/api/controllers/websockets.py's own note
  // on the API side), so this is just a URL builder, no session headers.
  function wsUrl(path: string): string {
    const base = config.public.apiBase as string
    return `${base.replace(/^http/, 'ws')}${path}`
  }

  return { apiFetch, wsUrl }
}
