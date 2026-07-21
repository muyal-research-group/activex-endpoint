<template>
  <v-app>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
    <v-snackbar v-model="snackbarState.show" :color="snackbarState.color" location="bottom right" timeout="4000">
      {{ snackbarState.text }}
    </v-snackbar>
  </v-app>
</template>

<script setup lang="ts">
// Applies the saved light/dark preference before first paint so reloads
// never flash the default theme first.
useThemeSetting()

// Mounted once here so any page can trigger it via useSnackbar().notify(...).
// Destructured to a top-level ref (state) rather than kept as
// snackbar.state.value in the template -- top-level refs auto-unwrap there.
const { state: snackbarState } = useSnackbar()
</script>
