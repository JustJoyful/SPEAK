/** Deterministic-but-irregular jitter so timings never look metronomic. */
export function makeRng(seed) {
  let s = (seed >>> 0) || 1
  return () => {
    s ^= s << 13
    s ^= s >>> 17
    s ^= s << 5
    s >>>= 0
    return s / 4294967296
  }
}

const CIPHERS = ["AES-256-GCM", "AES-256-GCM"]

function kindLabel(k) {
  switch (k) {
    case "NAME":
      return "person.name"
    case "PHONE":
      return "contact.phone"
    case "AADHAAR":
      return "gov.id.aadhaar"
    case "ADDRESS":
      return "geo.address"
    case "AGE":
      return "demo.age"
  }
}

/**
 * Builds the full post-dictation pipeline for a case.
 */
export function buildPipeline(c, transcript, seed) {
  const rng = makeRng(seed)
  const j = (base, spread = 0.45) => Math.round(base * (1 - spread / 2 + rng() * spread))
  const words = transcript.trim().split(/\s+/).filter(Boolean).length
  const bytes = new TextEncoder().encode(transcript).length
  const entities = (c?.pii || []).length
  const steps = []

  steps.push({
    stage: "INGEST",
    level: "info",
    phase: "received",
    wait: 120,
    spans: [
      { t: "text", v: "Transcript received · " },
      { t: "em", v: `${words} tokens` },
      { t: "text", v: ` / ${bytes} B · ` },
      { t: "em", v: "hi-IN + en-IN" },
    ],
    metric: `${j(34)} ms`,
  })

  steps.push({
    stage: "INGEST",
    level: "ok",
    depth: 1,
    wait: j(220),
    spans: [{ t: "text", v: "Audio buffer discarded at source — no raw voice retained" }],
  })

  steps.push({
    stage: "PII",
    level: "run",
    phase: "scanning",
    wait: j(340),
    progress: true,
    spans: [{ t: "text", v: "PII scan · NER + rule ensemble sweeping transcript" }],
  })

  steps.push({
    stage: "PII",
    level: "warn",
    wait: j(620),
    spans: [
      { t: "text", v: "PII scan: " },
      { t: "em", v: `${entities} ${entities === 1 ? "entity" : "entities"} found` },
      { t: "arrow" },
      { t: "text", v: "redacting" },
    ],
    metric: `${j(210)} ms`,
  })

  ;(c?.pii || []).forEach((p, i) => {
    const shown = p.raw.length > 26 ? p.raw.slice(0, 24) + "…" : p.raw
    steps.push({
      stage: "PII",
      level: "redact",
      depth: 1,
      wait: j(300 + i * 40),
      fx: "redact",
      spans: [
        { t: "text", v: `${kindLabel(p.kind)} · ` },
        { t: "strike", v: shown },
        { t: "arrow" },
        { t: "hash", v: p.hash },
      ],
      metric: `conf ${(0.94 + rng() * 0.055).toFixed(3)}`,
    })
  })

  steps.push({
    stage: "PII",
    level: "ok",
    phase: "redacted",
    wait: j(300),
    spans: [
      { t: "text", v: "Redaction map sealed in local enclave · " },
      { t: "em", v: "re-identification key never leaves device" },
    ],
  })

  steps.push({
    stage: "MODEL",
    level: "run",
    phase: "structuring",
    wait: j(360),
    progress: true,
    spans: [
      { t: "text", v: "Sending to structuring model · " },
      { t: "em", v: "redacted payload only" },
    ],
  })

  steps.push({
    stage: "MODEL",
    level: "info",
    depth: 1,
    wait: j(700),
    spans: [{ t: "text", v: `egress ${bytes - entities * 6} B · 0 identifiers · TLS 1.3 pinned` }],
    metric: `${j(880)} ms`,
  })

  steps.push({
    stage: "FHIR",
    level: "ok",
    phase: "bundling",
    wait: j(520),
    fx: "bundle",
    spans: [
      { t: "text", v: "FHIR bundle received · " },
      { t: "em", v: "R4 · 6 resources" },
    ],
    metric: `${j(120)} ms`,
  })

  steps.push({
    stage: "FHIR",
    level: "info",
    depth: 1,
    wait: j(240),
    spans: [{ t: "text", v: "Condition · Observation×3 · MedicationRequest · CarePlan" }],
  })

  steps.push({
    stage: "VALID",
    level: "run",
    phase: "validating",
    wait: j(300),
    progress: true,
    spans: [{ t: "text", v: "Schema validation against ABDM profile" }],
  })

  steps.push({
    stage: "VALID",
    level: "ok",
    wait: j(560),
    spans: [
      { t: "text", v: "Schema validated " },
      { t: "em", v: "✓" },
      { t: "text", v: " · 0 errors · 0 warnings · " },
      { t: "em", v: "ABDM v1.4" },
    ],
    metric: `${j(64)} ms`,
  })

  steps.push({
    stage: "CRYPT",
    level: "run",
    phase: "encrypting",
    wait: j(320),
    progress: true,
    spans: [
      { t: "text", v: "Encrypting (" },
      { t: "em", v: CIPHERS[0] },
      { t: "text", v: ")…" },
    ],
  })

  steps.push({
    stage: "CRYPT",
    level: "info",
    depth: 1,
    wait: j(520),
    spans: [{ t: "text", v: `key ${hexBlock(rng, 4)} · iv ${hexBlock(rng, 3)} · aad token#${c.token}` }],
    metric: `${j(46)} ms`,
  })

  steps.push({
    stage: "LEDGER",
    level: "ok",
    phase: "sealed",
    wait: j(420),
    fx: "seal",
    spans: [
      { t: "text", v: "Stored, chain-linked " },
      { t: "em", v: "✓" },
      { t: "text", v: " prev " },
      { t: "hash", v: hexBlock(rng, 3) },
      { t: "arrow" },
      { t: "hash", v: hexBlock(rng, 3) },
    ],
  })

  steps.push({
    stage: "LEDGER",
    level: "ok",
    depth: 1,
    wait: j(240),
    spans: [{ t: "text", v: "Record immutable · audit trail append-only · doctor notified" }],
  })

  return steps
}

function hexBlock(rng, groups) {
  const hex = "0123456789ABCDEF"
  let out = ""
  for (let g = 0; g < groups; g++) {
    if (g) out += "·"
    for (let i = 0; i < 4; i++) out += hex[Math.floor(rng() * 16)]
  }
  return out
}

/** Idle chatter shown before any dictation, so the vault never looks dead. */
export function idleLines() {
  return [
    {
      id: "boot-0",
      at: 0,
      stage: "BOOT",
      level: "ok",
      spans: [{ t: "text", v: "Enclave attested · SGX quote verified" }],
    },
    {
      id: "boot-1",
      at: 0,
      stage: "BOOT",
      level: "ok",
      spans: [{ t: "text", v: "Redaction ruleset v2.9.1 loaded · 41 entity classes" }],
    },
    {
      id: "boot-2",
      at: 0,
      stage: "BOOT",
      level: "info",
      spans: [{ t: "text", v: "Ledger head " }, { t: "hash", v: "4F1C·A82D·9E03" }, { t: "text", v: " · 1,284 records" }],
    },
    {
      id: "boot-3",
      at: 0,
      stage: "READY",
      level: "info",
      spans: [{ t: "text", v: "Awaiting transcript — zero data at rest outside vault" }],
    },
  ]
}
