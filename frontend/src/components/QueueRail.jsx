import { cn } from "@/lib/utils"

const STATUS_STYLE = {
  waiting: {
    label: "waiting",
    dot: "bg-clinical-muted",
    pill: "bg-clinical text-clinical-muted border-clinical-line",
  },
  "in-progress": {
    label: "in progress",
    dot: "bg-running",
    pill: "bg-running/12 text-[#8a5c12] border-running/35",
  },
  done: {
    label: "done",
    dot: "bg-teal",
    pill: "bg-teal-soft text-teal border-teal/25",
  },
}

export function QueueRail({ cases, activeToken, onSelect, doneCount, selectionBusy }) {
  return (
    <aside className="flex min-h-0 flex-col border-clinical-line lg:border-r bg-clinical">
      <header className="flex items-baseline justify-between gap-3 border-b border-clinical-line px-5 pb-4 pt-5">
        <div>
          <h2 className="text-[0.95rem] font-semibold leading-none tracking-[-0.01em] text-clinical-ink">
            Today&apos;s queue
          </h2>
          <p className="tnum mt-1.5 text-[0.7rem] font-normal text-clinical-muted">
            Wed 12 Aug · PHC Kolar · Dr. A. Menon
          </p>
        </div>
        <span className="tnum shrink-0 rounded-full border border-clinical-line bg-clinical-surface px-2 py-[3px] text-[0.66rem] font-medium text-clinical-muted">
          {doneCount}/{cases.length}
        </span>
      </header>

      <ul className="vault-scroll min-h-0 flex-1 overflow-y-auto px-2.5 py-3">
        {cases.map((c) => {
          const active = c.token === activeToken
          const st = STATUS_STYLE[c.status] ?? STATUS_STYLE.waiting
          return (
            <li key={c.token}>
              <button
                type="button"
                onClick={() => onSelect(c.token)}
                disabled={selectionBusy != null}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "group relative mb-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-all duration-200 disabled:cursor-wait disabled:opacity-70",
                  active
                    ? "bg-clinical-surface shadow-[0_1px_2px_rgba(26,34,38,0.06),0_6px_16px_-8px_rgba(31,111,111,0.28)]"
                    : "hover:bg-clinical-surface/70",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute left-0 top-1/2 w-[3px] -translate-y-1/2 rounded-r-full bg-teal transition-all duration-300",
                    active ? "h-[62%] opacity-100" : "h-0 opacity-0",
                  )}
                />
                <span
                  className={cn(
                    "tnum flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-[0.78rem] font-semibold tabular-nums transition-colors duration-200",
                    active
                      ? "bg-teal text-clinical-surface"
                      : "bg-clinical-surface text-clinical-muted ring-1 ring-inset ring-clinical-line group-hover:text-clinical-ink",
                  )}
                >
                  {c.token}
                </span>

                <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                  <span className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "truncate text-[0.855rem] font-medium leading-tight",
                        active ? "text-clinical-ink" : "text-clinical-ink/85",
                      )}
                    >
                      {c.name}
                    </span>
                    <span className="tnum shrink-0 text-[0.68rem] font-normal text-clinical-muted">
                      {c.age}
                      {c.sex}
                    </span>
                  </span>
                  <span className="truncate text-[0.71rem] leading-tight text-clinical-muted">{c.complaint}</span>
                </span>

                <span
                  className={cn(
                    "flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-[3px] text-[0.62rem] font-medium tracking-[0.02em]",
                    st.pill,
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn("h-1.5 w-1.5 rounded-full", st.dot, c.status === "in-progress" && "animate-breath")}
                  />
                  {st.label}
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      <footer className="border-t border-clinical-line px-5 py-3.5">
        <p className="text-[0.68rem] leading-relaxed text-clinical-muted">
          Tokens only. No patient IDs, phone numbers or Aadhaar are ever rendered in the clinical zone.
        </p>
      </footer>
    </aside>
  )
}
