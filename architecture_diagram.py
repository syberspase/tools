"""
FinBERT Trading System Architecture Visualization
"""

ARCHITECTURE_DIAGRAM = """
┌─────────────────────────────────────────────────────────────────────────┐
│                         FinBERT AI Trading System                        │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  USER INTERFACE (Browser)                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │  Price Chart │  │  Portfolio   │  │ AI Dashboard │                  │
│  │  (Candles)   │  │  Management  │  │  (Signals)   │                  │
│  └──────────────┘  └──────────────┘  └──────────────┘                  │
└─────────────────────────────────────────────────────────────────────────┘
                                 ▲
                                 │ HTTP/JSON
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FLASK BACKEND (app_stock_sim.py)                                        │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  REST API Endpoints                                             │    │
│  │  • GET  /api/symbols         - Real-time prices                │    │
│  │  • GET  /api/ohlc/:symbol/:tf - OHLC candlestick data         │    │
│  │  • POST /api/trade           - Execute buy/sell orders         │    │
│  │  • GET  /api/portfolio/:user - Portfolio status                │    │
│  │  • POST /api/ai/start        - Start AI trading                │    │
│  │  • POST /api/ai/stop         - Stop AI trading                 │    │
│  │  • GET  /api/ai/signals      - Get current signals             │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  Price Simulation Engine                                        │    │
│  │  • Real-time price updates (1 second interval)                  │    │
│  │  • OHLC candle aggregation (1m/15m/1h/4h timeframes)          │    │
│  │  • Volume simulation                                            │    │
│  └────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  Portfolio Management                                           │    │
│  │  • Cash tracking                                                │    │
│  │  • Position management                                          │    │
│  │  • Trade execution & logging                                    │    │
│  │  • Commission calculation                                       │    │
│  └────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                 ▲
                                 │ REST API Calls
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FINBERT AI TRADING AGENT (finbert_trading_agent.py)                    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Trading Loop (60 second intervals)                              │   │
│  │  1. Fetch OHLCV data for each symbol                            │   │
│  │  2. Generate trading signals                                     │   │
│  │  3. Execute high-confidence trades                               │   │
│  │  4. Update portfolio tracking                                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌──────────────────────────────┐  ┌─────────────────────────────────┐ │
│  │  FinBERT Sentiment Analysis  │  │  Technical Analysis              │ │
│  │  ┌─────────────────────────┐ │  │  ┌──────────────────────────┐  │ │
│  │  │ ProsusAI/finbert Model  │ │  │  │ RSI (14, 7)              │  │ │
│  │  │ • 768-dim BERT encoder  │ │  │  │ MACD (12, 26, 9)         │  │ │
│  │  │ • Financial fine-tuning │ │  │  │ Bollinger Bands (20, 2)  │  │ │
│  │  │ • 3-class output:       │ │  │  │ EMA (12, 26)             │  │ │
│  │  │   - Positive            │ │  │  │ SMA (20, 50)             │  │ │
│  │  │   - Negative            │ │  │  │ ATR (14)                 │  │ │
│  │  │   - Neutral             │ │  │  │ Volume Analysis          │  │ │
│  │  └─────────────────────────┘ │  │  │ Trend Detection          │  │ │
│  │                               │  │  │ Momentum Calculation     │  │ │
│  │  Input:                       │  │  └──────────────────────────┘  │ │
│  │  • Market context text        │  │                                 │ │
│  │  • News articles (optional)   │  │  Output:                        │ │
│  │                               │  │  • Technical Score (-1 to +1)   │ │
│  │  Output:                      │  │  • Support/Resistance           │ │
│  │  • Sentiment Score (-1 to +1) │  │  • Volatility Regime            │ │
│  │  • Confidence (0.0 to 1.0)    │  │  • Market Phase                 │ │
│  └──────────────────────────────┘  └─────────────────────────────────┘ │
│                      ▼                              ▼                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Signal Fusion & Decision Engine                                 │   │
│  │  ┌───────────────────────────────────────────────────────────┐  │   │
│  │  │  Combined Score = (Technical * 0.6) + (Sentiment * 0.4)    │  │   │
│  │  └───────────────────────────────────────────────────────────┘  │   │
│  │                                                                   │   │
│  │  Decision Rules:                                                 │   │
│  │  • BUY:  Combined Score > +0.3 AND Confidence > 0.65            │   │
│  │  • SELL: Combined Score < -0.3 AND Confidence > 0.65            │   │
│  │  • HOLD: Otherwise                                               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Risk Management Module                                          │   │
│  │  • Position Sizing: Max 15% per trade                           │   │
│  │  • Stop Loss: 3% from entry                                     │   │
│  │  • Take Profit: 5% from entry                                   │   │
│  │  • Portfolio Diversification                                     │   │
│  │  • Drawdown Limits                                               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Trade Execution                                                 │   │
│  │  • Calculate position size                                       │   │
│  │  • Submit order via API                                          │   │
│  │  • Track active positions                                        │   │
│  │  • Log all trades                                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  DATA FLOW EXAMPLE (Single Trading Cycle)                                │
│                                                                           │
│  Symbol: AAPL                                                             │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ 1. Fetch OHLCV (15m timeframe, 100 candles)                    │     │
│  │    └─> [{'time': 1699..., 'open': 230.5, 'high': 231.2, ...}] │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                          ▼                                                │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ 2. Technical Analysis                                           │     │
│  │    └─> RSI: 45.3, Trend: Uptrend, Momentum: Positive           │     │
│  │    └─> Technical Score: +0.42                                  │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                          ▼                                                │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ 3. Generate Market Context                                      │     │
│  │    └─> "AAPL shows strong momentum with positive technical     │     │
│  │         signals. RSI indicates healthy buying pressure."        │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                          ▼                                                │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ 4. FinBERT Sentiment Analysis (50ms inference)                 │     │
│  │    └─> Positive: 0.78, Negative: 0.12, Neutral: 0.10          │     │
│  │    └─> Sentiment Score: +0.66                                  │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                          ▼                                                │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ 5. Signal Fusion                                                │     │
│  │    └─> Combined: (0.42 * 0.6) + (0.66 * 0.4) = +0.516         │     │
│  │    └─> Confidence: 0.516 (51.6%)                               │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                          ▼                                                │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ 6. Decision: HOLD (confidence < 0.65 threshold)                │     │
│  │    └─> Wait for stronger signal                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                           │
│  Example BUY Signal:                                                      │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ Technical Score: +0.75, Sentiment Score: +0.82                 │     │
│  │ Combined: +0.778, Confidence: 77.8% ✅ EXCEEDS THRESHOLD       │     │
│  │                                                                  │     │
│  │ Action: BUY                                                      │     │
│  │ Position Size: 11.67% of portfolio                              │     │
│  │ Stop Loss: $226.59 (-3%)                                        │     │
│  │ Take Profit: $244.93 (+5%)                                      │     │
│  │ Reasoning: Strong Uptrend | RSI(45.3) | Positive sentiment     │     │
│  └────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  PERFORMANCE METRICS                                                      │
│                                                                           │
│  Latency Breakdown (per symbol):                                         │
│  ┌──────────────────────────────┬─────────┬──────────┐                  │
│  │ Component                     │ CPU     │ GPU      │                  │
│  ├──────────────────────────────┼─────────┼──────────┤                  │
│  │ OHLCV API Fetch              │ 5-10ms  │ 5-10ms   │                  │
│  │ Technical Calculation         │ 5-10ms  │ 5-10ms   │                  │
│  │ FinBERT Inference             │ 50-100ms│ 10-20ms  │                  │
│  │ Signal Generation             │ 5ms     │ 5ms      │                  │
│  │ Trade Execution (if needed)   │ 10-20ms │ 10-20ms  │                  │
│  ├──────────────────────────────┼─────────┼──────────┤                  │
│  │ TOTAL per symbol              │ 75-145ms│ 35-65ms  │                  │
│  └──────────────────────────────┴─────────┴──────────┘                  │
│                                                                           │
│  Throughput:                                                              │
│  • CPU: ~10 symbols/second (parallel processing)                         │
│  • GPU: ~30 symbols/second (parallel processing)                         │
│                                                                           │
│  Resource Usage:                                                          │
│  • RAM: 2-3 GB (FinBERT model + data)                                   │
│  • CPU: 1-2 cores @ 50-70% utilization                                   │
│  • GPU: Optional (VRAM: 2GB+, utilization: 20-40%)                      │
│  • Disk: 600 MB (model storage)                                          │
│  • Network: Minimal (local API calls)                                    │
└─────────────────────────────────────────────────────────────────────────┘
"""

print(ARCHITECTURE_DIAGRAM)
