import type { AuthSession, SignupPayload } from '~/types/auth'

interface AuthenticatedDTO {
  username: string
  first_name: string
  last_name: string
  email: string
  profile_photo: string
  access_token: string
  temporal_secret: string
  user_id?: string
}

export const useAuthStore = defineStore('auth', () => {
  const session = useAuthSession()
  const { apiFetch } = useApi()

  const username = ref('')
  const password = ref('')
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!session.value)
  const currentUser = computed(() => session.value)

  async function signIn(usernameArg?: string, passwordArg?: string) {
    loading.value = true
    error.value = null
    try {
      const dto = await apiFetch<AuthenticatedDTO>('/login', {
        method: 'POST',
        body: {
          username: usernameArg ?? username.value,
          password: passwordArg ?? password.value,
          scope: 'axo',
        },
      })
      console.log(dto)

      const newSession: AuthSession = {
        access_token: dto.access_token,
        temporal_secret: dto.temporal_secret,
        user_id: dto.user_id ?? '',
        username: dto.username,
        first_name: dto.first_name,
        last_name: dto.last_name,
        email: dto.email,
        profile_photo: dto.profile_photo,
      }
      session.value = newSession
      await navigateTo('/dashboard')
    } catch (err: any) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }

  // POST /signup only ever returns the created UserProfileCreated event
  // data (user_id/profile_photo/preferences) -- never a token pair, so
  // landing on /dashboard right after would get the visitor immediately
  // bounced back to /login by the auth middleware. Chaining a real signIn()
  // with the same credentials is what actually produces a session.
  async function signUp(payload: SignupPayload) {
    loading.value = true
    error.value = null
    try {
      await apiFetch('/signup', {
        method: 'POST',
        body: { ...payload, view_mode: 'list', language: 'en' },
      })
      await signIn(payload.username, payload.password)
    } catch (err: any) {
      error.value = err.message
      loading.value = false
    }
  }

  async function signOut() {
    session.value = null
    await navigateTo('/login')
  }

  return {
    username, password, loading, error,
    isAuthenticated, currentUser,
    signIn, signUp, signOut,
  }
})
