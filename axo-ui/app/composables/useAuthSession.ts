import type { AuthSession } from '~/types/auth'

// One JSON cookie holding the full session, not two separate token cookies:
// axo_vem's UserProfile never carries username/first_name/
// last_name/email (only the /login response, AuthenticatedDTO, does), so
// those identity fields have to be captured once at login/signup time and
// persisted alongside the (access_token, temporal_secret) pair -- bundling
// them keeps "is logged in" and "who is logged in" one atomic piece of
// state that hydrates identically on SSR and client reloads.
export function useAuthSession() {
  return useCookie<AuthSession | null>('axo_session', {
    default: () => null,
    sameSite: 'lax',
  })
}
