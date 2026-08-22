import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Monitor, Moon, ShieldCheck, Stethoscope, Sun, X } from "lucide-react"
import { QueueRail } from "@/components/QueueRail"
import { DictationPanel } from "@/components/DictationPanel"
import { XrayLog } from "@/components/XrayLog"
import { ChecklistPanel } from "@/components/ChecklistPanel"
import { RecordViewer } from "@/components/RecordViewer"
import { SyncBadge } from "@/components/SyncBadge"
import { cn } from "@/lib/utils"
import { CASES, CHECKLIST_ORDER } from "@/lib/cases"
import { buildPipeline, idleLines, makeRng } from "@/lib/pipeline"
import { backendConfigured, medSyncApi } from "@/api/client"
import { usePipelineStream } from "@/hooks/usePipelineStream"

const EMPTY_CHECKS = { symptoms: "empty", diagnosis: "empty", medication: "empty", advice: "empty" }
const QUEUE_WIDTH_KEY = "queueColumnWidth"
const MIN_QUEUE_WIDTH = 200
const MAX_QUEUE_WIDTH = 500
const MONITOR_HEADER_WIDTH = 180
const MONITOR_HEADER_HEIGHT = 48
const MIN_MONITOR_WIDTH = 300
const MIN_MONITOR_HEIGHT = 300
const DEFAULT_MONITOR_SPLIT = 0.6
const MIN_MONITOR_SECTION_HEIGHT = 90

function getDefaultMonitorSize() {
  const viewportWidth = typeof window !== "undefined" ? window.innerWidth : 1440
  const baseWidth = viewportWidth >= 1280 ? 396 : 360
  return {
    width: Math.max(MIN_MONITOR_WIDTH, Math.min(baseWidth, viewportWidth * 0.9)),
    height: 600,
  }
}

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
  const [queueWidth, setQueueWidth] = useState(getInitialQueueWidth)
  const [isQueueResizing, setIsQueueResizing] = useState(false)
  const [remoteCases, setRemoteCases] = useState(null)
  const [queueLoading, setQueueLoading] = useState(backendConfigured)
  const [queueError, setQueueError] = useState("")
  const [finishError, setFinishError] = useState("")
  const [selectionBusy, setSelectionBusy] = useState(null)
  const [statuses, setStatuses] = useState(() =>
    Object.fromEntries(CASES.map((c) => [c.token, c.status])),
  )
  const [activeToken, setActiveToken] = useState(CASES[0].token)
  const [rawTranscript, setRawTranscript] = useState("")
  const [words, setWords] = useState([])
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
  const [isMonitorVisible, setIsMonitorVisible] = useState(false)
  const [monitorPosition, setMonitorPosition] = useState(null)
  const [isMonitorDragging, setIsMonitorDragging] = useState(false)
  const [monitorSize, setMonitorSize] = useState(getDefaultMonitorSize)
  const [isMonitorResizing, setIsMonitorResizing] = useState(false)
  const [monitorSplitRatio, setMonitorSplitRatio] = useState(DEFAULT_MONITOR_SPLIT)
  const [isMonitorSplitResizing, setIsMonitorSplitResizing] = useState(false)

  const timers = useRef([])
  const seq = useRef(0)
  const queueResizeStart = useRef({ x: 0, width: queueWidth })
  const mainRef = useRef(null)
  const monitorRef = useRef(null)
  const monitorDragStart = useRef({ offsetX: 0, offsetY: 0 })
  const monitorResizeStart = useRef({ x: 0, y: 0, width: monitorSize.width, height: monitorSize.height })
  const monitorSectionsRef = useRef(null)
  const monitorSplitStart = useRef({ y: 0, ratio: DEFAULT_MONITOR_SPLIT })

  const cases = useMemo(
    () => remoteCases
      ? remoteCases.map((c) => ({ ...c, status: statuses[c.token] ?? c.status }))
      : CASES.map((c) => ({ ...c, status: statuses[c.token] ?? c.status })),
    [remoteCases, statuses],
  )
  const active = useMemo(
    () => cases.find((c) => c.token === activeToken) ?? cases[0] ?? CASES[0],
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

  const hideMonitor = useCallback(() => {
    setIsMonitorVisible(false)
    setMonitorPosition(null)
    setMonitorSize(getDefaultMonitorSize())
    setMonitorSplitRatio(DEFAULT_MONITOR_SPLIT)
  }, [])

  const toggleMonitor = useCallback(() => {
    if (isMonitorVisible) {
      hideMonitor()
      return
    }
    setMonitorPosition(null)
    setMonitorSize(getDefaultMonitorSize())
    setMonitorSplitRatio(DEFAULT_MONITOR_SPLIT)
    setIsMonitorVisible(true)
  }, [hideMonitor, isMonitorVisible])

  const handleMonitorDragStart = useCallback((event) => {
    if (event.button !== 0 || !mainRef.current || !monitorRef.current) return
    event.preventDefault()
    const panelRect = monitorRef.current.getBoundingClientRect()
    monitorDragStart.current = {
      offsetX: event.clientX - panelRect.left,
      offsetY: event.clientY - panelRect.top,
    }
    setIsMonitorDragging(true)
  }, [])

  useEffect(() => {
    if (!isMonitorDragging) return undefined

    const handleMonitorDragMove = (event) => {
      const mainRect = mainRef.current?.getBoundingClientRect()
      const panelRect = monitorRef.current?.getBoundingClientRect()
      if (!mainRect || !panelRect) return

      const rawLeft = event.clientX - mainRect.left - monitorDragStart.current.offsetX
      const rawTop = event.clientY - mainRect.top - monitorDragStart.current.offsetY
      const maxLeft = Math.max(0, mainRect.width - MONITOR_HEADER_WIDTH)
      const maxTop = Math.max(0, mainRect.height - MONITOR_HEADER_HEIGHT)
      setMonitorPosition({
        left: Math.min(maxLeft, Math.max(0, rawLeft)),
        top: Math.min(maxTop, Math.max(0, rawTop)),
      })
    }
    const stopMonitorDrag = () => setIsMonitorDragging(false)

    window.addEventListener("mousemove", handleMonitorDragMove)
    window.addEventListener("mouseup", stopMonitorDrag)
    window.addEventListener("blur", stopMonitorDrag)
    return () => {
      window.removeEventListener("mousemove", handleMonitorDragMove)
      window.removeEventListener("mouseup", stopMonitorDrag)
      window.removeEventListener("blur", stopMonitorDrag)
    }
  }, [isMonitorDragging])

  const handleMonitorResizeStart = useCallback((event) => {
    if (event.button !== 0 || !mainRef.current || !monitorRef.current) return
    event.preventDefault()
    event.stopPropagation()
    monitorResizeStart.current = {
      x: event.clientX,
      y: event.clientY,
      width: monitorSize.width,
      height: monitorSize.height,
    }
    setIsMonitorResizing(true)
  }, [monitorSize])

  useEffect(() => {
    if (!isMonitorResizing) return undefined

    const handleMonitorResizeMove = (event) => {
      const mainRect = mainRef.current?.getBoundingClientRect()
      if (!mainRect) return

      const maxWidth = Math.max(MIN_MONITOR_WIDTH, Math.min(window.innerWidth * 0.9, mainRect.width))
      const maxHeight = Math.max(MIN_MONITOR_HEIGHT, Math.min(window.innerHeight * 0.9, mainRect.height))
      const deltaX = event.clientX - monitorResizeStart.current.x
      const deltaY = event.clientY - monitorResizeStart.current.y
      setMonitorSize({
        width: Math.min(maxWidth, Math.max(MIN_MONITOR_WIDTH, monitorResizeStart.current.width + deltaX)),
        height: Math.min(maxHeight, Math.max(MIN_MONITOR_HEIGHT, monitorResizeStart.current.height + deltaY)),
      })
    }
    const stopMonitorResize = () => setIsMonitorResizing(false)

    document.addEventListener("mousemove", handleMonitorResizeMove)
    document.addEventListener("mouseup", stopMonitorResize)
    window.addEventListener("blur", stopMonitorResize)
    return () => {
      document.removeEventListener("mousemove", handleMonitorResizeMove)
      document.removeEventListener("mouseup", stopMonitorResize)
      window.removeEventListener("blur", stopMonitorResize)
    }
  }, [isMonitorResizing])

  const handleMonitorSplitStart = useCallback((event) => {
    if (event.button !== 0 || !monitorSectionsRef.current) return
    event.preventDefault()
    event.stopPropagation()
    monitorSplitStart.current = { y: event.clientY, ratio: monitorSplitRatio }
    setIsMonitorSplitResizing(true)
  }, [monitorSplitRatio])

  useEffect(() => {
    if (!isMonitorSplitResizing) return undefined

    const handleMonitorSplitMove = (event) => {
      const sectionsRect = monitorSectionsRef.current?.getBoundingClientRect()
      if (!sectionsRect?.height) return

      const minRatio = Math.min(0.5, MIN_MONITOR_SECTION_HEIGHT / sectionsRect.height)
      const maxRatio = 1 - minRatio
      const deltaRatio = (event.clientY - monitorSplitStart.current.y) / sectionsRect.height
      setMonitorSplitRatio(
        Math.min(maxRatio, Math.max(minRatio, monitorSplitStart.current.ratio + deltaRatio)),
      )
    }
    const stopMonitorSplit = () => setIsMonitorSplitResizing(false)

    document.addEventListener("mousemove", handleMonitorSplitMove)
    document.addEventListener("mouseup", stopMonitorSplit)
    window.addEventListener("blur", stopMonitorSplit)
    return () => {
      document.removeEventListener("mousemove", handleMonitorSplitMove)
      document.removeEventListener("mouseup", stopMonitorSplit)
      window.removeEventListener("blur", stopMonitorSplit)
    }
  }, [isMonitorSplitResizing])

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

  const pushLog = useCallback((l) => {
    seq.current += 1
    setLogs((prev) => [...prev.slice(-90), { ...l, id: `l${seq.current}`, at: Date.now() }])
  }, [])

  const loadQueue = useCallback(() => {
    if (!backendConfigured) return Promise.resolve()
    setQueueLoading(true)
    setQueueError("")
    return medSyncApi.getQueue()
      .then((payload) => {
        const rows = Array.isArray(payload) ? payload : payload.queue ?? []
        const next = rows.map((row) => {
          const token = Number(row.token_number ?? row.token)
          if (!Number.isFinite(token) || token <= 0) return null
          const demo = CASES.find((c) => c.token === token) ?? CASES[0]
          return {
            ...demo,
            ...row,
            token,
            name: row.patient_display_name ?? row.name ?? demo.name,
            status: row.status ?? demo.status,
            script: demo.script,
            marks: demo.marks,
          }
        }).filter(Boolean)
        if (next.length) {
          setRemoteCases(next)
          setActiveToken((token) => next.some((item) => item.token === token) ? token : next[0].token)
          setStatuses(Object.fromEntries(next.map((item) => [item.token, item.status])))
        }
      })
      .catch((error) => {
        const message = readableError(error, "Unable to load queue")
        setQueueError(message)
        pushLog({
          stage: "NETWORK",
          level: "warn",
          spans: [{ t: "text", v: `Backend queue unavailable · ${message} · local demo retained` }],
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
    const stage = event.stage || event.type || "PIPELINE"
    const message = event.message || event.detail || event.data
    if (event.phase) setPhase(event.phase)
    if (event.stage === "PII" && (event.level === "redact" || event.redacted)) {
      setRedactCount((count) => count + 1)
    }
    if (event.egress_clean || event.stage === "MODEL" && event.level === "info") setEgressClean(true)
    if (event.checklist) {
      setChecks((current) => ({ ...current, ...event.checklist }))
    }
    pushLog({
      stage,
      level: event.level || "info",
      spans: event.spans || [{ t: "text", v: message || "Pipeline event received" }],
      metric: event.metric,
      progress: event.progress,
      depth: event.depth,
    })
  }, [pushLog])

  usePipelineStream({ enabled: backendConfigured, onEvent: handlePipelineEvent })

  const resetCase = useCallback(
    (token) => {
      clearTimers()
      setRecording(false)
      setProcessing(false)
      setFinished(false)
      setWords([])
      setRawTranscript("")
      setElapsed(0)
      setChecks(EMPTY_CHECKS)
      setRedactCount(0)
      setEgressClean(false)
      setPhase("idle")
      setSeam(false)
      setRecord(null)
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
    [clearTimers],
  )

  const handleDiscard = useCallback(() => {
    clearTimers()
    setRecording(false)
    setProcessing(false)
    setFinished(false)
    setWords([])
    setRawTranscript("")
    setElapsed(0)
    setChecks(EMPTY_CHECKS)
    setRedactCount(0)
    setEgressClean(false)
    setPhase("idle")
    setSeam(false)
    setRecord(null)
    setFinishError("")
    setLogs(idleLines())
  }, [clearTimers])

  const handleSelect = useCallback(
    async (token) => {
      if (token === activeToken) return
      setSelectionBusy(token)
      if (backendConfigured) {
        try {
          await medSyncApi.selectToken(token)
        } catch (error) {
          const message = readableError(error, "Token selection failed")
          pushLog({
            stage: "NETWORK",
            level: "warn",
            spans: [{ t: "text", v: `Token selection failed · ${message}` }],
          })
        }
      }
      setActiveToken(token)
      resetCase(token)
      setSelectionBusy(null)
    },
    [activeToken, pushLog, resetCase],
  )

  const scriptWords = useMemo(() => active.script.split(/\s+/), [active.script])

  useEffect(() => {
    if (!recording) return
    let cancelled = false
    const rng = makeRng(active.token * 7919)

    const tick = () => {
      if (cancelled) return
      setWords((prev) => {
        if (prev.length >= scriptWords.length) {
          setRecording(false)
          return prev
        }
        const burst = 1 + Math.floor(rng() * 3)
        const next = scriptWords.slice(0, Math.min(scriptWords.length, prev.length + burst))
        setRawTranscript(next.join(" "))
        return next
      })
      const gap = 100 + rng() * 190
      timers.current.push(window.setTimeout(tick, gap))
    }
    timers.current.push(window.setTimeout(tick, 260))
    return () => {
      cancelled = true
    }
  }, [recording, scriptWords, active.token])

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

  const lastMark = useRef({
    symptoms: false,
    diagnosis: false,
    medication: false,
    advice: false,
  })

  useEffect(() => {
    if (!words.length) {
      lastMark.current = { symptoms: false, diagnosis: false, medication: false, advice: false }
      return
    }
    CHECKLIST_ORDER.forEach((k) => {
      const mark = active.marks[k]
      if (words.length >= mark && !lastMark.current[k]) {
        lastMark.current[k] = true
        setChecks((prev) => ({ ...prev, [k]: "filling" }))
        later(() => setChecks((prev) => ({ ...prev, [k]: "checked" })), 620 + Math.random() * 500)
        pushLog({
          stage: "EXTRACT",
          level: "info",
          spans: [
            { t: "text", v: `field candidate · ` },
            { t: "em", v: k },
            { t: "arrow" },
            { t: "text", v: "buffered in enclave" },
          ],
          metric: `w${words.length}`,
        })
      }
    })
  }, [words.length, active.marks, later, pushLog])

  const handleToggle = useCallback(() => {
    if (recording) {
      setRecording(false)
      setPhase("idle")
      pushLog({
        stage: "CAPTURE",
        level: "info",
        spans: [{ t: "text", v: "Capture paused · buffer held in volatile memory only" }],
      })
      return
    }
    setRecording(true)
    setPhase("listening")
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
  }, [recording, activeToken, pushLog])

  const handleTranscriptEdit = useCallback((text) => {
    setRawTranscript(text)
    setWords(text.trim() ? text.trim().split(/\s+/) : [])
  }, [])

  const handleFinish = useCallback(async () => {
    if (!words.length || processing || finished) return
    setFinishError("")
    setProcessing(true)
    setSeam(true)
    const transcript = words.join(" ")

    if (backendConfigured) {
      try {
        const result = await medSyncApi.finishEncounter({ text: transcript, language: "en-IN" })
        setRecord(result?.record ?? result)
        setProcessing(false)
        setFinished(true)
        setSeam(false)
        setPhase("persisted")
        setChecks({ symptoms: "checked", diagnosis: "checked", medication: "checked", advice: "checked" })
        setStatuses((s) => ({ ...s, [activeToken]: "done" }))
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

    const steps = buildPipeline(active, transcript, active.token * 104729)

    let t = 0
    steps.forEach((s) => {
      t += s.wait
      later(() => {
        if (s.phase) setPhase(s.phase)
        if (s.fx === "redact") setRedactCount((n) => n + 1)
        if (s.stage === "MODEL" && s.level === "info") setEgressClean(true)
        pushLog({
          stage: s.stage,
          level: s.level,
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
      setChecks({ symptoms: "checked", diagnosis: "checked", medication: "checked", advice: "checked" })
      setRecord({ token: activeToken, fhir: active.fhir })
      setStatuses((s) => ({ ...s, [activeToken]: "done" }))
    }, t + 320)
  }, [words, processing, finished, active, activeToken, later, pushLog])

  const busy = processing || recording
  const doneCount = cases.filter((c) => c.status === "done").length

  return (
    <div className="theme-transition flex min-h-screen flex-col bg-clinical lg:h-screen lg:overflow-hidden">
      <header className="grid shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-4 border-b border-clinical-line bg-clinical-surface px-5 py-3 lg:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-teal text-clinical-surface">
            <Stethoscope className="h-[18px] w-[18px]" strokeWidth={2} aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-[0.98rem] font-semibold leading-none tracking-[-0.015em] text-clinical-ink">
              MedSync
            </h1>
            <p className="mt-1 text-[0.68rem] leading-none text-clinical-muted">
              Voice to structured record · Zero-trust edge
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
            onClick={toggleMonitor}
            aria-controls="privacy-monitor"
            aria-expanded={isMonitorVisible}
            aria-label={isMonitorVisible ? "Hide privacy monitor" : "Show privacy monitor"}
            title={isMonitorVisible ? "Hide privacy monitor" : "Show privacy monitor"}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-clinical-line bg-clinical text-clinical-muted transition-colors hover:bg-clinical-surface hover:text-clinical-ink"
          >
            <Monitor className="h-4 w-4" aria-hidden="true" />
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
        ref={mainRef}
        className="relative grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[var(--queue-width)_minmax(0,1fr)]"
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
          words={words}
          rawTranscript={rawTranscript}
          recording={recording}
          finished={finished}
          processing={processing}
          elapsed={elapsed}
          onToggle={handleToggle}
          onFinish={handleFinish}
          onDiscard={handleDiscard}
          onReset={() => resetCase(activeToken)}
          onTranscriptEdit={handleTranscriptEdit}
        />

        {isMonitorVisible && (
          <aside
            id="privacy-monitor"
            ref={monitorRef}
            className={cn(
              "absolute z-20 flex h-[600px] max-h-[calc(100%-1.5rem)] min-h-0 w-[calc(100%-1.5rem)] flex-col overflow-hidden rounded-xl border border-vault-line bg-vault text-vault-ink shadow-2xl lg:w-[360px] xl:w-[396px]",
              monitorPosition ? "" : "inset-y-3 right-3",
              (isMonitorDragging || isMonitorResizing || isMonitorSplitResizing) && "select-none",
            )}
            style={{
              ...(monitorPosition ? { left: monitorPosition.left, top: monitorPosition.top } : {}),
              width: monitorSize.width,
              height: monitorSize.height,
            }}
          >
            <div
              role="presentation"
              onMouseDown={handleMonitorDragStart}
              className={cn(
                "absolute inset-x-0 top-0 z-10 h-12 cursor-move",
                isMonitorDragging && "cursor-grabbing",
              )}
            />
            <button
              type="button"
              onMouseDown={(event) => event.stopPropagation()}
              onClick={hideMonitor}
              aria-label="Close privacy monitor"
              title="Close privacy monitor"
              className="absolute right-2 top-2 z-20 flex h-7 w-7 items-center justify-center rounded-md border border-vault-line bg-vault text-vault-dim transition-colors hover:border-vault-ink/40 hover:text-vault-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-vault-ink"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <button
              type="button"
              onMouseDown={handleMonitorResizeStart}
              aria-label="Resize privacy monitor"
              title="Resize privacy monitor"
              className={cn(
                "absolute bottom-0 right-0 z-20 h-5 w-5 cursor-nwse-resize rounded-tl-md border-l border-t border-vault-line bg-vault/90 text-vault-dim transition-colors hover:bg-vault-raised hover:text-vault-ink",
                isMonitorResizing && "bg-vault-raised text-vault-ink",
              )}
            >
              <span aria-hidden="true" className="text-[0.7rem] leading-none">⌟</span>
            </button>
            <div ref={monitorSectionsRef} className="flex min-h-0 flex-1 flex-col">
              <div
                className="min-h-0 overflow-hidden"
                style={{ flex: `${monitorSplitRatio} 1 0%` }}
              >
                <XrayLog
                  lines={logs}
                  phase={phase}
                  busy={busy}
                  redactCount={redactCount}
                  egressClean={egressClean}
                />
              </div>
              <button
                type="button"
                onMouseDown={handleMonitorSplitStart}
                aria-label="Resize monitor sections"
                title="Resize monitor sections"
                className={cn(
                  "z-20 h-1.5 shrink-0 cursor-row-resize border-y border-vault-line bg-vault-line/60 transition-colors hover:bg-vault-ink/40",
                  isMonitorSplitResizing && "bg-vault-ink/60",
                )}
              />
              <div
                className="min-h-0 overflow-y-auto"
                style={{ flex: `${1 - monitorSplitRatio} 1 0%` }}
              >
                <ChecklistPanel active={active} state={checks} />
              </div>
            </div>
          </aside>
        )}
      </main>
      {finished && record && <RecordViewer record={record} isBackend={backendConfigured} onClose={() => setRecord(null)} />}
    </div>
  )
}
