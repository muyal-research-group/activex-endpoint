<template>
  <v-main class="auth-layout">
    <slot />
  </v-main>
</template>

<style scoped>
.auth-layout {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #000;
  color: #fff;
}
</style>
