<template>
  <!-- Drawer/app-bar stay hardcoded black in both light and dark theme --
       they are not theme-driven, by design. -->
  <v-navigation-drawer
    permanent
    :rail="rail"
    rail-width="72"
    color="#000000"
    width="240"
    class="app-drawer"
  >
    <div class="pa-4 d-flex align-center">
      <img src="~/assets/images/logo.png" alt="axo" width="32" height="32" class="mr-2">
      <span v-if="!rail" class="text-white font-weight-bold">axo</span>
    </div>

    <v-list bg-color="transparent" base-color="white" color="accent" nav class="px-2">
      <v-list-item
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        :prepend-icon="item.icon"
        :title="item.title"
        rounded="lg"
        class="mb-1"
      />
    </v-list>

    <v-btn
      icon
      size="28"
      elevation="2"
      color="white"
      class="drawer-rail-toggle"
      :aria-label="rail ? 'Expand navigation' : 'Collapse navigation'"
      @click="rail = !rail"
    >
      <v-icon :icon="rail ? 'mdi-chevron-right' : 'mdi-chevron-left'" size="18" color="#000000" />
    </v-btn>
  </v-navigation-drawer>

  <v-app-bar color="#000000" flat>
    <v-spacer />
    <v-menu>
      <template #activator="{ props }">
        <div class="d-flex align-center user-menu-activator mr-4" v-bind="props">
          <v-avatar size="36" class="mr-2 avatar-ring">
            <v-img v-if="authStore.currentUser?.profile_photo" :src="authStore.currentUser.profile_photo" />
            <v-icon v-else icon="mdi-account" color="white" />
          </v-avatar>
          <span class="text-white mr-1">{{ displayName }}</span>
          <v-icon icon="mdi-chevron-down" color="white" size="18" />
        </div>
      </template>
      <v-list density="compact" min-width="200" rounded="lg">
        <v-list-item prepend-icon="mdi-cog-outline" title="Settings" to="/settings" />
        <v-list-item prepend-icon="mdi-logout" title="Logout" @click="authStore.signOut()" />
      </v-list>
    </v-menu>
  </v-app-bar>

  <v-main class="app-main">
    <slot />
  </v-main>
</template>

<script setup lang="ts">
const authStore = useAuthStore()
const rail = ref(false)

const displayName = computed(() => {
  const u = authStore.currentUser
  return u ? `${u.first_name} ${u.last_name}`.trim() : ''
})

const navItems = [
  { to: '/dashboard', icon: 'mdi-view-dashboard', title: 'Dashboard' },
  { to: '/virtual-environments', icon: 'mdi-cube-outline', title: 'Virtual Environments' },
  { to: '/endpoints', icon: 'mdi-server', title: 'Endpoints' },
  { to: '/active-objects', icon: 'mdi-shape-outline', title: 'Active Objects' },
  { to: '/functions', icon: 'mdi-function-variant', title: 'Functions' },
  { to: '/buckets', icon: 'mdi-bucket-outline', title: 'Buckets' },
]
</script>

<style scoped>
.app-drawer {
  position: relative;
}

.app-main {
  min-height: 100vh;
}

.avatar-ring {
  border: 2px solid #6fa8ff;
}

.user-menu-activator {
  cursor: pointer;
}

.drawer-rail-toggle {
  position: absolute;
  top: 50%;
  right: -14px;
  transform: translateY(-50%);
  z-index: 10;
}
</style>
