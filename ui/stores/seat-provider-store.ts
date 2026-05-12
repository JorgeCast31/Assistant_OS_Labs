import { create } from 'zustand'
import type { MSOSeatProviderResponse } from '@/lib/types'

interface SeatProviderState {
  seatProvider: MSOSeatProviderResponse | null
  isPolling: boolean
  lastPolled: string | null
  pollError: string | null
  setSeatProvider: (data: MSOSeatProviderResponse) => void
  setPolling: (v: boolean) => void
  setLastPolled: (ts: string) => void
  setPollError: (err: string | null) => void
}

export const useSeatProviderStore = create<SeatProviderState>((set) => ({
  seatProvider: null,
  isPolling: false,
  lastPolled: null,
  pollError: null,
  setSeatProvider: (data) => set({ seatProvider: data }),
  setPolling: (v) => set({ isPolling: v }),
  setLastPolled: (ts) => set({ lastPolled: ts }),
  setPollError: (err) => set({ pollError: err }),
}))
