// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },
  modules: ['vuetify-nuxt-module', '@pinia/nuxt'],
  css: ['~/assets/css/main.css'],
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8080',
    },
  },
  vuetify: {
    moduleOptions: {
      icons: {
        defaultSet: 'mdi',
        sets: ['mdi'],
      },
    },
    vuetifyOptions: {
      // Theme organization: two named themes, light is the app default.
      // The drawer/app-bar are intentionally NOT theme-driven -- they stay
      // hardcoded black (see app/layouts/default.vue) in both themes, per
      // design. `accent` (#0086FF) is the one brand color, reused as both
      // `primary` and `secondary` so every existing `color="secondary"`
      // reference stays correct without touching every page.
      theme: {
        defaultTheme: 'axoLight',
        themes: {
          axoLight: {
            dark: false,
            colors: {
              background: '#F4F5F8',
              surface: '#FFFFFF',
              'surface-variant': '#E7E9EE',
              primary: '#0086FF',
              secondary: '#0086FF',
              accent: '#0086FF',
            },
          },
          axoDark: {
            dark: true,
            colors: {
              background: '#0B0B0D',
              surface: '#1B1C1F',
              'surface-variant': '#2A2B2F',
              primary: '#0086FF',
              secondary: '#0086FF',
              accent: '#0086FF',
            },
          },
        },
      },
    },
  },
})
