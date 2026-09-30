#!/bin/bash

# Stop all FinBERT AI Trading services

echo "🛑 Stopping FinBERT AI Trading System..."

# Stop Flask backend
if [ -f .flask.pid ]; then
    FLASK_PID=$(cat .flask.pid)
    if ps -p $FLASK_PID > /dev/null 2>&1; then
        kill $FLASK_PID 2>/dev/null
        echo "✅ Flask backend stopped (PID: $FLASK_PID)"
    fi
    rm -f .flask.pid
fi

# Stop FinBERT agent
if [ -f .finbert.pid ]; then
    FINBERT_PID=$(cat .finbert.pid)
    if ps -p $FINBERT_PID > /dev/null 2>&1; then
        kill $FINBERT_PID 2>/dev/null
        echo "✅ FinBERT agent stopped (PID: $FINBERT_PID)"
    fi
    rm -f .finbert.pid
fi

# Kill any remaining processes on port 5000
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    lsof -ti:5000 | xargs kill -9 2>/dev/null || true
    echo "✅ Cleaned up port 5000"
fi

# Kill by process name (fallback)
pkill -f "app_stock_sim.py" 2>/dev/null || true
pkill -f "finbert_trading_agent.py" 2>/dev/null || true

echo "✅ All services stopped"
