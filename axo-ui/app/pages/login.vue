<template>
  <div class="login-page d-flex flex-column align-center">
    <img src="~/assets/images/logo.png" alt="axo" class="axo-logo mb-8">
    <AuthLoginForm />
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'auth' })
</script>

<style scoped>
.login-page {
  width: 100%;
  max-width: 480px;
  padding: 0 16px;
}

.axo-logo {
  width: 140px;
  height: 140px;
  /* filter: invert(1); */
}
</style>
