/**
 * AudioWorklet processor — runs in a dedicated audio thread.
 * Converts microphone audio from any hardware sample rate (e.g. 44.1kHz, 48kHz)
 * into guaranteed 16,000 Hz 16-bit PCM for faster-whisper.
 *
 * Loaded via: audioCtx.audioWorklet.addModule('/audio-processor.js')
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.targetSampleRate = 16000
    this.resampleRatio = sampleRate / this.targetSampleRate
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true

    const channelData = input[0] // Float32Array
    const currentRate = sampleRate

    if (Math.abs(currentRate - this.targetSampleRate) < 1) {
      // Native 16 kHz: Direct 1:1 Int16 conversion
      const pcm16 = new Int16Array(channelData.length)
      for (let i = 0; i < channelData.length; i++) {
        const s = Math.max(-1, Math.min(1, channelData[i]))
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      this.port.postMessage(pcm16.buffer, [pcm16.buffer])
    } else {
      // Hardware sample rate is 44.1kHz, 48kHz, etc.
      // High-quality linear resampling to 16,000 Hz
      const ratio = currentRate / this.targetSampleRate
      const outputLength = Math.floor(channelData.length / ratio)
      if (outputLength <= 0) return true

      const pcm16 = new Int16Array(outputLength)
      for (let i = 0; i < outputLength; i++) {
        const srcIndex = i * ratio
        const indexFloor = Math.floor(srcIndex)
        const indexCeil = Math.min(indexFloor + 1, channelData.length - 1)
        const fraction = srcIndex - indexFloor

        const sample = channelData[indexFloor] * (1 - fraction) + channelData[indexCeil] * fraction
        const s = Math.max(-1, Math.min(1, sample))
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      this.port.postMessage(pcm16.buffer, [pcm16.buffer])
    }

    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
