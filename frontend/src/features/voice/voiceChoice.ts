import { useApi } from '../../api/client'
import { useIsMutating } from '@tanstack/react-query'
import type { Preferences } from '../../api/types'
import { ElevenRealtime } from '../briefings/elevenRealtime'
import { RealtimeVoice, unlockVoiceAudio, type VoiceCallbacks } from '../briefings/realtimeVoice'
import { customVoicePath, type CustomVoiceState } from './CustomVoice'

export type VoiceEngine = 'openai' | 'elevenlabs'
export type VoiceConnection = RealtimeVoice | ElevenRealtime

export function useVoiceChoice() {
  const preferences = useApi<Preferences>('/users/me/preferences')
  const custom = useApi<CustomVoiceState>(customVoicePath)
  const prefs = preferences.data
  const saving = useIsMutating({ mutationKey: ['voice-preferences'] }) > 0
  const engine: VoiceEngine = prefs?.voice_engine === 'openai' ? 'openai' : 'elevenlabs'
  return { engine, ready: !!prefs && !saving, signature: prefs ? `${engine}:${prefs.voice_profile_id}:${!!custom.data?.active}:${custom.data?.revision || ''}` : '' }
}

export function createVoiceConnection(engine: VoiceEngine, id: string, callbacks: VoiceCallbacks, context?: AudioContext): VoiceConnection {
  return engine === 'elevenlabs'
    ? new ElevenRealtime(id, callbacks, context || unlockVoiceAudio(null))
    : new RealtimeVoice(id, callbacks, context)
}
