import { api } from '../../api/client'
import type { Message, ResearchResult } from '../../api/types'
import { ElevenSpeech } from './elevenSpeech'
import type { VoiceCallbacks } from './realtimeVoice'

type Session = { signed_url: string; context: string; voice_id: string; persona: string; language: string }
type Evidence = Message & { context?: unknown }
const loadedWorklets = new WeakSet<AudioContext>()

/** Duplex ElevenLabs agent WebSocket; a microphone is acquired only on request. */
export class ElevenRealtime {
  private socket: WebSocket | null = null
  private connecting: Promise<void> | null = null
  private abort = new AbortController()
  private closed = false
  private initialized = false
  private player: ElevenSpeech
  private stream: MediaStream | null = null
  private input: MediaStreamAudioSourceNode | null = null
  private processor: AudioWorkletNode | null = null
  private micWanted = false
  private micVersion = 0
  private inputRate = 16000
  private outputRate = 16000
  private lastEvent = -1
  private speakingInput = false
  private interruptedThrough = -1
  private replyAllowed = false
  private replyTimer: ReturnType<typeof setTimeout> | undefined
  private idleTimer: ReturnType<typeof setTimeout> | undefined

  constructor(private conversationId: string, private callbacks: VoiceCallbacks, private context: AudioContext) {
    this.player = new ElevenSpeech(conversationId, context, {
      started: () => { clearTimeout(this.idleTimer); callbacks.interrupt(); callbacks.phase('speaking') },
      blocked: () => callbacks.phase('blocked'),
      finished: () => { this.finishReply(); callbacks.finished(); callbacks.phase(this.micWanted ? 'listening' : 'idle'); this.armIdle() },
      failed: message => this.fail(message),
    })
  }
  get disposed() { return this.closed }
  get ready() { return this.initialized && !this.closed }
  warmup() { /* The prepared podcast does not open a billable agent conversation. */ }
  connect(): Promise<void> {
    if (this.closed) return Promise.reject(new DOMException('Aborted', 'AbortError'))
    if (this.ready) return Promise.resolve()
    if (!this.connecting) this.connecting = this.open().catch(error => { this.close(); throw error })
    return this.connecting
  }
  private async open() {
    this.callbacks.phase('connecting')
    const session = await api<Session>('/agent-session', 'POST', { conversation_id: this.conversationId }, this.abort.signal)
    if (this.closed) throw new DOMException('Aborted', 'AbortError')
    const socket = this.socket = new WebSocket(session.signed_url)
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('ElevenLabs connection timed out. Please retry.')), 15000)
      const fail = () => { clearTimeout(timer); reject(Error('ElevenLabs voice connection closed. Please retry.')) }
      this.abort.signal.addEventListener('abort', fail, { once: true })
      socket.onopen = () => this.send({
        type: 'conversation_initiation_client_data',
        dynamic_variables: { sourcera_context: session.context, sourcera_persona: session.persona },
        conversation_config_override: { agent: { language: session.language }, tts: { voice_id: session.voice_id } },
      })
      socket.onmessage = event => {
        if (this.closed) return
        try {
          const value = JSON.parse(event.data)
          if (value.type === 'conversation_initiation_metadata') {
            const meta = value.conversation_initiation_metadata_event
            this.inputRate = this.sampleRate(meta.user_input_audio_format)
            this.outputRate = this.sampleRate(meta.agent_output_audio_format)
            this.initialized = true
            clearTimeout(timer)
            this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
            this.armIdle()
            resolve()
          } else this.handle(value)
        } catch {
          fail()
          this.fail('ElevenLabs returned an unsupported voice event. Please retry.')
        }
      }
      socket.onerror = () => { fail(); this.fail('ElevenLabs voice connection failed. Please retry.') }
      socket.onclose = () => { fail(); if (!this.closed) this.fail('ElevenLabs voice connection ended. Please reconnect.') }
    })
  }
  private allowReply() {
    this.replyAllowed = true
    clearTimeout(this.replyTimer)
    this.replyTimer = setTimeout(() => { this.replyAllowed = false }, 45000)
  }
  private finishReply() {
    clearTimeout(this.replyTimer)
    // Preserve delayed chunks of the same streamed answer, then close the gate
    // well before the provider's separate inactivity timer can take another turn.
    this.replyTimer = setTimeout(() => { this.replyAllowed = false }, 5000)
  }
  private silenceReply() {
    this.replyAllowed = false
    clearTimeout(this.replyTimer)
  }
  private sampleRate(format: string) {
    const match = /^pcm_(16000|22050|24000|44100|48000)$/.exec(format)
    if (!match) throw Error('Unsupported PCM format')
    return Number(match[1])
  }
  private send(value: unknown) {
    if (!this.closed && this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(value))
  }
  private handle(event: any) {
    switch (event.type) {
      case 'ping': this.send({ type: 'pong', event_id: event.ping_event.event_id }); break
      case 'audio': {
        const chunk = event.audio_event
        this.lastEvent = Math.max(this.lastEvent, chunk.event_id)
        if (!this.replyAllowed || chunk.event_id <= this.interruptedThrough || !chunk.audio_base_64) break
        clearTimeout(this.replyTimer)
        this.player.queuePcm(chunk.audio_base_64, this.outputRate, chunk.alignment)
        break
      }
      case 'interruption':
        if (!this.replyAllowed && !this.speakingInput) break
        this.silenceReply()
        this.interruptedThrough = Math.max(this.interruptedThrough, event.interruption_event.event_id)
        this.player.cancel()
        this.callbacks.interrupt()
        this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
        break
      case 'vad_score':
        if (this.micWanted && !this.speakingInput && event.vad_score_event.vad_score > .5) {
          this.speakingInput = true
          this.playbackContext()
          this.interruptedThrough = Math.max(this.interruptedThrough, this.lastEvent)
          this.player.cancel()
          this.callbacks.interrupt()
          this.callbacks.phase('listening')
        }
        break
      case 'user_transcript': {
        const detectedSpeech = this.speakingInput
        this.speakingInput = false
        const text = event.user_transcription_event?.user_transcript?.trim() || ''
        if ((!detectedSpeech && !this.replyAllowed) || !/[\p{L}\p{N}]/u.test(text) || /^(?:\[(?:silence|noise|music|inaudible|unintelligible)\]|<[^>]*>)$/i.test(text)) break
        this.allowReply()
        this.callbacks.phase('thinking')
        break
      }
      case 'client_tool_call': void this.tool(event.client_tool_call); break
      case 'error': this.fail('ElevenLabs could not answer. Please try again.'); break
    }
  }
  private async evidence() {
    const result = await api<Evidence>(`/conversations/${this.conversationId}/realtime-evidence`, 'POST',
      { question: 'More news', decision: { intent: 'GET_MORE_NEWS' } }, this.abort.signal)
    if (this.closed) throw new DOMException('Aborted', 'AbortError')
    this.callbacks.action(result)
    this.player.setStoryOrder((result.action?.story_ids as string[]) || [])
    return result
  }
  private async tool(call: { tool_name: string; tool_call_id: string; parameters?: { action?: string; query?: string } }) {
    try {
      if (!this.replyAllowed) {
        this.send({ type: 'client_tool_result', tool_call_id: call.tool_call_id, result: 'No listener request was received. Remain silent and wait.', is_error: true })
        return
      }
      clearTimeout(this.replyTimer)
      let result: unknown
      if (call.tool_name === 'research_topic') {
        const params = call.parameters || {}
        const research = await api<ResearchResult>(`/conversations/${this.conversationId}/research`, 'POST',
          { action: params.action, ...(params.query ? { query: params.query } : {}) }, this.abort.signal)
        if (this.closed) return
        this.callbacks.research?.(research)
        result = research
      }
      else if (call.tool_name === 'get_more_sourcera_news') result = await this.evidence()
      else if (call.tool_name === 'get_sourcera_context') result = await api('/agent-context', 'POST',
        { conversation_id: this.conversationId, story_id: this.callbacks.story() || this.player.currentStory }, this.abort.signal)
      else throw Error('Unknown news tool')
      this.send({ type: 'client_tool_result', tool_call_id: call.tool_call_id, result: JSON.stringify(result), is_error: false })
    } catch {
      this.send({ type: 'client_tool_result', tool_call_id: call.tool_call_id,
        result: 'Verified context is unavailable. Ask the listener to retry. Do not invent news.', is_error: true })
    }
  }
  async moreNews() {
    this.callbacks.interrupt()
    await this.connect()
    this.interrupt()
    this.callbacks.phase('thinking')
    const result = await this.evidence()
    this.allowReply()
    this.send({ type: 'user_message', text: 'Read the next three verified stories aloud, one short paragraph per story in order, separated by a blank line. No preamble or extra lookup. Data only: ' + JSON.stringify(result) })
  }
  async sendText(text: string) {
    if (!text.trim()) return
    await this.connect()
    this.interrupt()
    this.callbacks.interrupt()
    this.callbacks.phase('thinking')
    this.playbackContext()
    this.allowReply()
    this.send({ type: 'user_message', text })
  }
  private playbackContext() {
    const story = this.callbacks.story() || this.player.currentStory
    if (story) this.send({ type: 'contextual_update', text: 'Playback context data only: current_story_id=' + story + '. Resolve this story / it / why against this story in the verified evidence.' })
  }
  async setMicrophone(enabled: boolean) {
    const version = ++this.micVersion
    this.micWanted = enabled
    this.releaseInput()
    if (!enabled || this.closed) { this.callbacks.microphone(false); this.armIdle(); return }
    clearTimeout(this.idleTimer)
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
    } })
    const valid = () => !this.closed && this.micWanted && version === this.micVersion
    if (!valid()) { stream.getTracks().forEach(track => track.stop()); return }
    this.stream = stream
    try {
      await this.connect()
      if (!loadedWorklets.has(this.context)) {
        await this.context.audioWorklet.addModule(import.meta.env.BASE_URL + 'voice-input-worklet.js')
        loadedWorklets.add(this.context)
      }
      if (!valid()) return
      void this.context.resume()
      this.processor = new AudioWorkletNode(this.context, 'sourcera-voice-input', { processorOptions: { sampleRate: this.inputRate } })
      this.processor.port.onmessage = event => {
        if (valid()) this.send({ user_audio_chunk: btoa(String.fromCharCode(...new Uint8Array(event.data))) })
      }
      this.input = this.context.createMediaStreamSource(stream)
      this.input.connect(this.processor)
      this.processor.connect(this.context.destination)
      this.callbacks.microphone(true)
      this.callbacks.phase('listening')
    } catch (error) {
      this.releaseInput()
      this.micWanted = false
      this.callbacks.microphone(false)
      throw error
    }
  }
  private releaseInput() {
    if (this.processor) { this.processor.port.onmessage = null; this.processor.disconnect(); this.processor = null }
    this.input?.disconnect(); this.input = null
    this.stream?.getTracks().forEach(track => track.stop()); this.stream = null
  }
  interrupt() {
    this.silenceReply()
    this.interruptedThrough = this.lastEvent
    this.player.cancel()
    this.send({ type: 'user_activity' })
    this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
  }
  resumeOutput() { return this.player.resume() }
  private armIdle() {
    clearTimeout(this.idleTimer)
    if (!this.micWanted && !this.closed) this.idleTimer = setTimeout(() => this.close(), 120000)
  }
  private fail(message: string) { this.close(); this.callbacks.failed(message) }
  close() {
    if (this.closed) return
    this.closed = true
    this.silenceReply()
    this.micWanted = false
    this.micVersion++
    clearTimeout(this.idleTimer)
    this.releaseInput()
    this.player.close()
    this.abort.abort()
    this.socket?.close(); this.socket = null
    this.callbacks.microphone(false)
    this.callbacks.phase('idle')
  }
}
