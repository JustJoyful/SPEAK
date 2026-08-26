#!/usr/bin/env bash
# ==============================================================================
#  S.P.E.A.K.: Secure Patient Extraction & Anonymization Kernel
#  Zero-Trust Edge Gateway for ABDM Outpatient Consultations
#  Live Process & Resource Terminal Dashboard
# ==============================================================================

set -m # Enable job control

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI Color Palette & Styling
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[38;2;45;212;191m'      # S.P.E.A.K. Teal (#2DD4BF)
BLUE='\033[38;2;96;165;250m'      # Vault Blue (#60A5FA)
GREEN='\033[38;2;52;211;153m'     # Verified Green (#34D399)
YELLOW='\033[38;2;251;191;36m'    # Alert Yellow (#FBBF24)
PURPLE='\033[38;2;192;132;252m'   # Crypto Purple (#C084FC)
RED='\033[38;2;248;113;113m'      # Error Red (#F87171)
NC='\033[0m'                      # Reset

LOG_BACKEND="$SCRIPT_DIR/.backend.log"
LOG_FRONTEND="$SCRIPT_DIR/.frontend.log"

# ── Clean Pre-flight ──────────────────────────────────────────────────────────
clear 2>/dev/null || true
echo -e "${CYAN}${BOLD}"
cat << "EOF"
  ____  ____  _____    _    _  __
 / ___||  _ \| ____|  / \  | |/ /
 \___ \| |_) |  _|   / _ \ | ' / 
  ___) |  __/| |___ / ___ \| . \ 
 |____/|_|   |_____/_/   \_\_|\_\

 S.P.E.A.K. (Secure Patient Extraction & Anonymization Kernel)
 Zero-Trust ABDM Edge Node · Live Process Dashboard
EOF
echo -e "${NC}"

echo -e "${DIM}[*] Initializing edge environment & freeing ports (8000, 5173)...${NC}"
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 5173/tcp 2>/dev/null || true
fuser -k 3000/tcp 2>/dev/null || true
fuser -k 3001/tcp 2>/dev/null || true
rm -f "$LOG_BACKEND" "$LOG_FRONTEND"
sleep 0.3

# ── Launch Backend ────────────────────────────────────────────────────────────
echo -e "${BLUE}[1/2] Starting FastAPI Zero-Trust Backend (port 8000)...${NC}"
PYTHONUNBUFFERED=1 PYTHONPATH="$SCRIPT_DIR" \
  "$SCRIPT_DIR/.venv/bin/python" -m uvicorn backend.main:app \
  --host 0.0.0.0 --port 8000 \
  --log-level info > "$LOG_BACKEND" 2>&1 &
BACKEND_PID=$!

# Wait for backend readiness
printf "      ${DIM}Booting faster-whisper ASR & SQLite enclave...${NC} "
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
  echo -e "      ${YELLOW}! Backend startup delayed, proceeding with dashboard...${NC}"
fi

# ── Launch Frontend ───────────────────────────────────────────────────────────
echo -e "${CYAN}[2/2] Starting React Vite Clinical Interface (port 5173)...${NC}"
cd "$SCRIPT_DIR/frontend"
npm run dev > "$LOG_FRONTEND" 2>&1 &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"
sleep 0.8
echo -e "      ${GREEN}✓ Frontend dev server ready!${NC}"
sleep 0.5

# ── Instant Shutdown Handler ──────────────────────────────────────────────────
cleanup() {
  trap - INT TERM EXIT
  echo ""
  echo -e "${YELLOW}[*] Shutting down S.P.E.A.K. edge processes cleanly...${NC}"
  kill -9 -$BACKEND_PID $BACKEND_PID 2>/dev/null || true
  kill -9 -$FRONTEND_PID $FRONTEND_PID 2>/dev/null || true
  fuser -k 8000/tcp 2>/dev/null || true
  fuser -k 5173/tcp 2>/dev/null || true
  fuser -k 3000/tcp 2>/dev/null || true
  fuser -k 3001/tcp 2>/dev/null || true
  rm -f "$LOG_BACKEND" "$LOG_FRONTEND"
  echo -e "${GREEN}✓ All processes stopped and ports released.${NC}"
  exit 0
}
trap cleanup INT TERM EXIT

# ── Live Monitoring Dashboard Loop ────────────────────────────────────────────
START_TIME=$(date +%s)

while true; do
  sleep 1.5

  NOW=$(date +%s)
  ELAPSED=$((NOW - START_TIME))
  ELAPSED_FMT=$(printf "%02d:%02d:%02d" $((ELAPSED/3600)) $(( (ELAPSED%3600)/60 )) $((ELAPSED%60)))
  TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

  # Health check status
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    B_STATUS="${GREEN}ONLINE${NC}  (Port 8000)"
  else
    B_STATUS="${RED}OFFLINE${NC}"
  fi

  if nc -z 127.0.0.1 5173 2>/dev/null || nc -z 127.0.0.1 3000 2>/dev/null; then
    F_STATUS="${GREEN}ONLINE${NC}  (Port 5173)"
  else
    F_STATUS="${YELLOW}STARTING${NC}"
  fi

  # Redraw without flicker
  tput cup 0 0 2>/dev/null || clear

  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║${NC}  ${BOLD}🛡️  S.P.E.A.K. ZERO-TRUST EDGE GATEWAY · LIVE DASHBOARD${NC}                             ${CYAN}║${NC}"
  echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════════════════╣${NC}"
  echo -e "${CYAN}║${NC}  ${BOLD}Node Time:${NC} ${TIMESTAMP}   │  ${BOLD}Uptime:${NC} ${ELAPSED_FMT}                              ${CYAN}║${NC}"
  echo -e "${CYAN}║${NC}  ${BOLD}Doctor Desk:${NC} ${GREEN}http://localhost:5173${NC}    │  ${BOLD}API Gateway:${NC} ${BLUE}http://localhost:8000${NC}       ${CYAN}║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════════════════════════╝${NC}"
  echo ""

  # ── Service Status ──────────────────────────────────────────────────────────
  echo -e "${BOLD}🟢 SERVICE STATUS${NC}"
  echo -e "${DIM}────────────────────────────────────────────────────────────────────────────────────────────${NC}"
  printf "  ${BOLD}%-30s${NC}  PID %-8s  %b\n" "FastAPI Gateway + ASR" "$BACKEND_PID"  "$B_STATUS"
  printf "  ${BOLD}%-30s${NC}  PID %-8s  %b\n" "Vite Clinical UI"      "$FRONTEND_PID" "$F_STATUS"
  echo -e "${DIM}────────────────────────────────────────────────────────────────────────────────────────────${NC}"
  echo ""

  # ── Pipeline Architecture ───────────────────────────────────────────────────
  echo -e "${BOLD}⚙️  EDGE PIPELINE ARCHITECTURE${NC}"
  echo -e "   ${CYAN}•${NC} ${BOLD}On-Device ASR:${NC}       faster-whisper (small.en, int8_float16) + Silero VAD"
  echo -e "   ${BLUE}•${NC} ${BOLD}Zero-Trust Privacy:${NC}  Regex + GLiNER scrub prior to any egress"
  echo -e "   ${PURPLE}•${NC} ${BOLD}Local Cryptography:${NC}  AES-256-GCM sealed envelopes · SQLite WAL ledger"
  echo -e "   ${GREEN}•${NC} ${BOLD}ABDM FHIR R4:${NC}        Standardized OP-Consultation Bundle generator"
  echo ""

  # ── Live Backend Activity Stream ───────────────────────────────────────────
  echo -e "${BOLD}📜 LIVE BACKEND LOG (last 8 events)${NC}"
  echo -e "${DIM}────────────────────────────────────────────────────────────────────────────────────────────${NC}"
  if [ -f "$LOG_BACKEND" ]; then
    tail -n 8 "$LOG_BACKEND" | while IFS= read -r line; do
      if [[ "$line" =~ "ERROR" ]] || [[ "$line" =~ "error" ]]; then
        echo -e "  ${RED}✖ ${line}${NC}"
      elif [[ "$line" =~ "POST" ]] || [[ "$line" =~ "GET" ]] || [[ "$line" =~ "WS" ]] || [[ "$line" =~ "200" ]] || [[ "$line" =~ "101" ]]; then
        echo -e "  ${GREEN}▸ ${line}${NC}"
      else
        echo -e "  ${DIM}• ${line}${NC}"
      fi
    done
  else
    echo -e "  ${DIM}Awaiting backend logs...${NC}"
  fi
  echo -e "${DIM}────────────────────────────────────────────────────────────────────────────────────────────${NC}"
  echo -e "${DIM}Press ${BOLD}Ctrl+C${DIM} to stop all services and free ports.${NC}"

done
