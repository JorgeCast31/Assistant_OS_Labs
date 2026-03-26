'use client'

/**
 * chat-sessions-store.ts — M18
 *
 * Backend-first Zustand store for chat sessions.
 * Backend is the authoritative source of truth.
 * Local state is a UI cache only.
 *
 * Shape:
 *   sessions        — flat list of session summaries (no messages)
 *   sessionDetails  — map of id → full ChatSession with messages (loaded on demand)
 *   activeSessionId — which session is visible in the chat panel
 */
import { create } from 'zustand'
import type { ChatSession, PersistedChatMessage } from '@/lib/chat-sessions'
import {
  apiListSessions,
  apiCreateSession,
  apiGetSession,
  apiUpdateSession,
  apiDeleteSession,
} from '@/lib/api'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Persist the last-active session id across page reloads (UX only). */
const ACTIVE_KEY = 'assistantos.chat.activeSessionId'

function loadSavedActiveId(): string | null {
  try { return localStorage.getItem(ACTIVE_KEY) } catch { return null }
}
function persistActiveId(id: string | null): void {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, id)
    else     localStorage.removeItem(ACTIVE_KEY)
  } catch { /* quota or SSR */ }
}

/** Convert a snake_case backend session to a ChatSession. */
function fromBackend(s: {
  id: string; title: string; context_id: string | null
  created_at: string; updated_at: string
  messages?: Array<Record<string, unknown>>
}): ChatSession {
  return {
    id:        s.id,
    title:     s.title,
    contextId: s.context_id,
    messages:  (s.messages ?? []) as unknown as PersistedChatMessage[],
    createdAt: s.created_at,
    updatedAt: s.updated_at,
  }
}

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

export interface ChatSessionsStore {
  /** Session summaries for the sidebar. Messages array is intentionally empty here. */
  sessions:        ChatSession[]
  /** id → full ChatSession with messages (populated by loadSessionDetail). */
  sessionDetails:  Record<string, ChatSession>
  activeSessionId: string | null

  /** True while the sessions list is being fetched. */
  loading:         boolean
  /** Id of the session whose detail is currently being fetched. Null otherwise. */
  detailLoadingId: string | null
  sessionsError:   string | null
  detailError:     string | null
  _initialized:    boolean

  /** Load sessions list from backend. Idempotent (no-op if already initialized). */
  fetchSessions(): Promise<void>
  /** Fetch full session detail (messages + contextId) and make it the active session. */
  loadSessionDetail(id: string): Promise<void>
  /** Create a new session on the backend and make it active. */
  createSessionRemote(): Promise<void>
  /** Optimistic rename + fire-and-forget PATCH. */
  renameSessionRemote(id: string, title: string): void
  /** Delete session on backend and clean up local state. */
  deleteSessionRemote(id: string): Promise<void>
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

export const useChatSessionsStore = create<ChatSessionsStore>((set, get) => ({
  sessions:        [],
  sessionDetails:  {},
  activeSessionId: null,
  loading:         false,
  detailLoadingId: null,
  sessionsError:   null,
  detailError:     null,
  _initialized:    false,

  // ── fetchSessions ──────────────────────────────────────────────────────────

  async fetchSessions() {
    if (get()._initialized) return
    set({ loading: true, sessionsError: null })

    try {
      const list     = await apiListSessions()
      const sessions = list.map(fromBackend)

      // Pick active session: prefer the one the user had open last
      const savedId  = loadSavedActiveId()
      const activeId =
        (savedId && sessions.some(s => s.id === savedId))
          ? savedId
          : (sessions[0]?.id ?? null)

      set({ sessions, activeSessionId: activeId, loading: false, _initialized: true })
      persistActiveId(activeId)

      // Eagerly load messages for the active session
      if (activeId) {
        await get().loadSessionDetail(activeId)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      set({ loading: false, sessionsError: msg })
      // Leave _initialized false so the next mount can retry
    }
  },

  // ── loadSessionDetail ──────────────────────────────────────────────────────

  async loadSessionDetail(id: string) {
    // Immediately switch to this session — old messages show until new ones arrive
    set({ activeSessionId: id, detailLoadingId: id, detailError: null })
    persistActiveId(id)

    try {
      const raw     = await apiGetSession(id)
      const session = fromBackend(raw)

      set(st => ({
        // Keep summary title/updatedAt in sync
        sessions: st.sessions.map(s =>
          s.id === id ? { ...s, title: session.title, updatedAt: session.updatedAt } : s,
        ),
        sessionDetails:  { ...st.sessionDetails, [id]: session },
        detailLoadingId: st.detailLoadingId === id ? null : st.detailLoadingId,
      }))
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      set(st => ({
        detailLoadingId: st.detailLoadingId === id ? null : st.detailLoadingId,
        detailError: msg,
      }))
    }
  },

  // ── createSessionRemote ────────────────────────────────────────────────────

  async createSessionRemote() {
    try {
      const raw     = await apiCreateSession({ title: 'Nuevo chat' })
      const session = fromBackend(raw)
      set(st => ({
        sessions:        [session, ...st.sessions],
        activeSessionId: session.id,
        // Register an empty detail so the chat panel shows immediately
        sessionDetails:  { ...st.sessionDetails, [session.id]: session },
        detailError:     null,
      }))
      persistActiveId(session.id)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      set({ sessionsError: msg })
    }
  },

  // ── renameSessionRemote ────────────────────────────────────────────────────

  renameSessionRemote(id: string, title: string) {
    const truncated = title.slice(0, 40)
    set(st => ({
      sessions: st.sessions.map(s => s.id === id ? { ...s, title: truncated } : s),
      sessionDetails: st.sessionDetails[id]
        ? { ...st.sessionDetails, [id]: { ...st.sessionDetails[id], title: truncated } }
        : st.sessionDetails,
    }))
    apiUpdateSession(id, { title: truncated }).catch(() => {})
  },

  // ── deleteSessionRemote ────────────────────────────────────────────────────

  async deleteSessionRemote(id: string) {
    try { await apiDeleteSession(id) } catch { /* proceed regardless */ }

    set(st => {
      const sessions = st.sessions.filter(s => s.id !== id)
      const { [id]: _dropped, ...remainingDetails } = st.sessionDetails

      // Pick next active: prefer the most recently updated remaining session
      const newActiveId =
        st.activeSessionId !== id
          ? st.activeSessionId
          : ([...sessions].sort(
              (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
            )[0]?.id ?? null)

      persistActiveId(newActiveId)
      return { sessions, sessionDetails: remainingDetails, activeSessionId: newActiveId }
    })

    // Load detail for the newly active session if not cached
    const newActive = get().activeSessionId
    if (newActive && !get().sessionDetails[newActive]) {
      await get().loadSessionDetail(newActive)
    }
  },
}))
