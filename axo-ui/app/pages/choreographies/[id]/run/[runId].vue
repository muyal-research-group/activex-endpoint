<template>
  <v-container fluid class="pa-6">
    <NuxtLink :to="`/choreographies/${choreographyId}`" class="text-body-2 mb-4 d-inline-block">
      &larr; {{ choreographiesStore.current?.name ?? choreographyId }}
    </NuxtLink>

    <div class="d-flex align-center mb-4" style="gap: 12px;">
      <h2 class="text-h6">
        Run {{ runId }}
      </h2>
      <v-chip :color="statusColor(run?.status)" variant="elevated">
        {{ run?.status ?? '—' }}
      </v-chip>
      <v-spacer />
      <v-btn
        v-if="run && isActive"
        color="error"
        variant="tonal"
        prepend-icon="mdi-stop"
        :loading="stopping"
        @click="onStop"
      >
        Stop
      </v-btn>
    </div>

    <v-card style="height: 65vh; position: relative;" class="pa-0">
      <ClientOnly>
        <VueFlow
          v-model:nodes="nodes"
          :edges="edges"
          :nodes-draggable="false"
          fit-view-on-init
          @node-click="({ node }) => (selectedNodeId = node.id)"
        />
        <template #fallback>
          <div class="d-flex align-center justify-center" style="height: 100%;">
            <v-progress-circular indeterminate color="secondary" />
          </div>
        </template>
      </ClientOnly>
    </v-card>

    <v-card v-if="selectedState" class="pa-4 mt-4">
      <h3 class="text-subtitle-1 mb-2">
        {{ selectedState.node_id }}
      </h3>
      <p class="text-body-2 mb-1">
        Status: {{ selectedState.status }}
      </p>
      <p v-if="selectedState.job_id" class="text-body-2 mb-1">
        Job: {{ selectedState.job_id }}
      </p>
      <p v-if="selectedState.error" class="text-body-2 text-error mb-1">
        Error: {{ selectedState.error }}
      </p>
      <p v-for="(w, i) in selectedState.warnings" :key="i" class="text-body-2 text-warning mb-1">
        Warning: {{ w }}
      </p>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import { VueFlow, type Node, type Edge } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import type { NodeStatus } from '~/types/choreography'

definePageMeta({
  key: to => to.fullPath,
})

const route = useRoute()
const choreographyId = computed(() => route.params.id as string)
const runId = computed(() => route.params.runId as string)

const choreographiesStore = useChoreographiesStore()
const snackbar = useSnackbar()

const run = computed(() => choreographiesStore.currentRun)
const isActive = computed(() => run.value?.status === 'pending' || run.value?.status === 'running')

const nodes = ref<Node[]>([])
const edges = ref<Edge[]>([])
const selectedNodeId = ref<string | null>(null)
const selectedState = computed(() => (selectedNodeId.value ? run.value?.node_states[selectedNodeId.value] : null))

function statusColor(status?: string) {
  switch (status) {
    case 'completed': return 'success'
    case 'failed': return 'error'
    case 'cancelled': return 'default'
    case 'running': return 'secondary'
    default: return 'default'
  }
}

function nodeClass(status: NodeStatus | undefined) {
  switch (status) {
    case 'completed': return 'choreo-run-node choreo-run-node--completed'
    case 'failed': return 'choreo-run-node choreo-run-node--failed'
    case 'cancelled': return 'choreo-run-node choreo-run-node--cancelled'
    case 'running': return 'choreo-run-node choreo-run-node--running'
    default: return 'choreo-run-node choreo-run-node--pending'
  }
}

function rebuildElements() {
  const graph = choreographiesStore.current?.graph
  if (!graph) return
  nodes.value = graph.nodes.map(n => ({
    id: n.node_id,
    position: n.position,
    label: n.kind === 'function' ? `${n.function_id} v${n.function_version}` : `Bucket: ${n.bucket_name}`,
    class: nodeClass(run.value?.node_states[n.node_id]?.status),
  }))
  edges.value = graph.edges.map(e => ({
    id: e.edge_id,
    source: e.source_node_id,
    target: e.target_node_id,
    animated: run.value?.node_states[e.source_node_id]?.status === 'running'
      || run.value?.node_states[e.source_node_id]?.status === 'completed',
  }))
}

watch(() => run.value?.node_states, rebuildElements, { deep: true })

onMounted(async () => {
  await choreographiesStore.fetchOne(choreographyId.value)
  await choreographiesStore.fetchRun(choreographyId.value, runId.value)
  rebuildElements()
  choreographiesStore.connectRunSocket(runId.value)
})

onBeforeUnmount(() => {
  choreographiesStore.disconnectRunSocket()
})

async function onStop() {
  stopping.value = true
  try {
    await choreographiesStore.cancelRun(choreographyId.value, runId.value)
  } catch (err: any) {
    snackbar.notify(err.message, 'error')
  } finally {
    stopping.value = false
  }
}

const stopping = ref(false)
</script>

<style scoped>
:deep(.choreo-run-node) {
  transition: background-color 0.3s ease, border-color 0.3s ease;
}

:deep(.choreo-run-node--pending) {
  opacity: 0.6;
}

:deep(.choreo-run-node--running) {
  border: 2px solid rgb(var(--v-theme-secondary));
  background-color: rgba(var(--v-theme-secondary), 0.1);
}

:deep(.choreo-run-node--completed) {
  border: 2px solid #22c55e;
  background-color: rgba(34, 197, 94, 0.1);
}

:deep(.choreo-run-node--failed) {
  border: 2px solid #ef4444;
  background-color: rgba(239, 68, 68, 0.1);
}

:deep(.choreo-run-node--cancelled) {
  border: 2px dashed #9ca3af;
  opacity: 0.5;
}
</style>
