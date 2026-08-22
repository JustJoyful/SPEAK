import { useEffect, useRef } from "react"
import { cn } from "@/lib/utils"

const LEVEL = {
  info: { text: "text-vault-ink/70", badge: "text-vault-dim", glyph: "·" },
  run: { text: "text-running", badge: "text-running", glyph: "▸" },
  ok: { text: "text-verified", badge: "text-verified", glyph: "✓" },
  success: { text: "text-verified", badge: "text-verified", glyph: "✓" },
  warn: { text: "text-running", badge: "text-running", glyph: "!" },
  warning: { text: "text-running", badge: "text-running", glyph: "!" },
  err: { text: "text-rejected", badge: "text-rejected", glyph: "×" },
  error: { text: "text-rejected", badge: "text-rejected", glyph: "×" },
  redact: { text: "text-vault-ink/85", badge: "text-rejected", glyph: "▚" },
  hash: { text: "text-verified", badge: "text-verified", glyph: "#" },
}

const PHASE_LABEL = {
  idle: "monitoring",
  listening: "capturing",
  received: "ingest",
  scanning: "pii scan",
  redacted: "redacted",
  structuring: "model",
  bundling: "fhir",
  validating: "validate",
  encrypting: "encrypt",
  sealed: "sealed",
  persisted: "persisted",
  synced: "synced",
  error: "error",
}

export function XrayLog({ lines, phase, busy, redactCount, egressClean }) {
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [lines.length])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* header */}
      <div className="flex items-center justify-between gap-3 border-b border-vault-line px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
            <span
              className={cn(
                "absolute inset-0 rounded-full",
                busy ? "bg-running" : phase === "sealed" ? "bg-verified" : "bg-vault-dim",
              )}
            />
            {busy && <span className="absolute inset-0 animate-ping rounded-full bg-running/60" />}
          </span>
          <h2 className="font-mono text-[0.72rem] font-medium uppercase tracking-[0.13em] text-vault-ink">
            Privacy X-Ray
          </h2>
        </div>
        <span
          className={cn(
            "font-mono text-[0.62rem] uppercase tracking-[0.1em] transition-colors",
            busy ? "text-running" : phase === "sealed" || phase === "persisted" || phase === "synced" ? "text-verified" : "text-vault-dim",
          )}
        >
          {PHASE_LABEL[phase] || phase || "monitoring"}
          {busy && <span className="animate-caret">_</span>}
        </span>
      </div>

      {/* counters */}
      <div className="grid grid-cols-3 divide-x divide-vault-line border-b border-vault-line">
        <Counter label="redacted" value={String(redactCount).padStart(2, "0")} tone={redactCount ? "warn" : "dim"} />
        <Counter label="egress PII" value={egressClean ? "00" : "--"} tone={egressClean ? "ok" : "dim"} />
        <Counter
          label="integrity"
          value={phase === "sealed" || phase === "persisted" || phase === "synced" ? "PASS" : busy ? "···" : "—"}
          tone={phase === "sealed" || phase === "persisted" || phase === "synced" ? "ok" : busy ? "warn" : "dim"}
        />
      </div>

      {/* log */}
      <div ref={ref} className="vault-scroll min-h-0 flex-1 overflow-y-auto px-3 py-3">
        <ol className="flex flex-col gap-[3px]">
          {lines.map((l) => {
            const lv = LEVEL[l.level] || LEVEL.info
            const spans = Array.isArray(l.spans) ? l.spans : typeof l.spans === "string" ? [{ t: "text", v: l.spans }] : [{ t: "text", v: String(l.message || "") }]
            return (
              <li
                key={l.id}
                className={cn(
                  "animate-line-in group relative flex gap-2 rounded px-1.5 py-[3px] font-mono text-[0.7rem] leading-[1.45]",
                  l.depth === 1 && "ml-3.5 opacity-85",
                  (l.level === "redact") && "bg-rejected/[0.06]",
                  (l.level === "ok" || l.level === "success") && "bg-verified/[0.035]",
                )}
              >
                <span className={cn("w-2.5 shrink-0 select-none text-center", lv.badge)} aria-hidden="true">
                  {lv.glyph}
                </span>

                {l.depth !== 1 && (
                  <span className="w-[3.1rem] shrink-0 select-none text-[0.6rem] uppercase tracking-[0.06em] text-vault-dim">
                    {l.stage || "LOG"}
                  </span>
                )}

                <span className={cn("min-w-0 flex-1 break-words", lv.text)}>
                  {spans.map((s, i) => {
                    if (!s) return null
                    if (typeof s === "string") return <span key={i}>{s}</span>
                    if (s.t === "text") return <span key={i}>{s.v}</span>
                    if (s.t === "em")
                      return (
                        <span key={i} className="text-vault-ink">
                          {s.v}
                        </span>
                      )
                    if (s.t === "arrow")
                      return (
                        <span key={i} className="mx-1 text-vault-dim">
                          →
                        </span>
                      )
                    if (s.t === "strike")
                      return (
                        <span
                          key={i}
                          className="animate-redact rounded-[2px] px-[3px] text-rejected/85 line-through decoration-rejected decoration-[1.5px]"
                        >
                          {s.v}
                        </span>
                      )
                    return (
                      <span
                        key={i}
                        className="rounded-[2px] bg-verified/12 px-[4px] py-[1px] text-verified ring-1 ring-inset ring-verified/25"
                      >
                        {s.v}
                      </span>
                    )
                  })}

                  {l.progress && (
                    <span className="relative mt-1 block h-[2px] w-full overflow-hidden rounded-full bg-vault-line">
                      <span className="animate-sweep absolute inset-y-0 w-1/3 rounded-full bg-running/80" />
                    </span>
                  )}
                </span>

                {l.metric && (
                  <span className="tnum shrink-0 select-none text-[0.6rem] text-vault-dim">{l.metric}</span>
                )}
              </li>
            )
          })}
        </ol>
      </div>
    </div>
  )
}

function Counter({ label, value, tone }) {
  return (
    <div className="px-3 py-2.5">
      <p className="font-mono text-[0.56rem] uppercase tracking-[0.11em] text-vault-dim">{label}</p>
      <p
        className={cn(
          "tnum mt-1 font-mono text-[0.98rem] font-medium leading-none transition-colors duration-300",
          tone === "ok" && "text-verified",
          tone === "warn" && "text-running",
          tone === "dim" && "text-vault-dim",
        )}
      >
        {value}
      </p>
    </div>
  )
}
