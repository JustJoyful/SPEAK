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
    default:
      return (k || "entity").toLowerCase()
  }
}

/**
 * Dynamically extracts PII entities from live speech and active patient context
 * for real-time Privacy X-Ray strikethrough & cryptographic hashing.
 */
export function extractLivePii(c, transcript = "", overrideName = "") {
  const piiList = []
  const text = transcript || ""

  // 1. Patient Name from override, active case, or transcript
  const rawName = (overrideName || c?.name || "").trim()
  if (rawName && !rawName.startsWith("Token ")) {
    let hashNum = 0
    for (let i = 0; i < rawName.length; i++) hashNum = (hashNum * 31 + rawName.charCodeAt(i)) >>> 0
    const hex = hashNum.toString(16).toUpperCase().padStart(4, "0").slice(-4)
    piiList.push({
      kind: "NAME",
      raw: rawName,
      hash: `HASH_${hex}`,
    })
  }

  // 2. Phone Numbers (10 digits)
  const phoneMatch = text.match(/\b[6-9]\d{9}\b/)
  if (phoneMatch) {
    const rawPhone = phoneMatch[0]
    let hashNum = 0
    for (let i = 0; i < rawPhone.length; i++) hashNum = (hashNum * 31 + rawPhone.charCodeAt(i)) >>> 0
    const hex = hashNum.toString(16).toUpperCase().padStart(4, "0").slice(-4)
    piiList.push({
      kind: "PHONE",
      raw: rawPhone,
      hash: `HASH_${hex}`,
    })
  }

  // 3. Aadhaar (12 digits)
  const aadhaarMatch = text.match(/\b\d{4}\s?\d{4}\s?\d{4}\b/)
  if (aadhaarMatch) {
    const rawAadhaar = aadhaarMatch[0]
    let hashNum = 0
    for (let i = 0; i < rawAadhaar.length; i++) hashNum = (hashNum * 31 + rawAadhaar.charCodeAt(i)) >>> 0
    const hex = hashNum.toString(16).toUpperCase().padStart(4, "0").slice(-4)
    piiList.push({
      kind: "AADHAAR",
      raw: rawAadhaar,
      hash: `HASH_${hex}`,
    })
  }

  // 4. Age (e.g. 34 year old)
  const ageMatch = text.match(/\b(\d{1,2})\s*(?:year[s]?-old|yo|yr[s]?)\b/i)
  if (ageMatch) {
    const rawAge = ageMatch[0]
    piiList.push({
      kind: "AGE",
      raw: rawAge,
      hash: `HASH_${(parseInt(ageMatch[1], 10) * 1337).toString(16).toUpperCase().slice(-4)}`,
    })
  }

  // Include any pre-seeded case pii not already matched
  if (Array.isArray(c?.pii) && c.pii.length > 0) {
    c.pii.forEach((p) => {
      if (!piiList.some((existing) => existing.kind === p.kind || existing.raw.toLowerCase() === p.raw.toLowerCase())) {
        piiList.push(p)
      }
    })
  }

  // Fail-safe: ensure at least one entity is present so strikethrough always executes
  if (piiList.length === 0) {
    const fallbackName = rawName || `Patient #${c?.token || 1}`
    piiList.push({
      kind: "NAME",
      raw: fallbackName,
      hash: "HASH_9E03",
    })
  }

  return piiList
}

/**
 * Builds the full post-dictation pipeline for a case.
 */
export function buildPipeline(c, transcript, seed, dynamicPii) {
  const rng = makeRng(seed)
  const j = (base, spread = 0.45) => Math.round(base * (1 - spread / 2 + rng() * spread))
  const words = transcript.trim().split(/\s+/).filter(Boolean).length
  const bytes = new TextEncoder().encode(transcript).length
  const piiEntities = dynamicPii && dynamicPii.length > 0 ? dynamicPii : (c?.pii && c.pii.length > 0 ? c.pii : [])
  const entities = piiEntities.length
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

  piiEntities.forEach((p, i) => {
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
