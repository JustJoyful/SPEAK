import { useState } from "react"
import { Check, Code2, X } from "lucide-react"

export function RecordViewer({ record, onClose }) {
  const [showJson, setShowJson] = useState(false)
  const clinical = record?.fhir ?? record ?? {}
  const symptoms = clinical.symptoms ?? clinical.presentingComplaint ?? []
  const medications = clinical.medication ?? clinical.medications ?? []
  const advice = clinical.advice ?? clinical.plan ?? []

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/35 p-4 sm:items-center">
      <section className="max-h-[88vh] w-full max-w-3xl overflow-hidden rounded-xl border border-clinical-line bg-clinical-surface shadow-2xl">
        <header className="flex items-center justify-between border-b border-clinical-line px-5 py-4">
          <div>
            <p className="text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-teal">Consultation finalized</p>
            <h2 className="mt-1 text-lg font-semibold text-clinical-ink">Structured clinical record</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-clinical-muted hover:bg-clinical" aria-label="Close record viewer">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="max-h-[calc(88vh-76px)] overflow-y-auto p-5">
          <div className="mb-5 flex items-center gap-2 rounded-md border border-teal/25 bg-teal-soft px-3 py-2 text-sm text-teal">
            <Check className="h-4 w-4" />
            NRCeS validation and encrypted persistence completed
          </div>

          {!showJson && (
            <div className="grid gap-4 sm:grid-cols-2">
              <RecordSection title="Symptoms" values={symptoms} />
              <RecordSection title="Diagnosis" values={clinical.diagnosis ?? clinical.assessment} />
              <RecordSection title="Medication" values={medications} />
              <RecordSection title="Advice" values={advice} />
            </div>
          )}

          {showJson && (
            <pre className="overflow-x-auto rounded-md bg-vault p-4 font-mono text-xs leading-relaxed text-vault-ink">
              {JSON.stringify(record, null, 2)}
            </pre>
          )}

          <button type="button" onClick={() => setShowJson((value) => !value)} className="mt-5 inline-flex items-center gap-2 rounded-md border border-clinical-line px-3 py-2 text-xs font-medium text-clinical-muted hover:bg-clinical">
            <Code2 className="h-3.5 w-3.5" />
            {showJson ? "Show clinical summary" : "Inspect raw JSON"}
          </button>
        </div>
      </section>
    </div>
  )
}

function RecordSection({ title, values }) {
  const items = Array.isArray(values) ? values : values ? [values] : []
  return (
    <div className="rounded-md border border-clinical-line p-4">
      <h3 className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-clinical-muted">{title}</h3>
      {items.length ? (
        <ul className="mt-2 space-y-1.5 text-sm text-clinical-ink">
          {items.map((item, index) => <li key={`${title}-${index}`}>• {typeof item === "string" ? item : JSON.stringify(item)}</li>)}
        </ul>
      ) : <p className="mt-2 text-sm text-clinical-muted">Not recorded</p>}
    </div>
  )
}

