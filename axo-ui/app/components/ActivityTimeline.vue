<template>
  <div v-if="events.length" :style="scrollStyle">
    <v-list density="comfortable" class="pa-0">
      <v-list-item
        v-for="event in events"
        :key="event.event_id"
        class="px-0"
        link
        @click="openDetail(event)"
      >
        <v-list-item-title>{{ event.event_type }}</v-list-item-title>
        <v-list-item-subtitle>
          <span :title="formatAbsoluteMxTime(event.created_at)">{{ formatRelativeTime(event.created_at, now) }}</span>
        </v-list-item-subtitle>
      </v-list-item>
    </v-list>
  </div>
  <p v-else class="text-body-2 text-medium-emphasis">
    No activity yet
  </p>

  <v-dialog v-model="showDetail" max-width="560">
    <v-card v-if="selectedEvent" class="pa-6">
      <h3 class="text-h6 mb-1">
        {{ selectedEvent.event_type }}
      </h3>
      <p class="text-body-2 text-medium-emphasis mb-4">
        {{ formatAbsoluteMxTime(selectedEvent.created_at) }} · {{ formatRelativeTime(selectedEvent.created_at, now) }}
      </p>

      <div class="text-caption text-medium-emphasis mb-1">
        Metadata
      </div>
      <pre v-if="hasMeta" class="pa-3 rounded bg-surface-variant meta-block">{{ prettyMeta }}</pre>
      <p v-else class="text-body-2 text-medium-emphasis">
        No metadata for this event
      </p>

      <div class="d-flex justify-end mt-4">
        <v-btn variant="text" @click="showDetail = false">
          Close
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
import type { ActivityEvent } from '~/types/activity'

const props = withDefaults(defineProps<{ events: ActivityEvent[]; maxHeight?: number | string }>(), {
  maxHeight: 336,
})

const scrollStyle = computed(() => ({
  maxHeight: typeof props.maxHeight === 'number' ? `${props.maxHeight}px` : props.maxHeight,
  overflowY: 'auto' as const,
}))

const now = ref(new Date())
let refreshInterval: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  refreshInterval = setInterval(() => {
    now.value = new Date()
  }, 60_000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})

const showDetail = ref(false)
const selectedEvent = ref<ActivityEvent | null>(null)

function openDetail(event: ActivityEvent) {
  selectedEvent.value = event
  showDetail.value = true
}

const hasMeta = computed(() => !!selectedEvent.value && Object.keys(selectedEvent.value.meta ?? {}).length > 0)
const prettyMeta = computed(() => (selectedEvent.value ? JSON.stringify(selectedEvent.value.meta, null, 2) : ''))
</script>

<style scoped>
.meta-block {
  color: rgb(var(--v-theme-on-surface));
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
}
</style>
