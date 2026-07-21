<template>
  <v-form class="signup-form" @submit.prevent="onSubmit">
    <v-text-field
      v-model="username"
      placeholder="Username"
      variant="solo"
      flat
      rounded="lg"
      bg-color="#f0f0f0"
      density="comfortable"
      hide-details
      class="mb-4 signup-field"
    />
    <div class="d-flex mb-4" style="gap: 12px;">
      <v-text-field
        v-model="firstName"
        placeholder="First name"
        variant="solo"
        flat
        rounded="lg"
        bg-color="#f0f0f0"
        density="comfortable"
        hide-details
        class="signup-field"
      />
      <v-text-field
        v-model="lastName"
        placeholder="Last name"
        variant="solo"
        flat
        rounded="lg"
        bg-color="#f0f0f0"
        density="comfortable"
        hide-details
        class="signup-field"
      />
    </div>
    <v-text-field
      v-model="email"
      type="email"
      placeholder="Email"
      variant="solo"
      flat
      rounded="lg"
      bg-color="#f0f0f0"
      density="comfortable"
      hide-details
      class="mb-4 signup-field"
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
      class="mb-4 signup-field"
    />
    <v-text-field
      v-model="confirmPassword"
      type="password"
      placeholder="Confirm password"
      variant="solo"
      flat
      rounded="lg"
      bg-color="#f0f0f0"
      density="comfortable"
      hide-details
      class="mb-8 signup-field"
    />
    <v-alert
      v-if="formError || authStore.error"
      type="error"
      variant="tonal"
      density="compact"
      class="mb-4"
    >
      {{ formError || authStore.error }}
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
      Sign Up
    </v-btn>
    <p class="text-center text-body-2 login-caption">
      Already have an account?
      <NuxtLink to="/login" class="font-weight-bold login-link">Sign in</NuxtLink>
    </p>
  </v-form>
</template>

<script setup lang="ts">
const authStore = useAuthStore()

const username = ref('')
const firstName = ref('')
const lastName = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const formError = ref<string | null>(null)

async function onSubmit() {
  formError.value = null
  if (password.value !== confirmPassword.value) {
    formError.value = 'Passwords do not match'
    return
  }
  await authStore.signUp({
    username: username.value,
    first_name: firstName.value,
    last_name: lastName.value,
    email: email.value,
    password: password.value,
  })
}
</script>

<style scoped>
.signup-field :deep(.v-field__input) {
  color: rgba(0, 0, 0, 0.87);
}

.signup-field :deep(input::placeholder) {
  color: rgba(0, 0, 0, 0.6);
  opacity: 1;
}

.login-caption {
  color: rgba(255, 255, 255, 0.7);
}

.login-link {
  color: #0086ff;
  text-decoration: none;
}
</style>
