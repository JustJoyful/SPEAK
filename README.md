<div align="center">

# 🩺 S.P.E.A.K.

### Secure Patient Extraction & Anonymization Kernel

**Local-edge voice-to-structured-record workflow for clinical consultations**

*Smart India Hackathon 2026 · Team OPSEC · PS ID 26133*

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi)](backend/main.py)
[![React](https://img.shields.io/badge/React-19-149eca?logo=react)](frontend/package.json)
[![faster‑whisper](https://img.shields.io/badge/faster--whisper-small.en-blueviolet)](backend/pipeline/stt.py)
[![GLiNER](https://img.shields.io/badge/GLiNER-PII%20masking-orange)](backend/pipeline/pii_mask.py)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-red)](backend/pipeline/fhir_schema.py)

</div>

---

## Table of Contents

1. [The Problem](#the-problem)
2. [Our Approach](#our-approach)
3. [Architecture](#architecture)
4. [Tech Stack](#tech-stack)
5. [Key Features](#key-features)
6. [Getting Started](#getting-started)
7. [Environment Variables](#environment-variables)
8. [Running Tests](#running-tests)
9. [Project Structure](#project-structure)
10. [Standards & References](#standards--references)

---

## The Problem

Indian primary-care physicians spend 30–40% of consultation time on manual documentation. Rural and Tier-2 clinics operate on intermittent connectivity and legacy dual-core hardware. Existing EMR solutions require cloud round-trips for every keystroke, making real-time dictation impractical and privacy-risky.

---

## Our Approach

S.P.E.A.K. keeps every sensitive computation on the edge node — the local clinic PC:

| Challenge | Solution |
|---|---|
| Documentation workload | Single workspace: queue, mic dictation, typed notes, transcript editing, structured record review |
| Legacy CPU + no GPU | faster-whisper `small.en` with `int8_float32` quantization; Silero VAD gates inference, eliminating idle CPU spin |
| Intermittent connectivity | WAL-mode SQLite outbox; background poller retries every 10 s, processes pending records only when internet returns |
| PII on the wire | GLiNER + regex mask the transcript **before** any optional external LLM call; only de-identified clinical text leaves the clinic |
| Indian accent & vocabulary | `initial_prompt` pre-loaded with Indian clinical vocabulary (Dolo 650, Metformin, Amlodipine…); hotword injection for unscheduled-patient names |

---

## Architecture

![S.P.E.A.K. architecture overview](docs/architecture.svg)

### Data Flow

```
Doctor mic
  → AudioWorklet (16 kHz PCM, Float32→Int16 in-browser)
  → WebSocket /encounter/{token}/audio-stream
  → Silero VAD chunks → faster-whisper (asyncio.to_thread, non-blocking)
  → TRANSCRIPT_CHUNK → React UI (useTranscriptDebouncer, 700ms/3s ceiling)
  → Finalize button
  → GLiNER + regex PII masking
  → Pydantic-validated FHIR R4 Bundle
  → AES-256-GCM encryption
  → SQLite outbox
  → Sync poller (internet? → optional Gemini/OpenAI/Anthropic structuring → hash-chain ledger)
```

The browser communicates with the local FastAPI service over **HTTP** (queue, reception, finalization), **WebSocket** (audio streaming + real-time transcript), and **SSE** (Privacy X-Ray pipeline event stream). No audio or raw transcript data is transmitted beyond the local network unless the operator explicitly configures an LLM API key.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| API service | FastAPI ≥ 0.110, Uvicorn | `reception`, `encounter`, and `events` routers; security headers middleware; CORS locked to localhost origins |
| Frontend | React 19, Vite 8, Tailwind CSS v4 | `@tailwindcss/vite` plugin; `@` path alias to `src/` |
| Audio capture | Web Audio API, AudioWorklet | `AudioContext({ sampleRate: 16000 })` requests OS-level resampling; custom Int16 downsampler polyfill if the context refuses the hint (`public/audio-processor.js`) |
| Speech-to-text | faster-whisper ≥ 1.0, NumPy | `small.en`, `int8_float32` (int8 weights, float32 activations — correct CPU equivalent of int8_float16); 8 CPU threads; Silero VAD pre-segments audio; 4-layer hallucination suppression |
| Concurrency | `asyncio.to_thread()` | Isolates faster-whisper and Silero VAD from the FastAPI event loop; audio frames are never dropped due to ML inference blocking |
| PII masking | GLiNER ≥ 0.1.12 + Python `re` | Detects `PERSON` entities; regex masks ABHA IDs, Aadhaar, phone numbers, and PINs |
| Checklist extraction | Python `re` (backend) + JS `RegExp` (frontend) | Dual-layer: instant local match on every debounce tick + backend `/encounter/{token}/text` endpoint |
| Data models | Pydantic ≥ 2.6 | Queue, care-context, outpatient record, encrypted bundle, and sync-pointer models |
| Local storage | Python `sqlite3` + `aiosqlite` | WAL mode; tables: `queue`, `care_contexts`, `encounters`, `hash_chain` |
| Encryption | `cryptography` ≥ 42 / `AESGCM` | 96-bit nonce, 256-bit key from env; ciphertext, nonce, and auth tag stored separately |
| HTTP client | `httpx` ≥ 0.27 | LLM structuring requests + connectivity check (HEAD `1.1.1.1`) |
| LLM structuring | OpenAI-compatible API | Supports `gemini`, `openai`, `anthropic` providers via env; local rule-based fallback when no key is set |
| Icons | `lucide-react` | |
| Auth (prototype) | `X-Role: doctor` header | Checked by `verify_doctor` FastAPI dependency |

---

## Key Features

### 🎙️ Live Dictation Pipeline
- **Browser-side resampling**: `AudioContext({ sampleRate: 16000 })` requests OS-level anti-aliased downsampling. The AudioWorklet converts `Float32` PCM to signed `Int16` and streams it over WebSocket — the FastAPI server receives clean 16 kHz PCM and performs **zero audio preprocessing**.
- **Non-blocking inference**: `asyncio.to_thread()` isolates faster-whisper and Silero VAD from the FastAPI event loop; audio frames are never dropped due to ML inference blocking the main coroutine.
- **Hallucination suppression**: 4 independent layers prevent the model from transcribing silence — decoder parameters, per-segment log-prob gate, known-phrase blocklist, and RMS energy floor.

### 🧾 Unified Transcript Ingestion
- `useTranscriptDebouncer` routes live Whisper chunks, mock word bursts, and manual textarea edits through a single state machine.
- **Trailing quiet timer** (700 ms) with a **max-wait ceiling** (3 s) prevents starvation during continuous speech while flushing promptly after pauses.
- **In-flight race guard**: if the active patient token changes mid-network-request, the stale response is silently dropped.

### 🔍 Note Completeness Checklist
- Instant local regex evaluation on every debounce tick (no network required) via `SYMPTOM_PATTERN`, `DIAGNOSIS_PATTERN`, `MEDICATION_PATTERN`, and `ADVICE_PATTERN` in `src/lib/cases.js`.
- Backend `checklist.py` confirms boolean flags (`symptoms_present`, `diagnosis_present`, …); `normalizeChecklistState()` bridges the backend boolean schema to the frontend `"checked"/"filling"/"empty"` string schema.
- `lastMark.current` unlatches on every `activeToken` change so the `filling → checked` animation fires fresh for each new patient.

### 🚶 Unscheduled Encounter ("Quick Override")
- Doctor types a patient name into the search bar; if not found, the UI offers *"Start Unscheduled Encounter for 'X'?"*
- On confirm, the name is sent to `POST /unscheduled`; the backend creates a queue entry and returns a token number.
- `initial_prompt` and hotwords are seeded with the patient name so Whisper nails the spelling on first utterance.

### 🔒 Privacy X-Ray
- Server-Sent Events stream every pipeline stage (PII detection, redaction count, validation state, encryption, hash-chain) to `XrayLog.jsx` in real time.
- Finalization calls `pii_mask.py` before the transcript is eligible for any external request.

### 📡 Offline Store-and-Forward
- Finalized encounters land in a SQLite WAL outbox row with status `pending`.
- `sync_poller.py` runs as a background `asyncio` task, polling every **10 seconds**. On connectivity return (HEAD `1.1.1.1`), it structures, validates, encrypts, and hash-links each pending record.
- Rows exceeding the retry threshold are moved to `failed` status to prevent infinite retry loops on malformed LLM responses.

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- A browser with microphone permission and AudioWorklet support (Chrome 74+, Safari 14.1+, Firefox 61+)

### Installation

```bash
git clone https://github.com/JustJoyful/medsync-proto.git
cd medsync-proto

# Backend
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt

# Frontend
npm --prefix frontend ci
```

### Configure Environment

```bash
cp .env.example .env
```

Generate a fresh AES-256 encryption key (required before finalizing any encounter):

```bash
printf '\nAES_ENCRYPTION_KEY=%s\n' \
  "$(python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())')" >> .env
```

### Run (two terminals)

```bash
# Terminal 1 — FastAPI backend on :8000
PYTHONPATH=. .venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

```bash
# Terminal 2 — Vite dev server on :3000
npm --prefix frontend run dev
```

Open **http://localhost:3000**. The frontend defaults to `http://localhost:8000`; set `VITE_MEDSYNC_API_URL` in `.env` to override.

### One-shot demo launcher

Requires `curl`, `fuser`, and `nc`:

```bash
./run_demo.sh
```

### Production build

```bash
npm --prefix frontend run build   # outputs to frontend/dist/
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AES_ENCRYPTION_KEY` | *(required)* | Base64-encoded 256-bit key for AES-256-GCM record encryption |
| `ABDM_SALT` | `medsync-sih-2026-edge-node-salt-secret` | Pepper for HMAC-SHA256 ABHA hash |
| `SQLITE_DB_PATH` | `medsync_edge.db` | Local SQLite database file path |
| `WHISPER_MODEL_SIZE` | `small.en` | `tiny.en`, `base.en`, `small.en`, or `distil-small.en` |
| `WHISPER_COMPUTE_TYPE` | `int8_float32` | CPU: `int8_float32`; CUDA: `int8_float16` |
| `WHISPER_CPU_THREADS` | `8` | Set to `nproc/2`; leaves threads free for OS and browser |
| `LLM_PROVIDER` | `gemini` | `gemini`, `openai`, or `anthropic` |
| `GEMINI_API_KEY` | *(optional)* | Enables Gemini-based FHIR structuring |
| `OPENAI_API_KEY` | *(optional)* | Enables OpenAI-based structuring |
| `ANTHROPIC_API_KEY` | *(optional)* | Enables Claude-based structuring |
| `FRONTEND_URL` | `""` | Add a non-localhost origin to the CORS allowlist |
| `TURSO_URL` / `TURSO_AUTH_TOKEN` | *(optional)* | Central index sync target |
| `MOCK_TURSO` | `true` | Skip real Turso calls during development |
| `VITE_MEDSYNC_API_URL` | `http://localhost:8000` | Backend URL consumed by the React client |

> **Note:** Whisper and GLiNER models are **lazily loaded on first use** — not at startup. This avoids OOM kills on constrained edge hardware and keeps FastAPI boot time under 1 second.

---

## Running Tests

```bash
# All backend tests
PYTHONPATH=. .venv/bin/pytest backend/tests -v

# Specific module
PYTHONPATH=. .venv/bin/pytest backend/tests/test_stt_pipeline.py -v
```

Test coverage: auth, care-context HMAC hashing, PII masking, FHIR model validation, AES-GCM encryption and hash-chain integrity, queue/session lifecycle, startup seeding, LLM structuring (mocked), STT buffering and hallucination filtering, and encounter finalization / 409 session locks.

---

## Project Structure

```
medsync-proto/
├── backend/
│   ├── main.py                       # FastAPI app, middleware, router registration
│   ├── requirements.txt
│   ├── db/
│   │   └── local.py                  # SQLite schema, CRUD, WAL outbox
│   ├── events/
│   │   └── bus.py                    # In-process SSE event bus
│   ├── pipeline/
│   │   ├── stt.py                    # faster-whisper + Silero VAD session
│   │   ├── pii_mask.py               # GLiNER + regex masking
│   │   ├── checklist.py              # Clinical field extraction (regex)
│   │   ├── fhir_schema.py            # Pydantic models (FHIR R4 subset)
│   │   ├── crypto.py                 # AES-256-GCM encrypt/decrypt + hash chain
│   │   ├── llm_structurer.py         # OpenAI-compatible structuring + local fallback
│   │   └── sync_poller.py            # Background store-and-forward poller
│   ├── routes/
│   │   ├── reception.py              # /queue/*, /unscheduled, care-context
│   │   ├── encounter.py              # WebSocket audio, text append, finalize
│   │   └── events.py                 # GET /events SSE stream
│   ├── session/
│   │   └── active_encounter.py       # In-memory encounter session state
│   └── tests/                        # pytest suite (9 test files)
├── frontend/
│   ├── public/
│   │   └── audio-processor.js        # AudioWorklet: Float32 → Int16 PCM
│   └── src/
│       ├── App.jsx                   # Root state, orchestration
│       ├── api/client.js             # medSyncApi, backendConfigured flag
│       ├── components/
│       │   ├── DictationPanel.jsx
│       │   ├── QueueRail.jsx
│       │   ├── ChecklistPanel.jsx
│       │   ├── XrayLog.jsx
│       │   ├── RecordViewer.jsx
│       │   └── SyncBadge.jsx
│       ├── hooks/
│       │   ├── useAudioStreamer.js         # Mic → AudioWorklet → WebSocket
│       │   ├── useTranscriptDebouncer.js  # Unified text ingestion + debounce
│       │   └── usePipelineStream.js       # SSE consumer
│       └── lib/
│           ├── cases.js              # Clinical regex patterns, checklist normalizer
│           └── pipeline.js           # Mock pipeline data for offline demo
├── docs/
│   └── architecture.svg
├── .env.example
├── run_demo.sh
└── conftest.py
```

---

## Standards & References

| Standard | Status |
|---|---|
| **HL7 FHIR R4** | Output record modeled as a `Bundle/document` with patient care-context reference, complaints, vitals, diagnoses, medications, and advice |
| **NRCeS / ABDM outpatient subset** | Structuring prompt targets NRCeS-aligned terminology; a full ABDM gateway bridge is out of scope for this prototype |
| **DPDPA 2023** | Local masking before any external call, AES-256-GCM at rest, salted HMAC for ABHA IDs; legal compliance requires deployment-specific review |

---



---

<div align="center">
<sub>Built for Smart India Hackathon 2026 · PS ID 26133 · All patient data stays on-device.</sub>
</div>



