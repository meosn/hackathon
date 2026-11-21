import { useEffect, useRef } from 'react'
import { api } from '../../api/client'
import type { BriefingDetail } from '../../api/types'

/** Count actual listening, not a seek to the end or an opened page. */
export function useStoryLearning(edition: BriefingDetail | undefined, position: number, playing: boolean) {
  const progress = useRef(new Map<string, number>()), sent = useRef(new Set<string>())
  const previous = useRef<{ position: number; storyId: string } | undefined>(undefined)
  useEffect(() => { progress.current.clear(); sent.current.clear(); previous.current = undefined }, [edition?.id])
  useEffect(() => {
    const storyId = edition?.segments.find(s => s.story_id && s.start_seconds <= position && s.end_seconds > position)?.story_id
    if (!playing || !storyId) { previous.current = undefined; return }
    const last = previous.current
    previous.current = { position, storyId }
    if (!last || last.storyId !== storyId) return
    const delta = position - last.position
    if (delta <= 0 || delta > 1) return
    const seconds = (progress.current.get(storyId) || 0) + delta
    progress.current.set(storyId, seconds)
    const rows = edition!.segments.filter(s => s.story_id === storyId)
    const duration = Math.max(...rows.map(s => s.end_seconds)) - Math.min(...rows.map(s => s.start_seconds))
    if (seconds >= Math.max(8, duration * 0.6) && !sent.current.has(storyId)) {
      sent.current.add(storyId)
      void api('/listening-history/' + storyId, 'PUT').catch(() => {})
    }
  }, [edition, position, playing])
}
