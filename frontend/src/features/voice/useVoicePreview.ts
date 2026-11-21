import { useCallback, useEffect, useRef, useState } from 'react'
import { queryClient, request } from '../../api/client'

export const PREVIEW_START = 'sourcera:preview-start'
export const PLAYBACK_START = 'sourcera:playback-start'

/** Unlock inside the click, before loading audio, so delayed samples work in Safari. */
export function useVoicePreview() {
  const context = useRef<AudioContext | null>(null)
  const source = useRef<AudioBufferSourceNode | null>(null)
  const sequence = useRef(0)
  const [state, setState] = useState({ id: '', loading: false, error: '' })
  const stop = useCallback(() => {
    sequence.current++
    if (source.current) { source.current.onended = null; source.current.stop(); source.current.disconnect(); source.current = null }
    setState({ id: '', loading: false, error: '' })
  }, [])
  useEffect(() => {
    window.addEventListener(PREVIEW_START, stop)
    window.addEventListener(PLAYBACK_START, stop)
    document.addEventListener('play', stop, true)
    return () => {
      window.removeEventListener(PREVIEW_START, stop)
      window.removeEventListener(PLAYBACK_START, stop)
      document.removeEventListener('play', stop, true)
      stop()
      void context.current?.close().catch(() => {})
      context.current = null
    }
  }, [stop])

  function play(id: string, engine: string, language: string) {
    window.dispatchEvent(new Event(PREVIEW_START))
    document.querySelectorAll<HTMLMediaElement>('audio,video').forEach(media => media.pause())
    const current = ++sequence.current
    setState({ id, loading: true, error: '' })
    void (async () => {
      try {
        const audio = context.current?.state !== 'closed' && context.current ? context.current : new AudioContext()
        context.current = audio
        const resumed = audio.resume()
        const unlock = audio.createBufferSource()
        unlock.buffer = audio.createBuffer(1, 1, audio.sampleRate)
        unlock.connect(audio.destination)
        unlock.onended = () => unlock.disconnect()
        unlock.start()
        await resumed
        const load = async (signal?: AbortSignal) => {
          const response = await request('/voices/' + id + '/preview', 'POST', { engine, language }, signal)
          return response.blob()
        }
        // Custom samples are resolved by the server on every click, including after re-cloning.
        const blob = id.startsWith('custom') ? await load() : await queryClient.fetchQuery({
          queryKey: ['voice-preview', id, engine, language],
          queryFn: ({ signal }) => load(signal), staleTime: Infinity,
        })
        if (sequence.current !== current) return
        const buffer = await audio.decodeAudioData(await blob.arrayBuffer())
        if (sequence.current !== current) return
        const node = audio.createBufferSource()
        node.buffer = buffer
        node.connect(audio.destination)
        source.current = node
        node.onended = () => {
          node.disconnect()
          if (sequence.current === current) { source.current = null; setState({ id: '', loading: false, error: '' }) }
        }
        setState({ id, loading: false, error: '' })
        node.start()
      } catch (error) {
        if (sequence.current === current) setState({ id: '', loading: false,
          error: error instanceof Error ? error.message : 'The voice sample could not play. Please retry.' })
      }
    })()
  }
  return { ...state, play, stop }
}
