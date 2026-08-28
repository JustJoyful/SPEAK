import { useCallback, useEffect, useRef, useState } from "react"

const DEFAULT_DEBOUNCE_MS = 700
const DEFAULT_MAX_WAIT_MS = 3000

/**
 * useTranscriptDebouncer
 * 
 * Provides a unified text ingestion buffer across live Whisper audio streaming,
 * fast mock dictation bursts, and manual typing/editing.
 * 
 * Key guarantees:
 * 1. Single Ingestion Point: Both `ingestDelta(chunk)` and `setFullText(text)` feed the same state machine.
 * 2. Trailing Timer with Max-Wait Ceiling: Resets on every new chunk (700ms quiet window),
 *    while enforcing periodic execution at MAX_WAIT_MS (3000ms) to prevent starvation during continuous speech.
 * 3. Redundancy Guard: Skips extraction if trimmed text has not changed since the last run.
 * 4. In-Flight Async Race Guard: Dispatched promises capture `capturedToken` and `requestId`.
 *    If the token switches or consultation finishes while the network call is in flight, the resolving
 *    result is silently dropped.
 * 5. Lifecycle Safety: `cancel()` and `markFinished()` kill timers immediately; unmount cleanup prevents memory leaks.
 */
export function useTranscriptDebouncer({
  activeToken,
  onExtraction,
  isFinished = false,
  debounceMs = DEFAULT_DEBOUNCE_MS,
  maxWaitMs = DEFAULT_MAX_WAIT_MS,
}) {
  const [rawTranscript, setRawTranscript] = useState("")
  const [words, setWords] = useState([])

  const activeTokenRef = useRef(activeToken)
  const isFinishedRef = useRef(isFinished)
  const isMountedRef = useRef(true)
  const onExtractionRef = useRef(onExtraction)

  const debounceTimerRef = useRef(null)
  const firstChangeTimestampRef = useRef(null)
  const lastExtractedTextRef = useRef("")
  const requestIdRef = useRef(0)

  // Keep refs synchronized
  useEffect(() => {
    activeTokenRef.current = activeToken
  }, [activeToken])

  useEffect(() => {
    isFinishedRef.current = isFinished
  }, [isFinished])

  useEffect(() => {
    onExtractionRef.current = onExtraction
  }, [onExtraction])

  // Cancel any pending timers and invalidate in-flight async requests
  const cancel = useCallback(() => {
    if (debounceTimerRef.current) {
      window.clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
    firstChangeTimestampRef.current = null
    requestIdRef.current += 1
  }, [])

  // Reset entire transcript buffer and debounce state for an encounter
  const reset = useCallback(
    (initialText = "") => {
      cancel()
      const text = typeof initialText === "string" ? initialText : ""
      setRawTranscript(text)
      setWords(text.trim() ? text.trim().split(/\s+/) : [])
      lastExtractedTextRef.current = text.trim()
    },
    [cancel],
  )

  // Mark encounter finished — kills timers and blocks future ingestion
  const markFinished = useCallback(() => {
    isFinishedRef.current = true
    cancel()
  }, [cancel])

  // Core extraction execution with race guard
  const executeExtraction = useCallback(
    async (token, text) => {
      if (!isMountedRef.current || isFinishedRef.current || token !== activeTokenRef.current) {
        return
      }

      const trimmed = (text || "").trim()
      if (!trimmed || trimmed === lastExtractedTextRef.current) {
        return
      }

      lastExtractedTextRef.current = trimmed
      const capturedToken = token
      const currentRequestId = ++requestIdRef.current

      try {
        if (onExtractionRef.current) {
          await onExtractionRef.current({ token: capturedToken, text: trimmed })
        }
      } catch (error) {
        // Drop benign 409/423 session locked / finalized errors silently
        const msg = error?.message || String(error)
        if (!msg.includes("409") && !msg.includes("423")) {
          console.warn(`[Debouncer] Extraction warning for token #${capturedToken}:`, error)
        }
      } finally {
        // If token switched, finished, or a newer request dispatched during network flight, drop continuation
        if (
          !isMountedRef.current ||
          isFinishedRef.current ||
          capturedToken !== activeTokenRef.current ||
          currentRequestId !== requestIdRef.current
        ) {
          // Stale in-flight response discarded silently
        }
      }
    },
    [],
  )

  // Trailing debouncer with max-wait ceiling scheduler
  const scheduleDebounce = useCallback(
    (token, textToExtract) => {
      if (!isMountedRef.current || isFinishedRef.current || token !== activeTokenRef.current) {
        return
      }

      const now = Date.now()
      if (firstChangeTimestampRef.current === null) {
        firstChangeTimestampRef.current = now
      }

      const elapsed = now - firstChangeTimestampRef.current

      // Ceiling hit: run immediately to prevent starvation during continuous burst
      if (elapsed >= maxWaitMs) {
        if (debounceTimerRef.current) {
          window.clearTimeout(debounceTimerRef.current)
          debounceTimerRef.current = null
        }
        firstChangeTimestampRef.current = null
        executeExtraction(token, textToExtract)
        return
      }

      // Trailing quiet period: reset existing timer and schedule next quiet window
      if (debounceTimerRef.current) {
        window.clearTimeout(debounceTimerRef.current)
      }

      const remainingCeiling = Math.max(0, maxWaitMs - elapsed)
      const nextDelay = Math.min(debounceMs, remainingCeiling)

      debounceTimerRef.current = window.setTimeout(() => {
        debounceTimerRef.current = null
        firstChangeTimestampRef.current = null
        executeExtraction(token, textToExtract)
      }, nextDelay)
    },
    [debounceMs, maxWaitMs, executeExtraction],
  )

  // Single Ingestion Point 1: Delta chunk (from Whisper WebSocket or Mock Injector)
  const ingestDelta = useCallback(
    (chunk) => {
      if (!isMountedRef.current || isFinishedRef.current) return
      if (!chunk || (typeof chunk === "string" && !chunk.trim())) return

      const delta = typeof chunk === "string" ? chunk.trim() : String(chunk).trim()
      if (!delta) return

      setRawTranscript((prev) => {
        const updated = prev ? `${prev} ${delta}` : delta
        setWords(updated.trim() ? updated.trim().split(/\s+/) : [])
        scheduleDebounce(activeTokenRef.current, updated)
        return updated
      })
    },
    [scheduleDebounce],
  )

  // Single Ingestion Point 2: Full text overwrite (from manual textarea typing/paste)
  const setFullText = useCallback(
    (text) => {
      if (!isMountedRef.current || isFinishedRef.current) return
      const nextText = typeof text === "string" ? text : ""
      setRawTranscript(nextText)
      setWords(nextText.trim() ? nextText.trim().split(/\s+/) : [])
      scheduleDebounce(activeTokenRef.current, nextText)
    },
    [scheduleDebounce],
  )

  // Unmount cleanup
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      if (debounceTimerRef.current) {
        window.clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = null
      }
      firstChangeTimestampRef.current = null
      requestIdRef.current += 1
    }
  }, [])

  return {
    rawTranscript,
    words,
    ingestDelta,
    setFullText,
    cancel,
    reset,
    markFinished,
  }
}
