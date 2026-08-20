import { Check } from "lucide-react"
import { cn } from "@/lib/utils"
import { CHECKLIST_LABELS, CHECKLIST_ORDER } from "@/lib/cases"

export function ChecklistPanel({ active, state }) {
  const done = CHECKLIST_ORDER.filter((k) => state[k] === "checked").length

  return (
    <div className="flex shrink-0 flex-col border-t border-vault-line">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <h2 className="font-mono text-[0.72rem] font-medium uppercase tracking-[0.13em] text-vault-ink">
          Note completeness
        </h2>
        <span className="tnum font-mono text-[0.62rem] tracking-[0.08em] text-vault-dim">
          <span className={cn(done === 4 ? "text-verified" : "text-running")}>{done}</span>/4
        </span>
      </div>

      {/* segmented progress */}
      <div className="flex gap-1 px-4 pb-3" aria-hidden="true">
        {CHECKLIST_ORDER.map((k) => (
          <span
            key={k}
            className={cn(
              "h-[3px] flex-1 rounded-full transition-all duration-500",
              state[k] === "checked" ? "bg-verified" : state[k] === "filling" ? "bg-running" : "bg-vault-line",
            )}
          />
        ))}
      </div>

      <ul className="flex flex-col gap-px px-2 pb-3">
        {CHECKLIST_ORDER.map((k) => {
          const st = state[k]
          const content = fieldPreview(active, k)
          return (
            <li
              key={k}
              className={cn(
                "flex gap-2.5 rounded px-2 py-2 transition-colors duration-300",
                st === "checked" && "bg-verified/[0.045]",
                st === "filling" && "bg-running/[0.06]",
              )}
            >
              <span
                className={cn(
                  "mt-[1px] flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border transition-all duration-300",
                  st === "checked"
                    ? "animate-tick border-verified bg-verified/15 text-verified"
                    : st === "filling"
                      ? "border-running/60 bg-running/10"
                      : "border-vault-line bg-transparent",
                )}
                aria-hidden="true"
              >
                {st === "checked" ? (
                  <Check className="h-3 w-3" strokeWidth={3} />
                ) : st === "filling" ? (
                  <span className="h-1.5 w-1.5 animate-breath rounded-full bg-running" />
                ) : null}
              </span>

              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-2">
                  <span
                    className={cn(
                      "font-mono text-[0.72rem] font-medium tracking-[0.01em] transition-colors duration-300",
                      st === "empty" ? "text-vault-dim" : "text-vault-ink",
                    )}
                  >
                    {CHECKLIST_LABELS[k]}
                  </span>
                  <span
                    className={cn(
                      "font-mono text-[0.58rem] uppercase tracking-[0.09em] transition-colors duration-300",
                      st === "checked" ? "text-verified" : st === "filling" ? "text-running" : "text-vault-dim/70",
                    )}
                  >
                    {st === "checked" ? "captured" : st === "filling" ? "extracting" : "pending"}
                  </span>
                </span>

                <span
                  className={cn(
                    "mt-1 block overflow-hidden font-mono text-[0.645rem] leading-[1.5] transition-all duration-500",
                    st === "empty" ? "max-h-0 opacity-0" : "max-h-24 opacity-100",
                  )}
                >
                  {content.map((line, i) => (
                    <span key={i} className="block truncate text-vault-ink/60">
                      {st === "filling" ? "░".repeat(Math.min(28, line.length)) : line}
                    </span>
                  ))}
                </span>
              </span>
            </li>
          )
        })}
      </ul>

      <p className="border-t border-vault-line px-4 py-3 font-mono text-[0.6rem] leading-relaxed text-vault-dim">
        Extracted from redacted text only. Fields never contain identifiers.
      </p>
    </div>
  )
}

function fieldPreview(c, k) {
  if (k === "symptoms") return c.fhir.symptoms
  if (k === "diagnosis") return [c.fhir.diagnosis, c.fhir.code]
  if (k === "medication") return c.fhir.medication
  return c.fhir.advice
}
