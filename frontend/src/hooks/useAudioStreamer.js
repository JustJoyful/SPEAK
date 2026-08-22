/**
 * useAudioStreamer — real-time microphone → WebSocket PCM streaming
 *
 * Key decisions:
 *  - AudioContext is forced to 16 000 Hz to match faster-whisper's expected sample rate.
 *    Without this the browser captures at 44 100 / 48 000 Hz and Whisper hears slow,
 *    pitched-down audio and produces garbage transcripts.
 *  - AudioWorklet replaces the deprecated ScriptProcessorNode (removed in Chrome 115+).
 *    The worklet runs in a dedicated audio-rendering thread and posts int16 PCM buffers
 *    back to the main thread zero-copy via transferable ArrayBuffers.
 *  - The WebSocket sends raw binary PCM frames. Auth is via ?role=doctor query param
 *    because the browser WebSocket API cannot send custom HTTP headers.
 */

import { useState, useRef, useCallback, useEffect } from 'react'
import { medSyncApi } from '@/api/client'

// Accumulate PCM bytes here; ship to backend every ~1 s (32 000 bytes at 16 kHz int16)
const CHUNK_BYTES = 32000

export function useAudioStreamer(token, onTranscript, onToggles) {
  const wsRef       = useRef(null)
  const audioCtxRef = useRef(null)
  const streamRef   = useRef(null)
  const workletRef  = useRef(null)
  const analyserRef = useRef(null)
  const bufferRef   = useRef([])        // Array of Int16Array chunks pending send
  const rafRef      = useRef(null)

  const [audioLevel, setAudioLevel] = useState(0)
  const [error,      setError]      = useState(null)

  // ── stop ────────────────────────────────────────────────────────────────────
  const stopStreaming = useCallback(() => {
    if (rafRef.current)      { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (workletRef.current)  { workletRef.current.disconnect(); workletRef.current = null }
    if (analyserRef.current) { analyserRef.current.disconnect(); analyserRef.current = null }
    if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null }
    if (streamRef.current)   { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null }
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) wsRef.current.close()
      wsRef.current = null
    }
    bufferRef.current = []
    setAudioLevel(0)
  }, [])

  // ── start ────────────────────────────────────────────────────────────────────
  const startStreaming = useCallback(async () => {
    try {
      setError(null)

      // 1. Mic access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        video: false,
      })
      streamRef.current = stream

      // 2. AudioContext forced to 16 kHz — browser resamples for us
      const AudioContext = window.AudioContext || window.webkitAudioContext
      const audioCtx = new AudioContext({ sampleRate: 16000 })
      audioCtxRef.current = audioCtx

      // Resume context if browser suspended it (autoplay policy)
      if (audioCtx.state === 'suspended') await audioCtx.resume()

      const source = audioCtx.createMediaStreamSource(stream)

      // 3. Analyser for the waveform visualiser (UI only)
      const analyser = audioCtx.createAnalyser()
      analyser.fftSize = 256
      source.connect(analyser)
      analyserRef.current = analyser

      const freqData = new Uint8Array(analyser.frequencyBinCount)
      const updateLevel = () => {
        if (!analyserRef.current) return
        analyser.getByteFrequencyData(freqData)
        let sum = 0
        for (let i = 0; i < freqData.length; i++) sum += freqData[i]
        setAudioLevel(sum / freqData.length)
        rafRef.current = requestAnimationFrame(updateLevel)
      }
      rafRef.current = requestAnimationFrame(updateLevel)

      // 4. WebSocket — must be open before we start sending audio
      const wsUrl = medSyncApi.baseURL.replace(/^http/, 'ws')
        + `/encounter/${token}/audio-stream?role=doctor`
      const ws = new WebSocket(wsUrl)
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'TRANSCRIPT_CHUNK') {
            if (data.text)       onTranscript(data.text)
            if (data.ui_toggles && Object.keys(data.ui_toggles).length)
              onToggles(data.ui_toggles)
          }
        } catch (e) {
          console.error('[STT] WS message parse error', e)
        }
      }

      ws.onerror = () => {
        setError('WebSocket connection failed — check backend is running')
        stopStreaming()
      }

      ws.onclose = () => setAudioLevel(0)

      // Wait for WS to open before attaching the worklet
      await new Promise((resolve, reject) => {
        ws.onopen  = resolve
        // If it closes before opening it's a hard error
        const origClose = ws.onclose
        ws.onclose = (e) => { origClose && origClose(e); reject(new Error('WS closed before open')) }
      })
      // Restore the real onclose handler now that we're open
      ws.onclose = () => setAudioLevel(0)

      // 5. AudioWorklet — replaces deprecated ScriptProcessorNode
      await audioCtx.audioWorklet.addModule('/audio-processor.js')
      const worklet = new AudioWorkletNode(audioCtx, 'pcm-processor')
      workletRef.current = worklet

      // Accumulate PCM chunks and ship in ~1 s batches to match backend buffer size
      let pending = new Uint8Array(0)
      worklet.port.onmessage = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return

        const incoming = new Uint8Array(e.data)
        // Append to pending
        const merged = new Uint8Array(pending.length + incoming.length)
        merged.set(pending)
        merged.set(incoming, pending.length)
        pending = merged

        if (pending.length >= CHUNK_BYTES) {
          ws.send(pending.slice(0, CHUNK_BYTES).buffer)
          pending = pending.slice(CHUNK_BYTES)
        }
      }

      source.connect(worklet)
      worklet.connect(audioCtx.destination) // Required: worklet must be connected to output graph

    } catch (err) {
      console.error('[STT] Failed to start:', err)
      setError(err.message || 'Microphone access denied')
      stopStreaming()
    }
  }, [token, onTranscript, onToggles, stopStreaming])

  // Cleanup on unmount
  useEffect(() => () => stopStreaming(), [stopStreaming])

  return { startStreaming, stopStreaming, audioLevel, error }
}
