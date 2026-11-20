import { create } from 'zustand'
export const usePlayer = create<{
  speed: number
  activeId: string | null
  setSpeed: (n: number) => void
  setActive: (id: string | null) => void
}>((set) => ({
  speed: 1,
  activeId: null,
  setSpeed: (speed) => set({ speed }),
  setActive: (activeId) => set({ activeId }),
}))
