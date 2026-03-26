/**
 * chat-session.ts — M15
 *
 * Lightweight sessionStorage persistence for the chat thread.
 * Handles: save, load, clear. All operations are defensive with silent
 * fallback so a storage failure never breaks the chat.
 */
import type { ChatMessage } from './types'

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'assistantos.chat.session.v1'
const SCHEMA_VERSION = 1

/** Serialisable subset of ChatMessage — strips ephemeral/non-serialisable fields. */
interface PersistedMessage {
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
}

export interface ChatSessionSnapshot {
  version: number
  contextId: string | undefined
  messages: PersistedMessage[]
  savedAt: string
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function toPersistedMessage(m: ChatMessage): PersistedMessage | null {
  // Drop loading placeholders — they are ephemeral by definition
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
  }
}

function isValidSnapshot(raw: unknown): raw is ChatSessionSnapshot {
  if (!raw || typeof raw !== 'object') return false
  const s = raw as Record<string, unknown>
  return (
    s.version === SCHEMA_VERSION &&
    typeof s.savedAt === 'string' &&
    Array.isArray(s.messages)
  )
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Load the persisted chat snapshot.
 * Returns null if storage is unavailable, empty, or the snapshot is invalid.
 */
export function loadChatSession(): ChatSessionSnapshot | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isValidSnapshot(parsed)) return null
    return parsed
  } catch {
    return null
  }
}

/**
 * Persist the current chat state.
 * Filters out loading messages. Silent on storage failure.
 */
export function saveChatSession(
  contextId: string | undefined,
  messages: ChatMessage[],
): void {
  try {
    const persisted = messages
      .map(toPersistedMessage)
      .filter((m): m is PersistedMessage => m !== null)

    const snapshot: ChatSessionSnapshot = {
      version:   SCHEMA_VERSION,
      contextId,
      messages:  persisted,
      savedAt:   new Date().toISOString(),
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
  } catch {
    // sessionStorage unavailable or quota exceeded — silent fallback
  }
}

/**
 * Remove the persisted snapshot. Call on explicit user clear.
 */
export function clearChatSession(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // silent
  }
}
