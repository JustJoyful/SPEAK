import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ShieldCheck, Stethoscope } from "lucide-react"
import { QueueRail } from "@/components/QueueRail"
import { DictationPanel } from "@/components/DictationPanel"
import { XrayLog } from "@/components/XrayLog"
import { ChecklistPanel } from "@/components/ChecklistPanel"
import { cn } from "@/lib/utils"
import { CASES, CHECKLIST_ORDER } from "@/lib/cases"
import { buildPipeline, idleLines, makeRng } from "@/lib/pipeline"

const EMPTY_CHECKS = { symptoms: "empty", diagnosis: "empty", medication: "empty", advice: "empty" }

export default function App() {
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

  const timers = useRef([])
  const seq = useRef(0)

  const active = useMemo(
    () => CASES.find((c) => c.token === activeToken) ?? CASES[0],
    [activeToken],
  )
  const cases = useMemo(
    () => CASES.map((c) => ({ ...c, status: statuses[c.token] ?? c.status })),
    [statuses],
  )

  const clearTimers = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t))
    timers.current = []
  }, [])
  const later = useCallback((fn, ms) => {
    timers.current.push(window.setTimeout(fn, ms))
  }, [])

  useEffect(() => clearTimers, [clearTimers])

  const pushLog = useCallback((l) => {
    seq.current += 1
    setLogs((prev) => [...prev.slice(-90), { ...l, id: `l${seq.current}`, at: Date.now() }])
  }, [])

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

  const handleSelect = useCallback(
    (token) => {
      if (token === activeToken) return
      setActiveToken(token)
      resetCase(token)
    },
    [activeToken, resetCase],
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

  const handleFinish = useCallback(() => {
    if (!words.length || processing || finished) return
    setProcessing(true)
    setSeam(true)
    const transcript = words.join(" ")
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
      setStatuses((s) => ({ ...s, [activeToken]: "done" }))
    }, t + 320)
  }, [words, processing, finished, active, activeToken, later, pushLog])

  const busy = processing || recording
  const doneCount = cases.filter((c) => c.status === "done").length

  return (
    <div className="flex min-h-screen flex-col bg-clinical lg:h-screen lg:overflow-hidden">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-clinical-line bg-clinical-surface px-5 py-3 lg:px-6">
        <div className="flex items-center gap-3">
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

        <div className="flex items-center gap-2 rounded-full border border-teal/20 bg-teal-soft px-3 py-1.5">
          <ShieldCheck className="h-3.5 w-3.5 text-teal" strokeWidth={2.2} aria-hidden="true" />
          <span className="text-[0.68rem] font-medium tracking-[0.01em] text-teal">
            Zero-trust boundary active
          </span>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[248px_minmax(0,1fr)_13px_360px] xl:grid-cols-[272px_minmax(0,1fr)_13px_396px]">
        <QueueRail cases={cases} activeToken={activeToken} onSelect={handleSelect} doneCount={doneCount} />

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
    </div>
  )
}
