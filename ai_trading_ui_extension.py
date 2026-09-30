"""
AI Trading Dashboard Extension for app_stock_sim.py
Add this to your Flask app to visualize FinBERT trading signals
"""

AI_TRADING_DASHBOARD_HTML = """
<!-- AI Trading Dashboard Tab -->
<style>
.ai-dashboard {
    padding: 20px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 12px;
    margin: 20px 0;
}

.ai-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: white;
    margin-bottom: 20px;
}

.ai-status {
    display: inline-block;
    padding: 8px 16px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 14px;
}

.ai-status.active {
    background: #10b981;
    animation: pulse 2s infinite;
}

.ai-status.inactive {
    background: #ef4444;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

.signal-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 15px;
    margin-top: 15px;
}

.signal-card {
    background: white;
    border-radius: 10px;
    padding: 20px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    transition: transform 0.2s;
}

.signal-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 8px 12px rgba(0,0,0,0.15);
}

.signal-card.buy {
    border-left: 4px solid #10b981;
}

.signal-card.sell {
    border-left: 4px solid #ef4444;
}

.signal-card.hold {
    border-left: 4px solid #6b7280;
}

.signal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 15px;
}

.signal-symbol {
    font-size: 20px;
    font-weight: bold;
    color: #1f2937;
}

.signal-action {
    padding: 6px 12px;
    border-radius: 6px;
    font-weight: bold;
    font-size: 12px;
    text-transform: uppercase;
}

.signal-action.buy {
    background: #d1fae5;
    color: #065f46;
}

.signal-action.sell {
    background: #fee2e2;
    color: #991b1b;
}

.signal-action.hold {
    background: #e5e7eb;
    color: #374151;
}

.confidence-bar {
    width: 100%;
    height: 8px;
    background: #e5e7eb;
    border-radius: 4px;
    overflow: hidden;
    margin: 10px 0;
}

.confidence-fill {
    height: 100%;
    background: linear-gradient(90deg, #10b981 0%, #3b82f6 100%);
    transition: width 0.5s;
}

.signal-metrics {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-top: 15px;
}

.metric {
    padding: 10px;
    background: #f9fafb;
    border-radius: 6px;
}

.metric-label {
    font-size: 11px;
    color: #6b7280;
    text-transform: uppercase;
    margin-bottom: 4px;
}

.metric-value {
    font-size: 16px;
    font-weight: bold;
    color: #1f2937;
}

.metric-value.positive {
    color: #10b981;
}

.metric-value.negative {
    color: #ef4444;
}

.reasoning {
    margin-top: 15px;
    padding: 12px;
    background: #f3f4f6;
    border-radius: 6px;
    font-size: 13px;
    color: #374151;
    line-height: 1.6;
}

.ai-controls {
    display: flex;
    gap: 10px;
    margin-top: 20px;
}

.ai-btn {
    padding: 12px 24px;
    border: none;
    border-radius: 8px;
    font-weight: bold;
    cursor: pointer;
    transition: all 0.2s;
}

.ai-btn-start {
    background: #10b981;
    color: white;
}

.ai-btn-start:hover {
    background: #059669;
}

.ai-btn-stop {
    background: #ef4444;
    color: white;
}

.ai-btn-stop:hover {
    background: #dc2626;
}

.ai-btn-refresh {
    background: #3b82f6;
    color: white;
}

.ai-btn-refresh:hover {
    background: #2563eb;
}

.trade-history {
    background: white;
    border-radius: 10px;
    padding: 20px;
    margin-top: 20px;
}

.trade-history h3 {
    margin-bottom: 15px;
    color: #1f2937;
}

.trade-list {
    max-height: 400px;
    overflow-y: auto;
}

.trade-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px;
    border-bottom: 1px solid #e5e7eb;
}

.trade-item:last-child {
    border-bottom: none;
}

.trade-info {
    display: flex;
    gap: 15px;
    align-items: center;
}

.trade-time {
    font-size: 12px;
    color: #6b7280;
}

.sentiment-gauge {
    display: flex;
    justify-content: space-between;
    margin: 15px 0;
    font-size: 12px;
}

.sentiment-bar {
    height: 6px;
    background: linear-gradient(90deg, #ef4444 0%, #6b7280 50%, #10b981 100%);
    border-radius: 3px;
    position: relative;
}

.sentiment-marker {
    position: absolute;
    width: 12px;
    height: 12px;
    background: white;
    border: 2px solid #1f2937;
    border-radius: 50%;
    top: -3px;
    transform: translateX(-50%);
}
</style>

<div class="ai-dashboard">
    <div class="ai-header">
        <div>
            <h2 style="margin: 0; font-size: 24px;">🤖 FinBERT AI Trading Agent</h2>
            <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">
                Sentiment Analysis + Technical Indicators
            </p>
        </div>
        <div class="ai-status" id="aiStatus">
            <span id="aiStatusText">INACTIVE</span>
        </div>
    </div>

    <div class="ai-controls">
        <button class="ai-btn ai-btn-start" onclick="startAITrading()">
            ▶ Start Auto-Trading
        </button>
        <button class="ai-btn ai-btn-stop" onclick="stopAITrading()">
            ⏹ Stop
        </button>
        <button class="ai-btn ai-btn-refresh" onclick="refreshSignals()">
            🔄 Refresh Signals
        </button>
    </div>

    <div style="background: rgba(255,255,255,0.1); padding: 15px; border-radius: 8px; margin-top: 20px; color: white;">
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; text-align: center;">
            <div>
                <div style="font-size: 12px; opacity: 0.8;">Active Signals</div>
                <div style="font-size: 24px; font-weight: bold;" id="activeSignalsCount">0</div>
            </div>
            <div>
                <div style="font-size: 12px; opacity: 0.8;">Trades Today</div>
                <div style="font-size: 24px; font-weight: bold;" id="tradesToday">0</div>
            </div>
            <div>
                <div style="font-size: 12px; opacity: 0.8;">Win Rate</div>
                <div style="font-size: 24px; font-weight: bold;" id="winRate">0%</div>
            </div>
            <div>
                <div style="font-size: 12px; opacity: 0.8;">P&L Today</div>
                <div style="font-size: 24px; font-weight: bold;" id="plToday">$0</div>
            </div>
        </div>
    </div>
</div>

<div class="signal-grid" id="signalsGrid">
    <!-- Trading signals will be injected here -->
</div>

<div class="trade-history">
    <h3>📊 Recent AI Trades</h3>
    <div class="trade-list" id="tradeHistory">
        <div style="text-align: center; color: #6b7280; padding: 40px;">
            No trades yet. Start AI trading to see results.
        </div>
    </div>
</div>

<script>
let aiTradingActive = false;
let signalRefreshInterval = null;

function startAITrading() {
    fetch('/api/ai/start', {method: 'POST'})
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                aiTradingActive = true;
                updateAIStatus(true);
                
                // Start refreshing signals
                refreshSignals();
                signalRefreshInterval = setInterval(refreshSignals, 10000); // Every 10 seconds
                
                alert('✅ AI Trading Started!');
            } else {
                alert('❌ Failed to start AI trading: ' + data.message);
            }
        })
        .catch(err => {
            alert('Error starting AI trading: ' + err.message);
        });
}

function stopAITrading() {
    fetch('/api/ai/stop', {method: 'POST'})
        .then(res => res.json())
        .then(data => {
            aiTradingActive = false;
            updateAIStatus(false);
            
            if (signalRefreshInterval) {
                clearInterval(signalRefreshInterval);
                signalRefreshInterval = null;
            }
            
            alert('⏹️ AI Trading Stopped');
        })
        .catch(err => {
            alert('Error stopping AI trading: ' + err.message);
        });
}

function updateAIStatus(active) {
    const statusElement = document.getElementById('aiStatus');
    const statusText = document.getElementById('aiStatusText');
    
    if (active) {
        statusElement.className = 'ai-status active';
        statusText.textContent = '🟢 ACTIVE';
    } else {
        statusElement.className = 'ai-status inactive';
        statusText.textContent = '🔴 INACTIVE';
    }
}

function refreshSignals() {
    fetch('/api/ai/signals')
        .then(res => res.json())
        .then(data => {
            renderSignals(data.signals || []);
            updateStats(data.stats || {});
        })
        .catch(err => {
            console.error('Error fetching signals:', err);
        });
    
    // Also refresh trade history
    fetch('/api/ai/trades')
        .then(res => res.json())
        .then(data => {
            renderTradeHistory(data.trades || []);
        })
        .catch(err => {
            console.error('Error fetching trades:', err);
        });
}

function renderSignals(signals) {
    const grid = document.getElementById('signalsGrid');
    
    if (signals.length === 0) {
        grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: white; padding: 40px;">No signals generated yet. Start AI trading or refresh.</div>';
        return;
    }
    
    grid.innerHTML = signals.map(signal => `
        <div class="signal-card ${signal.action.toLowerCase()}">
            <div class="signal-header">
                <div class="signal-symbol">${signal.symbol}</div>
                <div class="signal-action ${signal.action.toLowerCase()}">
                    ${signal.action}
                </div>
            </div>
            
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 10px;">
                Confidence: ${(signal.confidence * 100).toFixed(1)}%
            </div>
            <div class="confidence-bar">
                <div class="confidence-fill" style="width: ${signal.confidence * 100}%"></div>
            </div>
            
            <div class="signal-metrics">
                <div class="metric">
                    <div class="metric-label">Technical</div>
                    <div class="metric-value ${signal.technical_score > 0 ? 'positive' : signal.technical_score < 0 ? 'negative' : ''}">
                        ${signal.technical_score > 0 ? '+' : ''}${signal.technical_score.toFixed(2)}
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Sentiment</div>
                    <div class="metric-value ${signal.sentiment_score > 0 ? 'positive' : signal.sentiment_score < 0 ? 'negative' : ''}">
                        ${signal.sentiment_score > 0 ? '+' : ''}${signal.sentiment_score.toFixed(2)}
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">RSI</div>
                    <div class="metric-value">
                        ${signal.technicals.rsi_14.toFixed(1)}
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Price</div>
                    <div class="metric-value">
                        $${signal.technicals.price.toFixed(2)}
                    </div>
                </div>
            </div>
            
            <div class="reasoning">
                ${signal.reasoning}
            </div>
            
            <div style="margin-top: 10px; font-size: 11px; color: #9ca3af;">
                ${signal.technicals.trend} • ${signal.technicals.momentum}
            </div>
        </div>
    `).join('');
}

function updateStats(stats) {
    document.getElementById('activeSignalsCount').textContent = stats.active_signals || 0;
    document.getElementById('tradesToday').textContent = stats.trades_today || 0;
    document.getElementById('winRate').textContent = (stats.win_rate || 0) + '%';
    document.getElementById('plToday').textContent = '$' + (stats.pl_today || 0).toLocaleString();
}

function renderTradeHistory(trades) {
    const container = document.getElementById('tradeHistory');
    
    if (trades.length === 0) {
        container.innerHTML = '<div style="text-align: center; color: #6b7280; padding: 40px;">No trades yet</div>';
        return;
    }
    
    container.innerHTML = trades.slice(0, 20).map(trade => `
        <div class="trade-item">
            <div class="trade-info">
                <div class="signal-action ${trade.action.toLowerCase()}" style="margin: 0;">
                    ${trade.action}
                </div>
                <div>
                    <div style="font-weight: bold;">${trade.symbol}</div>
                    <div style="font-size: 12px; color: #6b7280;">
                        ${trade.shares} shares @ $${trade.price.toFixed(2)}
                    </div>
                </div>
            </div>
            <div class="trade-time">
                ${new Date(trade.timestamp).toLocaleTimeString()}
            </div>
        </div>
    `).join('');
}

// Auto-refresh if AI is active
setInterval(() => {
    if (aiTradingActive) {
        refreshSignals();
    }
}, 15000);
</script>
"""


def add_ai_routes_to_app(app, agent):
    """
    Add AI trading routes to Flask app
    
    Usage:
        from finbert_trading_agent import FinBERTTradingAgent, AutoTradingLoop
        from ai_trading_ui_extension import add_ai_routes_to_app
        
        agent = FinBERTTradingAgent()
        symbols = ['AAPL', 'GOOGL', 'BTC-USD']
        trading_loop = AutoTradingLoop(agent, symbols)
        
        add_ai_routes_to_app(app, agent)
    """
    trading_loop_ref = {'loop': None}
    
    @app.route('/api/ai/start', methods=['POST'])
    def api_ai_start():
        """Start AI trading"""
        try:
            if trading_loop_ref['loop'] and trading_loop_ref['loop'].running:
                return jsonify({'success': False, 'message': 'AI trading already running'})
            
            from finbert_trading_agent import AutoTradingLoop
            symbols = ['AAPL', 'GOOGL', 'ORCL', 'BTC-USD', 'ETH-USD']
            trading_loop = AutoTradingLoop(agent, symbols, interval_seconds=60)
            trading_loop.start()
            trading_loop_ref['loop'] = trading_loop
            
            return jsonify({'success': True, 'message': 'AI trading started'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/ai/stop', methods=['POST'])
    def api_ai_stop():
        """Stop AI trading"""
        try:
            if trading_loop_ref['loop']:
                trading_loop_ref['loop'].stop()
                trading_loop_ref['loop'] = None
            return jsonify({'success': True, 'message': 'AI trading stopped'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/ai/signals')
    def api_ai_signals():
        """Get current AI trading signals"""
        try:
            signals = list(agent.signal_history)[-10:]  # Last 10 signals
            
            # Calculate stats
            trades = list(agent.trade_history)
            trades_today = len([t for t in trades if datetime.fromisoformat(t['timestamp']).date() == datetime.now().date()])
            
            return jsonify({
                'signals': [s['signal'] for s in signals],
                'stats': {
                    'active_signals': len([s for s in signals if s['signal']['action'] != 'HOLD']),
                    'trades_today': trades_today,
                    'win_rate': 0,  # Calculate from trade results
                    'pl_today': 0  # Calculate from portfolio
                }
            })
        except Exception as e:
            return jsonify({'signals': [], 'stats': {}, 'error': str(e)})
    
    @app.route('/api/ai/trades')
    def api_ai_trades():
        """Get AI trade history"""
        try:
            trades = list(agent.trade_history)[-50:]  # Last 50 trades
            return jsonify({'trades': trades})
        except Exception as e:
            return jsonify({'trades': [], 'error': str(e)})
