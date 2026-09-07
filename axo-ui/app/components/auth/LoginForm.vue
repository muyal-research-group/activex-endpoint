<template>
  <v-form class="login-form" @submit.prevent="authStore.signIn()">
    <v-text-field
      v-model="username"
      placeholder="Username"
      variant="solo"
      flat
      rounded="lg"
      bg-color="#f0f0f0"
      density="comfortable"
      hide-details
      class="mb-4 login-field"
    />
    <v-text-field
      v-model="password"
      type="password"
      placeholder="Password"
      variant="solo"
      flat
      rounded="lg"
      bg-color="#f0f0f0"
      density="comfortable"
      hide-details
      class="mb-8 login-field"
    />
    <v-alert
      v-if="authStore.error"
      type="error"
      variant="tonal"
      density="compact"
      class="mb-4"
    >
      {{ authStore.error }}
    </v-alert>
    <v-btn
      type="submit"
      block
      size="x-large"
      rounded="lg"
      color="#1e1e1e"
      :loading="authStore.loading"
      class="text-uppercase font-weight-bold mb-6 text-white"
    >
      Sign In
    </v-btn>
    <p class="text-center text-body-2 signup-caption">
      Don't have an account yet?
      <NuxtLink to="/signup" class="font-weight-bold signup-link">Sign up</NuxtLink>
    </p>
  </v-form>
</template>

<script setup lang="ts">
const authStore = useAuthStore()
const { username, password } = storeToRefs(authStore)
</script>

<style scoped>
.login-field :deep(.v-field__input) {
  color: rgba(0, 0, 0, 0.87);
}

.login-field :deep(input::placeholder) {
  color: rgba(0, 0, 0, 0.6);
  opacity: 1;
}

.signup-caption {
  color: rgba(255, 255, 255, 0.7);
}

.signup-link {
  color: #0086ff;
  text-decoration: none;
}
</style>
