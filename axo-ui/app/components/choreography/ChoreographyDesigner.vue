<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-4" style="gap: 12px;">
      <NuxtLink to="/choreographies" class="text-body-2">
        &larr; Choreographies
      </NuxtLink>
    </div>

    <div class="d-flex align-center mb-4" style="gap: 12px;">
      <v-text-field
        v-model="name"
        label="Name"
        variant="outlined"
        density="comfortable"
        hide-details
        style="max-width: 360px;"
      />
      <v-spacer />
      <v-chip v-if="hasActiveRun" color="secondary" variant="elevated">
        Run in progress
      </v-chip>
      <v-btn variant="tonal" prepend-icon="mdi-check-circle-outline" :loading="validating" @click="onValidate">
        Validate
      </v-btn>
      <v-btn color="secondary" prepend-icon="mdi-content-save-outline" :loading="saving" @click="onSave">
        Save
      </v-btn>
      <v-btn
        v-if="choreographyId"
        color="secondary"
        variant="elevated"
        prepend-icon="mdi-play"
        :disabled="hasActiveRun"
        :loading="starting"
        @click="showRunConfirm = true"
      >
        Run
      </v-btn>
    </div>

    <v-alert v-if="saveError" type="error" variant="tonal" density="compact" class="mb-4">
      {{ saveError }}
    </v-alert>
    <v-alert
      v-if="validation && !validation.ok"
      type="warning"
      variant="tonal"
      density="compact"
      class="mb-4"
    >
      <div v-for="v in validation.violations" :key="v.node_id">
        Node "{{ v.node_id }}" ({{ v.function_id }}) needs {{ v.required_concurrency }} concurrent slots,
        but max_concurrency is {{ v.max_concurrency }}.
      </div>
    </v-alert>
    <v-alert v-else-if="validation && validation.ok" type="success" variant="tonal" density="compact" class="mb-4">
      No concurrency issues found.
    </v-alert>

    <div class="d-flex" style="gap: 16px; height: 70vh;">
      <!-- Side list: registered functions -->
      <v-card class="pa-4" width="260" style="overflow-y: auto;">
        <h3 class="text-subtitle-1 mb-3">
          Functions
        </h3>
        <v-list density="compact">
          <v-list-item
            v-for="fn in functionsStore.items"
            :key="`${fn.function_id}:${fn.version}`"
            :title="fn.name || fn.function_id"
            :subtitle="`v${fn.version}`"
            @click="addFunctionNode(fn)"
          />
        </v-list>

        <v-divider class="my-3" />

        <v-btn block variant="tonal" prepend-icon="mdi-bucket-outline" @click="openBucketPicker">
          Add Bucket
        </v-btn>

        <v-divider class="my-3" />

        <v-btn
          block
          variant="text"
          color="error"
          prepend-icon="mdi-delete-outline"
          :disabled="!selectedNodeId && !selectedEdgeId"
          @click="removeSelected"
        >
          Remove selected
        </v-btn>
      </v-card>

      <!-- Canvas -->
      <v-card class="flex-grow-1 pa-0" style="position: relative; overflow: hidden;">
        <ClientOnly>
          <VueFlow
            v-model:nodes="nodes"
            v-model:edges="edges"
            :default-viewport="{ zoom: 1 }"
            fit-view-on-init
            @node-click="onNodeClick"
            @edge-click="onEdgeClick"
            @pane-click="clearSelection"
          />
          <template #fallback>
            <div class="d-flex align-center justify-center" style="height: 100%;">
              <v-progress-circular indeterminate color="secondary" />
            </div>
          </template>
        </ClientOnly>
      </v-card>

      <!-- Config panel -->
      <v-card v-if="selectedNode || selectedEdge" class="pa-4" width="300" style="overflow-y: auto;">
        <template v-if="selectedNode && selectedNode.data.kind === 'function'">
          <h3 class="text-subtitle-1 mb-3">
            {{ selectedNode.data.function_id }} v{{ selectedNode.data.function_version }}
          </h3>
          <v-text-field
            v-model.number="selectedNode.data.max_retries"
            label="Max retries"
            type="number"
            min="0"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <v-select
            v-model="selectedNode.data.retry_policy"
            :items="['constant', 'exponential_backoff', 'jitter']"
            label="Retry policy"
            variant="outlined"
            density="comfortable"
          />
        </template>

        <template v-else-if="selectedNode && selectedNode.data.kind === 'bucket'">
          <h3 class="text-subtitle-1 mb-3">
            Bucket: {{ selectedNode.data.bucket_name }}
          </h3>
          <p v-if="bucketsStore.loading" class="text-body-2 text-medium-emphasis">
            Loading…
          </p>
          <template v-else-if="bucketDetail">
            <p class="text-caption text-medium-emphasis mb-2">
              {{ bucketDetail.items.length }} item(s)
            </p>
            <v-list density="compact" class="mb-3">
              <v-list-item
                v-for="item in bucketDetail.items"
                :key="`${item.name}:${item.version}`"
                :title="item.name"
                :subtitle="`v${item.version} — ${item.status}`"
              >
                <template #prepend>
                  <v-checkbox-btn
                    :model-value="isItemSelected(item)"
                    @update:model-value="v => toggleItemSelected(item, v)"
                  />
                </template>
              </v-list-item>
            </v-list>
            <p v-if="bucketDetail.items.length === 0" class="text-body-2 text-medium-emphasis mb-3">
              Bucket is empty. Upload a file to seed it.
            </p>
            <v-file-input
              v-model="uploadFile"
              label="Upload file"
              density="comfortable"
              variant="outlined"
              hide-details
              class="mb-2"
            />
            <v-btn size="small" variant="tonal" block :disabled="!uploadFile" @click="onUploadToBucket">
              Upload
            </v-btn>
          </template>
        </template>

        <template v-else-if="selectedEdge">
          <h3 class="text-subtitle-1 mb-3">
            Edge: {{ selectedEdge.data.kind }}
          </h3>
          <v-select
            v-if="selectedEdge.data.kind === 'fn_to_fn'"
            v-model="selectedEdge.data.target_param"
            :items="targetParamOptions(selectedEdge)"
            label="Target parameter"
            variant="outlined"
            density="comfortable"
          />
          <template v-if="selectedEdge.data.kind === 'bucket_to_fn'">
            <v-select
              v-model="selectedEdge.data.target_param"
              :items="targetParamOptions(selectedEdge)"
              label="Target parameter"
              variant="outlined"
              density="comfortable"
              class="mb-3"
            />
            <v-text-field
              v-model.number="selectedEdge.data.parallelism"
              label="Parallelism"
              type="number"
              min="1"
              variant="outlined"
              density="comfortable"
              hint="How many items to process at once (capped at the function's max_concurrency)"
              persistent-hint
            />
          </template>
          <p v-if="selectedEdge.data.kind === 'fn_to_bucket'" class="text-body-2 text-medium-emphasis">
            This function's result will be saved as a new item in the bucket.
          </p>
        </template>
      </v-card>
    </div>

    <!-- Bucket picker dialog -->
    <v-dialog v-model="showBucketPicker" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Add a bucket
        </h3>
        <v-btn-toggle v-model="bucketPickerMode" mandatory class="mb-4" color="secondary" variant="outlined">
          <v-btn value="existing">
            Existing
          </v-btn>
          <v-btn value="new">
            Create new
          </v-btn>
        </v-btn-toggle>

        <template v-if="bucketPickerMode === 'existing'">
          <v-select
            v-model="pickedBucketName"
            :items="bucketsStore.items.map(b => b.name)"
            label="Bucket"
            variant="outlined"
            density="comfortable"
          />
        </template>
        <template v-else>
          <v-text-field v-model="newBucketName" label="Name" variant="outlined" density="comfortable" class="mb-3" />
          <v-text-field
            v-model.number="newBucketQuotaMb"
            label="Quota (MB)"
            type="number"
            variant="outlined"
            density="comfortable"
            class="mb-3"
          />
          <v-select
            v-model="newBucketEndpointId"
            :items="endpointsStore.items"
            item-title="endpoint_id"
            item-value="endpoint_id"
            label="Endpoint"
            variant="outlined"
            density="comfortable"
          />
        </template>

        <v-alert v-if="bucketPickerError" type="error" variant="tonal" density="compact" class="mt-3">
          {{ bucketPickerError }}
        </v-alert>

        <div class="d-flex justify-end mt-4" style="gap: 8px;">
          <v-btn variant="text" @click="showBucketPicker = false">
            Cancel
          </v-btn>
          <v-btn color="secondary" @click="confirmBucketPicker">
            Add
          </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- Run confirmation -->
    <v-dialog v-model="showRunConfirm" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Run this choreography?
        </h3>
        <v-alert v-if="validation && !validation.ok" type="warning" variant="tonal" density="compact" class="mb-4">
          There are unresolved concurrency warnings -- some branches may queue instead of running in parallel.
        </v-alert>
        <div class="d-flex justify-end" style="gap: 8px;">
          <v-btn variant="text" @click="showRunConfirm = false">
            Cancel
          </v-btn>
          <v-btn color="secondary" :loading="starting" @click="onRun">
            Run
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import { VueFlow, useVueFlow, type Node, type Edge } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import type { ChoreographyGraph, ValidationResult } from '~/types/choreography'
import type { BucketWithItems, DataItem } from '~/types/bucket'
import type { FunctionRecord } from '~/types/functionRecord'

const props = defineProps<{ choreographyId?: string }>()

const router = useRouter()
const choreographiesStore = useChoreographiesStore()
const functionsStore = useFunctionsStore()
const bucketsStore = useBucketsStore()
const endpointsStore = useEndpointsStore()
const snackbar = useSnackbar()

const { onConnect: onConnectHook, addEdges, removeNodes, removeEdges } = useVueFlow()

const name = ref('New Choreography')
const nodes = ref<Node[]>([])
const edges = ref<Edge[]>([])
const saving = ref(false)
const validating = ref(false)
const starting = ref(false)
const saveError = ref<string | null>(null)
const validation = ref<ValidationResult | null>(null)
const hasActiveRun = ref(false)

const selectedNodeId = ref<string | null>(null)
const selectedEdgeId = ref<string | null>(null)
const selectedNode = computed(() => nodes.value.find(n => n.id === selectedNodeId.value) ?? null)
const selectedEdge = computed(() => edges.value.find(e => e.id === selectedEdgeId.value) ?? null)

let nextNodeSeq = 1
let nextEdgeSeq = 1

onMounted(async () => {
  functionsStore.fetchAll()
  bucketsStore.fetchAll()
  endpointsStore.fetchAll()
  if (props.choreographyId) {
    await choreographiesStore.fetchOne(props.choreographyId)
    const loaded = choreographiesStore.current
    if (loaded) {
      name.value = loaded.name
      hasActiveRun.value = !!loaded.has_active_run
      nodes.value = loaded.graph.nodes.map(n => ({
        id: n.node_id,
        position: n.position,
        label: n.kind === 'function' ? `${n.function_id} v${n.function_version}` : `Bucket: ${n.bucket_name}`,
        class: n.kind === 'bucket' ? 'choreo-node choreo-node--bucket' : 'choreo-node choreo-node--function',
        data: { ...n, kind: n.kind },
      }))
      edges.value = loaded.graph.edges.map(e => ({
        id: e.edge_id,
        source: e.source_node_id,
        target: e.target_node_id,
        label: e.kind === 'bucket_to_fn' ? `x${e.parallelism ?? 1}` : (e.target_param || ''),
        data: { ...e },
      }))
    }
  }
})

function addFunctionNode(fn: FunctionRecord) {
  const id = `n${nextNodeSeq++}`
  nodes.value.push({
    id,
    position: { x: 80 + Math.random() * 200, y: 80 + Math.random() * 300 },
    label: `${fn.name || fn.function_id} v${fn.version}`,
    class: 'choreo-node choreo-node--function',
    data: {
      node_id: id, kind: 'function', function_id: fn.function_id, function_version: fn.version,
      max_retries: 3, retry_policy: 'constant',
    },
  })
}

function addBucketNode(bucketName: string) {
  const id = `n${nextNodeSeq++}`
  nodes.value.push({
    id,
    position: { x: 80 + Math.random() * 200, y: 80 + Math.random() * 300 },
    label: `Bucket: ${bucketName}`,
    class: 'choreo-node choreo-node--bucket',
    data: { node_id: id, kind: 'bucket', bucket_name: bucketName, selected_items: [] },
  })
}

function nodeKind(id: string): 'function' | 'bucket' | undefined {
  return nodes.value.find(n => n.id === id)?.data?.kind
}

function edgeKindFor(sourceId: string, targetId: string): 'fn_to_fn' | 'fn_to_bucket' | 'bucket_to_fn' | null {
  const sourceKind = nodeKind(sourceId)
  const targetKind = nodeKind(targetId)
  if (sourceKind === 'function' && targetKind === 'function') return 'fn_to_fn'
  if (sourceKind === 'function' && targetKind === 'bucket') return 'fn_to_bucket'
  if (sourceKind === 'bucket' && targetKind === 'function') return 'bucket_to_fn'
  return null
}

onConnectHook((connection) => {
  const kind = edgeKindFor(connection.source, connection.target)
  if (!kind) {
    snackbar.notify('That connection is not supported.', 'error')
    return
  }
  const id = `e${nextEdgeSeq++}`
  addEdges([{
    ...connection,
    id,
    label: kind === 'bucket_to_fn' ? 'x1' : '',
    data: {
      edge_id: id, source_node_id: connection.source, target_node_id: connection.target,
      kind, target_param: null, parallelism: 1,
    },
  }])
})

function onNodeClick({ node }: { node: Node }) {
  selectedNodeId.value = node.id
  selectedEdgeId.value = null
  if (node.data.kind === 'bucket' && node.data.bucket_name) {
    bucketsStore.fetchOne(node.data.bucket_name)
  }
}

function onEdgeClick({ edge }: { edge: Edge }) {
  selectedEdgeId.value = edge.id
  selectedNodeId.value = null
}

function clearSelection() {
  selectedNodeId.value = null
  selectedEdgeId.value = null
}

const bucketDetail = computed<BucketWithItems | null>(() => bucketsStore.current)

function isItemSelected(item: DataItem): boolean {
  const selected = selectedNode.value?.data?.selected_items as { name: string, version: number }[] | undefined
  return !!selected?.some(s => s.name === item.name && s.version === item.version)
}

function toggleItemSelected(item: DataItem, checked: boolean) {
  if (!selectedNode.value) return
  const list = (selectedNode.value.data.selected_items ?? []) as { name: string, version: number }[]
  if (checked) {
    selectedNode.value.data.selected_items = [...list, { name: item.name, version: item.version }]
  } else {
    selectedNode.value.data.selected_items = list.filter(s => !(s.name === item.name && s.version === item.version))
  }
}

const uploadFile = ref<File | null>(null)
async function onUploadToBucket() {
  if (!uploadFile.value || !selectedNode.value?.data?.bucket_name) return
  const endpoint = endpointsStore.items[0]
  if (!endpoint) {
    snackbar.notify('No endpoint available to upload through.', 'error')
    return
  }
  try {
    const key = uploadFile.value.name
    await bucketsStore.uploadData(endpoint.endpoint_id, selectedNode.value.data.bucket_name, key, 1, uploadFile.value)
    await bucketsStore.fetchOne(selectedNode.value.data.bucket_name)
    uploadFile.value = null
  } catch (err: any) {
    snackbar.notify(err.message, 'error')
  }
}

function targetParamOptions(edge: Edge): string[] {
  const target = nodes.value.find(n => n.id === edge.target)
  if (!target) return []
  const fn = functionsStore.items.find(
    f => f.function_id === target.data.function_id && f.version === target.data.function_version,
  )
  return (fn?.params_schema ?? []).map(p => p.name)
}

function removeSelected() {
  if (selectedNodeId.value) {
    removeNodes([selectedNodeId.value])
    edges.value = edges.value.filter(e => e.source !== selectedNodeId.value && e.target !== selectedNodeId.value)
  }
  if (selectedEdgeId.value) {
    removeEdges([selectedEdgeId.value])
  }
  clearSelection()
}

const showBucketPicker = ref(false)
const bucketPickerMode = ref<'existing' | 'new'>('existing')
const pickedBucketName = ref<string | null>(null)
const newBucketName = ref('')
const newBucketQuotaMb = ref(100)
const newBucketEndpointId = ref<string | null>(null)
const bucketPickerError = ref<string | null>(null)

function openBucketPicker() {
  bucketPickerMode.value = 'existing'
  pickedBucketName.value = null
  newBucketName.value = ''
  newBucketQuotaMb.value = 100
  newBucketEndpointId.value = null
  bucketPickerError.value = null
  showBucketPicker.value = true
}

async function confirmBucketPicker() {
  bucketPickerError.value = null
  if (bucketPickerMode.value === 'existing') {
    if (!pickedBucketName.value) {
      bucketPickerError.value = 'Select a bucket'
      return
    }
    addBucketNode(pickedBucketName.value)
    showBucketPicker.value = false
    return
  }
  if (!newBucketName.value || !newBucketEndpointId.value) {
    bucketPickerError.value = 'Name and endpoint are required'
    return
  }
  try {
    await bucketsStore.create(newBucketEndpointId.value, {
      name: newBucketName.value, quota_bytes: Math.round(newBucketQuotaMb.value * 1024 * 1024),
    })
    addBucketNode(newBucketName.value)
    showBucketPicker.value = false
  } catch (err: any) {
    bucketPickerError.value = err.message
  }
}

function buildGraph(): ChoreographyGraph {
  return {
    nodes: nodes.value.map(n => ({
      node_id: n.id,
      kind: n.data.kind,
      position: { x: n.position.x, y: n.position.y },
      function_id: n.data.function_id ?? null,
      function_version: n.data.function_version ?? null,
      max_retries: n.data.max_retries ?? 3,
      retry_policy: n.data.retry_policy ?? 'constant',
      bucket_name: n.data.bucket_name ?? null,
      selected_items: n.data.selected_items ?? null,
    })),
    edges: edges.value.map(e => ({
      edge_id: e.id,
      source_node_id: e.source,
      target_node_id: e.target,
      kind: e.data.kind,
      target_param: e.data.target_param ?? null,
      parallelism: e.data.parallelism ?? 1,
    })),
  }
}

async function onSave() {
  saveError.value = null
  saving.value = true
  try {
    const graph = buildGraph()
    if (props.choreographyId) {
      await choreographiesStore.update(props.choreographyId, name.value, graph)
      snackbar.notify('Saved', 'success')
    } else {
      const created = await choreographiesStore.create(name.value, graph)
      snackbar.notify('Created', 'success')
      router.replace(`/choreographies/${created.choreography_id}`)
    }
  } catch (err: any) {
    saveError.value = err.message
  } finally {
    saving.value = false
  }
}

async function onValidate() {
  if (!props.choreographyId) {
    snackbar.notify('Save the choreography before validating.', 'error')
    return
  }
  validating.value = true
  try {
    validation.value = await choreographiesStore.validate(props.choreographyId)
  } catch (err: any) {
    snackbar.notify(err.message, 'error')
  } finally {
    validating.value = false
  }
}

const showRunConfirm = ref(false)

async function onRun() {
  if (!props.choreographyId) return
  starting.value = true
  try {
    const run = await choreographiesStore.run(props.choreographyId)
    showRunConfirm.value = false
    router.push(`/choreographies/${props.choreographyId}/run/${run.run_id}`)
  } catch (err: any) {
    snackbar.notify(err.message, 'error')
  } finally {
    starting.value = false
  }
}
</script>

<style scoped>
:deep(.choreo-node--function) {
  border: 2px solid rgb(var(--v-theme-secondary));
}

:deep(.choreo-node--bucket) {
  border: 2px solid #f59e0b;
  border-radius: 4px;
}
</style>
