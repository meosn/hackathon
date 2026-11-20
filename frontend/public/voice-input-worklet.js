/* Capture 20 ms PCM frames without playing the microphone through the speakers. */
class SourceraVoiceInput extends AudioWorkletProcessor {
  constructor(options) {
    super()
    this.rate = options.processorOptions.sampleRate
    this.frame = new Int16Array(Math.round(this.rate / 50))
    this.offset = 0
    this.phase = 0
    this.sum = 0
    this.count = 0
  }
  process(inputs) {
    const samples = inputs[0]?.[0]
    if (samples) for (const value of samples) {
      this.sum += value
      this.count++
      this.phase += this.rate
      if (this.phase >= sampleRate) {
        const sample = Math.max(-1, Math.min(1, this.sum / this.count))
        this.frame[this.offset++] = Math.round(sample * (sample < 0 ? 32768 : 32767))
        this.phase -= sampleRate
        this.sum = 0
        this.count = 0
        if (this.offset === this.frame.length) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer])
          this.frame = new Int16Array(Math.round(this.rate / 50))
          this.offset = 0
        }
      }
    }
    return true
  }
}
registerProcessor('sourcera-voice-input', SourceraVoiceInput)
