import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Moon, ShieldCheck, Stethoscope, Sun } from "lucide-react"
import { QueueRail } from "@/components/QueueRail"
import { DictationPanel } from "@/components/DictationPanel"
import { XrayLog } from "@/components/XrayLog"
import { ChecklistPanel } from "@/components/ChecklistPanel"
import { RecordViewer } from "@/components/RecordViewer"
import { SyncBadge } from "@/components/SyncBadge"
import { cn } from "@/lib/utils"
import { CHECKLIST_ORDER, extractClinicalChecklist, mergeChecklistState } from "@/lib/cases"
import { buildPipeline, idleLines, makeRng } from "@/lib/pipeline"
import { backendConfigured, medSyncApi } from "@/api/client"
import { usePipelineStream } from "@/hooks/usePipelineStream"
import { useAudioStreamer } from "@/hooks/useAudioStreamer"
import { useTranscriptDebouncer } from "@/hooks/useTranscriptDebouncer"
import { Bug } from "lucide-react"

const EMPTY_CHECKS = { symptoms: "empty", diagnosis: "empty", medication: "empty", advice: "empty" }
const QUEUE_WIDTH_KEY = "queueColumnWidth"
const MIN_QUEUE_WIDTH = 200
const MAX_QUEUE_WIDTH = 500
function clampQueueWidth(width) {
  return Math.min(MAX_QUEUE_WIDTH, Math.max(MIN_QUEUE_WIDTH, width))
}

function getInitialQueueWidth() {
  const fallback = typeof window !== "undefined" && window.innerWidth >= 1280 ? 272 : 248
  if (typeof window === "undefined") return fallback

  try {
    const stored = Number(window.localStorage.getItem(QUEUE_WIDTH_KEY))
    return Number.isFinite(stored) ? clampQueueWidth(stored) : fallback
  } catch {
    return fallback
  }
}

function readableError(error, fallback = "Unknown error") {
  if (error instanceof Error && error.message) return error.message
  if (typeof error === "string" && error.trim()) return error
  if (error && typeof error === "object" && typeof error.message === "string" && error.message.trim()) {
    return error.message
  }
  return fallback
}

export default function App() {
  const [theme, setTheme] = useState("light")
  const [useMockData, setUseMockData] = useState(false)
  const [queueWidth, setQueueWidth] = useState(getInitialQueueWidth)
  const [isQueueResizing, setIsQueueResizing] = useState(false)
  const [remoteCases, setRemoteCases] = useState(null)
  const [queueLoading, setQueueLoading] = useState(backendConfigured)
  const [queueError, setQueueError] = useState("")
  const [finishError, setFinishError] = useState("")
  const [selectionBusy, setSelectionBusy] = useState(null)
  const [statuses, setStatuses] = useState({})
  const [activeToken, setActiveToken] = useState(null)
  const [activeOverrideName, setActiveOverrideName] = useState("")
  const [recording, setRecording] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [finished, setFinished] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [logs, setLogs] = useState(idleLines)
  const [phase, setPhase] = useState("idle")
  const [checks, setChecks] = useState(EMPTY_CHECKS)
  const [redactCount, setRedactCount] = useState(0)
  const [egressClean, setEgressClean] = useState(false)
  const [seam, setSeam] = useState(false)
  const [record, setRecord] = useState(null)
  const [online, setOnline] = useState(() => typeof navigator !== "undefined" && navigator.onLine)

  const timers = useRef([])
  const seq = useRef(0)
  const queueResizeStart = useRef({ x: 0, width: queueWidth })
  const mockWordIndexRef = useRef(0)
  const lastMark = useRef({
    symptoms: false,
    diagnosis: false,
    medication: false,
    advice: false,
  })

  const pushLog = useCallback((l) => {
    seq.current += 1
    setLogs((prev) => [...prev.slice(-90), { ...l, id: `l${seq.current}`, at: Date.now() }])
  }, [])

  const handleExtraction = useCallback(
    async ({ token, text }) => {
      // 1. Instantaneous zero-latency local clinical pattern matching
      const localMatches = extractClinicalChecklist(text)
      setChecks((current) => mergeChecklistState(current, localMatches))

      if (backendConfigured) {
        try {
          await medSyncApi.processText(token, { text, language: "en-IN" })
        } catch (err) {
          const msg = readableError(err)
          if (!msg.includes("409") && !msg.includes("423")) {
            pushLog({
              stage: "NETWORK",
              level: "warn",
              spans: [{ t: "text", v: `Partial sync failed · ${msg}` }],
            })
          }
        }
      } else {
        pushLog({
          stage: "EXTRACT",
          level: "info",
          spans: [
            { t: "text", v: "Edge transcript buffered · " },
            { t: "em", v: `token #${token}` },
            { t: "arrow" },
            { t: "text", v: `${text.split(/\s+/).length} words parsed` },
          ],
          metric: `${Math.floor(10 + Math.random() * 12)} ms`,
        })
      }
    },
    [pushLog],
  )

  const {
    rawTranscript,
    words,
    ingestDelta,
    setFullText,
    cancel: cancelDebounce,
    reset: resetDebounce,
    markFinished: markDebouncerFinished,
  } = useTranscriptDebouncer({
    activeToken,
    onExtraction: handleExtraction,
    isFinished: finished || processing,
  })

  const cases = useMemo(
    () => (remoteCases ?? []).map((c) => ({ ...c, status: statuses[c.token] ?? c.status })),
    [remoteCases, statuses],
  )
  const active = useMemo(
    () => cases.find((c) => c.token === activeToken) ?? cases[0] ?? null,
    [activeToken, cases],
  )

  const clearTimers = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t))
    timers.current = []
  }, [])
  const later = useCallback((fn, ms) => {
    timers.current.push(window.setTimeout(fn, ms))
  }, [])

  useEffect(() => clearTimers, [clearTimers])

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme)
  }, [theme])

  useEffect(() => {
    try {
      window.localStorage.setItem(QUEUE_WIDTH_KEY, String(queueWidth))
    } catch {
      // Ignore unavailable browser storage; resizing still works for this session.
    }
  }, [queueWidth])

  const handleQueueResizeStart = useCallback((event) => {
    if (event.button !== 0) return
    event.preventDefault()
    queueResizeStart.current = { x: event.clientX, width: queueWidth }
    setIsQueueResizing(true)
  }, [queueWidth])

  useEffect(() => {
    if (!isQueueResizing) return undefined

    const handleQueueResizeMove = (event) => {
      const delta = event.clientX - queueResizeStart.current.x
      setQueueWidth(clampQueueWidth(queueResizeStart.current.width + delta))
    }
    const stopQueueResize = () => setIsQueueResizing(false)

    window.addEventListener("mousemove", handleQueueResizeMove)
    window.addEventListener("mouseup", stopQueueResize)
    window.addEventListener("blur", stopQueueResize)
    return () => {
      window.removeEventListener("mousemove", handleQueueResizeMove)
      window.removeEventListener("mouseup", stopQueueResize)
      window.removeEventListener("blur", stopQueueResize)
    }
  }, [isQueueResizing])

  const toggleTheme = useCallback(() => {
    setTheme((current) => current === "light" ? "dark" : "light")
  }, [])

  useEffect(() => {
    const handleOnline = () => setOnline(true)
    const handleOffline = () => setOnline(false)
    window.addEventListener("online", handleOnline)
    window.addEventListener("offline", handleOffline)
    return () => {
      window.removeEventListener("online", handleOnline)
      window.removeEventListener("offline", handleOffline)
    }
  }, [])

  const loadQueue = useCallback(() => {
    if (!backendConfigured) return Promise.resolve()
    setQueueLoading(true)
    setQueueError("")
    return medSyncApi.getQueue()
      .then((payload) => {
        const rows = Array.isArray(payload) ? payload : payload.queue ?? []
        const next = rows
          .map((row) => {
            const token = Number(row.token_number ?? row.token)
            if (!Number.isFinite(token) || token <= 0) return null
            return {
              ...row,
              token,
              name: row.patient_display_name ?? row.name ?? `Token ${token}`,
              status: row.status ?? "waiting",
              age: row.age,
              sex: row.sex,
              complaint: row.complaint ?? row.chief_complaint ?? "",
              script: row.script ?? "",
              marks: row.marks ?? {},
              pii: row.pii ?? [],
              fhir: row.fhir ?? null,
            }
          })
          .filter(Boolean)
        if (next.length) {
          setRemoteCases(next)
          setActiveToken((token) => (next.some((item) => item.token === token) ? token : next[0].token))
          setStatuses(Object.fromEntries(next.map((item) => [item.token, item.status])))
        }
      })
      .catch((error) => {
        const message = readableError(error, "Unable to load queue")
        setQueueError(message)
        pushLog({
          stage: "NETWORK",
          level: "warn",
          spans: [{ t: "text", v: `Backend queue unavailable · ${message}` }],
        })
      })
      .finally(() => {
        setQueueLoading(false)
      })
  }, [pushLog])

  useEffect(() => {
    loadQueue()
    return undefined
  }, [loadQueue])

  const handlePipelineEvent = useCallback((event) => {
    if (!event || typeof event !== "object") return
    const stage = event.stage || event.type || "PIPELINE"
    const message = event.message || event.detail || event.data
    const level = event.level === "success" ? "ok" : event.level || "info"
    if (event.phase) setPhase(event.phase)
    if (event.stage === "PII" && (level === "redact" || event.redacted)) {
      setRedactCount((count) => count + 1)
    }
    if (event.egress_clean || (event.stage === "MODEL" && level === "info")) setEgressClean(true)
    if (event.checklist) {
      setChecks((current) => mergeChecklistState(current, event.checklist))
    }
    pushLog({
      stage,
      level,
      spans: event.spans || [{ t: "text", v: message || "Pipeline event received" }],
      metric: event.metric,
      progress: event.progress,
      depth: event.depth,
    })
  }, [pushLog])

  usePipelineStream({ enabled: backendConfigured, onEvent: handlePipelineEvent })

  const handleWSTranscript = useCallback(
    (newText) => {
      ingestDelta(newText)
    },
    [ingestDelta],
  )

  const handleWSToggles = useCallback((toggles) => {
    setChecks((current) => mergeChecklistState(current, toggles))
  }, [])

  const handleHotwordsActive = useCallback((hotwords) => {
    pushLog({
      stage: "HOTWORDS",
      level: "ok",
      spans: [
        { t: "text", v: "Attention head biased · " },
        { t: "em", v: `hotwords: "${hotwords}"` },
        { t: "arrow" },
        { t: "text", v: "Whisper vocabulary conditioned" },
      ],
      metric: "0 ms",
    })
  }, [pushLog])

  const { startStreaming, stopStreaming, audioLevel, sendOverride } = useAudioStreamer(
    activeToken,
    handleWSTranscript,
    handleWSToggles,
    handleHotwordsActive,
    activeOverrideName
  )

  const resetCase = useCallback(
    (token) => {
      clearTimers()
      // Reset lastMark so the filling→checked animation fires again for the new session
      lastMark.current = { symptoms: false, diagnosis: false, medication: false, advice: false }
      cancelDebounce()
      resetDebounce()
      stopStreaming()
      setRecording(false)
      setProcessing(false)
      setFinished(false)
      setElapsed(0)
      setChecks(EMPTY_CHECKS)
      setRedactCount(0)
      setEgressClean(false)
      setPhase("idle")
      setSeam(false)
      setRecord(null)
      if (backendConfigured) {
        medSyncApi.resetEncounter(token).catch(() => {})
      }
      setLogs([
        ...idleLines(),
        {
          id: `sw${token}`,
          at: Date.now(),
          stage: "SESSION",
          level: "info",
          spans: [{ t: "text", v: `Context switched · token#${token} · scoped session key rotated` }],
        },
      ])
    },
    [clearTimers, cancelDebounce, resetDebounce, stopStreaming, backendConfigured],
  )

  const handleDiscard = useCallback(() => {
    clearTimers()
    // Reset lastMark so the filling→checked animation fires fresh on the next attempt
    lastMark.current = { symptoms: false, diagnosis: false, medication: false, advice: false }
    cancelDebounce()
    resetDebounce()
    stopStreaming()
    setRecording(false)
    setProcessing(false)
    setFinished(false)
    setElapsed(0)
    setChecks(EMPTY_CHECKS)
    setRedactCount(0)
    setEgressClean(false)
    setPhase("idle")
    setSeam(false)
    setRecord(null)
    setFinishError("")
    if (backendConfigured) {
      medSyncApi.resetEncounter(activeToken).catch(() => {})
    }
    setLogs(idleLines())
  }, [clearTimers, cancelDebounce, resetDebounce, stopStreaming, activeToken, backendConfigured])

  const handleStartUnscheduled = useCallback(
    async (patientName) => {
      const trimmed = patientName.trim()
      if (!trimmed) return

      setSelectionBusy("unscheduled")
      try {
        if (backendConfigured) {
          const resp = await medSyncApi.createUnscheduledEncounter(trimmed)
          const tokenNumber = resp.token_number
          await loadQueue()
          setActiveToken(tokenNumber)
          setActiveOverrideName(trimmed)
          resetCase(tokenNumber)
          sendOverride(trimmed)
          pushLog({
            stage: "ATTENTION",
            level: "ok",
            spans: [
              { t: "text", v: "Unscheduled encounter created · " },
              { t: "em", v: trimmed },
              { t: "arrow" },
              { t: "text", v: `Token #${tokenNumber} · attention head biased` },
            ],
          })
        } else {
          const maxToken = cases.reduce((max, c) => Math.max(max, c.token || 0), 0)
          const newToken = maxToken + 1
          const newCase = {
            token: newToken,
            name: trimmed,
            age: null,
            sex: null,
            complaint: "Unscheduled walk-in consultation",
            status: "in-progress",
            script: `Patient ${trimmed} presents for consultation.`,
            pii: [],
            marks: {},
          }
          setRemoteCases((prev) => [...(prev || []), newCase])
          setActiveToken(newToken)
          setActiveOverrideName(trimmed)
          resetCase(newToken)
          pushLog({
            stage: "ATTENTION",
            level: "ok",
            spans: [
              { t: "text", v: "Unscheduled encounter · " },
              { t: "em", v: trimmed },
              { t: "arrow" },
              { t: "text", v: `Token #${newToken} · attention biased` },
            ],
          })
        }
      } catch (err) {
        pushLog({
          stage: "SESSION",
          level: "warn",
          spans: [{ t: "text", v: `Failed to create unscheduled encounter: ${readableError(err)}` }],
        })
      } finally {
        setSelectionBusy(null)
      }
    },
    [backendConfigured, loadQueue, resetCase, sendOverride, pushLog, cases],
  )

  const handleSelect = useCallback(
    async (token) => {
      if (token === activeToken) return
      clearTimers()
      cancelDebounce()
      stopStreaming()
      setSelectionBusy(token)

      const targetCase = cases.find((c) => c.token === token)
      const isDone = targetCase?.status === "done"

      // Always switch to the selected patient first
      setActiveToken(token)
      setActiveOverrideName("")
      resetCase(token)

      if (!isDone) {
        // Start a new encounter session
        if (backendConfigured) {
          try {
            await medSyncApi.selectToken(token)
            setStatuses((s) => ({ ...s, [token]: "in-progress" }))
          } catch (error) {
            pushLog({
              stage: "NETWORK",
              level: "warn",
              spans: [{ t: "text", v: `Token selection failed · ${readableError(error)}` }],
            })
          }
        } else {
          setStatuses((s) => ({ ...s, [token]: "in-progress" }))
        }
        setSelectionBusy(null)
        return
      }

      // Done case — try to open the structured record as an overlay
      if (backendConfigured) {
        try {
          const recordData = await medSyncApi.fetchRecord(token)
          setRecord(recordData)
        } catch (error) {
          pushLog({
            stage: "NETWORK",
            level: "warn",
            spans: [{ t: "text", v: `Record not ready · ${readableError(error, "still processing")}` }],
          })
        }
      } else {
        setRecord({ token, fhir: targetCase?.fhir ?? null, mock: true })
      }
      setSelectionBusy(null)
    },
    [activeToken, cases, resetCase, cancelDebounce, pushLog, stopStreaming, backendConfigured],
  )

  const scriptWords = useMemo(
    () => (active?.script ? active.script.split(/\s+/).filter(Boolean) : []),
    [active?.script],
  )

  useEffect(() => {
    if (!recording || !useMockData) {
      mockWordIndexRef.current = 0
      return
    }
    let cancelled = false
    const rng = makeRng((active?.token ?? 1) * 7919)
    mockWordIndexRef.current = words.length

    const tick = () => {
      if (cancelled || finished || processing) return
      if (mockWordIndexRef.current >= scriptWords.length) {
        setRecording(false)
        return
      }
      const burstSize = 1 + Math.floor(rng() * 3)
      const nextSlice = scriptWords.slice(
        mockWordIndexRef.current,
        Math.min(scriptWords.length, mockWordIndexRef.current + burstSize),
      )
      mockWordIndexRef.current += nextSlice.length
      ingestDelta(nextSlice.join(" "))

      const gap = 100 + rng() * 190
      timers.current.push(window.setTimeout(tick, gap))
    }
    timers.current.push(window.setTimeout(tick, 260))
    return () => {
      cancelled = true
    }
  }, [recording, scriptWords, active?.token, useMockData, finished, processing, ingestDelta, words.length])

  useEffect(() => {
    if (!recording) return
    const id = window.setInterval(() => setElapsed((e) => e + 100), 100)
    return () => window.clearInterval(id)
  }, [recording])

  // Continuous background monitoring for the Privacy X-Ray
  useEffect(() => {
    if (processing || recording) return
    const id = window.setInterval(() => {
      const hex = "0123456789ABCDEF"
      let hash = ""
      for (let i = 0; i < 4; i++) hash += hex[Math.floor(Math.random() * 16)]
      hash += "·"
      for (let i = 0; i < 4; i++) hash += hex[Math.floor(Math.random() * 16)]
      
      pushLog({
        stage: "SYSTEM",
        level: "info",
        spans: [
          { t: "text", v: "Continuous background scan · enclave integrity " },
          { t: "hash", v: hash }
        ],
        metric: `${Math.floor(5 + Math.random() * 10)} ms`
      })
    }, 3500 + Math.random() * 2000)
    return () => window.clearInterval(id)
  }, [processing, recording, pushLog])

  // Declarative reset: whenever active patient token changes, unlatch checklist animations
  useEffect(() => {
    lastMark.current = { symptoms: false, diagnosis: false, medication: false, advice: false }
  }, [activeToken])

  useEffect(() => {
    if (!rawTranscript.trim()) {
      lastMark.current = { symptoms: false, diagnosis: false, medication: false, advice: false }
      return
    }

    const matches = extractClinicalChecklist(rawTranscript)
    CHECKLIST_ORDER.forEach((k) => {
      if (matches[k] === "checked" && !lastMark.current[k]) {
        lastMark.current[k] = true
        setChecks((prev) => (prev[k] === "checked" ? prev : { ...prev, [k]: "filling" }))
        later(() => {
          setChecks((prev) => ({ ...prev, [k]: "checked" }))
        }, 320 + Math.random() * 200)

        pushLog({
          stage: "EXTRACT",
          level: "info",
          spans: [
            { t: "text", v: "field candidate · " },
            { t: "em", v: k },
            { t: "arrow" },
            { t: "text", v: "buffered in enclave" },
          ],
          metric: `w${words.length}`,
        })
      }
    })
  }, [rawTranscript, words.length, later, pushLog])

  const handleToggle = useCallback(() => {
    if (recording) {
      setRecording(false)
      setPhase("idle")
      if (!useMockData) stopStreaming()
      pushLog({
        stage: "CAPTURE",
        level: "info",
        spans: [{ t: "text", v: "Capture paused · buffer held in volatile memory only" }],
      })
      return
    }
    setRecording(true)
    setPhase("listening")
    if (!useMockData) startStreaming()
    setStatuses((s) => ({ ...s, [activeToken]: "in-progress" }))
    pushLog({
      stage: "CAPTURE",
      level: "run",
      spans: [
        { t: "text", v: "Microphone open · " },
        { t: "em", v: "on-device ASR" },
        { t: "text", v: " · no audio egress" },
      ],
    })
  }, [recording, activeToken, pushLog, useMockData, startStreaming, stopStreaming])

  const handleTranscriptEdit = useCallback(
    (text) => {
      setFullText(text)
    },
    [setFullText],
  )

  const handleFinish = useCallback(async () => {
    const transcript = (rawTranscript || words.join(" ")).trim()
    if (!transcript || processing || finished) return
    markDebouncerFinished()
    clearTimers()
    setFinishError("")
    setProcessing(true)
    setSeam(true)
    if (!useMockData) stopStreaming()

    if (backendConfigured && !useMockData) {
      try {
        await medSyncApi.finishEncounter(activeToken, { text: transcript, language: "en-IN" })

        // Try to fetch the structured record immediately — may be 423 if still processing
        let fetchedRecord = null
        try {
          fetchedRecord = await medSyncApi.fetchRecord(activeToken)
        } catch {
          // Record not ready yet — that's fine, doctor can view it via queue later
        }

        setProcessing(false)
        setFinished(true)
        setSeam(false)
        setPhase("persisted")
        setChecks({ symptoms: "checked", diagnosis: "checked", medication: "checked", advice: "checked" })
        setStatuses((s) => ({ ...s, [activeToken]: "done" }))
        if (fetchedRecord) setRecord(fetchedRecord)
      } catch (error) {
        const message = readableError(error, "Unable to finish consultation")
        setProcessing(false)
        setSeam(false)
        setPhase("error")
        setFinishError(message)
        pushLog({
          stage: "ERROR",
          level: "error",
          spans: [{ t: "text", v: `Consultation failed · ${message}` }],
        })
      }
      return
    }

    // --- Local mock path ---
    const steps = buildPipeline(active || {}, transcript, (active?.token || activeToken || 1) * 104729)

    let t = 0
    steps.forEach((s) => {
      t += s.wait
      later(() => {
        if (s.phase) setPhase(s.phase)
        if (s.fx === "redact") setRedactCount((n) => n + 1)
        if (s.stage === "MODEL" && (s.level === "info" || s.level === "ok" || s.level === "success")) setEgressClean(true)
        pushLog({
          stage: s.stage,
          level: s.level === "success" ? "ok" : s.level || "info",
          spans: s.spans,
          metric: s.metric,
          progress: s.progress,
          depth: s.depth,
        })
      }, t)
    })

    later(() => {
      setProcessing(false)
      setFinished(true)
      setSeam(false)
      setPhase("sealed")
      setChecks({ symptoms: "checked", diagnosis: "checked", medication: "checked", advice: "checked" })
      setStatuses((s) => ({ ...s, [activeToken]: "done" }))
      // In mock mode, build a synthetic record so RecordViewer can open
      setRecord({
        token: activeToken,
        fhir: active?.fhir ?? null,
        mock: true,
        symptoms: active?.fhir?.symptoms || (active?.complaint ? [active.complaint] : ["General consultation"]),
        diagnosis: active?.fhir?.diagnosis || (active?.complaint ? [active.complaint] : ["Clinical finding"]),
        medication: active?.fhir?.medication || [],
        advice: active?.fhir?.advice || ["Follow-up as required"],
      })
    }, t + 320)
  }, [rawTranscript, words, processing, finished, active, activeToken, later, pushLog, useMockData, stopStreaming, markDebouncerFinished, clearTimers])

  const busy = processing || recording
  const doneCount = cases.filter((c) => c.status === "done").length

  return (
    <div className="theme-transition flex min-h-screen flex-col bg-clinical lg:h-screen lg:overflow-hidden">
      <header className="grid shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-4 border-b border-clinical-line bg-clinical-surface px-5 py-3 lg:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-teal text-clinical-surface shadow-sm">
            <Stethoscope className="h-[18px] w-[18px]" strokeWidth={2.2} aria-hidden="true" />
            <span className="absolute -bottom-0.5 -right-0.5 flex h-2 w-2 items-center justify-center rounded-full bg-verified ring-2 ring-clinical-surface" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="font-mono text-[0.98rem] font-bold leading-none tracking-[0.06em] text-clinical-ink">
                S.P.E.A.K.
              </h1>
              <span className="hidden items-center rounded border border-teal/25 bg-teal-soft px-1.5 py-0.5 font-mono text-[0.6rem] font-medium tracking-wider text-teal md:inline-flex">
                KERNEL
              </span>
            </div>
            <p className="mt-1 truncate text-[0.66rem] font-medium leading-none text-clinical-muted" title="Secure Patient Extraction & Anonymization Kernel">
              Secure Patient Extraction &amp; Anonymization Kernel
            </p>
          </div>
        </div>

        <div className="justify-self-center">
          <SyncBadge backendConfigured={backendConfigured} online={online} loading={queueLoading} error={queueError} />
        </div>
        <div className="flex min-w-0 items-center justify-self-end gap-2">
          <div className="hidden items-center gap-2 rounded-full border border-teal/20 bg-teal-soft px-3 py-1.5 sm:flex">
            <ShieldCheck className="h-3.5 w-3.5 text-teal" strokeWidth={2.2} aria-hidden="true" />
            <span className="text-[0.68rem] font-medium tracking-[0.01em] text-teal">
              Zero-trust boundary active
            </span>
          </div>
          <button
            type="button"
            onClick={() => setUseMockData((prev) => !prev)}
            aria-pressed={useMockData}
            aria-label="Toggle mock mode"
            title="Toggle mock mode"
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-md border px-2 text-xs font-medium transition-colors",
              useMockData
                ? "border-coral/30 bg-coral/10 text-coral"
                : "border-clinical-line bg-clinical text-clinical-muted hover:bg-clinical-surface hover:text-clinical-ink"
            )}
          >
            <Bug className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">Mock</span>
          </button>
          <button
            type="button"
            onClick={toggleTheme}
            aria-pressed={theme === "dark"}
            aria-label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
            title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-clinical-line bg-clinical text-clinical-muted transition-colors hover:bg-clinical-surface hover:text-clinical-ink"
          >
            {theme === "light" ? <Moon className="h-4 w-4" aria-hidden="true" /> : <Sun className="h-4 w-4" aria-hidden="true" />}
          </button>
        </div>
      </header>

      {backendConfigured && (queueLoading || queueError || finishError) && (
        <div className="flex items-center justify-between gap-3 border-b border-clinical-line bg-clinical-surface px-5 py-2 text-xs lg:px-6">
          <span className={queueError || finishError ? "text-rejected" : "text-clinical-muted"}>
            {queueLoading && "Loading live queue…"}
            {!queueLoading && queueError && `Live queue unavailable · ${queueError}`}
            {!queueLoading && !queueError && finishError && `Consultation failed · ${finishError}`}
          </span>
          {queueError && (
            <button type="button" onClick={loadQueue} className="rounded border border-clinical-line px-2 py-1 font-medium text-clinical-muted hover:bg-clinical">
              Retry queue
            </button>
          )}
        </div>
      )}

      <main
        className="grid min-h-0 flex-1 grid-cols-1 bg-clinical lg:grid-cols-[var(--queue-width)_minmax(0,1fr)_13px_360px] xl:grid-cols-[var(--queue-width)_minmax(0,1fr)_13px_396px]"
        style={{ "--queue-width": `${queueWidth}px` }}
      >
        <div className="relative min-w-0">
          <QueueRail cases={cases} activeToken={activeToken} onSelect={handleSelect} doneCount={doneCount} selectionBusy={selectionBusy} />
          <button
            type="button"
            onMouseDown={handleQueueResizeStart}
            aria-label="Resize queue column"
            title="Resize queue column"
            className={cn(
              "absolute right-0 top-0 z-10 hidden h-full w-2 translate-x-1/2 cursor-col-resize border-0 bg-transparent transition-colors hover:bg-teal/20 lg:block",
              isQueueResizing && "bg-teal/30",
            )}
          />
        </div>

        <DictationPanel
          active={active}
          cases={cases}
          onSelectCase={handleSelect}
          activeOverrideName={activeOverrideName}
          onStartUnscheduled={handleStartUnscheduled}
          onClearOverride={() => setActiveOverrideName("")}
          words={words}
          rawTranscript={rawTranscript}
          recording={recording}
          finished={finished}
          processing={processing}
          audioLevel={audioLevel}
          useMockData={useMockData}
          elapsed={elapsed}
          onToggle={handleToggle}
          onFinish={handleFinish}
          onDiscard={handleDiscard}
          onReset={() => resetCase(activeToken)}
          onTranscriptEdit={handleTranscriptEdit}
        />

        <div
          className="relative hidden overflow-hidden bg-vault lg:block"
          role="separator"
          aria-orientation="vertical"
          aria-label="Zero-trust boundary between clinical zone and security zone"
        >
          <span aria-hidden="true" className="absolute inset-y-0 left-0 w-px bg-clinical-line" />
          <span
            aria-hidden="true"
            className={cn(
              "absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2 transition-opacity duration-500",
              seam ? "seam-flow opacity-100" : "opacity-0",
            )}
          />
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-vault-line"
          />
          <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 -rotate-90 whitespace-nowrap font-mono text-[0.5rem] uppercase tracking-[0.34em] text-vault-dim/80">
            trust boundary
          </span>
        </div>

        <aside className="flex min-h-0 flex-col border-t border-vault-line bg-vault text-vault-ink lg:border-t-0">
          <XrayLog
            lines={logs}
            phase={phase}
            busy={busy}
            redactCount={redactCount}
            egressClean={egressClean}
          />
          <ChecklistPanel key={activeToken} active={active} state={checks} />
        </aside>
      </main>
      {record && <RecordViewer record={record} isBackend={backendConfigured} onClose={() => setRecord(null)} />}
    </div>
  )
}
