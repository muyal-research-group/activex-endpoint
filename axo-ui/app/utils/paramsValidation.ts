import type { ParamSpec } from '~/types/functionRecord'

export interface ParamValidationError {
  field: string
  message: string
}

export type ParamValidationResult =
  | { ok: true, values: Record<string, unknown> }
  | { ok: false, errors: ParamValidationError[] }

function typeMatches(value: unknown, type: ParamSpec['type']): boolean {
  if (type === 'string') return typeof value === 'string'
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value)
  if (type === 'boolean') return typeof value === 'boolean'
  if (type === 'json') return true
  if (type === 'data_ref') {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
      && typeof (value as any).kind === 'string' && typeof (value as any).location === 'string'
  }
  return false
}

// Mirrors axo_endpoint/core/functions/params_validation.py::validate_and_fill_params.
// Fail-fast UX only -- the server re-validates unconditionally.
export function validateAndFillParams(
  schema: ParamSpec[],
  params: Record<string, unknown>,
): ParamValidationResult {
  if (schema.length === 0) return { ok: true, values: params }

  const declaredNames = new Set(schema.map(spec => spec.name))
  const unknown = Object.keys(params).filter(key => !declaredNames.has(key))
  if (unknown.length > 0) {
    return {
      ok: false,
      errors: unknown.map(field => ({ field, message: 'unknown param, not declared in params_schema' })),
    }
  }

  const errors: ParamValidationError[] = []
  const values: Record<string, unknown> = {}

  for (const spec of schema) {
    if (!(spec.name in params)) {
      const hasDefault = spec.default !== null && spec.default !== undefined
      if (spec.required && !hasDefault) {
        errors.push({ field: spec.name, message: `missing required param '${spec.name}'` })
        continue
      }
      values[spec.name] = spec.default ?? null
      continue
    }
    const value = params[spec.name]
    if (!typeMatches(value, spec.type)) {
      errors.push({ field: spec.name, message: `does not match declared type '${spec.type}'` })
      continue
    }
    values[spec.name] = value
  }

  return errors.length > 0 ? { ok: false, errors } : { ok: true, values }
}
