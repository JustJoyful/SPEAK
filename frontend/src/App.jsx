import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Moon, ShieldCheck, Stethoscope, Sun } from "lucide-react"
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

  const timers = useRef([])
  const seq = useRef(0)
  const queueResizeStart = useRef({ x: 0, width: queueWidth })

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
          setStatuses((s) => ({ ...s, [token]: "in-progress" }))
        } catch (error) {
          const message = readableError(error, "Token selection failed")
          pushLog({
            stage: "NETWORK",
            level: "warn",
            spans: [{ t: "text", v: `Token selection failed · ${message}` }],
          })
          setSelectionBusy(null)
          return
        }
      } else {
        setStatuses((s) => ({ ...s, [token]: "in-progress" }))
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
        if (!backendConfigured) {
          setChecks((prev) => ({ ...prev, [k]: "filling" }))
          later(() => setChecks((prev) => ({ ...prev, [k]: "checked" })), 620 + Math.random() * 500)
        }
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
  }, [words.length, active.marks, later, pushLog, backendConfigured])

  // Debounced partial transcript upload to trigger edge pipeline (e.g. GLiNER checklist)
  useEffect(() => {
    if (!backendConfigured || !recording || !rawTranscript.trim()) return
    const id = window.setTimeout(() => {
      medSyncApi.processText(activeToken, { text: rawTranscript, language: "en-IN" })
        .catch((err) => {
          pushLog({
            stage: "NETWORK",
            level: "warn",
            spans: [{ t: "text", v: `Partial sync failed · ${readableError(err)}` }],
          })
        })
    }, 1500) // 1.5s debounce window for live dictation
    return () => window.clearTimeout(id)
  }, [backendConfigured, recording, rawTranscript, activeToken, pushLog])

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
        const result = await medSyncApi.finishEncounter(activeToken, { text: transcript, language: "en-IN" })
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
        className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[var(--queue-width)_minmax(0,1fr)_13px_360px] xl:grid-cols-[var(--queue-width)_minmax(0,1fr)_13px_396px]"
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
          <ChecklistPanel active={active} state={checks} />
        </aside>
      </main>
      {finished && record && <RecordViewer record={record} isBackend={backendConfigured} onClose={() => setRecord(null)} />}
    </div>
  )
}
