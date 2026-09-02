/**
 * useAudioStreamer — real-time microphone → WebSocket PCM streaming
 *
 * Key decisions:
 *  - Lazy user-gesture initialization: Mic hardware & AudioContext are initialized once on the
 *    first doctor click to satisfy modern browser Autoplay Policies.
 *  - Persistent warm stream: The MediaStream and AudioContext stay alive across patient switches
 *    and mic pauses (suspended to save CPU, resumed instantly without hardware DC pop).
 *  - Strict hardware constraints: autoGainControl=false and noiseSuppression=false prevent
 *    browser AGC from surging background noise into Silero VAD during doctor pauses.
 *  - Direct zero-copy dispatch: AudioWorklet PCM buffers are piped directly to WebSocket.send()
 *    with zero mutable accumulator arrays or poison teardown flushes.
 */

import { useState, useRef, useCallback, useEffect } from 'react'
import { medSyncApi } from '@/api/client'

export function useAudioStreamer(token, onTranscript, onToggles, onHotwordsActive, overrideName) {
  const wsRef             = useRef(null)
  const audioCtxRef       = useRef(null)
  const streamRef         = useRef(null)
  const sourceRef         = useRef(null)
  const workletRef        = useRef(null)
  const analyserRef       = useRef(null)
  const isInitializedRef  = useRef(false)
  const isInitializingRef = useRef(false)
  const rafRef            = useRef(null)

  // Keep latest callbacks in refs to avoid stale closures
  const onTranscriptRef     = useRef(onTranscript)
  const onTogglesRef        = useRef(onToggles)
  const onHotwordsActiveRef = useRef(onHotwordsActive)
  useEffect(() => {
    onTranscriptRef.current     = onTranscript
    onTogglesRef.current        = onToggles
    onHotwordsActiveRef.current = onHotwordsActive
  }, [onTranscript, onToggles, onHotwordsActive])

  const [audioLevel, setAudioLevel] = useState(0)
  const [error,      setError]      = useState(null)

  // ── One-time lazy initialization on first user gesture ───────────────────────
  const initAudio = useCallback(async () => {
    if (isInitializedRef.current || isInitializingRef.current) return
    isInitializingRef.current = true

    try {
      // 1. Mic access with strict constraints (no AGC surging)
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          autoGainControl: false,
          noiseSuppression: false,
          echoCancellation: true,
        },
        video: false,
      })
      streamRef.current = stream

      // 2. AudioContext locked to 16 kHz (with fallback if host refuses sampleRate parameter)
      const AudioContext = window.AudioContext || window.webkitAudioContext
      let audioCtx
      try {
        audioCtx = new AudioContext({ sampleRate: 16000 })
      } catch {
        audioCtx = new AudioContext()
      }
      audioCtxRef.current = audioCtx

      const source = audioCtx.createMediaStreamSource(stream)
      sourceRef.current = source

      // 3. Analyser for waveform visualiser
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

      // 4. AudioWorklet node
      await audioCtx.audioWorklet.addModule('/audio-processor.js')
      const worklet = new AudioWorkletNode(audioCtx, 'pcm-processor')
      workletRef.current = worklet

      // Route worklet through silent gain to prevent acoustic feedback to speakers
      const silentGain = audioCtx.createGain()
      silentGain.gain.value = 0
      source.connect(worklet)
      worklet.connect(silentGain)
      silentGain.connect(audioCtx.destination)

      isInitializedRef.current = true
    } finally {
      isInitializingRef.current = false
    }
  }, [])

  // ── stopStreaming ────────────────────────────────────────────────────────────
  const stopStreaming = useCallback(() => {
    // 1. Immediately unbind worklet port to prevent trailing clicks/buffers
    if (workletRef.current) {
      workletRef.current.port.onmessage = null
    }

    // 2. Close WebSocket cleanly (no poison teardown flush)
    if (wsRef.current) {
      const ws = wsRef.current
      wsRef.current = null
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
    }

    // 3. Suspend AudioContext to save CPU without destroying hardware tracks
    if (audioCtxRef.current && audioCtxRef.current.state === 'running') {
      audioCtxRef.current.suspend().catch(() => {})
    }

    setAudioLevel(0)
  }, [])

  // ── sendOverride ────────────────────────────────────────────────────────────
  const sendOverride = useCallback((name) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && name && name.trim()) {
      wsRef.current.send(JSON.stringify({ type: 'OVERRIDE_PATIENT', name: name.trim() }))
    }
  }, [])

  // ── startStreaming ───────────────────────────────────────────────────────────
  const startStreaming = useCallback(async (explicitToken, explicitOverride) => {
    const currentToken = explicitToken || token
    const activeOverride = explicitOverride !== undefined ? explicitOverride : overrideName
    try {
      setError(null)

      // 1. Lazy init on first user gesture
      if (!isInitializedRef.current) {
        await initAudio()
      }

      // 2. Resume AudioContext
      if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
        await audioCtxRef.current.resume()
      }

      // 3. Clean up any previous socket before creating a new one
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.onerror = null
        wsRef.current.onmessage = null
        wsRef.current.close()
        wsRef.current = null
      }

      // 4. Open WebSocket for this specific patient encounter
      let wsUrl = medSyncApi.baseURL.replace(/^http/, 'ws')
        + `/encounter/${currentToken}/audio-stream?role=doctor`
      if (activeOverride && activeOverride.trim()) {
        wsUrl += `&override_name=${encodeURIComponent(activeOverride.trim())}`
      }
      const ws = new WebSocket(wsUrl)
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'TRANSCRIPT_CHUNK') {
            if (data.text) onTranscriptRef.current?.(data.text)
            if (data.ui_toggles && Object.keys(data.ui_toggles).length) {
              onTogglesRef.current?.(data.ui_toggles)
            }
          } else if (data.type === 'HOTWORDS_ACTIVE') {
            if (data.hotwords) onHotwordsActiveRef.current?.(data.hotwords)
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

      // Wait for WS to open before attaching the worklet port
      await new Promise((resolve, reject) => {
        ws.onopen = resolve
        const origClose = ws.onclose
        ws.onclose = (e) => {
          if (origClose) origClose(e)
          reject(new Error('WS closed before open'))
        }
      })
      ws.onclose = () => setAudioLevel(0)

      // 5. Pipe PCM chunks directly to WebSocket (zero mutable accumulator, zero latency)
      if (workletRef.current) {
        workletRef.current.port.onmessage = (event) => {
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(event.data)
          }
        }
      }

    } catch (err) {
      console.error('[STT] Failed to start:', err)
      setError(err.message || 'Microphone access denied')
      stopStreaming()
    }
  }, [token, overrideName, initAudio, stopStreaming])

  // Full unmount cleanup (hardware release on page exit only)
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      if (workletRef.current) {
        workletRef.current.port.onmessage = null
        workletRef.current.disconnect()
      }
      if (analyserRef.current) analyserRef.current.disconnect()
      if (sourceRef.current) sourceRef.current.disconnect()
      if (audioCtxRef.current) audioCtxRef.current.close().catch(() => {})
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop())
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [])

  return { startStreaming, stopStreaming, audioLevel, error, sendOverride }
}

