import { useEffect, useMemo, useRef } from "react"
import { Mic, Square, Check, RotateCcw, Loader2, Pencil } from "lucide-react"
import { cn, clock } from "@/lib/utils"

const BAR_COUNT = 28

export function DictationPanel({
  active,
  words,
  rawTranscript,
  recording,
  finished,
  processing,
  elapsed,
  onToggle,
  onFinish,
  onReset,
  onTranscriptEdit,
}) {
  const scrollRef = useRef(null)
  const hasText = words.length > 0

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [words.length])

  const bars = useMemo(
    () =>
      Array.from({ length: BAR_COUNT }, (_, i) => ({
        dur: 0.5 + ((i * 37) % 60) / 100,
        delay: ((i * 53) % 90) / 100,
        base: 0.2 + ((i * 29) % 70) / 100,
      })),
    [],
  )

  const wordCount = words.length
  const totalWords = active.script.split(/\s+/).length
  const pct = Math.min(100, Math.round((wordCount / totalWords) * 100))

  return (
    <section className="flex min-h-0 flex-col bg-clinical-surface">
      {/* patient header */}
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-clinical-line px-6 pb-4 pt-5 lg:px-8">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span className="tnum rounded-md bg-teal-soft px-2 py-[3px] text-[0.7rem] font-semibold text-teal">
              Token #{active.token}
            </span>
            <span className="text-[0.68rem] font-medium uppercase tracking-[0.09em] text-clinical-muted">
              Consultation
            </span>
          </div>
          <h1 className="mt-2 flex items-baseline gap-2.5 text-[1.55rem] font-semibold leading-none tracking-[-0.02em] text-clinical-ink">
            {active.name}
            <span className="tnum text-[0.9rem] font-normal tracking-normal text-clinical-muted">
              {active.age}
              {active.sex} · {active.complaint}
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
      <div className="flex flex-col items-center gap-4 border-b border-clinical-line px-6 py-7">
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
                ? "animate-halo bg-coral shadow-[0_10px_30px_-8px_rgba(217,99,59,0.55)]"
                : "bg-teal shadow-[0_8px_24px_-10px_rgba(31,111,111,0.6)] hover:scale-[1.035] active:scale-95",
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
                  ? {
                      height: "100%",
                      animation: `barLive ${b.dur}s ease-in-out ${b.delay}s infinite alternate`,
                      transformOrigin: "center",
                    }
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
                  ? "Paused — tap to continue dictating"
                  : "Tap to dictate. Nothing is stored until you finish."}
        </p>
      </div>

      {/* transcript */}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3 px-6 pb-2 pt-4 lg:px-8">
          <div className="flex items-center gap-2">
            <h3 className="text-[0.66rem] font-semibold uppercase tracking-[0.1em] text-clinical-muted">
              Live transcript
            </h3>
            {/* editable badge — shown when the user can type */}
            {hasText && !recording && !finished && !processing && (
              <span className="flex items-center gap-1 rounded-full border border-teal/25 bg-teal-soft px-2 py-[2px] text-[0.58rem] font-medium text-teal">
                <Pencil className="h-2.5 w-2.5" aria-hidden="true" />
                editable
              </span>
            )}
          </div>
          <div className="flex items-center gap-2.5">
            <span className="tnum text-[0.68rem] text-clinical-muted">{wordCount} words</span>
            <span aria-hidden="true" className="h-3 w-px bg-clinical-line" />
            <span className="tnum text-[0.68rem] text-clinical-muted">{pct}%</span>
          </div>
        </div>

        <div
          ref={scrollRef}
          className="vault-scroll min-h-0 flex-1 overflow-y-auto px-6 pb-4 lg:px-8"
        >
          {/* ---- RECORDING: animated word-by-word (read-only) ---- */}
          {recording ? (
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
          ) : hasText ? (
            /* ---- PAUSED / DONE: fully editable textarea ---- */
            <textarea
              id="transcript-editor"
              aria-label="Transcript — click to edit"
              value={rawTranscript}
              onChange={(e) => onTranscriptEdit(e.target.value)}
              readOnly={finished || processing}
              spellCheck={true}
              className={cn(
                "w-full max-w-[62ch] resize-none bg-transparent text-[1.02rem] leading-relaxed tracking-[-0.005em] text-clinical-ink outline-none transition-all duration-200",
                "min-h-[120px] pb-2",
                finished || processing
                  ? "cursor-default select-text"
                  : "cursor-text rounded-md border border-transparent focus:border-teal/30 focus:bg-teal-soft/30 focus:px-2 focus:py-1",
              )}
              style={{ fieldSizing: "content" }}
            />
          ) : (
            /* ---- EMPTY: placeholder ---- */
            <div className="flex h-full min-h-[120px] items-center">
              <p className="max-w-[46ch] text-[0.95rem] leading-relaxed text-clinical-muted">
                Your words appear here as you speak. Dictate the history, findings, impression and advice in one
                continuous flow — structuring happens afterwards.
              </p>
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
        <button
          type="button"
          onClick={onFinish}
          disabled={!hasText || finished || processing || recording}
          className={cn(
            "flex shrink-0 items-center gap-2 rounded-md px-5 py-2.5 text-[0.85rem] font-semibold transition-all duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal",
            finished
              ? "cursor-default bg-teal-soft text-teal"
              : !hasText || processing || recording
                ? "cursor-not-allowed bg-clinical text-clinical-muted/70 ring-1 ring-inset ring-clinical-line"
                : "bg-teal text-clinical-surface shadow-[0_6px_18px_-8px_rgba(31,111,111,0.7)] hover:brightness-110 active:scale-[0.98]",
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
    </section>
  )
}
