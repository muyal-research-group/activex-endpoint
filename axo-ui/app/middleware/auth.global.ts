// Global (not per-page named) so every route is protected by default --
// a new page added later without remembering to tag
// definePageMeta({ middleware: 'auth' }) would otherwise stay silently
// public. Only /login and /signup are allowlisted as genuinely public.
const PUBLIC_PATHS = new Set(['/login', '/signup'])

export default defineNuxtRouteMiddleware((to) => {
  const session = useAuthSession()
  const isAuthenticated = !!session.value

  if (!isAuthenticated && !PUBLIC_PATHS.has(to.path)) {
    return navigateTo('/login')
  }
  if (isAuthenticated && PUBLIC_PATHS.has(to.path)) {
    return navigateTo('/dashboard')
  }
})
