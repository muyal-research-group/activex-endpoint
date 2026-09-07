export interface SnackbarState {
  show: boolean
  text: string
  color: 'success' | 'error'
}

// useState-backed global singleton (same rationale as useThemeSetting: one
// piece of shared UI state, no need for a full Pinia store) so any page can
// trigger the single <v-snackbar> mounted once in app.vue.
export function useSnackbar() {
  const state = useState<SnackbarState>('snackbar', () => ({ show: false, text: '', color: 'success' }))

  function notify(text: string, color: SnackbarState['color'] = 'success') {
    state.value = { show: true, text, color }
  }

  return { state, notify }
}
