<template>
  <v-container fluid class="pa-6">
    <NuxtLink :to="`/functions/${functionId}`" class="text-body-2 mb-4 d-inline-block">
      &larr; {{ functionId }}
    </NuxtLink>

    <v-card class="pa-6 mb-6">
      <h2 class="text-h6 mb-1">
        Run {{ functionId }} v{{ version }}
      </h2>
      <p v-if="jobId" class="text-body-2 text-medium-emphasis">
        Job {{ jobId }}
      </p>
    </v-card>

    <!-- Function info -->
    <v-card v-if="!jobId" class="pa-6 mb-6">
      <h3 class="text-h6 mb-4">
        Function info
      </h3>
      <v-table density="comfortable">
        <tbody>
          <tr>
            <td class="text-medium-emphasis">Name</td>
            <td>{{ versionRecord?.name ?? '—' }}</td>
          </tr>
          <tr>
            <td class="text-medium-emphasis">Function ID</td>
            <td class="function-id-cell">{{ functionId }}</td>
          </tr>
          <tr>
            <td class="text-medium-emphasis">Version</td>
            <td>{{ version }}</td>
          </tr>
          <tr>
            <td class="text-medium-emphasis">Runtime</td>
            <td>{{ versionRecord?.runtime_spec?.type ?? 'process' }}</td>
          </tr>
          <tr>
            <td class="text-medium-emphasis">State</td>
            <td>{{ versionRecord?.state ?? '—' }}</td>
          </tr>
          <tr>
            <td class="text-medium-emphasis">Parameters</td>
            <td>
              <span v-if="paramsSchema.length === 0" class="text-medium-emphasis">—</span>
              <v-chip
                v-for="param in paramsSchema"
                :key="param.name"
                size="small"
                variant="tonal"
                :color="param.required ? 'secondary' : undefined"
                class="mr-1 mb-1"
              >
                {{ param.name }}: {{ param.type }}{{ param.required ? ' *' : '' }}
              </v-chip>
            </td>
          </tr>
        </tbody>
      </v-table>
    </v-card>

    <!-- Fresh-run form -->
    <v-card v-if="!jobId" class="pa-6 mb-6">
      <v-btn-toggle
        :model-value="paramsInputMode"
        mandatory
        color="secondary"
        rounded="lg"
        variant="outlined"
        density="comfortable"
        class="mb-4"
        @update:model-value="onToggleParamsMode"
      >
        <v-btn value="form">Form</v-btn>
        <v-btn value="json">JSON</v-btn>
      </v-btn-toggle>

      <p v-if="paramsSchema.length === 0 && paramsInputMode === 'form'" class="text-body-2 text-medium-emphasis mb-4">
        This function accepts an arbitrary params blob -- no schema declared.
      </p>

      <template v-if="paramsInputMode === 'form'">
        <div v-for="spec in nonDataRefSchema" :key="spec.name" class="mb-4">
          <v-text-field
            v-if="spec.type === 'string'"
            v-model="paramValues[spec.name]"
            :label="spec.name"
            :hint="spec.required ? 'Required' : `Optional, default: ${spec.default ?? '—'}`"
            persistent-hint
            variant="outlined"
            density="comfortable"
          />
          <v-text-field
            v-else-if="spec.type === 'number'"
            v-model="paramValues[spec.name]"
            :label="spec.name"
            type="number"
            :hint="spec.required ? 'Required' : `Optional, default: ${spec.default ?? '—'}`"
            persistent-hint
            variant="outlined"
            density="comfortable"
          />
          <v-switch
            v-else-if="spec.type === 'boolean'"
            v-model="paramValues[spec.name]"
            :label="spec.name"
            density="comfortable"
            hide-details
          />
          <v-textarea
            v-else-if="spec.type === 'json'"
            v-model="paramValues[spec.name]"
            :label="`${spec.name} (JSON)`"
            :hint="spec.required ? 'Required' : 'Optional'"
            persistent-hint
            variant="outlined"
            density="comfortable"
            rows="3"
          />
        </div>
      </template>
      <v-textarea
        v-else
        v-model="jsonParamsText"
        label="Params (JSON)"
        hint="A single JSON object with one key per parameter (excluding data references, set below)"
        persistent-hint
        variant="outlined"
        density="comfortable"
        rows="10"
        class="mb-4"
      />

      <div v-for="spec in dataRefSchema" :key="spec.name" class="mb-4">
        <div class="text-body-2 mb-1">
          {{ spec.name }} <span class="text-medium-emphasis">(data reference{{ spec.required ? '' : ', optional' }})</span>
        </div>
        <div class="d-flex" style="gap: 8px;">
          <v-select
            :model-value="dataRefBucketSelection[spec.name]"
            :items="bucketsStore.items"
            item-title="name"
            item-value="name"
            label="Bucket"
            variant="outlined"
            density="comfortable"
            hide-details
            @update:model-value="v => onSelectDataRefBucket(spec.name, v)"
          />
          <v-select
            :model-value="dataRefItemSelection[spec.name]"
            :items="dataRefItemOptions(spec.name)"
            label="Data item"
            variant="outlined"
            density="comfortable"
            hide-details
            :disabled="!dataRefBucketSelection[spec.name]"
            @update:model-value="v => onSelectDataRefItem(spec.name, v)"
          />
        </div>
      </div>

      <v-alert v-if="validationErrors.length > 0" type="error" variant="tonal" density="compact" class="mb-4">
        <div v-for="e in validationErrors" :key="e.field">{{ e.field }}: {{ e.message }}</div>
      </v-alert>
      <v-alert v-if="jsonParseError" type="error" variant="tonal" density="compact" class="mb-4">
        {{ jsonParseError }}
      </v-alert>

      <v-btn color="secondary" :loading="submitting" @click="onSubmit">
        Run
      </v-btn>
    </v-card>

    <!-- Status / result view -->
    <v-card v-else class="pa-6">
      <div class="d-flex align-center mb-4" style="gap: 8px;">
        <v-chip
          v-for="stage in stages"
          :key="stage"
          :color="stageColor(stage)"
          :variant="currentStatus === stage ? 'elevated' : 'tonal'"
          size="small"
        >
          {{ stage }}
        </v-chip>
      </div>

      <v-alert v-if="pollError" type="error" variant="tonal" density="compact" class="mb-4">
        Lost contact with the endpoint while polling this job -- it may have restarted since. {{ pollError }}
      </v-alert>

      <template v-else-if="isTerminal">
        <div class="text-caption text-medium-emphasis mb-1">
          {{ result?.status === 'COMPLETED' ? 'Result' : 'Error' }}
        </div>
        <pre class="pa-3 rounded bg-surface-variant meta-block mb-4">{{ prettyResult }}</pre>
        <v-btn variant="tonal" prepend-icon="mdi-download" @click="downloadResult">
          Download as JSON
        </v-btn>
      </template>

      <div v-else class="d-flex align-center" style="gap: 8px;">
        <v-progress-circular indeterminate size="20" width="2" />
        <span class="text-body-2 text-medium-emphasis">Waiting for the job to finish…</span>
      </div>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import type { ParamSpec } from '~/types/functionRecord'
import { validateAndFillParams, type ParamValidationError } from '~/utils/paramsValidation'

// Same route file is reused across /run/1 -> /run/2 (and across different
// ?job= entries) since it's the same page component -- force a remount on
// every navigation so functionId/version/all local state below stays in
// sync with the URL instead of holding onto the previously loaded version.
definePageMeta({
  key: to => to.fullPath,
})

const route = useRoute()
const functionsStore = useFunctionsStore()
const bucketsStore = useBucketsStore()
const jobsStore = useJobsStore()
const snackbar = useSnackbar()

const functionId = computed(() => route.params.id as string)
const version = computed(() => Number(route.params.version))

const jobId = ref<string | null>((route.query.job as string) || null)
const endpointId = ref<string | null>((route.query.endpoint as string) || null)

onMounted(async () => {
  await functionsStore.fetchOne(functionId.value)
  bucketsStore.fetchAll()
  if (jobId.value && endpointId.value) startPolling()
})

const versionRecord = computed(() => functionsStore.versions.find(v => v.version === version.value) ?? null)
const paramsSchema = computed<ParamSpec[]>(() => versionRecord.value?.params_schema ?? [])
// data_ref values are opaque {kind, location, format} triples resolved from
// live bucket/item picker state -- they keep their own pickers regardless of
// Form/JSON mode rather than being hand-typed into the JSON blob.
const nonDataRefSchema = computed(() => paramsSchema.value.filter(spec => spec.type !== 'data_ref'))
const dataRefSchema = computed(() => paramsSchema.value.filter(spec => spec.type === 'data_ref'))

const paramValues = reactive<Record<string, any>>({})
const resolvedDataRefs = reactive<Record<string, { kind: string, location: string, format: string } | null>>({})
const dataRefBucketSelection = reactive<Record<string, string | null>>({})
const dataRefItemSelection = reactive<Record<string, string | null>>({})

const paramsInputMode = ref<'form' | 'json'>('form')
const jsonParamsText = ref('')
const validationErrors = ref<ParamValidationError[]>([])

watch(paramsSchema, (schema) => {
  for (const spec of schema) {
    if (!(spec.name in paramValues)) {
      paramValues[spec.name] = spec.type === 'boolean' ? Boolean(spec.default) : (spec.default ?? '')
    }
  }
  // A schema-less function has nothing to render in Form mode ("arbitrary
  // params blob" case below) -- JSON mode is the only way to submit
  // anything for it, so default there.
  paramsInputMode.value = schema.length === 0 ? 'json' : 'form'
}, { immediate: true })

function dataRefItemOptions(paramName: string) {
  const bucketName = dataRefBucketSelection[paramName]
  if (!bucketName || bucketsStore.current?.name !== bucketName) return []
  return bucketsStore.current.items.map(item => ({
    title: `${item.name} v${item.version}`,
    value: `${item.name}:${item.version}`,
  }))
}

async function onSelectDataRefBucket(paramName: string, bucketName: string | null) {
  dataRefBucketSelection[paramName] = bucketName
  dataRefItemSelection[paramName] = null
  resolvedDataRefs[paramName] = null
  if (bucketName) await bucketsStore.fetchOne(bucketName)
}

function onSelectDataRefItem(paramName: string, itemKey: string | null) {
  dataRefItemSelection[paramName] = itemKey
  if (!itemKey || !bucketsStore.current) {
    resolvedDataRefs[paramName] = null
    return
  }
  const item = bucketsStore.current.items.find(i => `${i.name}:${i.version}` === itemKey)
  resolvedDataRefs[paramName] = item ? { kind: item.kind, location: item.name, format: item.format } : null
}

function buildFormParams(): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  for (const spec of nonDataRefSchema.value) {
    const raw = paramValues[spec.name]
    if (spec.type === 'boolean') {
      params[spec.name] = !!raw
      continue
    }
    if (raw === '' || raw === null || raw === undefined) continue
    if (spec.type === 'json') {
      params[spec.name] = JSON.parse(raw)
    } else if (spec.type === 'number') {
      params[spec.name] = Number(raw)
    } else {
      params[spec.name] = raw
    }
  }
  for (const spec of dataRefSchema.value) {
    if (resolvedDataRefs[spec.name]) params[spec.name] = resolvedDataRefs[spec.name]
  }
  return params
}

// Switching into JSON mode must never fail -- a field currently holding
// invalid embedded JSON text is carried through as a plain string rather
// than throwing, so the switch itself always succeeds.
function nonDataRefFormValuesAsObject(): Record<string, unknown> {
  const obj: Record<string, unknown> = {}
  for (const spec of nonDataRefSchema.value) {
    const raw = paramValues[spec.name]
    if (spec.type === 'boolean') {
      obj[spec.name] = !!raw
      continue
    }
    if (raw === '' || raw === null || raw === undefined) continue
    if (spec.type === 'number') {
      obj[spec.name] = Number(raw)
      continue
    }
    if (spec.type === 'json') {
      try {
        obj[spec.name] = JSON.parse(raw)
      } catch {
        obj[spec.name] = raw
      }
      continue
    }
    obj[spec.name] = raw
  }
  return obj
}

function buildJsonModeParams(): Record<string, unknown> {
  const text = jsonParamsText.value.trim()
  const parsed: unknown = text === '' ? {} : JSON.parse(text)
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('params JSON must be an object')
  }
  const params: Record<string, unknown> = { ...(parsed as Record<string, unknown>) }
  for (const spec of dataRefSchema.value) {
    if (resolvedDataRefs[spec.name]) params[spec.name] = resolvedDataRefs[spec.name]
  }
  return params
}

// Form -> JSON never blocks. JSON -> Form blocks if the current JSON text is
// invalid, so the toggle is a controlled (:model-value/@update:model-value)
// component rather than plain v-model.
//
// Keys in the JSON text that aren't declared non-data_ref schema fields are
// dropped silently when switching to Form mode (Form mode is inherently
// constrained to declared fields); submitting directly from JSON mode
// without switching instead surfaces those same stray keys via
// validateAndFillParams's unknown-key rejection.
function onToggleParamsMode(newMode: 'form' | 'json' | null) {
  if (!newMode || newMode === paramsInputMode.value) return

  if (newMode === 'json') {
    jsonParamsText.value = JSON.stringify(nonDataRefFormValuesAsObject(), null, 2)
    jsonParseError.value = null
    paramsInputMode.value = 'json'
    return
  }

  let parsed: unknown
  try {
    const text = jsonParamsText.value.trim()
    parsed = text === '' ? {} : JSON.parse(text)
  } catch (err: any) {
    jsonParseError.value = `Cannot switch to Form mode -- invalid JSON: ${err.message}`
    return
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    jsonParseError.value = 'Cannot switch to Form mode -- params JSON must be an object'
    return
  }

  const obj = parsed as Record<string, unknown>
  for (const spec of nonDataRefSchema.value) {
    const value = obj[spec.name]
    if (spec.type === 'boolean') {
      paramValues[spec.name] = !!value
      continue
    }
    if (value === undefined) {
      paramValues[spec.name] = ''
      continue
    }
    paramValues[spec.name] = spec.type === 'json' ? JSON.stringify(value, null, 2) : value
  }
  jsonParseError.value = null
  paramsInputMode.value = 'form'
}

const submitting = ref(false)
const jsonParseError = ref<string | null>(null)
const pollError = ref<string | null>(null)
let pollTimer: ReturnType<typeof setInterval> | undefined
let pollFailureCount = 0
const MAX_CONSECUTIVE_POLL_FAILURES = 5

async function onSubmit() {
  jsonParseError.value = null
  validationErrors.value = []
  let rawParams: Record<string, unknown>
  try {
    rawParams = paramsInputMode.value === 'json' ? buildJsonModeParams() : buildFormParams()
  } catch (err: any) {
    jsonParseError.value = `Invalid JSON in params: ${err.message}`
    return
  }

  const validation = validateAndFillParams(paramsSchema.value, rawParams)
  if (!validation.ok) {
    validationErrors.value = validation.errors
    return
  }

  submitting.value = true
  try {
    // Endpoint routing is resolved entirely server-side (the function's own
    // VE, preferring its currently-elected leader) -- this page never picks
    // one. A fresh submit doesn't transition into the polling/status view
    // below; it just toasts and leaves the form in place for another run.
    // Track a submitted job via the function detail page's Jobs table
    // instead (which links back here with ?job=&endpoint= to view status).
    const submitted = await jobsStore.submitForFunction(functionId.value, version.value, validation.values)
    snackbar.notify(`Job queued: ${submitted.job_id}`, 'success')
  } catch (err: any) {
    snackbar.notify(err.message, 'error')
  } finally {
    submitting.value = false
  }
}

// 'QUEUED' is a client-side placeholder for the gap before the first poll
// response arrives (jobsStore.current is null until then) -- the backend's
// real, only-ever-emitted statuses are QUEUED (JOB_SUBMIT's own response,
// never re-read from a poll), PENDING (JOB_RESULT while not yet finished),
// and COMPLETED/FAILED (terminal). There is no "STARTED" status.
const stages = ['QUEUED', 'PENDING', 'COMPLETED']
const currentStatus = computed(() => jobsStore.current?.status ?? 'QUEUED')
const result = computed(() => jobsStore.current)
const isTerminal = computed(() => result.value?.status === 'COMPLETED' || result.value?.status === 'FAILED')
const prettyResult = computed(() => (result.value ? JSON.stringify(result.value, null, 2) : ''))

function stageColor(stage: string) {
  if (result.value?.status === 'FAILED' && stage === 'COMPLETED') return 'error'
  return currentStatus.value === stage || (isTerminal.value && stage === 'COMPLETED') ? 'secondary' : 'default'
}

function startPolling() {
  if (!jobId.value || !endpointId.value) return
  pollError.value = null
  pollFailureCount = 0
  stopPolling()
  poll()
  pollTimer = setInterval(poll, 800)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

async function poll() {
  if (!jobId.value || !endpointId.value) return
  try {
    const polled = await jobsStore.poll(endpointId.value, jobId.value)
    pollFailureCount = 0
    pollError.value = null
    if (polled.status === 'COMPLETED' || polled.status === 'FAILED') stopPolling()
  } catch (err: any) {
    // Tolerate transient failures (a network blip, a momentary backend
    // hiccup) -- only give up polling after several in a row, so one bad
    // request doesn't permanently strand the UI on a stale status.
    pollFailureCount += 1
    if (pollFailureCount >= MAX_CONSECUTIVE_POLL_FAILURES) {
      pollError.value = err.message
      stopPolling()
    }
  }
}

onUnmounted(stopPolling)

function downloadResult() {
  if (!result.value) return
  const blob = new Blob([JSON.stringify(result.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${functionId.value}-v${version.value}-${jobId.value}.json`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.function-id-cell {
  font-family: monospace;
  word-break: break-all;
}

.meta-block {
  color: rgb(var(--v-theme-on-surface));
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}
</style>
