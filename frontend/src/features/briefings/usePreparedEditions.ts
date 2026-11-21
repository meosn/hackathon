import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, preloadBriefingAudio, useApi, useBriefingAudio } from '../../api/client'
import type { Briefing, BriefingDetail, Preferences } from '../../api/types'
import { customVoicePath, type CustomVoiceState } from '../voice/CustomVoice'

type Prepared = { daily: Briefing; weekly: Briefing }
const finished = (edition?: Briefing) => !!edition && ['completed', 'failed'].includes(edition.status)

export function usePreparedEditions() {
  const prefs = useApi<Preferences>('/users/me/preferences')
  const custom = useApi<CustomVoiceState>(customVoicePath)
  const fingerprint = JSON.stringify([prefs.data, custom.data?.active, custom.data?.revision])
  const [settled, setSettled] = useState(fingerprint)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(fingerprint), 1200)
    return () => clearTimeout(timer)
  }, [fingerprint])
  const result = useQuery({
    queryKey: ['prepared-editions', settled],
    enabled: !!prefs.data && !!custom.data && settled === fingerprint,
    queryFn: () => api<Prepared>('/briefings/prepare', 'POST'),
    staleTime: 30000,
    refetchInterval: query => finished(query.state.data?.daily) && finished(query.state.data?.weekly) ? 60000 : 2000,
  })
  const weeklyId = result.data?.weekly.status === 'completed' ? result.data.weekly.id : undefined
  const audio = useBriefingAudio(weeklyId)
  const detail = useQuery({
    queryKey: ['live-custom', weeklyId], enabled: !!weeklyId,
    queryFn: () => api<BriefingDetail>('/briefings/' + weeklyId), staleTime: Infinity,
  })
  useEffect(() => {
    if (result.data?.weekly.status === 'completed') void preloadBriefingAudio(result.data.weekly.id)
    if (result.data?.daily.status === 'completed') void preloadBriefingAudio(result.data.daily.id)
  }, [result.data?.weekly.id, result.data?.weekly.status, result.data?.daily.id, result.data?.daily.status])
  return { ...result, error: result.error || audio.error || detail.error, weeklyPlayable: !!audio.data && !!detail.data,
    updating: settled !== fingerprint || !finished(result.data?.daily) || !finished(result.data?.weekly) }
}
