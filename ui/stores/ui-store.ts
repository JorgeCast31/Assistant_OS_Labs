'use client'

import { create } from 'zustand'
import type { ViewId, ExecutionListItem, SystemData } from '@/lib/types'

const SYSTEM_DATA_INIT: SystemData = {
  apiStatus:         'unknown',
  webhookStatus:     'unknown',
  activeExecutions:  0,
  needsReview:       0,
  lastUpdated:       null,
  error:             null,
  operationalMode:   'UNKNOWN',
  recentEvents:      [],
}

interface UIState {
  activeView: ViewId
  selectedExecutionId: string | null
  /**
   * Set by ActionsView after a successful execute POST.
   * Consumed (prepended + cleared) by ExecutionsView on mount.
   */
  pendingExecution: ExecutionListItem | null

  /** Real system health — polled by AppShell, read by TopHUD + SystemView */
  systemData: SystemData
  isSystemRefreshing: boolean

  setView: (view: ViewId) => void
  setSelectedExecution: (id: string | null) => void
  setPendingExecution: (exec: ExecutionListItem | null) => void
  setSystemData: (data: SystemData) => void
  setSystemRefreshing: (v: boolean) => void
}

export const useUIStore = create<UIState>((set) => ({
  activeView:          'chat',
  selectedExecutionId: null,
  pendingExecution:    null,
  systemData:          SYSTEM_DATA_INIT,
  isSystemRefreshing:  false,

  setView:              (view) => set({ activeView: view }),
  setSelectedExecution: (id)   => set({ selectedExecutionId: id }),
  setPendingExecution:  (exec) => set({ pendingExecution: exec }),
  setSystemData:        (data) => set({ systemData: data }),
  setSystemRefreshing:  (v)    => set({ isSystemRefreshing: v }),
}))
