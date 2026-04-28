/**
 * chat-sessions.ts — M16
 *
 * Multi-session model and localStorage persistence.
 * All storage operations are defensive with silent fallback.
 */
import type { ChatMessage } from './types'

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const STORAGE_KEY    = 'assistantos.chat.sessions.v1'
const SCHEMA_VERSION = 1
/** Key used by M15 — read once for migration then removed. */
export const M15_KEY = 'assistantos.chat.session.v1'

/** Serialisable subset of ChatMessage — drops ephemeral/runtime fields. */
export interface PersistedChatMessage {
  id: string
  role: ChatMessage['role']
  content: string
  status: 'sent' | 'error'
  createdAt: string
  uiActions?: ChatMessage['uiActions']
  plan?: ChatMessage['plan']
  meta?: ChatMessage['meta']
  kind?: ChatMessage['kind']
  handled?: boolean
  executionStatus?: ChatMessage['executionStatus']
  executionStatusSource?: ChatMessage['executionStatusSource']
}

export interface ChatSession {
  id: string
  title: string
  contextId: string | null
  messages: PersistedChatMessage[]
  createdAt: string
  updatedAt: string
}

export interface SessionsState {
  sessions: ChatSession[]
  activeSessionId: string | null
}

interface SessionsStorage {
  version: number
  sessions: ChatSession[]
  activeSessionId: string | null
  savedAt: string
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function newId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

export function createFreshSession(): ChatSession {
  const now = new Date().toISOString()
  return {
    id:        newId('sess'),
    title:     'Nuevo chat',
    contextId: null,
    messages:  [],
    createdAt: now,
    updatedAt: now,
  }
}

/** Convert a live ChatMessage to its persistable form. Returns null for loading placeholders. */
export function toPersistedMsg(m: ChatMessage): PersistedChatMessage | null {
  if (m.status === 'loading') return null
  return {
    id:        m.id,
    role:      m.role,
    content:   m.content,
    status:    m.status === 'error' ? 'error' : 'sent',
    createdAt: m.createdAt,
    uiActions: m.uiActions,
    plan:      m.plan,
    meta:      m.meta,
    kind:      m.kind,
    handled:   m.handled,
    executionStatus: m.executionStatus,
    executionStatusSource: m.executionStatusSource,
  }
}

function isValidStorage(raw: unknown): raw is SessionsStorage {
  if (!raw || typeof raw !== 'object') return false
  const s = raw as Record<string, unknown>
  return s.version === SCHEMA_VERSION && Array.isArray(s.sessions)
}

// ---------------------------------------------------------------------------
// localStorage I/O
// ---------------------------------------------------------------------------

export function loadSessionsState(): SessionsState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isValidStorage(parsed)) return null
    return { sessions: parsed.sessions, activeSessionId: parsed.activeSessionId }
  } catch {
    return null
  }
}

export function saveSessionsState(state: SessionsState): void {
  try {
    const storage: SessionsStorage = {
      version:         SCHEMA_VERSION,
      sessions:        state.sessions,
      activeSessionId: state.activeSessionId,
      savedAt:         new Date().toISOString(),
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storage))
  } catch {
    // Quota exceeded or storage unavailable — silent fallback
  }
}

// ---------------------------------------------------------------------------
// M15 → M16 migration
// ---------------------------------------------------------------------------

/**
 * If an M15 sessionStorage snapshot exists, convert it to a ChatSession,
 * remove the old key, and return the session for inclusion in the store.
 * Returns null if no M15 data is found or migration fails.
 */
export function migrateFromM15(): ChatSession | null {
  try {
    const raw = sessionStorage.getItem(M15_KEY)
    if (!raw) return null

    type M15Snap = { version?: number; contextId?: string; messages?: unknown[] }
    const snap = JSON.parse(raw) as M15Snap

    if (!Array.isArray(snap.messages) || snap.messages.length === 0) {
      sessionStorage.removeItem(M15_KEY)
      return null
    }

    const session     = createFreshSession()
    const firstMsg    = snap.messages[0] as { content?: string }
    session.title     = (firstMsg?.content ?? 'Chat importado').slice(0, 40)
    session.contextId = snap.contextId ?? null
    session.messages  = snap.messages as PersistedChatMessage[]
    sessionStorage.removeItem(M15_KEY)
    return session
  } catch {
    return null
  }
}
