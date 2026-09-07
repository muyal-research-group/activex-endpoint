interface ProfileResponse {
  user_id: string
  profile_photo: string
  preferences: {
    color: string | null
    view_mode: string
    language: string
    activity_window_minutes: number
    endpoint_purge_eligible_after_minutes: number
  }
}

export const useProfileStore = defineStore('profile', () => {
  const { apiFetch } = useApi()

  // Preferences besides activityWindowMinutes are tracked here too, even
  // though nothing in this UI edits them yet -- POST/PUT /profile is a
  // full-replace, not a partial patch, so setActivityWindowMinutes() has to
  // send them back unchanged rather than silently resetting them to
  // pydantic defaults on every save.
  const profilePhoto = ref('')
  const color = ref<string | null>(null)
  const viewMode = ref('list')
  const language = ref('en')
  const activityWindowMinutes = ref(60)
  const endpointPurgeEligibleAfterMinutes = ref(60)
  const exists = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)

  function _applyProfile(profile: ProfileResponse) {
    profilePhoto.value = profile.profile_photo
    color.value = profile.preferences.color
    viewMode.value = profile.preferences.view_mode
    language.value = profile.preferences.language
    activityWindowMinutes.value = profile.preferences.activity_window_minutes
    endpointPurgeEligibleAfterMinutes.value = profile.preferences.endpoint_purge_eligible_after_minutes
  }

  async function fetch() {
    loading.value = true
    error.value = null
    try {
      const profile = await apiFetch<ProfileResponse>('/profile')
      _applyProfile(profile)
      exists.value = true
    } catch {
      // 404 just means no profile exists yet -- defaults stand, not an error.
      exists.value = false
    } finally {
      loading.value = false
    }
  }

  async function setActivityWindowMinutes(minutes: number) {
    loading.value = true
    error.value = null
    const body = {
      profile_photo: profilePhoto.value,
      color: color.value,
      view_mode: viewMode.value,
      language: language.value,
      activity_window_minutes: minutes,
      endpoint_purge_eligible_after_minutes: endpointPurgeEligibleAfterMinutes.value,
    }
    try {
      await apiFetch('/profile', { method: exists.value ? 'PUT' : 'POST', body })
      activityWindowMinutes.value = minutes
      exists.value = true
    } catch (err: any) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  async function setEndpointPurgeEligibleAfterMinutes(minutes: number) {
    loading.value = true
    error.value = null
    const body = {
      profile_photo: profilePhoto.value,
      color: color.value,
      view_mode: viewMode.value,
      language: language.value,
      activity_window_minutes: activityWindowMinutes.value,
      endpoint_purge_eligible_after_minutes: minutes,
    }
    try {
      await apiFetch('/profile', { method: exists.value ? 'PUT' : 'POST', body })
      endpointPurgeEligibleAfterMinutes.value = minutes
      exists.value = true
    } catch (err: any) {
      error.value = err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    profilePhoto, color, viewMode, language, activityWindowMinutes, endpointPurgeEligibleAfterMinutes,
    exists, loading, error,
    fetch, setActivityWindowMinutes, setEndpointPurgeEligibleAfterMinutes,
  }
})
