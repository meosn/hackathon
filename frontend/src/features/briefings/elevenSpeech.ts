import { api, queryClient } from '../../api/client'
import type { Preferences } from '../../api/types'

type Session = {
  token: string
  voice_id: string
  voice_profile_id: string
  model_id: string
  sample_rate: number
}
type Turn = {
  id: string
  pending: string
  initialized: boolean
  ended: boolean
  final: boolean
  started: boolean
}
type Callbacks = {
  started: () => void
  finished: () => void
  failed: (message: string) => void
}

/** Stream generated words directly to TTS and play PCM before the reply is complete. */
export class ElevenSpeech {
  private socket: WebSocket | null = null
  private connecting: Promise<void> | null = null
  private requestedVoice: string | undefined
  private voice: string | undefined
  private version = 0
  private disposed = false
  private abort = new AbortController()
  private heartbeat: ReturnType<typeof setInterval> | undefined
  private turn: Turn | null = null
  private sources = new Set<AudioBufferSourceNode>()
  private nextTime = 0
  private carry: number | undefined
  private rate = 24000

  constructor(
    private conversationId: string,
    private context: AudioContext,
    private callbacks: Callbacks,
  ) {}

  private preferenceVoice() {
    return queryClient.getQueryData<Preferences>(['/users/me/preferences'])
      ?.voice_profile_id
  }

  connect(): Promise<void> {
    if (this.disposed)
      return Promise.reject(new DOMException('Aborted', 'AbortError'))
    const desired = this.preferenceVoice()
    if (
      this.socket?.readyState === WebSocket.OPEN &&
      (!desired || desired === this.voice)
    )
      return Promise.resolve()
    if (this.connecting && desired === this.requestedVoice)
      return this.connecting
    this.requestedVoice = desired
    const version = ++this.version
    this.socket?.close()
    clearInterval(this.heartbeat)
    const opening = this.open(version)
    this.connecting = opening
    void opening
      .finally(() => {
        if (this.connecting === opening) this.connecting = null
      })
      .catch(() => {})
    return opening
  }

  private async open(version: number) {
    const session = await api<Session>(
      `/conversations/${this.conversationId}/speech-session`,
      'POST',
      {},
      this.abort.signal,
    )
    if (this.disposed || version !== this.version)
      throw new DOMException('Aborted', 'AbortError')
    this.voice = session.voice_profile_id
    this.rate = session.sample_rate
    const url = new URL(
      `wss://api.elevenlabs.io/v1/text-to-speech/${encodeURIComponent(session.voice_id)}/multi-stream-input`,
    )
    url.searchParams.set('single_use_token', session.token)
    url.searchParams.set('model_id', session.model_id)
    url.searchParams.set('output_format', `pcm_${session.sample_rate}`)
    url.searchParams.set('inactivity_timeout', '180')
    url.searchParams.set('auto_mode', 'true')
    const socket = (this.socket = new WebSocket(url))
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        socket.close()
        reject(Error('Speech connection timed out. Please retry.'))
      }, 10000)
      const valid = () => !this.disposed && version === this.version
      socket.onopen = () => {
        clearTimeout(timer)
        if (!valid()) {
          socket.close()
          reject(new DOMException('Aborted', 'AbortError'))
          return
        }
        // Keep one silent context alive so questions do not pay another handshake.
        this.send({ context_id: 'standby', text: ' ' })
        this.heartbeat = setInterval(
          () => this.send({ context_id: 'standby', text: '' }),
          15000,
        )
        resolve()
      }
      socket.onmessage = (event) => {
        if (!valid()) return
        try {
          this.receive(JSON.parse(event.data))
        } catch {
          this.fail('The speech stream could not be decoded. Please retry.')
        }
      }
      socket.onerror = () => {
        if (valid())
          this.fail('ElevenLabs speech connection failed. Please retry.')
      }
      socket.onclose = () => {
        clearTimeout(timer)
        reject(Error('ElevenLabs speech connection closed. Please retry.'))
        if (!valid()) return
        clearInterval(this.heartbeat)
        this.socket = null
        if (this.turn && !this.turn.final)
          this.fail('The spoken answer was interrupted. Please retry.')
      }
      this.abort.signal.addEventListener(
        'abort',
        () => {
          clearTimeout(timer)
          socket.close()
          reject(new DOMException('Aborted', 'AbortError'))
        },
        { once: true },
      )
    })
  }

  prepare() {
    void this.connect().catch(() => {
      // Optional preparation must not interrupt narration. A real reply retries.
    })
  }

  append(id: string, text: string) {
    if (this.disposed || !text) return
    if (this.turn?.id !== id) {
      this.cancel()
      const turn: Turn = {
        id,
        pending: '',
        initialized: false,
        ended: false,
        final: false,
        started: false,
      }
      this.turn = turn
      void this.connect()
        .then(() => {
          if (this.turn !== turn || this.disposed) return
          this.send({
            context_id: id,
            text: ' ',
            voice_settings: {
              stability: 0.5,
              similarity_boost: 0.8,
              use_speaker_boost: false,
            },
          })
          turn.initialized = true
          this.flushText(turn)
        })
        .catch(() => {
          if (this.turn === turn)
            this.fail('The selected voice could not start. Please retry.')
        })
    }
    this.turn!.pending += text
    if (this.turn!.initialized) this.flushText(this.turn!)
  }

  private flushText(turn: Turn) {
    if (this.turn !== turn || !turn.initialized) return
    // Never feed incomplete words. Complete sentences are flushed immediately.
    const boundary = turn.ended
      ? turn.pending.length
      : Math.max(
          turn.pending.lastIndexOf(' ') + 1,
          turn.pending.lastIndexOf('\n') + 1,
        )
    if (boundary > 0) {
      const text = turn.pending.slice(0, boundary)
      turn.pending = turn.pending.slice(boundary)
      this.send({ context_id: turn.id, text, flush: /[.!?…]\s*$/.test(text) })
    }
    if (turn.ended) {
      this.send({ context_id: turn.id, close_context: true })
      // Mark once, including when token authorization completed after the text.
      turn.initialized = false
    }
  }

  finish(id: string) {
    const turn = this.turn
    if (!turn || turn.id !== id || turn.ended) return
    turn.ended = true
    turn.final = false
    this.flushText(turn)
  }

  private send(message: Record<string, unknown>) {
    if (this.socket?.readyState === WebSocket.OPEN)
      this.socket.send(JSON.stringify(message))
  }

  private receive(message: {
    context_id?: string
    contextId?: string
    audio?: string
    is_final?: boolean
    isFinal?: boolean
    error?: unknown
  }) {
    if (message.error) {
      this.fail(
        'ElevenLabs could not synthesize the selected voice. Please retry.',
      )
      return
    }
    const turn = this.turn
    if (!turn || (message.context_id || message.contextId) !== turn.id) return
    if (message.audio) this.schedule(message.audio, turn)
    if (message.is_final || message.isFinal) {
      turn.final = true
      this.complete(turn)
    }
  }

  private schedule(base64: string, turn: Turn) {
    const raw = atob(base64)
    const prefix = this.carry === undefined ? 0 : 1
    const bytes = new Uint8Array(raw.length + prefix)
    if (prefix) bytes[0] = this.carry!
    for (let i = 0; i < raw.length; i++) bytes[i + prefix] = raw.charCodeAt(i)
    this.carry = bytes.length % 2 ? bytes[bytes.length - 1] : undefined
    const samples = Math.floor(bytes.length / 2)
    if (!samples) return
    const buffer = this.context.createBuffer(1, samples, this.rate),
      out = buffer.getChannelData(0),
      view = new DataView(bytes.buffer)
    for (let i = 0; i < samples; i++)
      out[i] = view.getInt16(i * 2, true) / 32768
    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.context.destination)
    source.onended = () => {
      this.sources.delete(source)
      source.disconnect()
      this.complete(turn)
    }
    this.sources.add(source)
    const at = Math.max(this.context.currentTime + 0.025, this.nextTime)
    this.nextTime = at + buffer.duration
    source.start(at)
    if (!turn.started) {
      turn.started = true
      this.callbacks.started()
    }
  }

  private complete(turn: Turn) {
    if (this.turn !== turn || !turn.ended || !turn.final || this.sources.size)
      return
    this.turn = null
    this.carry = undefined
    this.callbacks.finished()
  }

  cancel() {
    const turn = this.turn
    this.turn = null
    if (turn?.initialized)
      this.send({ context_id: turn.id, close_context: true })
    for (const source of this.sources) {
      source.onended = null
      try {
        source.stop()
      } catch {
        /* already ended */
      }
      source.disconnect()
    }
    this.sources.clear()
    this.nextTime = this.context.currentTime
    this.carry = undefined
  }

  private fail(message: string) {
    this.cancel()
    this.socket?.close()
    this.socket = null
    clearInterval(this.heartbeat)
    this.callbacks.failed(message)
  }

  close() {
    if (this.disposed) return
    this.cancel()
    this.send({ close_socket: true })
    this.disposed = true
    this.version++
    this.abort.abort()
    clearInterval(this.heartbeat)
    this.socket?.close()
    this.socket = null
  }
}
