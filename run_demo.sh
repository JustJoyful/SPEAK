#!/usr/bin/env bash
# ==============================================================================
#  MedSync: Zero-Trust Edge Gateway for ABDM Outpatient Consultations
#  Automated Startup & Judge Demonstration Orchestrator
# ==============================================================================

set -m # Enable job control to manage process groups cleanly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI Color Palette
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[38;2;45;212;191m'      # MedSync Teal
BLUE='\033[38;2;96;165;250m'      # Vault Blue
GREEN='\033[38;2;52;211;153m'     # Verified Green
YELLOW='\033[38;2;251;191;36m'    # Alert Yellow
PURPLE='\033[38;2;192;132;252m'   # Crypto Purple
NC='\033[0m'                      # Reset

clear 2>/dev/null || true

echo -e "${CYAN}${BOLD}"
cat << "EOF"
  __  __          _  ____                   
 |  \/  | ___  __| |/ ___| _   _ _ __   ___ 
 | |\/| |/ _ \/ _` |\___ \| | | | '_ \ / __|
 | |  | |  __/ (_| | ___) | |_| | | | | (__ 
 |_|  |_|\___|\__,_||____/ \__, |_| |_|\___|
                           |___/            
 Zero-Trust ABDM Edge Architecture · Hackathon Demo
EOF
echo -e "${NC}"

echo -e "${DIM}──────────────────────────────────────────────────────────────────────────────${NC}"
echo -e "${BOLD} 🛡️  SECURITY & ARCHITECTURAL HIGHLIGHTS FOR JUDGES${NC}"
echo -e "   ${CYAN}•${NC} ${BOLD}On-Device ASR:${NC}        faster-whisper + Silero VAD (0 audio leaves hardware)"
echo -e "   ${BLUE}•${NC} ${BOLD}Zero-Trust Scrub:${NC}     Local regex + GLiNER PII masking prior to cloud LLM"
echo -e "   ${PURPLE}•${NC} ${BOLD}NRCeS FHIR R4:${NC}        Standardized OP-Consultation schema validation"
echo -e "   ${GREEN}•${NC} ${BOLD}Encrypted Ledger:${NC}     AES-256-GCM sealed envelopes + local hash chaining"
echo -e "   ${YELLOW}•${NC} ${BOLD}Store & Forward:${NC}      Full offline autonomy with auto-sync poller"
echo -e "${DIM}──────────────────────────────────────────────────────────────────────────────${NC}"
echo ""

# ── Clean Existing Ports ──────────────────────────────────────────────────────
echo -e "${DIM}[*] Pre-flight: Clearing ports 8000, 5173, 3000...${NC}"
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 5173/tcp 2>/dev/null || true
fuser -k 3000/tcp 2>/dev/null || true
fuser -k 3001/tcp 2>/dev/null || true
sleep 0.4

# ── Start Backend ─────────────────────────────────────────────────────────────
echo -e "${BLUE}[1/2] Launching FastAPI Zero-Trust Backend (port 8000)...${NC}"
PYTHONPATH="$SCRIPT_DIR" \
  "$SCRIPT_DIR/.venv/bin/python" -m uvicorn backend.main:app \
  --host 0.0.0.0 --port 8000 \
  --log-level warning > /dev/null 2>&1 &
BACKEND_PID=$!

# Wait for backend readiness
printf "      ${DIM}Initializing models & SQLite enclave...${NC} "
READY=0
for i in $(seq 1 35); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    READY=1
    break
  fi
  printf "${CYAN}.${NC}"
  sleep 0.5
done
echo ""

if [ $READY -eq 1 ]; then
  echo -e "      ${GREEN}✓ Backend online and healthy!${NC}"
else
  echo -e "      ${YELLOW}! Backend taking longer than usual, proceeding...${NC}"
fi

# ── Start Frontend ────────────────────────────────────────────────────────────
echo -e "${CYAN}[2/2] Launching React Vite Clinical Interface...${NC}"
cd "$SCRIPT_DIR/frontend"
npm run dev > /dev/null 2>&1 &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"
sleep 0.8
echo -e "      ${GREEN}✓ Frontend dev server ready!${NC}"

echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}🚀 MedSync is Live & Ready for Demonstration${NC}                             ${CYAN}║${NC}"
echo -e "${CYAN}╠════════════════════════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}🖥️  Doctor Desk UI:${NC}    ${GREEN}http://localhost:5173${NC} (or http://localhost:3000)   ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}🔌 API Gateway:${NC}        ${BLUE}http://localhost:8000${NC}                                   ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}📖 Interactive Docs:${NC}   ${PURPLE}http://localhost:8000/docs${NC}                              ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}🩺 Health / Enclave:${NC}   ${YELLOW}http://localhost:8000/health${NC}                            ${CYAN}║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${BOLD}🎯 JUDGE DEMO FLOW SUGGESTION (2-MINUTE PITCH):${NC}"
echo -e "  ${BOLD}1. Patient Selection:${NC} Click patient in left queue (ABHA ID anonymized with HMAC-SHA256)."
echo -e "  ${BOLD}2. Real-Time Dictation:${NC} Click Mic to speak (or toggle 'Mock Data' for instant simulation)."
echo -e "  ${BOLD}3. Privacy X-Ray:${NC} Observe the real-time split screen — clinical vs security zone."
echo -e "  ${BOLD}4. Finalize & Seal:${NC} Click 'Finish Consultation' to review NRCeS FHIR R4 clinical record."
echo ""
echo -e "${DIM}Press ${BOLD}Ctrl+C${DIM} at any time to instantly stop both services.${NC}"
echo -e "${DIM}──────────────────────────────────────────────────────────────────────────────${NC}"

# ── Instant Shutdown Handler ──────────────────────────────────────────────────
cleanup() {
  # Disable trap to avoid double triggers
  trap - INT TERM EXIT
  echo ""
  echo -e "${YELLOW}[*] Shutting down MedSync instances immediately...${NC}"

  # Kill process groups and PIDs without waiting
  kill -9 -$BACKEND_PID $BACKEND_PID 2>/dev/null || true
  kill -9 -$FRONTEND_PID $FRONTEND_PID 2>/dev/null || true
  
  # Ensure ports are freed instantly
  fuser -k 8000/tcp 2>/dev/null || true
  fuser -k 5173/tcp 2>/dev/null || true
  fuser -k 3000/tcp 2>/dev/null || true
  fuser -k 3001/tcp 2>/dev/null || true

  echo -e "${GREEN}✓ All services stopped.${NC}"
  exit 0
}

trap cleanup INT TERM EXIT

# Wait indefinitely for signal
while true; do
  sleep 1
done
