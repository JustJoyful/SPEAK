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

// Accumulate PCM bytes here; ship to backend every ~0.5 s (16 000 bytes at 16 kHz int16)
const CHUNK_BYTES = 16000

export function useAudioStreamer(token, onTranscript, onToggles) {
  const wsRef       = useRef(null)
  const audioCtxRef = useRef(null)
  const streamRef   = useRef(null)
  const workletRef  = useRef(null)
  const analyserRef = useRef(null)
  const pendingRef  = useRef(new Uint8Array(0))
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
      if (wsRef.current.readyState === WebSocket.OPEN) {
        // Flush any remaining buffer before closing
        if (pendingRef.current && pendingRef.current.length > 0) {
          try {
            wsRef.current.send(pendingRef.current.buffer)
          } catch (e) {
            // Ignore send error on teardown
          }
        }
        wsRef.current.close()
      }
      wsRef.current = null
    }
    pendingRef.current = new Uint8Array(0)
    setAudioLevel(0)
  }, [])

  // ── start ────────────────────────────────────────────────────────────────────
  const startStreaming = useCallback(async () => {
    try {
      setError(null)
      pendingRef.current = new Uint8Array(0)

      // 1. Mic access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
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
        const origClose = ws.onclose
        ws.onclose = (e) => { origClose && origClose(e); reject(new Error('WS closed before open')) }
      })
      ws.onclose = () => setAudioLevel(0)

      // 5. AudioWorklet — replaces deprecated ScriptProcessorNode
      await audioCtx.audioWorklet.addModule('/audio-processor.js')
      const worklet = new AudioWorkletNode(audioCtx, 'pcm-processor')
      workletRef.current = worklet

      worklet.port.onmessage = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return

        const incoming = new Uint8Array(e.data)
        const current = pendingRef.current
        const merged = new Uint8Array(current.length + incoming.length)
        merged.set(current)
        merged.set(incoming, current.length)
        pendingRef.current = merged

        if (pendingRef.current.length >= CHUNK_BYTES) {
          ws.send(pendingRef.current.slice(0, CHUNK_BYTES).buffer)
          pendingRef.current = pendingRef.current.slice(CHUNK_BYTES)
        }
      }

      // Connect source to worklet and route to a silent gain node to prevent speaker feedback
      const silentGain = audioCtx.createGain()
      silentGain.gain.value = 0
      source.connect(worklet)
      worklet.connect(silentGain)
      silentGain.connect(audioCtx.destination)

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
