# MedSync: Full Implementation Plan & Technical Roadmap (v2 — Decoupled Reception & Dynamic Checklist)

**Project:** ABDM-Compliant Zero-Trust Health Record Pipeline  
**Target:** Smart India Hackathon (SIH) 2026  
**Architecture:** React + Vite (3-Column Frontend) · FastAPI + Pydantic (Edge Node) · SQLite (Local Edge DB) · Turso (Central Index)  
**Status:** `medsyncplan.md` is superseded by this document.

---

## 🏛️ Decoupled Reception vs. Doctor Architecture

MedSync enforces a strict role-based zero-trust security perimeter:

1. **Reception Desk (Identity Layer):**
   - Receptionist enters patient details (Phone / Aadhaar / ABHA ID).
   - Local edge node creates a deterministic salted hash (`abha_hash = HMAC-SHA256(raw_abha_id, SALT)`).
   - Generates a local `care_context_id` (e.g. `CC-98124`) and adds the patient to the daily queue with a token number.
   - **Zero-Trust Rule:** This is the *only* place a raw ABHA ID is entered. It never leaves the local SQLite database.
   - **Demo Setup:** Pre-seeds 3–4 realistic patient tokens on app launch (`waiting` status).

2. **Doctor Desk (Clinical Layer):**
   - Doctor's screen displays the active patient queue on the left sidebar.
   - Doctor clicks a patient token (e.g., `Token #01 - Priya Sharma`).
   - `POST /encounter/select-token` silently sets the active `care_context_id` in server-side session state.
   - **Doctor's screen never sees or renders the ABHA ID or abha_hash.**
   - Doctor speaks or types clinical notes. The backend automatically injects the active session's `care_context_id` into the NRCeS FHIR R4 bundle during structuring.

```
[Reception] ABHA ID resolved → Care-Context created, added to queue (local SQLite only)
[Doctor] Token clicked → care_context_id loaded into active session (backend, silent)
   ↓
Audio Bytes / Typed Notes
   → faster-whisper (local STT, streamed to UI as live cumulative transcript)
   → Presidio (local PII masking: regex for ABHA/Aadhaar/phone/date + GLiNER NER, spaCy fallback)
   → [Passive Checklist Extraction] (debounce on 2-3s pause, fast/cheap LLM, ticks ⬜➔✅ live)
   → Cloud LLM call (scrubbed text + FHIR R4 prompt → structured JSON, triggered on "Finish")
   → Pydantic validation (NRCeS FHIR R4 schema — hard gate, blocks finalize on failure)
   → Backend auto-injects session's care_context_id into the FHIR bundle
   → Re-association (care_context_id → real ABHA ID, local only, for doctor's screen)
   → AES-256-GCM encryption → SQLite write (hash-chained) → background Turso sync (pointer only)
   → Live SSE updates streamed to Doctor's 3-Column UI & X-Ray Panel
```

---

## 🔒 Crucial Invariants & Edge Integrity Constraints

1. **Token Lock & In-Progress Protection:**
   - Selecting a token sets its status to `in-progress`.
   - If a doctor attempts to switch tokens while recording/dictating, the system locks the session and requires confirmation (or discards the draft) to prevent linking a record to the wrong patient's `care_context_id`.
2. **Explicit Status State Machine:**
   - `waiting` ➔ `in-progress` (on token select) ➔ `done` (strictly after Pydantic validation AND AES-256-GCM storage succeed).
   - If validation or LLM fails, status stays `in-progress` (never prematurely marked `done`).
3. **Advisory Checklist vs. Hard Pydantic Gate:**
   - The checklist is an advisory guide during dictation. The doctor can click "Finish" even if items are unticked.
   - However, "Finish" *always* runs the full NRCeS Pydantic schema validation. Missing essential fields (e.g. diagnosis) produces a clear, descriptive validation error.
4. **Cumulative Streaming Transcript:**
   - Speech-to-Text (`stt.py`) and typed input accumulate a full running transcript rather than disconnected fragments, preventing false negatives in both checklist extraction and FHIR structuring.
5. **Fail-Safe X-Ray Visualizer:**
   - The X-Ray panel supports `pending`, `running`, `done`, and `error` states with inline error reasons, turning unexpected API timeouts into a demonstration of system resilience.
6. **Cost & Latency Optimized Checklist:**
   - Checklist extraction runs on a fast/cheap LLM model tier with a minimal boolean JSON schema (`{"symptoms_present": bool, ...}`) on a 2–3s debounce.

---

## 📁 Complete Backend & Frontend Code Structure

```
backend/
  requirements.txt
  .env.example
  main.py                      # FastAPI app, CORS, SSE endpoint
  session/
    active_encounter.py        # Server-side active token/care_context session state & token lock
  routes/
    reception.py               # POST /queue/add, GET /queue/today, GET /queue/seed
    encounter.py               # POST /encounter/select-token, POST /encounter/process, /encounter/finish
    sync.py                    # Background Turso push, GET /sync/status
    consent.py                 # Mock ABDM consent + OTP flow
  pipeline/
    fhir_schema.py             # Pydantic models: QueueEntry, ChecklistState, CareContext, FHIROPConsultRecord, EncryptedBundle, SyncPointer
    checklist.py               # Debounced partial-transcript boolean field extractor (cheap LLM)
    stt.py                     # faster-whisper wrapper for cumulative audio transcription
    pii_mask.py                # Presidio + GLiNER/spaCy, ABHA/Aadhaar/Phone regexes
    care_context.py            # Salted HMAC-SHA256 generation, local mapping
    llm_structurer.py          # Prompt template + Cloud LLM call + Pydantic validation loop
    crypto.py                  # AES-256-GCM encrypt/decrypt
    hash_chain.py              # SHA-256 tamper-evident edge ledger
  db/
    local.py                   # SQLite: queue, care_contexts, encounters, hash_chain
    central.py                 # Turso client: zero-knowledge pointer index
  events/
    bus.py                     # SSE event broadcaster for live UI telemetry

frontend/
  src/
    App.jsx                    # 3-Column main layout
    components/
      QueueColumn.jsx          # Left: Live queue, token selection, token locking, status badges
      DictationColumn.jsx      # Middle: Mic visualizer, cumulative live transcript, preset note pills, Finish button
      XRayChecklistColumn.jsx  # Right container housing XRayPanel & ChecklistPanel
      XRayPanel.jsx            # Real-time pipeline step telemetry (X-ray view) with error indicators
      ChecklistPanel.jsx       # Passive ⬜→✅ live boolean checklist
      RecordViewer.jsx         # Doctor's view of finalized NRCeS FHIR record with decrypted patient context
    hooks/
      usePipelineStream.js     # SSE hook for stage events & checklist updates
    api/
      client.js                # REST client wrapper
```

---

## 🛠️ Step-by-Step Revised Build Order

### ✅ Phase 0: Foundations & Project Scaffolding
- [x] Project directory structure & subpackages.
- [x] `backend/requirements.txt` & `.env.example`.

### 🔄 Phase 1: Core Data Models & Database Layer (Extended)
- [x] **`backend/pipeline/fhir_schema.py`**:
  - Existing models: `CareContext`, `FHIROPConsultRecord`, `EncryptedBundle`, `SyncPointer`.
  - **[NEW Additions]**:
    - `QueueEntry`: `token_number` (int), `patient_display_name` (str), `abha_hash` (str), `status` (`waiting | in-progress | done`), `created_at`.
    - `ChecklistState`: `symptoms_present` (bool), `diagnosis_present` (bool), `medication_present` (bool), `advice_present` (bool).
- [x] **`backend/db/local.py`**:
  - SQLite edge tables: `queue`, `care_contexts`, `encounters`, `hash_chain`.
  - Pre-seeding helper to insert initial mock patients into the daily queue.
- [x] **`backend/db/central.py`**:
  - Zero-knowledge Turso sync client with in-memory fallback.

---

### ✅ Phase 1.5: Reception Queue & Active Session Layer
- [x] **`backend/session/active_encounter.py`**:
  - Thread-safe active encounter state: tracks `current_token`, `care_context_id`, and `is_locked` status.
  - `set_active_token(token_number, care_context_id)` with lock checks.
- [x] **`backend/routes/reception.py`**:
  - `GET /queue/today`: Returns today's patient queue for the doctor sidebar.
  - `POST /queue/add`: Receptionist endpoint to resolve patient ➔ generate salted hash ➔ create CareContext ➔ assign token.
  - `POST /queue/seed`: Pre-populates 3–4 demo patients.
- [x] **Verification:** Test queue seeding, status progression, and token collision locking.

---

### ✅ Phase 2: Local Edge PII Masking Engine
- [x] **`backend/pipeline/pii_mask.py`**:
  - Microsoft Presidio Analyzer + Anonymizer.
  - Custom recognizers for:
    - ABHA ID: `\d{2}-\d{4}-\d{4}-\d{4}` and `@abdm` handles.
    - Aadhaar Number: 12-digit Indian national ID.
    - Phone: `(\+91[\-\s]?)?[6-9]\d{9}`.
    - Patient names, locations, and PIN codes via NER & Indian Regex patterns.
    - Clinical term allowlist to prevent false-positive clinical vocabulary stripping.
  - Sanitizes text before any external transmission.
- [x] **Verification:** Run 10 Indian clinical notes; assert 0% PII leak in output.

---

### ✅ Phase 3: Care-Context Identity Layer
- [x] **`backend/pipeline/care_context.py`**:
  - Salted HMAC-SHA256 hash calculation (`abha_hash`).
  - `care_context_id` generation (`CC-XXXXXX`).
  - Local SQLite mapping and de-anonymized doctor screen resolution.
- [x] **Verification:** Assert bidirectional mapping integrity strictly on localhost.

---

### ✅ Phase 4: Cloud LLM FHIR R4 Structuring Engine
- [x] **`backend/pipeline/llm_structurer.py`**:
  - System prompt enforcing NRCeS FHIR R4 OP-Consult JSON.
  - Pydantic schema validation gate (`FHIROPConsultRecord.model_validate_json`).
  - Automatic error diagnostic reporting on malformed output.
- [x] **Verification:** 10 sample clinical notes pass Pydantic schema validation.

---

### ✅ Phase 5: AES-256-GCM Encryption & Tamper-Evident Hash Chain
- [x] **`backend/pipeline/crypto.py`**:
  - AES-256-GCM local bundle encryption/decryption with authenticated tags.
- [x] **`backend/pipeline/hash_chain.py`**:
  - Local SHA-256 blockchain-style ledger linkage (`record_hash` + `prev_hash`).
- [x] **Verification:** Cryptographic round-trip assert and hash chain tampering detection.

---

### ⏳ Phase 6: Pipeline Integration, Passive Checklist & FastAPI Endpoints
- [ ] **`backend/pipeline/checklist.py`**:
  - Debounced partial-transcript extractor using fast LLM tier to return boolean `ChecklistState`.
- [ ] **`backend/events/bus.py`**:
  - SSE event broadcaster supporting stages: `transcript`, `pii_masked`, `checklist_update`, `fhir_structured`, `pydantic_verified`, `encrypted`, `persisted`, `synced`, `error`.
- [ ] **`backend/routes/encounter.py`**:
  - `POST /encounter/select-token`: Binds session to selected patient token.
  - `POST /encounter/text`: Processes typed or audio-transcribed text through the complete pipeline.
  - `POST /encounter/finish`: Triggers final FHIR generation, Pydantic validation gate, AES encryption, and queue status update to `done`.
- [ ] **`backend/pipeline/stt.py`**:
  - Cumulative faster-whisper transcription wrapper.
- [ ] **`backend/main.py`**:
  - FastAPI application wiring routes, CORS, and lifecycle events.
- **Verification:** End-to-end `curl` testing from queue selection to encrypted storage.

---

### ⏳ Phase 7: 3-Column React + Vite Frontend & Hero Visualizers
- [ ] **Scaffold React + Vite application** (`frontend/`).
- [ ] **`frontend/src/components/QueueColumn.jsx`**:
  - Left panel: Patient tokens, status chips (`waiting`, `in-progress`, `done`), token locking.
- [ ] **`frontend/src/components/DictationColumn.jsx`**:
  - Center panel: Mic waveform, cumulative live transcript stream, quick-insert clinical note pills, "Finish Consultation" button.
- [ ] **`frontend/src/components/XRayChecklistColumn.jsx`**:
  - Right container combining:
    - **`XRayPanel.jsx`**: Real-time terminal visualizer displaying all pipeline stages with live strikethrough redactions, AES lock icon, and hash-chain block hashes.
    - **`ChecklistPanel.jsx`**: Live ⬜➔✅ checklist for Symptoms, Diagnosis, Medication, and Advice.
- [ ] **`frontend/src/components/RecordViewer.jsx`**:
  - Clean doctor-facing view of the finalized FHIR record and raw JSON inspector.
- **Verification:** Full interactive browser demo run from reception queue pick to finalized zero-trust sync.

---

## 🏆 Demonstration Flow for Judges

1. **Step 1 (Reception Separation):** Open UI, show pre-seeded queue on the left. Explain: *"The receptionist handles identity. The doctor never sees the ABHA ID or Aadhaar number."*
2. **Step 2 (Token Select):** Select *Token #01 (Priya Sharma)*. Show token status turn `in-progress`.
3. **Step 3 (Live Dictation & Checklist):** Click mic or select the *Hypertension & Diabetes* demo note. As the note appears, show the **Checklist Panel** ticking ⬜➔✅ in real time on pause.
4. **Step 4 (Zero-Trust Pipeline Execution):** Click *Finish Consultation*.
5. **Step 5 (The X-Ray Kill-Shot):** Watch the **X-Ray Panel** animate each step:
   - PII strings (phone, names) redacted with visual strikethrough.
   - Salted `CareContext` token injected.
   - Cloud LLM structures FHIR R4 JSON.
   - Pydantic verification badge turns green.
   - AES-256-GCM lock closes.
   - Local hash-chain block appends to SQLite.
   - Zero-knowledge pointer pushes to Turso.
6. **Step 6 (De-identified/Re-associated Doctor View):** Show the clean, structured clinical summary and explain: *"ABDM Milestone 1 & 2 achieved with complete Zero-Trust local edge privacy."*
