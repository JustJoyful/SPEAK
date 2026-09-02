/**
 * AudioWorklet processor — runs in a dedicated high-priority audio thread.
 * Converts microphone audio into guaranteed 16,000 Hz 16-bit mono Little-Endian PCM
 * and accumulates samples into 2,048-sample chunks (4KB / 128ms at 16kHz) for faster-whisper.
 *
 * Loaded via: audioCtx.audioWorklet.addModule('/audio-processor.js')
 */

const TARGET_SAMPLE_RATE = 16000
const CHUNK_SIZE = 2048

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.targetSampleRate = TARGET_SAMPLE_RATE
    this.chunkSize = CHUNK_SIZE
    this.chunkBuffer = new Int16Array(CHUNK_SIZE)
    this.bufferIndex = 0
    this.sourcePhase = 0
    this.inputRemainder = new Float32Array(0)
  }

  emitChunk() {
    const bufferToTransfer = this.chunkBuffer.buffer
    this.port.postMessage(bufferToTransfer, [bufferToTransfer])
    // CRITICAL: Immediately reallocate fresh memory because transferred buffer is detached
    this.chunkBuffer = new Int16Array(this.chunkSize)
    this.bufferIndex = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true

    const inputChannel = input[0] // Float32Array (typically 128 samples render quantum)
    if (inputChannel.length === 0) return true

    const currentRate = sampleRate

    if (Math.abs(currentRate - this.targetSampleRate) < 1) {
      // Primary Path: Native 16 kHz hardware / OS decimation
      for (let i = 0; i < inputChannel.length; i++) {
        const s = Math.max(-1, Math.min(1, inputChannel[i]))
        this.chunkBuffer[this.bufferIndex++] = s < 0 ? s * 0x8000 : s * 0x7FFF
        if (this.bufferIndex >= this.chunkSize) {
          this.emitChunk()
        }
      }
    } else {
      // Fallback Path: Phase-continuous linear resampling to 16,000 Hz
      const ratio = currentRate / this.targetSampleRate

      let sourceData
      if (this.inputRemainder.length > 0) {
        sourceData = new Float32Array(this.inputRemainder.length + inputChannel.length)
        sourceData.set(this.inputRemainder, 0)
        sourceData.set(inputChannel, this.inputRemainder.length)
      } else {
        sourceData = inputChannel
      }

      while (this.sourcePhase + 1 < sourceData.length) {
        const idx = Math.floor(this.sourcePhase)
        const frac = this.sourcePhase - idx
        const s0 = sourceData[idx]
        const s1 = sourceData[idx + 1]
        const sample = s0 + frac * (s1 - s0)
        const s = Math.max(-1, Math.min(1, sample))
        this.chunkBuffer[this.bufferIndex++] = s < 0 ? s * 0x8000 : s * 0x7FFF
        if (this.bufferIndex >= this.chunkSize) {
          this.emitChunk()
        }
        this.sourcePhase += ratio
      }

      const remainderStart = Math.floor(this.sourcePhase)
      if (remainderStart < sourceData.length) {
        this.inputRemainder = sourceData.slice(remainderStart)
        this.sourcePhase -= remainderStart
      } else {
        this.inputRemainder = new Float32Array(0)
        this.sourcePhase -= sourceData.length
      }
    }

    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
