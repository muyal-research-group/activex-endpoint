<template>
  <v-container fluid class="pa-6">
    <div class="d-flex mb-6" style="gap: 16px;">
      <v-card class="pa-4 stat-card" width="200">
        <div class="d-flex align-center justify-space-between">
          <span class="text-subtitle-1">Registered</span>
          <span class="status-dot status-dot--active" />
        </div>
        <div class="text-h4 font-weight-bold mt-1">
          {{ store.items.length }}
        </div>
      </v-card>
    </div>

    <v-btn
      color="secondary"
      size="large"
      rounded="lg"
      prepend-icon="mdi-plus"
      class="text-uppercase font-weight-bold mb-6"
      @click="openRegisterDialog"
    >
      Register Function
    </v-btn>

    <v-card class="pa-6">
      <h2 class="text-h6 mb-4">
        Functions
      </h2>

      <v-text-field
        v-model="search"
        placeholder="Search"
        variant="solo"
        flat
        rounded="pill"
        :bg-color="isDarkTheme ? '#1B1C1F' : '#f4f5f8'"
        density="comfortable"
        prepend-inner-icon="mdi-magnify"
        hide-details
        class="mb-4 search-field"
        :class="{ 'search-field--dark': isDarkTheme }"
        max-width="420"
      />

      <v-alert v-if="store.error" type="error" variant="tonal" density="compact" class="mb-4">
        {{ store.error }}
      </v-alert>

      <v-data-table
        :headers="headers"
        :items="filteredItems"
        :loading="store.loading"
        item-value="function_id"
        no-data-text="No functions registered yet"
      >
        <template #item.function_id="{ item }">
          <NuxtLink :to="`/functions/${item.function_id}`" class="d-flex align-center text-decoration-none">
            <v-avatar size="32" color="grey-lighten-2" class="mr-3">
              <v-icon icon="mdi-function-variant" size="18" />
            </v-avatar>
            <div>
              <div>{{ item.name ?? '(unnamed)' }}</div>
              <div class="text-caption text-medium-emphasis function-id-text" :title="item.function_id">
                {{ item.function_id }}
              </div>
            </div>
          </NuxtLink>
        </template>
        <template #item.runtime_type="{ item }">
          {{ item.runtime_spec?.type ?? 'process' }}
        </template>
        <template #item.state="{ item }">
          {{ item.state ?? '—' }}
          <v-chip v-if="item.deleted_at" size="small" variant="tonal" class="ml-2">
            Deleted
          </v-chip>
        </template>
        <template #item.actions="{ item }">
          <v-btn
            icon="mdi-delete-outline"
            variant="text"
            size="small"
            @click="confirmDelete(item)"
          />
        </template>
      </v-data-table>
    </v-card>

    <!-- Register dialog -->
    <v-dialog v-model="showRegisterDialog" max-width="640" scrollable>
      <v-card>
        <v-card-title class="pa-6 pb-0">
          <h3 class="text-h6">
            Register Function
          </h3>
        </v-card-title>
        <v-card-text class="pa-6">
          <v-form @submit.prevent="onRegister">
            <v-select
              v-model="form.virtual_environment_id"
              :items="virtualEnvironmentsStore.items"
              item-title="name"
              item-value="virtual_environment_id"
              label="Virtual environment"
              variant="outlined"
              density="comfortable"
              class="mb-3"
              :rules="[v => !!v || 'Select a virtual environment to register into']"
            />

            <v-text-field
              v-model="form.name"
              label="Function name"
              variant="outlined"
              density="comfortable"
              class="mb-3"
            />

            <v-btn-toggle
              v-model="codeInputMode"
              mandatory
              color="secondary"
              rounded="lg"
              variant="outlined"
              density="comfortable"
              class="mb-3"
            >
              <v-btn value="upload">Upload</v-btn>
              <v-btn value="write">Write</v-btn>
            </v-btn-toggle>

            <v-file-input
              v-if="codeInputMode === 'upload'"
              v-model="codeFile"
              label="Code (.py)"
              accept=".py,text/x-python"
              variant="outlined"
              density="comfortable"
              prepend-icon="mdi-file-code-outline"
              :hint="codeHint"
              persistent-hint
              class="mb-4"
            />
            <div v-else class="mb-4">
              <p class="text-caption text-medium-emphasis mb-1">
                {{ codeHint }}
              </p>
              <ClientOnly>
                <VueMonacoEditor
                  v-model:value="codeText"
                  language="python"
                  :theme="isDarkTheme ? 'vs-dark' : 'vs'"
                  height="300px"
                  :options="{
                    minimap: { enabled: false },
                    fontSize: 14,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                  }"
                />
                <template #fallback>
                  <v-sheet height="300px" class="d-flex align-center justify-center" border rounded>
                    <v-progress-circular indeterminate color="secondary" />
                  </v-sheet>
                </template>
              </ClientOnly>
            </div>

            <v-expansion-panels class="mb-4">
              <v-expansion-panel>
                <v-expansion-panel-title>
                  Runtime spec
                </v-expansion-panel-title>
                <v-expansion-panel-text>
                  <v-select
                    v-model="runtimeSpec.type"
                    :items="['process', 'container']"
                    label="Type"
                    variant="outlined"
                    density="comfortable"
                    class="mb-3"
                  />
                  <v-text-field
                    v-model="runtimeSpec.python_version"
                    label="Python version"
                    variant="outlined"
                    density="comfortable"
                    class="mb-3"
                  />
                  <v-text-field
                    v-if="runtimeSpec.type === 'container'"
                    v-model="runtimeSpec.image"
                    label="Image (optional)"
                    variant="outlined"
                    density="comfortable"
                    class="mb-3"
                  />
                  <v-text-field
                    v-model="requirementsInput"
                    label="Requirements (comma separated)"
                    variant="outlined"
                    density="comfortable"
                    class="mb-3"
                  />
                  <div class="d-flex mb-3" style="gap: 12px;">
                    <v-text-field
                      v-model.number="runtimeSpec.idle_ttl_seconds"
                      label="Idle TTL (seconds)"
                      type="number"
                      variant="outlined"
                      density="comfortable"
                    />
                    <v-text-field
                      v-model.number="runtimeSpec.max_invocations"
                      label="Max invocations (0 = unlimited)"
                      type="number"
                      variant="outlined"
                      density="comfortable"
                    />
                  </div>
                  <div class="d-flex mb-3" style="gap: 12px;">
                    <v-text-field
                      v-model.number="runtimeSpec.max_concurrency"
                      label="Max concurrency (parallel workers)"
                      type="number"
                      min="1"
                      variant="outlined"
                      density="comfortable"
                    />
                    <v-text-field
                      v-model.number="runtimeSpec.max_duration_seconds"
                      label="Max job duration, seconds (0 = unlimited)"
                      type="number"
                      variant="outlined"
                      density="comfortable"
                    />
                  </div>
                  <v-text-field
                    v-model="envVarsInput"
                    label="Env vars (KEY=value, comma separated)"
                    variant="outlined"
                    density="comfortable"
                    class="mb-3"
                  />
                  <div v-if="runtimeSpec.type === 'container'" class="d-flex" style="gap: 12px;">
                    <v-text-field
                      v-model.number="memoryLimitMb"
                      label="Memory limit (MB)"
                      type="number"
                      variant="outlined"
                      density="comfortable"
                    />
                    <v-text-field
                      v-model.number="cpuLimitCores"
                      label="CPU limit (cores)"
                      type="number"
                      step="0.1"
                      variant="outlined"
                      density="comfortable"
                    />
                  </div>
                </v-expansion-panel-text>
              </v-expansion-panel>
              <v-expansion-panel>
                <v-expansion-panel-title>
                  Parameters
                </v-expansion-panel-title>
                <v-expansion-panel-text>
                  <p v-if="paramsSchema.length === 0" class="text-body-2 text-medium-emphasis mb-3">
                    No parameters declared -- this function accepts an arbitrary, unvalidated params blob.
                  </p>
                  <div
                    v-for="(param, i) in paramsSchema"
                    :key="i"
                    class="d-flex align-center mb-3"
                    style="gap: 8px;"
                  >
                    <v-text-field
                      v-model="param.name"
                      label="Name"
                      variant="outlined"
                      density="comfortable"
                      hide-details
                    />
                    <v-select
                      v-model="param.type"
                      :items="['string', 'number', 'boolean', 'json', 'data_ref']"
                      label="Type"
                      variant="outlined"
                      density="comfortable"
                      hide-details
                      style="max-width: 160px;"
                    />
                    <v-checkbox
                      v-model="param.required"
                      label="Required"
                      density="comfortable"
                      hide-details
                      style="flex: none;"
                    />
                    <v-text-field
                      v-if="!param.required"
                      v-model="param.default"
                      label="Default"
                      variant="outlined"
                      density="comfortable"
                      hide-details
                    />
                    <v-btn icon="mdi-close" variant="text" size="small" @click="paramsSchema.splice(i, 1)" />
                  </div>
                  <v-btn variant="tonal" prepend-icon="mdi-plus" size="small" @click="addParamRow">
                    Add parameter
                  </v-btn>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>

            <v-alert v-if="registerError" type="error" variant="tonal" density="compact" class="mb-4">
              {{ registerError }}
            </v-alert>

            <div class="d-flex justify-end" style="gap: 8px;">
              <v-btn variant="text" @click="showRegisterDialog = false">
                Cancel
              </v-btn>
              <v-btn color="secondary" type="submit" :loading="store.loading">
                Register
              </v-btn>
            </div>
          </v-form>
        </v-card-text>
      </v-card>
    </v-dialog>

    <!-- Delete confirm dialog -->
    <v-dialog v-model="showDeleteDialog" max-width="480">
      <v-card class="pa-6">
        <h3 class="text-h6 mb-4">
          Delete "{{ pendingDelete?.function_id }}" v{{ pendingDelete?.version }}?
        </h3>
        <p class="text-body-2 mb-4">
          This cannot be undone.
        </p>
        <v-alert v-if="deleteError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ deleteError }}
        </v-alert>
        <div class="d-flex justify-end" style="gap: 8px;">
          <v-btn variant="text" @click="showDeleteDialog = false">
            Cancel
          </v-btn>
          <v-btn color="error" :loading="store.loading" @click="onDelete">
            Delete
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'
import type { FunctionRecord, ParamSpec, RuntimeSpec } from '~/types/functionRecord'

const store = useFunctionsStore()
const virtualEnvironmentsStore = useVirtualEnvironmentsStore()

const { preference } = useThemeSetting()
const isDarkTheme = computed(() => preference.value === 'axoDark')

const codeHint = computed(() =>
  `Must define a top-level function named exactly '${form.name || '<name>'}' with signature (params, ctx) -- only statically checked here, actually run on the target endpoint node.`,
)

onMounted(() => {
  store.fetchAll()
  virtualEnvironmentsStore.fetchAll()
  store.connectFleetSocket()
})

onBeforeUnmount(() => {
  store.disconnectFleetSocket()
})

const search = ref('')
const filteredItems = computed(() => {
  if (!search.value.trim()) return store.items
  const q = search.value.toLowerCase()
  return store.items.filter(f =>
    f.function_id.toLowerCase().includes(q) || (f.name ?? '').toLowerCase().includes(q),
  )
})

const headers = [
  { title: 'Function', key: 'function_id' },
  { title: 'Version', key: 'version' },
  { title: 'Runtime', key: 'runtime_type' },
  { title: 'State', key: 'state' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const showRegisterDialog = ref(false)
const registerError = ref<string | null>(null)
const codeFile = ref<File | null>(null)
const codeInputMode = ref<'upload' | 'write'>('upload')
const codeText = ref('')
const requirementsInput = ref('')
const envVarsInput = ref('')
const memoryLimitMb = ref(1024)
const cpuLimitCores = ref(1)

const form = reactive({
  virtual_environment_id: null as string | null,
  name: '',
})

const runtimeSpec = reactive<RuntimeSpec>({
  type: 'process',
  python_version: '3.11',
  requirements: [],
  image: null,
  env_vars: {},
  idle_ttl_seconds: 300,
  max_invocations: 0,
  max_concurrency: 1,
  max_duration_seconds: 0,
})

const paramsSchema = ref<ParamSpec[]>([])

function addParamRow() {
  paramsSchema.value.push({ name: '', type: 'string', required: true, default: undefined })
}

function openRegisterDialog() {
  registerError.value = null
  codeFile.value = null
  codeInputMode.value = 'upload'
  codeText.value = ''
  requirementsInput.value = ''
  envVarsInput.value = ''
  form.virtual_environment_id = null
  form.name = ''
  runtimeSpec.type = 'process'
  runtimeSpec.python_version = '3.11'
  runtimeSpec.image = null
  runtimeSpec.idle_ttl_seconds = 300
  runtimeSpec.max_invocations = 0
  runtimeSpec.max_concurrency = 1
  runtimeSpec.max_duration_seconds = 0
  memoryLimitMb.value = 1024
  cpuLimitCores.value = 1
  paramsSchema.value = []
  showRegisterDialog.value = true
}

function parseEnvVars(input: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const pair of input.split(',')) {
    const [key, ...rest] = pair.split('=')
    const trimmedKey = key?.trim()
    if (trimmedKey) result[trimmedKey] = rest.join('=').trim()
  }
  return result
}

async function onRegister() {
  registerError.value = null
  if (!form.virtual_environment_id) {
    registerError.value = 'Select a virtual environment to register into'
    return
  }
  let codeToSend: File
  if (codeInputMode.value === 'upload') {
    if (!codeFile.value) {
      registerError.value = 'A code file is required'
      return
    }
    codeToSend = codeFile.value
  } else {
    if (!codeText.value.trim()) {
      registerError.value = 'Code is required'
      return
    }
    codeToSend = new File([codeText.value], 'function.py', { type: 'text/x-python' })
  }

  try {
    await store.register(
      {
        name: form.name,
        virtual_environment_id: form.virtual_environment_id,
        runtime_spec: {
          ...runtimeSpec,
          requirements: requirementsInput.value.split(',').map(r => r.trim()).filter(Boolean),
          env_vars: parseEnvVars(envVarsInput.value),
          memory_limit_bytes: runtimeSpec.type === 'container' ? Math.round(memoryLimitMb.value * 1024 * 1024) : null,
          cpu_limit: runtimeSpec.type === 'container' ? cpuLimitCores.value : null,
        },
        params_schema: paramsSchema.value.filter(p => p.name.trim() !== ''),
      },
      codeToSend,
    )
    showRegisterDialog.value = false
  } catch (err: any) {
    registerError.value = err.message
  }
}

const showDeleteDialog = ref(false)
const deleteError = ref<string | null>(null)
const pendingDelete = ref<FunctionRecord | null>(null)

function confirmDelete(item: FunctionRecord) {
  pendingDelete.value = item
  deleteError.value = null
  showDeleteDialog.value = true
}

async function onDelete() {
  if (!pendingDelete.value) return
  try {
    await store.remove(pendingDelete.value.function_id, pendingDelete.value.version)
    showDeleteDialog.value = false
    pendingDelete.value = null
  } catch (err: any) {
    deleteError.value = err.message
  }
}
</script>

<style scoped>
.stat-card {
  border-radius: 16px;
}

.search-field--dark :deep(.v-field__input) {
  color: #fff;
}

.search-field--dark :deep(input::placeholder) {
  color: rgba(255, 255, 255, 0.6);
  opacity: 1;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot--active {
  background-color: #22c55e;
}

.function-id-text {
  font-family: monospace;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
