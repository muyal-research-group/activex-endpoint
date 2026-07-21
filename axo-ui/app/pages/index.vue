<script setup lang="ts">
// The global auth middleware already bounces unauthenticated visitors to
// /login before this page's own script runs, so this only ever needs to
// pick the authenticated landing route.
await navigateTo('/dashboard')
</script>

<template>
  <div />
</template>
