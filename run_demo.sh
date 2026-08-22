#!/bin/bash

# Ensure script stops on error
set -e

echo "======================================"
echo " Starting MedSync Zero-Trust Gateway"
echo "======================================"

# Start Backend in background
echo "[1/2] Starting Python FastAPI Backend..."
cd backend
../.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# Start Frontend in foreground
echo "[2/2] Starting React Vite Frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo "======================================"
echo " MedSync is running!"
echo " Backend: http://localhost:8000"
echo " Frontend: http://localhost:5173"
echo " Press Ctrl+C to stop both servers."
echo "======================================"

# Wait for both processes
trap "echo 'Stopping MedSync...'; kill $BACKEND_PID $FRONTEND_PID" EXIT
wait
