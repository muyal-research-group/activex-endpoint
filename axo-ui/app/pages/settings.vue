<template>
  <v-container fluid class="pa-6" style="max-width: 640px;">
    <h1 class="text-h5 mb-6">
      Settings
    </h1>

    <v-card class="pa-6" rounded="lg">
      <div class="text-subtitle-1 font-weight-medium mb-1">
        Appearance
      </div>
      <div class="text-caption text-medium-emphasis mb-4">
        Choose how axo looks on this device.
      </div>

      <v-btn-toggle
        v-model="selected"
        mandatory
        color="accent"
        rounded="lg"
        variant="outlined"
        @update:model-value="onChange"
      >
        <v-btn value="axoLight" prepend-icon="mdi-white-balance-sunny">
          Light
        </v-btn>
        <v-btn value="axoDark" prepend-icon="mdi-weather-night">
          Dark
        </v-btn>
      </v-btn-toggle>
    </v-card>

    <v-card class="pa-6 mt-4" rounded="lg">
      <div class="text-subtitle-1 font-weight-medium mb-1">
        Activity feed
      </div>
      <div class="text-caption text-medium-emphasis mb-4">
        How far back the events list defaults to showing, on the dashboard and
        every entity's history view. Bounded by how long this cluster
        actually retains activity data server-side -- a wider window may
        show fewer results than requested.
      </div>

      <v-select
        v-model="activityWindow"
        :items="windowOptions"
        item-title="label"
        item-value="minutes"
        variant="outlined"
        density="comfortable"
        max-width="320"
        :loading="profileStore.loading"
        @update:model-value="onActivityWindowChange"
      />
      <v-alert v-if="profileStore.error" type="error" variant="tonal" density="compact" class="mt-2">
        {{ profileStore.error }}
      </v-alert>
    </v-card>

    <v-card class="pa-6 mt-4" rounded="lg">
      <div class="text-subtitle-1 font-weight-medium mb-1">
        Endpoint purge eligibility
      </div>
      <div class="text-caption text-medium-emphasis mb-4">
        How long an endpoint must have been unreachable before its purge
        action is prominently surfaced on the endpoints page. Purely a
        display default -- an unreachable (or stopped) endpoint can always
        be purged immediately regardless of this setting.
      </div>

      <v-select
        v-model="purgeEligibleAfter"
        :items="purgeEligibleOptions"
        item-title="label"
        item-value="minutes"
        variant="outlined"
        density="comfortable"
        max-width="320"
        :loading="profileStore.loading"
        @update:model-value="onPurgeEligibleAfterChange"
      />
      <v-alert v-if="profileStore.error" type="error" variant="tonal" density="compact" class="mt-2">
        {{ profileStore.error }}
      </v-alert>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import type { ThemeName } from '~/composables/useThemeSetting'

const { preference, apply } = useThemeSetting()
const selected = ref<ThemeName>(preference.value)

function onChange(value: ThemeName) {
  apply(value)
}

const profileStore = useProfileStore()

const windowOptions = [
  { label: '15 minutes', minutes: 15 },
  { label: '30 minutes', minutes: 30 },
  { label: '1 hour', minutes: 60 },
  { label: '4 hours', minutes: 240 },
  { label: '24 hours', minutes: 1440 },
]

const activityWindow = ref(60)

const purgeEligibleOptions = [
  { label: '15 minutes', minutes: 15 },
  { label: '30 minutes', minutes: 30 },
  { label: '1 hour', minutes: 60 },
  { label: '4 hours', minutes: 240 },
  { label: '24 hours', minutes: 1440 },
]

const purgeEligibleAfter = ref(60)

onMounted(async () => {
  await profileStore.fetch()
  activityWindow.value = profileStore.activityWindowMinutes
  purgeEligibleAfter.value = profileStore.endpointPurgeEligibleAfterMinutes
})

async function onActivityWindowChange(minutes: number) {
  try {
    await profileStore.setActivityWindowMinutes(minutes)
  } catch {
    activityWindow.value = profileStore.activityWindowMinutes
  }
}

async function onPurgeEligibleAfterChange(minutes: number) {
  try {
    await profileStore.setEndpointPurgeEligibleAfterMinutes(minutes)
  } catch {
    purgeEligibleAfter.value = profileStore.endpointPurgeEligibleAfterMinutes
  }
}
</script>
