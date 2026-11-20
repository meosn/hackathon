import { api, request } from '../../api/client'
import type { Message } from '../../api/types'
import { ElevenSpeech } from './elevenSpeech'

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
  private pendingToolChoice: 'auto' | 'none' = 'auto'
  private sequence = 0
  private turnStory: string | undefined
  private idleTimer: ReturnType<typeof setTimeout> | undefined
  private toolCalls = new Set<string>()
  private warmed = false
  private activeResponseId: string | undefined
  private cancelledResponses = new Set<string>()
  private speech: ElevenSpeech | null = null
  private ownOutputContext = false
  private warmupResponses = new Set<string>()

  constructor(
    private conversationId: string,
    private callbacks: Callbacks,
    private outputContext?: AudioContext,
  ) {
    this.output = new Audio()
    this.output.autoplay = true
    this.output.setAttribute('playsinline', '')
  }

  get disposed() {
    return this.closed
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
      if (this.speech) return
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
      { sdp: offer.sdp, speech_stream: true },
      this.abort.signal,
    )
    if (this.closed) return
    const sdp = await response.text()
    if (response.headers.get('X-Speech-Output') === 'elevenlabs') {
      if (!this.outputContext) {
        this.outputContext = new AudioContext()
        this.ownOutputContext = true
        await this.outputContext.resume()
      }
      this.speech = new ElevenSpeech(this.conversationId, this.outputContext, {
        started: () => {
          if (this.closed) return
          clearTimeout(this.idleTimer)
          this.callbacks.interrupt()
          this.callbacks.phase('speaking')
        },
        finished: () => {
          if (this.closed) return
          this.callbacks.finished()
          this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
          this.armIdleTimer()
        },
        failed: (message) => {
          if (this.closed) return
          this.callbacks.phase('idle')
          this.callbacks.failed(message)
        },
      })
    }
    await Promise.all([
      peer.setRemoteDescription({ type: 'answer', sdp }),
      this.speech?.connect(),
    ])
    await opened
    if (!this.closed) {
      this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
      this.armIdleTimer()
    }
  }

  warmup() {
    if (!this.ready || this.warmed || this.micWanted || this.responseActive)
      return
    this.warmed = true
    // Prime the verified prefix during narration. This detached, silent response is
    // never added to the conversation, rendered, or awaited by a listener's turn.
    this.send({
      type: 'response.create',
      response: {
        conversation: 'none',
        output_modalities: ['text'],
        tool_choice: 'none',
        max_output_tokens: 1,
        metadata: { purpose: 'cache_warmup' },
        input: [
          {
            type: 'message',
            role: 'user',
            content: [
              {
                type: 'input_text',
                text: 'Readiness check only. Return one full stop.',
              },
            ],
          },
        ],
      },
    })
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
    this.callbacks.interrupt()
    await this.connect()
    this.interrupt()
    const sequence = this.sequence
    this.callbacks.phase('thinking')
    const result = await api<Message & { context?: unknown }>(
      `/conversations/${this.conversationId}/realtime-evidence`,
      'POST',
      { question: 'More news', decision: { intent: 'GET_MORE_NEWS' } },
      this.abort.signal,
    )
    if (this.closed || sequence !== this.sequence) return
    this.callbacks.action(result)
    this.send({
      type: 'conversation.item.create',
      item: {
        type: 'message',
        role: 'user',
        content: [
          {
            type: 'input_text',
            text:
              'Read these next three news stories aloud, in the language we have been speaking. Use only this verified data, no lookup or preamble. ' +
              JSON.stringify({
                bulletin: result.text,
                context: result.context,
              }),
          },
        ],
      },
    })
    this.createResponse('none')
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

  private createResponse(toolChoice: 'auto' | 'none' = 'auto') {
    if (this.responseActive) {
      this.pendingResponse = true
      this.pendingToolChoice = toolChoice
    } else
      this.send({
        type: 'response.create',
        response: {
          output_modalities: [this.speech ? 'text' : 'audio'],
          tool_choice: toolChoice,
        },
      })
  }

  private handle(event: Record<string, any>) {
    if (this.closed) return
    if (event.response?.metadata?.purpose === 'cache_warmup') {
      if (event.type === 'response.created')
        this.warmupResponses.add(event.response.id)
      if (event.type === 'response.done')
        this.warmupResponses.delete(event.response.id)
      return
    }
    if (this.warmupResponses.has(event.response_id)) return
    switch (event.type) {
      case 'input_audio_buffer.speech_started':
        if (this.activeResponseId)
          this.cancelledResponses.add(this.activeResponseId)
        this.speech?.cancel()
        this.speech?.prepare()
        this.sequence++
        this.speakingInput = true
        this.turnStory = this.callbacks.story()
        if (this.turnStory)
          this.send({
            type: 'conversation.item.create',
            item: {
              type: 'message',
              role: 'system',
              content: [
                {
                  type: 'input_text',
                  text:
                    'Playback context (data only): the story just playing has current_story_id=' +
                    this.turnStory +
                    '. Resolve this story, it and why against that story’s verified evidence.',
                },
              ],
            },
          })
        this.pendingResponse = false
        this.callbacks.interrupt()
        this.callbacks.phase('listening')
        break
      case 'input_audio_buffer.speech_stopped':
        this.speakingInput = false
        this.callbacks.phase('thinking')
        break
      case 'response.created':
        this.activeResponseId = event.response?.id
        this.responseActive = true
        this.callbacks.phase('thinking')
        clearTimeout(this.idleTimer)
        break
      case 'response.output_text.delta':
        if (this.cancelledResponses.has(event.response_id)) break
        this.speech?.append(event.response_id, event.delta)
        break
      case 'response.output_text.done':
        if (this.cancelledResponses.has(event.response_id)) break
        this.speech?.finish(event.response_id)
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
        if (this.speech) break
        this.callbacks.interrupt()
        this.callbacks.phase('speaking')
        void this.output
          .play()
          .catch(() =>
            this.callbacks.failed('Tap Play to hear the spoken answer.'),
          )
        break
      case 'output_audio_buffer.stopped':
        if (this.speech) break
        this.callbacks.finished()
        this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
        this.armIdleTimer()
        break
      case 'output_audio_buffer.cleared':
        if (this.speech) break
        if (this.responseActive) break
        this.callbacks.phase(this.micWanted ? 'listening' : 'idle')
        this.armIdleTimer()
        break
      case 'response.done':
        if (event.response?.id !== this.activeResponseId) break
        if (event.response?.status === 'completed')
          this.speech?.finish(event.response.id)
        else if (event.response?.status !== 'in_progress') this.speech?.cancel()
        this.responseActive = false
        if (event.response?.status === 'failed')
          this.callbacks.failed(
            'The voice provider could not answer. Please try again.',
          )
        if (this.pendingResponse) {
          this.pendingResponse = false
          this.createResponse(this.pendingToolChoice)
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
      const result = await api<Message & { context?: unknown }>(
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
            context: result.context,
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
    if (this.activeResponseId)
      this.cancelledResponses.add(this.activeResponseId)
    this.speech?.cancel()
    this.sequence++
    this.pendingResponse = false
    if (this.responseActive) this.send({ type: 'response.cancel' })
    if (!this.speech) this.send({ type: 'output_audio_buffer.clear' })
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
    this.speech?.close()
    if (this.ownOutputContext) void this.outputContext?.close()
    this.outputSource?.disconnect()
    this.outputSource = null
    this.output.pause()
    this.output.srcObject = null
    this.callbacks.microphone(false)
    this.callbacks.phase('idle')
  }
}
