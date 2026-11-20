/** Hold one microphone stream and submit only detected speech turns. */
export class LiveMicrophone {
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private recorder: MediaRecorder | null = null
  private timer: ReturnType<typeof setInterval> | null = null
  private chunks: Blob[] = []
  private speaking = false
  private active = false
  private started = 0
  private voiced = 0
  private silence = 0
  private candidate = 0

  constructor(
    private interrupt: () => void,
    private utterance: (blob: Blob) => void,
    private failed: (message: string) => void,
  ) {}

  async start() {
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === 'undefined'
    )
      throw Error(
        'Voice conversation needs microphone access on localhost or HTTPS.',
      )
    this.active = true
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    })
    if (!this.active) {
      stream.getTracks().forEach((t) => t.stop())
      return
    }
    this.stream = stream
    const context = (this.context = new AudioContext())
    await context.resume()
    const source = context.createMediaStreamSource(stream)
    const meter = context.createAnalyser()
    meter.fftSize = 1024
    source.connect(meter)
    const samples = new Float32Array(meter.fftSize)
    const supported = [
      'audio/webm;codecs=opus',
      'audio/mp4',
      'audio/ogg;codecs=opus',
    ].find((t) => MediaRecorder.isTypeSupported(t))
    const recorder = (this.recorder = new MediaRecorder(
      stream,
      supported ? { mimeType: supported } : undefined,
    ))
    recorder.ondataavailable = (e) => {
      if (e.data.size) this.chunks.push(e.data)
    }
    recorder.onerror = () => {
      this.stop()
      this.failed('Microphone recording stopped. Enable it again to continue.')
    }
    recorder.onstop = () => {
      const blob = new Blob(this.chunks, { type: recorder.mimeType })
      this.chunks = []
      const submit = this.speaking && this.voiced >= 240
      this.speaking = false
      this.voiced = 0
      this.candidate = 0
      this.silence = 0
      if (this.active && submit) this.utterance(blob)
      if (this.active) {
        this.started = performance.now()
        recorder.start(100)
      }
    }
    // Restart idle windows so encoded headers stay valid and memory stays bounded.
    this.started = performance.now()
    recorder.start(100)
    this.timer = setInterval(() => {
      if (!this.active || recorder.state !== 'recording') return
      meter.getFloatTimeDomainData(samples)
      const rms = Math.sqrt(
        samples.reduce((sum, v) => sum + v * v, 0) / samples.length,
      )
      const speech = rms > 0.025
      if (speech) {
        this.candidate += 40
        this.silence = 0
        if (!this.speaking && this.candidate >= 160) {
          this.speaking = true
          this.interrupt()
        }
        if (this.speaking) this.voiced += 40
      } else {
        this.candidate = 0
        if (this.speaking) this.silence += 40
      }
      const elapsed = performance.now() - this.started
      if (
        (this.speaking && (this.silence >= 760 || elapsed >= 20000)) ||
        (!this.speaking && elapsed >= 4000)
      )
        recorder.stop()
    }, 40)
  }

  stop() {
    this.active = false
    if (this.timer) clearInterval(this.timer)
    if (this.recorder?.state === 'recording') {
      this.recorder.onstop = null
      this.recorder.stop()
    }
    this.stream?.getTracks().forEach((t) => t.stop())
    void this.context?.close()
    this.stream = null
    this.context = null
    this.chunks = []
  }
}
