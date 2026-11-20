import { api, request } from '../../api/client'
import type { Message } from '../../api/types'

export type VoicePhase =
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'idle'
type Callbacks = {
  phase: (phase: VoicePhase) => void
  interrupt: () => void
  microphone: (enabled: boolean) => void
  story: () => string | undefined
  action: (message: Message) => void
  finished: () => void
  failed: (message: string) => void
}

/** Resume from a direct click, including browsers that gate delayed media playback. */
export function unlockVoiceAudio(previous: AudioContext | null) {
  const context =
    previous?.state !== 'closed' && previous ? previous : new AudioContext()
  void context.resume().catch(() => {})
  return context
}

/** One duplex audio transport. Input tracks can be released without touching output. */
export class RealtimeVoice {
  private peer: RTCPeerConnection | null = null
  private channel: RTCDataChannel | null = null
  private sender: RTCRtpSender | null = null
  private stream: MediaStream | null = null
  private output: HTMLAudioElement
  private outputSource: MediaStreamAudioSourceNode | null = null
  private connecting: Promise<void> | null = null
  private abort = new AbortController()
  private closed = false
  private micWanted = false
  private micVersion = 0
  private speakingInput = false
  private responseActive = false
  private pendingResponse = false
  private sequence = 0
  private turnStory: string | undefined
  private idleTimer: ReturnType<typeof setTimeout> | undefined
  private toolCalls = new Set<string>()

  constructor(
    private conversationId: string,
    private callbacks: Callbacks,
    private outputContext?: AudioContext,
  ) {
    this.output = new Audio()
    this.output.autoplay = true
    this.output.setAttribute('playsinline', '')
  }

  get ready() {
    return this.channel?.readyState === 'open' && !this.closed
  }

  connect() {
    if (this.ready) return Promise.resolve()
    if (this.connecting) return this.connecting
    this.connecting = this.open().catch((error) => {
      this.close()
      throw error
    })
    return this.connecting
  }

  private async open() {
    this.callbacks.phase('connecting')
    const peer = (this.peer = new RTCPeerConnection())
    this.sender = peer.addTransceiver('audio', { direction: 'sendrecv' }).sender
    peer.ontrack = (event) => {
      const stream = event.streams[0] || new MediaStream([event.track])
      this.output.srcObject = stream
      if (this.outputContext?.state === 'running') {
        this.outputSource?.disconnect()
        this.outputSource = this.outputContext.createMediaStreamSource(stream)
        this.outputSource.connect(this.outputContext.destination)
        // Keep the media element running while Web Audio provides the audible path.
        this.output.muted = true
      }
      void this.output
        .play()
        .catch(() => this.callbacks.failed('Tap Play to enable spoken audio.'))
    }
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === 'failed' && !this.closed) {
        this.close()
        this.callbacks.failed(
          'Voice connection lost. Turn the microphone on to reconnect.',
        )
      }
    }
    const channel = (this.channel = peer.createDataChannel('oai-events'))
    channel.onmessage = (event) => {
      try {
        this.handle(JSON.parse(event.data))
      } catch {
        this.callbacks.failed('Voice connection returned an invalid event.')
      }
    }
    const opened = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(Error('Voice connection timed out. Please try again.')),
        25000,
      )
      const done = () => clearTimeout(timer)
      channel.onopen = () => {
        done()
        resolve()
      }
      channel.onclose = () => {
        done()
        if (!this.closed) {
          this.close()
          this.callbacks.failed(
            'Voice connection closed. Turn the microphone on to reconnect.',
          )
          reject(Error('Voice connection closed.'))
        }
      }
      this.abort.signal.addEventListener(
        'abort',
        () => {
          done()
          reject(new DOMException('Aborted', 'AbortError'))
        },
        { once: true },
      )
    })
    // Attach a rejection handler immediately while the SDP request is in flight.
    void opened.catch(() => {})
    const offer = await peer.createOffer()
    await peer.setLocalDescription(offer)
    const response = await request(
      `/conversations/${this.conversationId}/realtime`,
      'POST',
      { sdp: offer.sdp },
      this.abort.signal,
    )
    if (this.closed) return
    await peer.setRemoteDescription({
      type: 'answer',
      sdp: await response.text(),
    })
    await opened
    if (!this.closed) {
      this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
      this.armIdleTimer()
    }
  }

  async setMicrophone(enabled: boolean) {
    if (this.closed) return
    this.micWanted = enabled
    const version = ++this.micVersion
    if (!enabled) {
      this.stream?.getTracks().forEach((track) => track.stop())
      this.stream = null
      await this.sender?.replaceTrack(null)
      this.callbacks.microphone(false)
      // Finish an utterance already spoken, preserving any response in progress.
      if (this.speakingInput) {
        this.speakingInput = false
        this.send({ type: 'input_audio_buffer.commit' })
        this.createResponse()
      } else this.send({ type: 'input_audio_buffer.clear' })
      this.armIdleTimer()
      return
    }
    if (!navigator.mediaDevices?.getUserMedia)
      throw Error('Microphone access requires HTTPS and browser permission.')
    // Ask from the click handler, before waiting for networking.
    const pending = navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    })
    const stream = await pending
    if (this.closed || version !== this.micVersion || !this.micWanted) {
      stream.getTracks().forEach((track) => track.stop())
      return
    }
    this.stream = stream
    try {
      await this.connect()
      if (this.closed || version !== this.micVersion || !this.micWanted) return
      await this.sender?.replaceTrack(stream.getAudioTracks()[0])
      clearTimeout(this.idleTimer)
      this.callbacks.microphone(true)
      this.callbacks.phase('listening')
    } catch (error) {
      stream.getTracks().forEach((track) => track.stop())
      this.stream = null
      this.callbacks.microphone(false)
      throw error
    }
  }

  async moreNews() {
    return this.sendText(
      'Give me three more news stories. Call news_evidence with GET_MORE_NEWS and then read the returned stories aloud in the language we have been speaking.',
    )
  }

  async sendText(text: string) {
    await this.connect()
    this.interrupt()
    this.turnStory = this.callbacks.story()
    this.callbacks.interrupt()
    this.callbacks.phase('thinking')
    this.send({
      type: 'conversation.item.create',
      item: {
        type: 'message',
        role: 'user',
        content: [{ type: 'input_text', text }],
      },
    })
    this.createResponse()
  }

  private send(event: Record<string, unknown>) {
    if (this.ready) this.channel!.send(JSON.stringify(event))
  }

  private createResponse() {
    if (this.responseActive) this.pendingResponse = true
    else
      this.send({
        type: 'response.create',
        response: { output_modalities: ['audio'] },
      })
  }

  private handle(event: Record<string, any>) {
    if (this.closed) return
    switch (event.type) {
      case 'input_audio_buffer.speech_started':
        this.sequence++
        this.speakingInput = true
        this.turnStory = this.callbacks.story()
        this.pendingResponse = false
        this.callbacks.interrupt()
        this.callbacks.phase('listening')
        break
      case 'input_audio_buffer.speech_stopped':
        this.speakingInput = false
        this.callbacks.phase('thinking')
        break
      case 'response.created':
        this.responseActive = true
        this.callbacks.phase('thinking')
        clearTimeout(this.idleTimer)
        break
      case 'response.function_call_arguments.done':
        if (
          event.name === 'news_evidence' &&
          !this.toolCalls.has(event.call_id)
        ) {
          this.toolCalls.add(event.call_id)
          void this.evidence(event.call_id, event.arguments)
        }
        break
      case 'output_audio_buffer.started':
        this.callbacks.interrupt()
        this.callbacks.phase('speaking')
        void this.output
          .play()
          .catch(() =>
            this.callbacks.failed('Tap Play to hear the spoken answer.'),
          )
        break
      case 'output_audio_buffer.stopped':
        this.callbacks.finished()
        this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
        this.armIdleTimer()
        break
      case 'output_audio_buffer.cleared':
        if (this.responseActive) break
        this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
        this.armIdleTimer()
        break
      case 'response.done':
        this.responseActive = false
        if (event.response?.status === 'failed')
          this.callbacks.failed(
            'The voice provider could not answer. Please try again.',
          )
        if (this.pendingResponse) {
          this.pendingResponse = false
          this.createResponse()
        }
        break
      case 'error':
        // Cancelling silence is harmless. Other errors should remain visible.
        if (
          ![
            'response_cancel_not_active',
            'input_audio_buffer_commit_empty',
          ].includes(event.error?.code)
        )
          this.callbacks.failed('Voice response interrupted. Please try again.')
        break
    }
  }

  private async evidence(callId: string, argumentsJson: string) {
    const sequence = this.sequence
    try {
      const args = JSON.parse(argumentsJson)
      const result = await api<Message>(
        `/conversations/${this.conversationId}/realtime-evidence`,
        'POST',
        {
          question: args.question,
          decision: args.decision,
          story_id: this.turnStory,
        },
        this.abort.signal,
      )
      this.send({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: callId,
          output: JSON.stringify({
            evidence: result.text,
            action: result.action,
            story_id: result.story_id,
          }),
        },
      })
      if (this.closed || sequence !== this.sequence) return
      this.callbacks.action(result)
      this.createResponse()
    } catch {
      if (this.closed) return
      this.send({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: callId,
          output: JSON.stringify({
            error:
              'Evidence is unavailable. Briefly apologize in the listener’s language and ask them to repeat. Do not invent an answer.',
          }),
        },
      })
      if (sequence === this.sequence) this.createResponse()
    }
  }

  interrupt() {
    this.sequence++
    this.pendingResponse = false
    if (this.responseActive) this.send({ type: 'response.cancel' })
    this.send({ type: 'output_audio_buffer.clear' })
    this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
  }

  resumeOutput() {
    return this.output.play()
  }

  private armIdleTimer() {
    clearTimeout(this.idleTimer)
    if (!this.micWanted) this.idleTimer = setTimeout(() => this.close(), 120000)
  }

  close() {
    if (this.closed) return
    this.closed = true
    this.micWanted = false
    this.micVersion++
    this.abort.abort()
    clearTimeout(this.idleTimer)
    this.stream?.getTracks().forEach((track) => track.stop())
    this.stream = null
    this.channel?.close()
    this.peer?.close()
    this.outputSource?.disconnect()
    this.outputSource = null
    this.output.pause()
    this.output.srcObject = null
    this.callbacks.microphone(false)
    this.callbacks.phase('idle')
  }
}
