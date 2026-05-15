import { describe, it, expect } from 'vitest'
import { COGNITIVE_ENTITY_REGISTRY, getEntity, hasCapability } from '../entity-registry'

describe('CognitiveEntityRegistry', () => {
  it('has all required entities', () => {
    const ids = COGNITIVE_ENTITY_REGISTRY.map((e) => e.id)
    expect(ids).toContain('main_chat')
    expect(ids).toContain('mso_console')
    expect(ids).toContain('mission_control')
    expect(ids).toContain('confirm_queue')
    expect(ids).toContain('prepared_actions')
    expect(ids).toContain('authority_matrix')
    expect(ids).toContain('agent_registry')
  })

  it('every entity has required fields', () => {
    for (const entity of COGNITIVE_ENTITY_REGISTRY) {
      expect(entity.id).toBeTruthy()
      expect(entity.label).toBeTruthy()
      expect(entity.cognitive_actor).toBeTruthy()
      expect(Array.isArray(entity.capabilities)).toBe(true)
      expect(Array.isArray(entity.boundaries)).toBe(true)
      expect(entity.execution_policy).toBeTruthy()
    }
  })

  it('no cognitive_only entity claims execute_action capability', () => {
    for (const entity of COGNITIVE_ENTITY_REGISTRY) {
      if (entity.execution_policy === 'cognitive_only') {
        expect(entity.capabilities).not.toContain('execute_action')
      }
    }
  })

  it('no read_only or display_only entity claims execute_action or confirm_action', () => {
    for (const entity of COGNITIVE_ENTITY_REGISTRY) {
      if (entity.execution_policy === 'read_only' || entity.execution_policy === 'display_only') {
        expect(entity.capabilities).not.toContain('execute_action')
        expect(entity.capabilities).not.toContain('confirm_action')
      }
    }
  })

  it('mso_console requires provenance and raw trace', () => {
    const e = getEntity('mso_console')
    expect(e?.provenance_required).toBe(true)
    expect(e?.raw_trace_required).toBe(true)
  })

  it('mso_console has no_direct_execution boundary', () => {
    const e = getEntity('mso_console')
    expect(e?.boundaries).toContain('no_direct_execution')
  })

  it('main_chat has governed_execution policy', () => {
    const e = getEntity('main_chat')
    expect(e?.execution_policy).toBe('governed_execution')
  })

  it('getEntity returns undefined for unknown id', () => {
    expect(getEntity('nonexistent')).toBeUndefined()
  })

  it('hasCapability works correctly', () => {
    const mso = getEntity('mso_console')!
    expect(hasCapability(mso, 'converse')).toBe(true)
    expect(hasCapability(mso, 'execute_action')).toBe(false)
  })

  it('all entities with provenance_required have a backend_endpoint or are mso_raw_trace', () => {
    for (const entity of COGNITIVE_ENTITY_REGISTRY) {
      if (entity.provenance_required && entity.id !== 'mso_raw_trace') {
        expect(entity.backend_endpoint).not.toBeNull()
      }
    }
  })
})
