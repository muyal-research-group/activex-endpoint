export type ThemeName = 'axoLight' | 'axoDark'

// Cookie-backed (not a Pinia store) for the same reason useAuthSession is a
// cookie: it needs to read consistently during SSR so the very first
// server-rendered response already matches the user's saved preference --
// no light-then-dark flash on reload.
export function useThemeSetting() {
  const theme = useTheme()
  const preference = useCookie<ThemeName>('axo_theme', {
    default: () => 'axoLight',
    sameSite: 'lax',
  })

  function apply(name: ThemeName) {
    preference.value = name
    theme.global.name.value = name
  }

  // Keep Vuetify's active theme in sync with the stored preference on every
  // layout mount (covers SSR hydration and client-side navigation alike).
  theme.global.name.value = preference.value

  return { preference, apply }
}
