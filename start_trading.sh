#!/bin/bash

# FinBERT AI Trading Agent - Startup Script
# This script starts the Flask backend and FinBERT trading agent

set -e

echo "================================================"
echo "🤖 FinBERT AI Trading System"
echo "================================================"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Check dependencies
echo ""
echo "📦 Checking dependencies..."

DEPS=("flask" "torch" "transformers" "numpy" "requests")
MISSING_DEPS=()

for dep in "${DEPS[@]}"; do
    if ! python3 -c "import $dep" 2>/dev/null; then
        MISSING_DEPS+=("$dep")
    fi
done

if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    echo "❌ Missing dependencies: ${MISSING_DEPS[*]}"
    echo ""
    echo "Install with:"
    echo "  pip install torch transformers numpy requests flask"
    echo ""
    read -p "Install now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing dependencies..."
        pip install torch transformers numpy requests flask
        echo "✅ Dependencies installed"
    else
        echo "❌ Cannot continue without dependencies"
        exit 1
    fi
else
    echo "✅ All dependencies installed"
fi

# Check if FinBERT model is downloaded
echo ""
echo "🔍 Checking FinBERT model..."

if python3 -c "
from transformers import AutoTokenizer, AutoModelForSequenceClassification
try:
    tokenizer = AutoTokenizer.from_pretrained('ProsusAI/finbert')
    print('Model found')
except Exception as e:
    print('Model not found')
    exit(1)
" 2>/dev/null | grep -q "Model found"; then
    echo "✅ FinBERT model ready"
else
    echo "⬇️  Downloading FinBERT model (first time only, ~500MB)..."
    python3 -c "
from transformers import AutoTokenizer, AutoModelForSequenceClassification
print('Downloading model...')
tokenizer = AutoTokenizer.from_pretrained('ProsusAI/finbert')
model = AutoModelForSequenceClassification.from_pretrained('ProsusAI/finbert')
print('✅ Model downloaded successfully')
"
fi

# Check GPU availability
echo ""
echo "🖥️  Hardware check..."

if python3 -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
    GPU_NAME=$(python3 -c "import torch; print(torch.cuda.get_device_name(0))")
    echo "✅ GPU detected: $GPU_NAME"
    echo "   Inference time: ~10-20ms per symbol"
else
    echo "⚠️  No GPU detected, using CPU"
    echo "   Inference time: ~50-100ms per symbol"
fi

# Start Flask backend
echo ""
echo "================================================"
echo "🚀 Starting Services"
echo "================================================"
echo ""

# Check if Flask app is already running
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Port 5000 already in use"
    read -p "Kill existing process? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        lsof -ti:5000 | xargs kill -9 2>/dev/null || true
        sleep 2
    else
        echo "❌ Cannot start Flask backend on port 5000"
        exit 1
    fi
fi

echo "📊 Starting Flask backend (app_stock_sim.py)..."

# Start Flask in background
python3 app_stock_sim.py > flask.log 2>&1 &
FLASK_PID=$!

echo "   PID: $FLASK_PID"
echo "   Log: flask.log"

# Wait for Flask to start
echo "   Waiting for Flask to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:5000 > /dev/null 2>&1; then
        echo "   ✅ Flask backend ready"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo "   ❌ Flask failed to start"
        kill $FLASK_PID 2>/dev/null || true
        cat flask.log
        exit 1
    fi
done

# Start FinBERT agent
echo ""
echo "🤖 Starting FinBERT Trading Agent..."

python3 finbert_trading_agent.py > finbert.log 2>&1 &
FINBERT_PID=$!

echo "   PID: $FINBERT_PID"
echo "   Log: finbert.log"

sleep 3

# Check if FinBERT started successfully
if ps -p $FINBERT_PID > /dev/null 2>&1; then
    echo "   ✅ FinBERT agent running"
else
    echo "   ❌ FinBERT agent failed to start"
    echo "   Check finbert.log for errors:"
    tail -20 finbert.log
    kill $FLASK_PID 2>/dev/null || true
    exit 1
fi

# Summary
echo ""
echo "================================================"
echo "✅ System Running"
echo "================================================"
echo ""
echo "Services:"
echo "  📊 Flask Backend:  http://localhost:5000"
echo "  🤖 AI Trading:     Active (60s interval)"
echo ""
echo "Processes:"
echo "  Flask PID:         $FLASK_PID"
echo "  FinBERT PID:       $FINBERT_PID"
echo ""
echo "Logs:"
echo "  Flask:             tail -f flask.log"
echo "  FinBERT:           tail -f finbert.log"
echo ""
echo "Controls:"
echo "  Stop All:          ./stop_trading.sh"
echo "  Restart:           ./start_trading.sh"
echo ""
echo "Dashboard:"
echo "  Open:              http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Save PIDs
echo "$FLASK_PID" > .flask.pid
echo "$FINBERT_PID" > .finbert.pid

# Wait for user interrupt
trap 'echo ""; echo "🛑 Stopping services..."; kill $FLASK_PID $FINBERT_PID 2>/dev/null; rm -f .flask.pid .finbert.pid; echo "✅ Stopped"; exit 0' INT

# Monitor processes
while true; do
    if ! ps -p $FLASK_PID > /dev/null 2>&1; then
        echo "❌ Flask backend crashed!"
        kill $FINBERT_PID 2>/dev/null || true
        exit 1
    fi
    
    if ! ps -p $FINBERT_PID > /dev/null 2>&1; then
        echo "❌ FinBERT agent crashed!"
        kill $FLASK_PID 2>/dev/null || true
        exit 1
    fi
    
    sleep 5
done
