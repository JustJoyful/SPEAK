/**
 * AudioWorklet processor — runs in a dedicated audio thread.
 * Receives raw float32 samples from the mic, converts them to int16,
 * and posts the ArrayBuffer back to the main thread.
 *
 * Loaded via: audioCtx.audioWorklet.addModule('/audio-processor.js')
 */
class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true

    const channelData = input[0]
    const pcm16 = new Int16Array(channelData.length)
    for (let i = 0; i < channelData.length; i++) {
      const s = Math.max(-1, Math.min(1, channelData[i]))
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    // Transfer the buffer (zero-copy) to main thread
    this.port.postMessage(pcm16.buffer, [pcm16.buffer])
    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
