#!/usr/bin/env python3
"""
Example: How to integrate FinBERT AI Trading into app_stock_sim.py

This file shows the minimal changes needed to add AI trading to your Flask app.
You can copy these snippets into your app_stock_sim.py
"""

# ============================================================================
# STEP 1: Add imports at the top of app_stock_sim.py (after existing imports)
# ============================================================================

from finbert_trading_agent import FinBERTTradingAgent, AutoTradingLoop
from ai_trading_ui_extension import add_ai_routes_to_app, AI_TRADING_DASHBOARD_HTML


# ============================================================================
# STEP 2: Initialize AI agent after Flask app creation
# ============================================================================

# After: app = Flask(__name__)
# Add:

# Initialize FinBERT Trading Agent
print("Initializing FinBERT AI Trading Agent...")
ai_agent = FinBERTTradingAgent(flask_backend_url="http://localhost:5000")

# Add AI routes to Flask app
add_ai_routes_to_app(app, ai_agent)

print("✅ AI Trading Agent ready")


# ============================================================================
# STEP 3: Add AI Dashboard to your HTML template
# ============================================================================

# Find your main HTML template (usually the index route)
# Add AI_TRADING_DASHBOARD_HTML to your page

# Example: If you have a template string, insert this section:

"""
@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Stock Trading Simulator with AI</title>
        <!-- Your existing CSS -->
    </head>
    <body>
        <!-- Your existing header -->
        
        <!-- ADD THIS: AI Trading Dashboard Tab -->
        <div id="ai-dashboard-tab" style="display: none;">
            ''' + AI_TRADING_DASHBOARD_HTML + '''
        </div>
        
        <!-- Your existing content -->
        
        <script>
        // Add tab switching logic
        function showAIDashboard() {
            document.getElementById('ai-dashboard-tab').style.display = 'block';
            // Hide other tabs
        }
        </script>
    </body>
    </html>
    ''')
"""


# ============================================================================
# STEP 4: (Optional) Add auto-start on Flask startup
# ============================================================================

# At the bottom of app_stock_sim.py, in the if __name__ == '__main__' block:

"""
if __name__ == '__main__':
    # Your existing initialization...
    
    # Optional: Auto-start AI trading
    import threading
    
    def start_ai_trading():
        import time
        time.sleep(5)  # Wait for Flask to be ready
        
        symbols = ['AAPL', 'GOOGL', 'ORCL', 'BTC-USD', 'ETH-USD']
        trading_loop = AutoTradingLoop(ai_agent, symbols, interval_seconds=60)
        trading_loop.start()
        print("🤖 AI Trading started automatically")
    
    # Start in background thread
    ai_thread = threading.Thread(target=start_ai_trading, daemon=True)
    ai_thread.start()
    
    # Start Flask
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
"""


# ============================================================================
# COMPLETE MINIMAL EXAMPLE
# ============================================================================

"""
Here's a minimal standalone example that shows the integration:

```python
#!/usr/bin/env python3
from flask import Flask, jsonify
from finbert_trading_agent import FinBERTTradingAgent, AutoTradingLoop
from ai_trading_ui_extension import add_ai_routes_to_app

app = Flask(__name__)

# Your existing code for price simulation, OHLC data, etc.
# ...

# Initialize AI agent
ai_agent = FinBERTTradingAgent(flask_backend_url="http://localhost:5000")
add_ai_routes_to_app(app, ai_agent)

@app.route('/')
def index():
    return '''
    <html>
    <body>
        <h1>AI Trading System</h1>
        <button onclick="fetch('/api/ai/start', {method: 'POST'})">Start AI</button>
        <button onclick="fetch('/api/ai/stop', {method: 'POST'})">Stop AI</button>
        <div id="signals"></div>
        <script>
        setInterval(() => {
            fetch('/api/ai/signals')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('signals').innerHTML = 
                        JSON.stringify(data.signals, null, 2);
                });
        }, 5000);
        </script>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(port=5000)
```
"""


# ============================================================================
# TESTING THE INTEGRATION
# ============================================================================

"""
After integration, test with:

1. Start Flask app:
   python3 app_stock_sim.py

2. Test API endpoints:
   curl http://localhost:5000/api/ohlc/AAPL/15m
   curl -X POST http://localhost:5000/api/ai/start
   curl http://localhost:5000/api/ai/signals

3. Test from browser:
   http://localhost:5000
   
4. Check logs:
   tail -f flask.log
"""


# ============================================================================
# ALTERNATIVE: Run as separate service (recommended for production)
# ============================================================================

"""
Instead of integrating directly, run as two separate services:

Terminal 1 (Flask Backend):
$ python3 app_stock_sim.py

Terminal 2 (AI Agent):
$ python3 finbert_trading_agent.py

This approach:
- ✅ Better isolation
- ✅ Independent scaling
- ✅ Easier debugging
- ✅ Can restart AI without affecting Flask

Or use the startup script:
$ ./start_trading.sh
"""


# ============================================================================
# CUSTOMIZATION EXAMPLES
# ============================================================================

def example_custom_signal_logic():
    """
    Example: Override signal generation with custom logic
    """
    from finbert_trading_agent import FinBERTTradingAgent
    
    class CustomTradingAgent(FinBERTTradingAgent):
        def _combine_signals(self, symbol, technicals, sentiment, current_price):
            # Call parent method
            signal = super()._combine_signals(symbol, technicals, sentiment, current_price)
            
            # Add custom logic
            if symbol == 'BTC-USD':
                # More aggressive for crypto
                if signal['combined_score'] > 0.2:
                    signal['action'] = 'BUY'
                    signal['position_size'] *= 1.5  # Larger position
            
            # Add time-based rules
            from datetime import datetime
            hour = datetime.now().hour
            if hour < 9 or hour > 16:  # Outside market hours
                signal['action'] = 'HOLD'
            
            return signal
    
    # Use custom agent
    agent = CustomTradingAgent()
    return agent


def example_multiple_timeframes():
    """
    Example: Use multiple timeframes for confirmation
    """
    from finbert_trading_agent import FinBERTTradingAgent
    
    agent = FinBERTTradingAgent()
    
    # Get data for multiple timeframes
    symbol = 'AAPL'
    ohlcv_15m = agent.get_ohlcv_from_backend(symbol, '15m')
    ohlcv_1h = agent.get_ohlcv_from_backend(symbol, '1h')
    ohlcv_4h = agent.get_ohlcv_from_backend(symbol, '4h')
    
    # Generate signals for each
    signal_15m = agent.generate_trading_signal(symbol, ohlcv_15m)
    signal_1h = agent.generate_trading_signal(symbol, ohlcv_1h)
    signal_4h = agent.generate_trading_signal(symbol, ohlcv_4h)
    
    # Only trade if all timeframes agree
    if (signal_15m['action'] == signal_1h['action'] == signal_4h['action'] == 'BUY'):
        print(f"✅ Strong BUY signal across all timeframes for {symbol}")
        # Execute trade with higher confidence
        portfolio = agent.get_portfolio()
        agent.execute_trade(symbol, signal_15m, portfolio['total_value'])
    else:
        print(f"⚠️  Conflicting signals for {symbol}, holding")


def example_news_integration():
    """
    Example: Integrate real news feeds
    """
    import feedparser
    from finbert_trading_agent import FinBERTTradingAgent
    
    def fetch_yahoo_news(symbol):
        """Fetch news from Yahoo Finance RSS"""
        url = f"https://finance.yahoo.com/rss/headline?s={symbol}"
        feed = feedparser.parse(url)
        return [entry.title + ". " + entry.summary for entry in feed.entries[:5]]
    
    agent = FinBERTTradingAgent()
    
    # Get news and OHLCV
    symbol = 'AAPL'
    news = fetch_yahoo_news(symbol)
    ohlcv = agent.get_ohlcv_from_backend(symbol, '15m')
    
    # Generate signal with news
    signal = agent.generate_trading_signal(symbol, ohlcv, news_texts=news)
    
    print(f"Signal with news sentiment: {signal['action']}")
    print(f"Sentiment score: {signal['sentiment_score']:+.2f}")


def example_risk_management():
    """
    Example: Add advanced risk management
    """
    from finbert_trading_agent import FinBERTTradingAgent
    
    class RiskManagedAgent(FinBERTTradingAgent):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.max_daily_loss = 0.05  # 5% max daily loss
            self.max_positions = 5  # Max 5 concurrent positions
            self.daily_trades = 0
            self.max_daily_trades = 20
        
        def execute_trade(self, symbol, signal, portfolio_value):
            # Check daily trade limit
            if self.daily_trades >= self.max_daily_trades:
                print("⚠️  Daily trade limit reached")
                return False
            
            # Check max positions
            if len(self.active_positions) >= self.max_positions:
                print("⚠️  Max positions reached")
                return False
            
            # Check daily loss
            portfolio = self.get_portfolio()
            daily_pnl = (portfolio['total_value'] - portfolio['start_value']) / portfolio['start_value']
            if daily_pnl < -self.max_daily_loss:
                print("🛑 Circuit breaker: Max daily loss reached")
                return False
            
            # Execute trade
            result = super().execute_trade(symbol, signal, portfolio_value)
            if result:
                self.daily_trades += 1
            return result
    
    agent = RiskManagedAgent()
    return agent


# ============================================================================
# MAIN: If you run this file, it shows integration examples
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("FinBERT AI Trading - Integration Examples")
    print("=" * 70)
    print()
    print("This file shows how to integrate AI trading into app_stock_sim.py")
    print()
    print("📚 See the code above for:")
    print("  1. Basic Flask integration")
    print("  2. Custom signal logic")
    print("  3. Multiple timeframe analysis")
    print("  4. News feed integration")
    print("  5. Advanced risk management")
    print()
    print("📖 Full documentation: README_FINBERT.md")
    print("🚀 Quick start: QUICKSTART_FINBERT.md")
    print("🧪 Test setup: python3 test_finbert.py")
    print("▶️  Start trading: ./start_trading.sh")
    print()
