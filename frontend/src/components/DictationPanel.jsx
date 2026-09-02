import { useEffect, useMemo, useRef, useState } from "react"
import { Mic, Square, Check, RotateCcw, Loader2, Pencil, Search, X, Zap, UserPlus, ArrowRight } from "lucide-react"
import { cn, clock } from "@/lib/utils"

const BAR_COUNT = 28

export function DictationPanel({
  active,
  cases,
  onSelectCase,
  activeOverrideName,
  onStartUnscheduled,
  onClearOverride,
  words,
  rawTranscript,
  recording,
  finished,
  processing,
  elapsed,
  onToggle,
  onFinish,
  onDiscard,
  onReset,
  onTranscriptEdit,
  audioLevel,
  useMockData
}) {
  const scrollRef = useRef(null)
  const searchInputRef = useRef(null)
  const [editing, setEditing] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const hasText = Boolean(rawTranscript && rawTranscript.trim().length > 0) || words.length > 0

  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
      if (e.key === "Escape") {
        setSearchQuery("")
        searchInputRef.current?.blur()
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [])

  const trimmedSearch = searchQuery.trim().toLowerCase()
  const matchingCases = useMemo(() => {
    if (!trimmedSearch) return []
    return (cases || []).filter((c) => {
      const name = (c.name || "").toLowerCase()
      const token = String(c.token || "")
      return name.includes(trimmedSearch) || token === trimmedSearch
    })
  }, [cases, trimmedSearch])

  const handleSearchKeyDown = (e) => {
    if (e.key === "Enter" && searchQuery.trim()) {
      e.preventDefault()
      if (matchingCases.length === 1) {
        onSelectCase?.(matchingCases[0].token)
        setSearchQuery("")
      } else {
        onStartUnscheduled?.(searchQuery.trim())
        setSearchQuery("")
      }
    }
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el && recording) el.scrollTop = el.scrollHeight
  }, [words.length, recording])

  const bars = useMemo(
    () =>
      Array.from({ length: BAR_COUNT }, (_, i) => ({
        dur: 0.5 + ((i * 37) % 60) / 100,
        delay: ((i * 53) % 90) / 100,
        base: 0.2 + ((i * 29) % 70) / 100,
      })),
    [],
  )

  const wordCount = rawTranscript.trim() ? rawTranscript.trim().split(/\s+/).length : words.length
  const totalWords = active?.script ? active.script.split(/\s+/).filter(Boolean).length : 1
  const pct = Math.min(100, Math.round((wordCount / Math.max(1, totalWords)) * 100))

  return (
    <section className="flex min-h-0 flex-col bg-clinical-surface">
      {/* Quick Search / Unscheduled Override Bar */}
      <div className="relative border-b border-clinical-line bg-clinical/40 px-6 py-2.5 lg:px-8">
        <div className="relative max-w-xl">
          <div className="flex items-center gap-2 rounded-md border border-clinical-line bg-clinical-surface px-3 py-1.5 text-xs shadow-xs transition-colors focus-within:border-teal/50 focus-within:ring-1 focus-within:ring-teal/30">
            <Search className="h-3.5 w-3.5 text-clinical-muted shrink-0" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search queue or type patient name for instant walk-in override..."
              className="w-full bg-transparent text-xs text-clinical-ink placeholder:text-clinical-muted/70 focus:outline-hidden"
            />
            {searchQuery ? (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="text-clinical-muted hover:text-clinical-ink"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : (
              <kbd className="hidden sm:inline-flex items-center rounded border border-clinical-line bg-clinical px-1.5 py-0.5 text-[0.65rem] font-mono text-clinical-muted">
                ⌘K
              </kbd>
            )}
          </div>

          {/* Search Dropdown / Unscheduled Action Banner */}
          {searchQuery.trim() && (
            <div className="absolute left-0 right-0 top-full z-30 mt-1.5 overflow-hidden rounded-lg border border-clinical-line bg-clinical-surface p-2 shadow-lg">
              {matchingCases.length > 0 ? (
                <div className="space-y-1">
                  <div className="px-2 py-1 text-[0.68rem] font-semibold uppercase tracking-wider text-clinical-muted">
                    Scheduled Patients ({matchingCases.length})
                  </div>
                  {matchingCases.map((c) => (
                    <button
                      key={c.token}
                      type="button"
                      onClick={() => {
                        onSelectCase?.(c.token)
                        setSearchQuery("")
                      }}
                      className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-clinical"
                    >
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-teal-soft px-1.5 py-0.5 text-[0.65rem] font-semibold text-teal">
                          #{c.token}
                        </span>
                        <span className="font-medium text-clinical-ink">{c.name}</span>
                        <span className="text-[0.7rem] text-clinical-muted">{c.complaint || ""}</span>
                      </div>
                      <ArrowRight className="h-3.5 w-3.5 text-clinical-muted" />
                    </button>
                  ))}
                  <div className="my-1 border-t border-clinical-line" />
                  <button
                    type="button"
                    onClick={() => {
                      onStartUnscheduled?.(searchQuery.trim())
                      setSearchQuery("")
                    }}
                    className="flex w-full items-center justify-between rounded-md bg-amber-500/10 px-2.5 py-2 text-left text-xs font-medium text-amber-700 transition-colors hover:bg-amber-500/20 dark:text-amber-400"
                  >
                    <div className="flex items-center gap-2">
                      <UserPlus className="h-3.5 w-3.5" />
                      <span>Start Unscheduled Encounter for <strong>"{searchQuery.trim()}"</strong></span>
                    </div>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-2">
                  <div className="flex items-center gap-2 text-xs text-clinical-ink">
                    <UserPlus className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
                    <span>
                      Patient not found. Start Unscheduled Encounter for{" "}
                      <strong className="font-semibold text-amber-700 dark:text-amber-400">
                        "{searchQuery.trim()}"
                      </strong>
                      ?
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onStartUnscheduled?.(searchQuery.trim())
                      setSearchQuery("")
                    }}
                    className="flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-amber-500 shrink-0"
                  >
                    <span>Start Unscheduled Encounter</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* patient header */}
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-clinical-line px-6 pb-4 pt-5 lg:px-8">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span className="tnum rounded-md bg-teal-soft px-2 py-[3px] text-[0.7rem] font-semibold text-teal">
              Token #{active?.token ?? "-"}
            </span>
            <span className="text-[0.68rem] font-medium uppercase tracking-[0.09em] text-clinical-muted">
              Consultation
            </span>
            {activeOverrideName && (
              <div className="flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[0.68rem] font-medium text-amber-700 dark:text-amber-400 animate-pulse">
                <Zap className="h-3 w-3 fill-amber-500 text-amber-500" />
                <span>Attention Biased: "{activeOverrideName}"</span>
                <button
                  type="button"
                  onClick={onClearOverride}
                  title="Clear override"
                  className="ml-1 text-clinical-muted hover:text-coral transition-colors"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            )}
          </div>
          <h1 className="mt-2 flex items-baseline gap-2.5 text-[1.55rem] font-semibold leading-none tracking-[-0.02em] text-clinical-ink">
            {active?.name ?? (active ? `Token ${active.token}` : "No patient selected")}
            <span className="tnum text-[0.9rem] font-normal tracking-normal text-clinical-muted">
              {active?.age ? `${active.age}` : ""}
              {active?.sex ? `${active.sex} · ` : ""}
              {active?.complaint || ""}
            </span>
          </h1>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-[0.62rem] font-medium uppercase tracking-[0.09em] text-clinical-muted">Elapsed</p>
            <p
              className={cn(
                "tnum text-[1.05rem] font-medium leading-tight tracking-tight transition-colors",
                recording ? "text-coral" : "text-clinical-ink",
              )}
            >
              {clock(elapsed)}
            </p>
          </div>
          {hasText && (
            <button
              type="button"
              onClick={onReset}
              className="flex items-center gap-1.5 rounded-md border border-clinical-line px-2.5 py-1.5 text-[0.72rem] font-medium text-clinical-muted transition-colors hover:border-clinical-muted/40 hover:text-clinical-ink"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Reset
            </button>
          )}
        </div>
      </header>

      {/* mic focal point */}
      <div className="relative flex flex-col items-center gap-4 border-b border-clinical-line px-6 py-7">
        {recording && !useMockData && (
          <div className="absolute top-4 right-4 flex items-center gap-1.5 rounded-full bg-coral/10 px-2.5 py-1" aria-hidden="true">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-coral opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-coral"></span>
            </span>
            <span className="text-[0.65rem] font-medium text-coral uppercase tracking-wider">Mic working</span>
          </div>
        )}
        <div className="relative flex items-center justify-center">
          {/* orbit ring */}
          <span
            aria-hidden="true"
            className={cn(
              "absolute h-[112px] w-[112px] rounded-full border transition-all duration-500",
              recording ? "border-coral/25 scale-100 opacity-100" : "border-teal/15 scale-90 opacity-70",
            )}
          />
          <button
            type="button"
            onClick={onToggle}
            disabled={finished || processing}
            aria-pressed={recording}
            aria-label={recording ? "Stop dictation" : "Start dictation"}
            className={cn(
              "relative flex h-[86px] w-[86px] items-center justify-center rounded-full text-clinical-surface transition-all duration-300 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-teal disabled:cursor-not-allowed disabled:opacity-45",
              recording
                ? "animate-halo bg-coral shadow-[var(--shadow-mic-coral)]"
                : "bg-teal shadow-[var(--shadow-mic-teal)] hover:scale-[1.035] active:scale-95",
            )}
          >
            {recording ? (
              <Square className="h-7 w-7" strokeWidth={2.2} aria-hidden="true" />
            ) : (
              <Mic className="h-8 w-8" strokeWidth={1.9} aria-hidden="true" />
            )}
          </button>
        </div>

        {/* waveform */}
        <div className="flex h-8 items-center gap-[3px]" aria-hidden="true">
          {bars.map((b, i) => (
            <span
              key={i}
              className={cn(
                "w-[3px] rounded-full transition-all duration-300",
                recording ? "bg-coral/70" : "bg-clinical-line",
              )}
              style={
                recording
                  ? (useMockData 
                     ? {
                          height: "100%",
                          animation: `barLive ${b.dur}s ease-in-out ${b.delay}s infinite alternate`,
                          transformOrigin: "center",
                        }
                     : {
                          height: `${Math.max(10, Math.min(100, 10 + ((audioLevel || 0) * (1 + b.base))))}%`,
                          transition: "height 0.1s ease-out",
                        })
                  : { height: `${6 + b.base * 5}px` }
              }
            />
          ))}
        </div>

        <p
          className="text-[0.78rem] font-medium tracking-[0.01em] text-clinical-muted"
          role="status"
          aria-live="polite"
        >
          {processing
            ? "Sealing record — see privacy X-ray"
            : finished
              ? "Note finalised and handed to the vault"
              : recording
                ? "Listening · Hindi + English · speak naturally"
                : hasText
                  ? "Dictation paused · Edit directly below or tap mic to resume"
                  : "Tap mic to dictate, or type directly into the notes box below"}
        </p>
      </div>

      {/* transcript & typing box */}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3 px-6 pb-2 pt-4 lg:px-8">
          <div className="flex items-center gap-2">
            <h3 className="text-[0.66rem] font-semibold uppercase tracking-[0.1em] text-clinical-muted">
              Clinical Notes & Transcript
            </h3>
            {!recording && !finished && !processing && (
              <span className="flex items-center gap-1 rounded-full border border-teal/25 bg-teal-soft px-2 py-[2px] text-[0.58rem] font-medium text-teal">
                <Pencil className="h-2.5 w-2.5" aria-hidden="true" />
                Type or dictate freely
              </span>
            )}
          </div>
          <div className="flex items-center gap-2.5">
            <span className="tnum text-[0.68rem] text-clinical-muted">{wordCount} words</span>
            {pct > 0 && (
              <>
                <span aria-hidden="true" className="h-3 w-px bg-clinical-line" />
                <span className="tnum text-[0.68rem] text-clinical-muted">{pct}%</span>
              </>
            )}
          </div>
        </div>

        <div
          ref={scrollRef}
          className="vault-scroll min-h-0 flex-1 overflow-y-auto px-6 pb-4 lg:px-8"
        >
          {/* ---- RECORDING: animated word-by-word (read-only live preview) ---- */}
          {recording ? (
            <div className="min-h-[140px] pt-1">
              <p
                className="max-w-[62ch] text-[1.02rem] leading-relaxed tracking-[-0.005em] text-clinical-ink"
                aria-live="polite"
                aria-atomic="false"
              >
                {words.map((w, i) => (
                  <span
                    key={i}
                    className={cn("animate-word-in", i >= words.length - 3 && "text-clinical-ink")}
                  >
                    {w}{" "}
                  </span>
                ))}
                <span
                  aria-hidden="true"
                  className="animate-caret ml-[1px] inline-block h-[1.05em] w-[2px] translate-y-[2px] bg-coral"
                />
              </p>
            </div>
          ) : (
            /* ---- ALWAYS EDITABLE TEXTAREA: type anytime, paste, edit speech results ---- */
            <div className="h-full min-h-[140px]">
              <textarea
                id="transcript-editor"
                aria-label="Clinical notes and transcript editor"
                placeholder="Type consultation notes directly (e.g. symptoms, history, clinical findings, prescription) or tap the microphone above to speak..."
                value={rawTranscript}
                onChange={(e) => onTranscriptEdit(e.target.value)}
                readOnly={finished || processing}
                disabled={finished || processing}
                spellCheck={true}
                className={cn(
                  "w-full h-full min-h-[140px] resize-none bg-transparent text-[1.02rem] leading-relaxed tracking-[-0.005em] text-clinical-ink placeholder:text-clinical-muted/60 outline-none transition-all duration-200",
                  "rounded-md border border-transparent focus:border-teal/30 focus:bg-teal-soft/20 focus:p-2.5",
                  finished || processing
                    ? "cursor-default opacity-80"
                    : "cursor-text hover:border-clinical-line"
                )}
              />
            </div>
          )}
        </div>
      </div>


      {/* finish */}
      <div className="flex items-center justify-between gap-4 border-t border-clinical-line px-6 py-4 lg:px-8">
        <p className="max-w-[38ch] text-[0.7rem] leading-relaxed text-clinical-muted">
          {finished
            ? "Signed. A copy has been chain-linked to the patient's ABHA record."
            : "On finish, identifiers are stripped before anything leaves this device."}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={onDiscard}
            disabled={!hasText || finished || processing || recording}
            className="rounded-md border border-clinical-line px-3.5 py-2.5 text-[0.82rem] font-semibold text-clinical-muted transition-colors hover:border-rejected/40 hover:text-rejected disabled:cursor-not-allowed disabled:opacity-50"
          >
            Discard
          </button>
          <button
            type="button"
            onClick={onFinish}
            disabled={!hasText || finished || processing || recording}
            className={cn(
              "flex items-center gap-2 rounded-md px-5 py-2.5 text-[0.85rem] font-semibold transition-all duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal",
              finished
                ? "cursor-default bg-teal-soft text-teal"
                : !hasText || processing || recording
                  ? "cursor-not-allowed bg-clinical text-clinical-muted/70 ring-1 ring-inset ring-clinical-line"
                  : "bg-teal text-clinical-surface shadow-[var(--shadow-finish)] hover:brightness-110 active:scale-[0.98]",
            )}
          >
            {processing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Sealing
              </>
            ) : finished ? (
              <>
                <Check className="h-4 w-4" strokeWidth={2.6} aria-hidden="true" />
                Finalised
              </>
            ) : (
              "Finish"
            )}
          </button>
        </div>
      </div>
    </section>
  )
}
