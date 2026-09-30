#!/usr/bin/env python3
"""
Real-time Stock Exchange Simulation - Short-term Trading
Focus: Maximize daily profit through rapid trades
"""

import os
import random
import time
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request, session
from collections import deque

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ----------------------------------------------------------------------
# SIMULATION CONFIGURATION
# ----------------------------------------------------------------------
STARTING_CASH = 1000000.00
COMMISSION_RATE = 0.001  # 0.1% per trade

# Market Indices (Yahoo Finance symbols)
INDICES = {
    '^VIX': {'name': 'CBOE Volatility Index', 'type': 'index'},
    '000001.SS': {'name': 'Shanghai Composite (SSE)', 'type': 'index'},
    '^HSI': {'name': 'Hang Seng Index (HSI)', 'type': 'index'},
    'QQQ': {'name': 'Invesco QQQ Trust', 'type': 'index'},
    '^GSPC': {'name': 'S&P 500 (SPX)', 'type': 'index'},
    '^NDX': {'name': 'NASDAQ 100 (NDX)', 'type': 'index'},
}

# Stock symbols
STOCKS = {
    'HPQ': {'name': 'HP Inc.', 'type': 'stock'},
    'NDAQ': {'name': 'Nasdaq Inc.', 'type': 'stock'},
    'ZM': {'name': 'Zoom Video', 'type': 'stock'},
    'SAP': {'name': 'SAP SE', 'type': 'stock'},
    'ORCL': {'name': 'Oracle Corp', 'type': 'stock'},
    'AAPL': {'name': 'Apple Inc.', 'type': 'stock'},
    'GOOGL': {'name': 'Alphabet (Google)', 'type': 'stock'},
}

# Cryptocurrencies
CRYPTOS = {
    'BTC-USD': {'name': 'Bitcoin', 'type': 'crypto'},
    'ETH-USD': {'name': 'Ethereum', 'type': 'crypto'},
    'DOGE-USD': {'name': 'Dogecoin', 'type': 'crypto'},
}

# Combine all symbols
ALL_SYMBOLS = {**INDICES, **STOCKS, **CRYPTOS}

# Global state for price history (last 100 data points)
price_history = {symbol: deque(maxlen=100) for symbol in ALL_SYMBOLS.keys()}

# OHLC data for different timeframes
ohlc_data = {
    '1m': {symbol: deque(maxlen=500) for symbol in ALL_SYMBOLS.keys()},    # 500 candles for dense chart
    '15m': {symbol: deque(maxlen=400) for symbol in ALL_SYMBOLS.keys()},   # 400 candles
    '1h': {symbol: deque(maxlen=350) for symbol in ALL_SYMBOLS.keys()},    # 350 candles
    '4h': {symbol: deque(maxlen=300) for symbol in ALL_SYMBOLS.keys()}     # 300 candles
}

# Current candle state for each timeframe
current_candle = {
    '1m': {symbol: {'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0, 'timestamp': None} for symbol in ALL_SYMBOLS.keys()},
    '15m': {symbol: {'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0, 'timestamp': None} for symbol in ALL_SYMBOLS.keys()},
    '1h': {symbol: {'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0, 'timestamp': None} for symbol in ALL_SYMBOLS.keys()},
    '4h': {symbol: {'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0, 'timestamp': None} for symbol in ALL_SYMBOLS.keys()}
}

current_prices = {}
last_price_fetch = {}
price_cache = {}

# Initialize prices with realistic defaults
INITIAL_PRICES = {
    '^VIX': 15.0, '000001.SS': 3000.0, '^HSI': 17000.0,
    'QQQ': 480.0, '^GSPC': 5900.0, '^NDX': 20500.0,
    'HPQ': 35.0, 'NDAQ': 70.0, 'ZM': 70.0,
    'SAP': 230.0, 'ORCL': 185.0, 'AAPL': 230.0, 'GOOGL': 175.0,
    'BTC-USD': 90000.0, 'ETH-USD': 3200.0, 'DOGE-USD': 0.40
}

for symbol in ALL_SYMBOLS.keys():
    current_prices[symbol] = INITIAL_PRICES.get(symbol, 100.00)
    last_price_fetch[symbol] = 0
    price_cache[symbol] = None
    price_history[symbol].append({
        'time': time.time(),
        'price': current_prices[symbol]
    })

def fetch_yahoo_historical_ohlc(symbol, timeframe, num_candles):
    """Fetch real historical OHLC data from Yahoo Finance and fill gaps."""
    try:
        # Map our timeframes to Yahoo intervals
        interval_map = {'1m': '1m', '15m': '15m', '1h': '1h', '4h': '1h'}  # Yahoo doesn't have 4h, use 1h
        yahoo_interval = interval_map.get(timeframe, '1h')
        
        # Calculate range needed
        range_map = {'1m': '1d', '15m': '5d', '1h': '1mo', '4h': '3mo'}
        yahoo_range = range_map.get(timeframe, '1d')
        
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
        params = {
            'interval': yahoo_interval,
            'range': yahoo_range
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
            
        data = response.json()
        
        if 'chart' not in data or 'result' not in data['chart']:
            return []
            
        result = data['chart']['result']
        if not result or len(result) == 0:
            return []
        
        quote = result[0]
        timestamps = quote.get('timestamp', [])
        indicators = quote.get('indicators', {})
        quote_data = indicators.get('quote', [{}])[0]
        
        opens = quote_data.get('open', [])
        highs = quote_data.get('high', [])
        lows = quote_data.get('low', [])
        closes = quote_data.get('close', [])
        volumes = quote_data.get('volume', [])
        
        candles = []
        for i in range(len(timestamps)):
            if opens[i] is None or highs[i] is None or lows[i] is None or closes[i] is None:
                continue
                
            candles.append({
                'x': timestamps[i] * 1000,  # Convert to milliseconds
                'o': round(opens[i], 2),
                'h': round(highs[i], 2),
                'l': round(lows[i], 2),
                'c': round(closes[i], 2),
                'v': int(volumes[i]) if volumes[i] else 0
            })
            
        # For 4h timeframe, aggregate 1h candles into 4h candles
        if timeframe == '4h' and len(candles) > 0:
            candles_4h = []
            for i in range(0, len(candles), 4):
                chunk = candles[i:i+4]
                if len(chunk) > 0:
                    candles_4h.append({
                        'x': chunk[0]['x'],
                        'o': chunk[0]['o'],
                        'h': max(c['h'] for c in chunk),
                        'l': min(c['l'] for c in chunk),
                        'c': chunk[-1]['c'],
                        'v': sum(c['v'] for c in chunk)
                    })
            candles = candles_4h
        
        # Return last N candles
        return candles[-num_candles:] if len(candles) > num_candles else candles
        
    except Exception as e:
        print(f"Error fetching historical data for {symbol}: {e}")
        return []

def generate_historical_ohlc(symbol, base_price, timeframe, num_candles):
  """Generate realistic historical OHLC data with trending movement"""
  import random
  from datetime import timedelta

  candles = []
  now = datetime.now()

  # Define time intervals
  intervals = {'1m': 60, '15m': 900, '1h': 3600, '4h': 14400}
  interval_seconds = intervals[timeframe]

  # Increased volatility for more natural-looking candles
  volatility_multipliers = {'1m': 0.004, '15m': 0.008, '1h': 0.015, '4h': 0.025}
  volatility = base_price * volatility_multipliers.get(timeframe, 0.005)

  # Generate more realistic movement
  price = base_price
  
  for i in range(num_candles, 0, -1):
    # Each candle has its own random movement
    # Mix of trend and random walk
    trend_component = random.uniform(-volatility * 0.3, volatility * 0.3)
    random_component = random.uniform(-volatility * 0.7, volatility * 0.7)
    
    open_price = price
    close_price = price + trend_component + random_component
    
    # Generate realistic high/low with wicks
    candle_range = abs(close_price - open_price)
    wick_size = random.uniform(candle_range * 0.2, candle_range * 0.8)
    
    high_price = max(open_price, close_price) + abs(random.uniform(0, wick_size))
    low_price = min(open_price, close_price) - abs(random.uniform(0, wick_size))
    
    # Ensure prices don't go negative
    if low_price < base_price * 0.5:
      adjustment = base_price * 0.5 - low_price
      low_price += adjustment
      open_price += adjustment
      close_price += adjustment
      high_price += adjustment

    # Generate volume (higher for crypto, lower for indices)
    if symbol in CRYPTOS:
      volume = random.uniform(1000000, 5000000)
    elif symbol in INDICES:
      volume = random.uniform(500000, 2000000)
    else:
      volume = random.uniform(100000, 1000000)

    candle_time = now - timedelta(seconds=interval_seconds * i)

    candles.append({
      'x': int(candle_time.timestamp() * 1000),
      'o': round(open_price, 2),
      'h': round(high_price, 2),
      'l': round(low_price, 2),
      'c': round(close_price, 2),
      'v': int(volume)
    })

    # Update price for next candle
    price = close_price

  # Ensure the series ends exactly at the requested base price so
  # real-time candles continue smoothly without a sudden jump.
  if candles:
    adjustment = base_price - candles[-1]['c']
    if abs(adjustment) > 0.0001:
      for candle in candles:
        candle['o'] = round(candle['o'] + adjustment, 2)
        candle['h'] = round(candle['h'] + adjustment, 2)
        candle['l'] = round(candle['l'] + adjustment, 2)
        candle['c'] = round(candle['c'] + adjustment, 2)

  return candles

# ----------------------------------------------------------------------
# TRADING LOGIC
# ----------------------------------------------------------------------
def fetch_yahoo_price(symbol):
    """Fetch real-time price from Yahoo Finance API"""
    global last_price_fetch, price_cache
    
    # Cache for 5 seconds to avoid rate limiting
    if time.time() - last_price_fetch.get(symbol, 0) < 5:
        if price_cache.get(symbol) is not None:
            return price_cache[symbol]
    
    try:
        # Yahoo Finance API endpoint
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
        params = {
            'interval': '1m',
            'range': '1d'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            if 'chart' not in data or 'result' not in data['chart']:
                return price_cache.get(symbol, current_prices.get(symbol))
                
            result = data['chart']['result']
            if not result or len(result) == 0:
                return price_cache.get(symbol, current_prices.get(symbol))
            
            # Get latest price
            meta = result[0].get('meta', {})
            price = meta.get('regularMarketPrice') or meta.get('previousClose')
            
            if price is not None and price > 0:
                price_cache[symbol] = float(price)
                last_price_fetch[symbol] = time.time()
                return price_cache[symbol]
    except Exception as e:
        pass  # Silently fail and return cached price
    
    # Return cached or current price
    return price_cache.get(symbol, current_prices.get(symbol))

def update_stock_prices():
    """Update all stock prices with simulated realistic movements"""
    global current_prices
    
    for symbol in list(INDICES.keys()) + list(STOCKS.keys()) + list(CRYPTOS.keys()):
        old_price = current_prices.get(symbol, INITIAL_PRICES.get(symbol, 100.0))
        
        # Simulate realistic price movement instead of fetching real data
        # This prevents huge jumps and maintains chart consistency
        volatility_map = {
            # Indices - low volatility
            '^VIX': 0.0006, '000001.SS': 0.0005, '^HSI': 0.0005,
            'QQQ': 0.0005, '^GSPC': 0.0004, '^NDX': 0.0005,
            # Stocks - medium volatility
            'HPQ': 0.0007, 'NDAQ': 0.0007, 'ZM': 0.0009,
            'SAP': 0.0007, 'ORCL': 0.0007, 'AAPL': 0.0007, 'GOOGL': 0.0007,
            # Crypto - higher but capped volatility
            'BTC-USD': 0.001, 'ETH-USD': 0.001, 'DOGE-USD': 0.0015
        }
        
        volatility = volatility_map.get(symbol, 0.0007)
        change = random.uniform(-volatility, volatility)
        new_price = old_price * (1 + change)
        
        current_prices[symbol] = round(new_price, 2)
        price_history[symbol].append({
            'time': int(datetime.now().timestamp()),
            'price': round(new_price, 2)
        })
        
        # Update OHLC candles for all timeframes
        now = datetime.now()
        price = round(new_price, 2)
        
        # Generate random volume for this update
        if symbol in CRYPTOS:
            volume_chunk = random.uniform(10000, 50000)
        elif symbol in INDICES:
            volume_chunk = random.uniform(5000, 20000)
        else:
            volume_chunk = random.uniform(1000, 10000)
        
        # Define timeframe boundaries
        timeframes = {
            '1m': now.replace(second=0, microsecond=0),
            '15m': now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0),
            '1h': now.replace(minute=0, second=0, microsecond=0),
            '4h': now.replace(hour=(now.hour // 4) * 4, minute=0, second=0, microsecond=0)
        }
        
        for tf, candle_time in timeframes.items():
            current_tf_state = current_candle[tf][symbol]
            if current_tf_state['timestamp'] != candle_time:
                # New candle - save previous if exists
                if current_tf_state['open'] is not None:
                    completed_candle = {
                        'x': int(current_tf_state['timestamp'].timestamp() * 1000),
                        'o': current_tf_state['open'],
                        'h': current_tf_state['high'],
                        'l': current_tf_state['low'],
                        'c': current_tf_state['close'],
                        'v': int(current_tf_state['volume'])
                    }
                    ohlc_data[tf][symbol].append(completed_candle)
                
                # Start new candle anchored to previous close
                if len(ohlc_data[tf][symbol]) > 0:
                    open_price = ohlc_data[tf][symbol][-1]['c']
                else:
                    prev_close = current_tf_state['close'] if current_tf_state['close'] is not None else price
                    open_price = prev_close if prev_close else price
                
                current_tf_state = {
                    'open': open_price,
                    'high': open_price,
                    'low': open_price,
                    'close': open_price,
                    'volume': 0,
                    'timestamp': candle_time
                }
                current_candle[tf][symbol] = current_tf_state
            
            # Update current candle (new or existing) with latest trade
            current_tf_state['close'] = price
            current_tf_state['high'] = max(current_tf_state['high'], price)
            current_tf_state['low'] = min(current_tf_state['low'], price)
            current_tf_state['volume'] += volume_chunk

def get_portfolio(user_id):
    """Get user's portfolio"""
    if 'portfolios' not in session:
        session['portfolios'] = {}
    
    if user_id not in session['portfolios']:
        session['portfolios'][user_id] = {
            'cash': STARTING_CASH,
            'holdings': {},
            'trades': [],
            'start_value': STARTING_CASH,
            'start_time': time.time()
        }
        session.modified = True
    
    return session['portfolios'][user_id]

def calculate_portfolio_value(portfolio):
    """Calculate total portfolio value"""
    cash = portfolio['cash']
    holdings_value = sum(
        qty * current_prices[symbol]
        for symbol, qty in portfolio['holdings'].items()
    )
    return cash + holdings_value

def execute_trade(user_id, symbol, action, quantity):
    """Execute buy/sell trade"""
    portfolio = get_portfolio(user_id)
    price = current_prices.get(symbol, 0)
    
    if price == 0:
        return {'success': False, 'error': 'Price not available'}
    
    if action == 'buy':
        cost = price * quantity
        commission = cost * COMMISSION_RATE
        total_cost = cost + commission
        
        if portfolio['cash'] < total_cost:
            return {'success': False, 'error': 'Insufficient funds'}
        
        portfolio['cash'] -= total_cost
        portfolio['holdings'][symbol] = portfolio['holdings'].get(symbol, 0) + quantity
        
    elif action == 'sell':
        if portfolio['holdings'].get(symbol, 0) < quantity:
            return {'success': False, 'error': 'Insufficient shares'}
        
        revenue = price * quantity
        commission = revenue * COMMISSION_RATE
        total_revenue = revenue - commission
        
        portfolio['cash'] += total_revenue
        portfolio['holdings'][symbol] -= quantity
        if portfolio['holdings'][symbol] == 0:
            del portfolio['holdings'][symbol]
    
    # Record trade
    portfolio['trades'].append({
        'time': time.time(),
        'symbol': symbol,
        'action': action,
        'quantity': quantity,
        'price': price,
        'commission': commission if action == 'buy' else commission
    })
    
    session.modified = True
    return {'success': True, 'portfolio': portfolio}

# ----------------------------------------------------------------------
# HTML TEMPLATE
# ----------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Stock Trading Simulator - Day Trading</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0a0e27; color: #e0e0e0; overflow: hidden; }
    
    /* Drawer Sidebar */
    .drawer {
      position: fixed;
      left: 0;
      top: 0;
      width: 280px;
      height: 100vh;
      background: #0d1127;
      border-right: 2px solid #2a3f5f;
      overflow-y: auto;
      z-index: 1000;
      display: flex;
      flex-direction: column;
    }
    .drawer::-webkit-scrollbar { width: 6px; }
    .drawer::-webkit-scrollbar-track { background: #0a0e27; }
    .drawer::-webkit-scrollbar-thumb { background: #2a3f5f; border-radius: 3px; }
    
    .drawer-header {
      padding: 20px;
      background: linear-gradient(135deg, #1a1f3a 0%, #0d1127 100%);
      border-bottom: 2px solid #2a3f5f;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .drawer-title {
      font-size: 1.3rem;
      font-weight: bold;
      color: #00ff88;
      margin-bottom: 5px;
    }
    .drawer-subtitle {
      font-size: 0.85rem;
      color: #888;
    }
    
    .drawer-section {
      border-bottom: 1px solid #1a1f3a;
    }
    .drawer-section-header {
      padding: 12px 20px;
      background: #1a1f3a;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      user-select: none;
      transition: background 0.2s;
    }
    .drawer-section-header:hover {
      background: #242a4a;
    }
    .drawer-section-title {
      font-size: 0.9rem;
      font-weight: bold;
      color: #00ff88;
      text-transform: uppercase;
      letter-spacing: 1px;
    }
    .drawer-section-icon {
      font-size: 0.9rem;
      color: #888;
      transition: transform 0.3s;
    }
    .drawer-section.collapsed .drawer-section-icon {
      transform: rotate(-90deg);
    }
    .drawer-section-content {
      max-height: 500px;
      overflow: hidden;
      transition: max-height 0.3s ease-out;
    }
    .drawer-section.collapsed .drawer-section-content {
      max-height: 0;
    }
    
    .drawer-item {
      padding: 12px 20px;
      cursor: pointer;
      border-left: 3px solid transparent;
      transition: all 0.2s;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .drawer-item:hover {
      background: #1a1f3a;
      border-left-color: #00ff88;
    }
    .drawer-item.active {
      background: #242a4a;
      border-left-color: #00ff88;
    }
    .drawer-item.crypto:hover, .drawer-item.crypto.active { border-left-color: #ffd700; }
    .drawer-item.index:hover, .drawer-item.index.active { border-left-color: #ff9500; }
    
    .drawer-item-left {
      flex: 1;
    }
    .drawer-item-symbol {
      font-size: 0.95rem;
      font-weight: bold;
      color: #00ff88;
      margin-bottom: 2px;
    }
    .drawer-item-name {
      font-size: 0.75rem;
      color: #888;
    }
    .drawer-item-right {
      text-align: right;
    }
    .drawer-item-price {
      font-size: 0.9rem;
      font-weight: bold;
      color: #e0e0e0;
      margin-bottom: 2px;
    }
    .drawer-item-change {
      font-size: 0.75rem;
      padding: 2px 6px;
      border-radius: 3px;
    }
    .drawer-item-change.up {
      background: rgba(0, 255, 136, 0.2);
      color: #00ff88;
    }
    .drawer-item-change.down {
      background: rgba(255, 68, 68, 0.2);
      color: #ff4444;
    }
    
    /* Main Content Area */
    .main-content {
      margin-left: 280px;
      height: 100vh;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
    }
    .main-content::-webkit-scrollbar { width: 8px; }
    .main-content::-webkit-scrollbar-track { background: #0a0e27; }
    .main-content::-webkit-scrollbar-thumb { background: #2a3f5f; border-radius: 4px; }
    
    /* Portfolio Section */
    .portfolio-section {
      background: #1a1f3a;
      border-radius: 12px;
      padding: 25px;
      border: 1px solid #2a3f5f;
      margin-bottom: 20px;
    }
    .portfolio-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
    }
    .portfolio-title {
      font-size: 1.3rem;
      font-weight: bold;
      color: #00ff88;
    }
    .portfolio-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 15px;
    }
    .portfolio-stat-card {
      background: #0d1127;
      padding: 15px;
      border-radius: 8px;
      border-left: 3px solid #00ff88;
    }
    .portfolio-stat-label {
      font-size: 0.8rem;
      color: #888;
      margin-bottom: 5px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .portfolio-stat-value {
      font-size: 1.4rem;
      font-weight: bold;
      color: #00ff88;
    }
    .portfolio-stat-value.negative {
      color: #ff4444;
    }
    
    .content-separator {
      height: 2px;
      background: linear-gradient(90deg, transparent 0%, #2a3f5f 50%, transparent 100%);
      margin: 20px 0;
    }
    
    /* Chart View */
    .chart-view {
      background: #1a1f3a;
      border-radius: 12px;
      padding: 30px;
      border: 1px solid #2a3f5f;
      flex: 1;
    }
    .chart-view-header {
      margin-bottom: 25px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 15px;
    }
    .chart-view-title-group {
      flex: 1;
    }
    .chart-view-symbol {
      font-size: 2rem;
      font-weight: bold;
      color: #00ff88;
      margin-bottom: 5px;
    }
    .chart-view-name {
      font-size: 1.1rem;
      color: #888;
    }
    .chart-view-price-group {
      text-align: right;
    }
    .chart-view-price {
      font-size: 2.5rem;
      font-weight: bold;
      color: #e0e0e0;
      margin-bottom: 5px;
    }
    .chart-view-change {
      font-size: 1.1rem;
      padding: 6px 12px;
      border-radius: 6px;
      display: inline-block;
    }
    .chart-view-change.up {
      background: rgba(0, 255, 136, 0.2);
      color: #00ff88;
    }
    .chart-view-change.down {
      background: rgba(255, 68, 68, 0.2);
      color: #ff4444;
    }
    
    .chart-container-main {
      background: #0d1127;
      border-radius: 8px;
      padding: 20px;
      height: 600px;
      margin-bottom: 30px;
    }
    .chart-main {
      width: 100%; 
      height: 100%;
    }
    
    .charts-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 15px;
      margin-bottom: 30px;
    }
    .chart-card {
      background: #0a0e1a;
      border-radius: 4px;
      border: 1px solid #1a2332;
      overflow: hidden;
    }
    .chart-card-header {
      padding: 10px 15px;
      background: #0d1220;
      border-bottom: 1px solid #1a2332;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .chart-card-title {
      font-size: 0.9rem;
      font-weight: 600;
      color: #a0a0a0;
    }
    .chart-card-timeframe {
      font-size: 0.8rem;
      color: #606060;
      font-weight: 500;
    }
    .chart-card-controls {
      padding: 8px 15px;
      background: #0d1220;
      border-bottom: 1px solid #1a2332;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .chart-range-slider {
      flex: 1;
      height: 4px;
      background: #1a2332;
      outline: none;
      border-radius: 2px;
      -webkit-appearance: none;
    }
    .chart-range-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 12px;
      height: 12px;
      background: #26a69a;
      cursor: pointer;
      border-radius: 50%;
    }
    .chart-range-slider::-moz-range-thumb {
      width: 12px;
      height: 12px;
      background: #26a69a;
      cursor: pointer;
      border-radius: 50%;
      border: none;
    }
    .chart-range-label {
      font-size: 0.75rem;
      color: #606060;
      min-width: 90px;
      text-align: right;
    }
    .chart-card-body {
      padding: 10px;
      height: 320px;
      background: #0a0e1a;
    }
    .chart-card canvas {
      width: 100% !important;
      height: 100% !important;
      display: block !important;
      opacity: 1 !important;
      visibility: visible !important;
    }
    
    .trade-panel {
      background: #0d1127;
      border-radius: 8px;
      padding: 25px;
      border: 1px solid #2a3f5f;
    }
    .trade-panel-title {
      font-size: 1.2rem;
      font-weight: bold;
      color: #00ff88;
      margin-bottom: 20px;
    }
    .trade-controls {
      display: flex;
      gap: 15px;
      align-items: center;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .trade-input {
      width: 120px;
      padding: 12px;
      background: #1a1f3a;
      border: 1px solid #2a3f5f;
      color: #e0e0e0;
      border-radius: 6px;
      font-size: 1rem;
    }
    .btn {
      padding: 12px 30px;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-weight: bold;
      font-size: 1rem;
      transition: all 0.2s;
    }
    .btn-buy {
      background: #00ff88;
      color: #0a0e27;
    }
    .btn-buy:hover {
      background: #00dd77;
      transform: translateY(-2px);
    }
    .btn-sell {
      background: #ff4444;
      color: white;
    }
    .btn-sell:hover {
      background: #dd3333;
      transform: translateY(-2px);
    }
    
    .empty-state {
      text-align: center;
      padding: 100px 20px;
      color: #888;
    }
    .empty-state-icon {
      font-size: 4rem;
      margin-bottom: 20px;
      opacity: 0.3;
    }
    .empty-state-text {
      font-size: 1.2rem;
    }
    
    .alert {
      padding: 12px 20px;
      border-radius: 6px;
      margin-bottom: 15px;
      animation: slideIn 0.3s ease-out;
    }
    .alert-error {
      background: rgba(255, 68, 68, 0.2);
      border: 1px solid #ff4444;
      color: #ff4444;
    }
    .alert-success {
      background: rgba(0, 255, 136, 0.2);
      border: 1px solid #00ff88;
      color: #00ff88;
    }
    @keyframes slideIn {
      from { transform: translateY(-20px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
    
    #live-indicator {
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #00ff88;
      border-radius: 50%;
      animation: pulse 2s infinite;
      margin-right: 8px;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.3; transform: scale(0.8); }
    }
  </style>
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
</head>
<body>
  <!-- Drawer Sidebar -->
  <div class="drawer">
    <div class="drawer-header">
      <div class="drawer-title"><span id="live-indicator"></span>Trading Simulator</div>
      <div class="drawer-subtitle">Select a symbol to view chart</div>
    </div>
    
    <div class="drawer-section" id="crypto-section-drawer">
      <div class="drawer-section-header" onclick="toggleDrawerSection('crypto')">
        <div class="drawer-section-title">Cryptocurrencies</div>
        <div class="drawer-section-icon">▼</div>
      </div>
      <div class="drawer-section-content" id="crypto-drawer-content"></div>
    </div>
    
    <div class="drawer-section" id="indices-section-drawer">
      <div class="drawer-section-header" onclick="toggleDrawerSection('indices')">
        <div class="drawer-section-title">Market Indices</div>
        <div class="drawer-section-icon">▼</div>
      </div>
      <div class="drawer-section-content" id="indices-drawer-content"></div>
    </div>
    
    <div class="drawer-section" id="stocks-section-drawer">
      <div class="drawer-section-header" onclick="toggleDrawerSection('stocks')">
        <div class="drawer-section-title">Stocks</div>
        <div class="drawer-section-icon">▼</div>
      </div>
      <div class="drawer-section-content" id="stocks-drawer-content"></div>
    </div>
  </div>

  <!-- Main Content -->
  <div class="main-content">
    <div id="alert-container"></div>
    
    <!-- Portfolio Section -->
    <div class="portfolio-section">
      <div class="portfolio-header">
        <div class="portfolio-title">Portfolio Summary</div>
      </div>
      <div class="portfolio-stats" id="portfolio-stats"></div>
    </div>
    
    <div class="content-separator"></div>
    
    <div id="main-chart-view"></div>
  </div>
  
  <script>
    const userId = 'user_' + Math.random().toString(36).substr(2, 9);
    let charts = { '1m': null, '15m': null, '1h': null, '4h': null };
    let chartRanges = { '1m': 60, '15m': 60, '1h': 60, '4h': 50 };
    let priceData = {};
    let updateScheduled = false;
    let lastCandles = { '1m': null, '15m': null, '1h': null, '4h': null };
    let lastUpdateTime = { '1m': 0, '15m': 0, '1h': 0, '4h': 0 };
    let updateOffsets = { '1m': 0, '15m': 500, '1h': 1000, '4h': 1500 };
    let chartsInitialized = false;
    let selectedSymbol = localStorage.getItem('selectedSymbol') || 'BTC-USD';
    let collapsedSections = JSON.parse(localStorage.getItem('collapsedSections') || '{"crypto":false,"indices":true,"stocks":true}');
    
    // Calculate y-axis bounds with minimal padding
    function calculateYAxisBounds(validOhlcData) {
      const allPrices = validOhlcData.flatMap(d => [d.o, d.c, d.h, d.l]);
      const minPrice = Math.min(...allPrices);
      const maxPrice = Math.max(...allPrices);
      const priceRange = maxPrice - minPrice;
      
      // Use 1% padding, with minimum of 0.1% of price for very small ranges
      const padding = Math.max(priceRange * 0.01, minPrice * 0.001);
      
      return {
        min: minPrice - padding,
        max: maxPrice + padding,
        minPrice: minPrice,
        maxPrice: maxPrice
      };
    }
    
    // Update chart datasets with new data
    function updateChartDatasets(chart, validOhlcData) {
      if (!chart || !chart.candlestickSeries) return;
      
      const candleData = validOhlcData.map(d => ({
        time: Math.floor(d.x / 1000),
        open: d.o,
        high: d.h,
        low: d.l,
        close: d.c
      }));
      
      chart.candlestickSeries.setData(candleData);
      chart.validOhlcData = validOhlcData;
    }
    
    // Apply y-axis scaling to chart
    function applyChartScaling(chart, validOhlcData) {
      if (!chart) return;
      
      const bounds = calculateYAxisBounds(validOhlcData);
      
      chart.priceScale().applyOptions({
        scaleMargins: {
          top: 0.1,
          bottom: 0.1
        }
      });
    }
    
    function updateChartRange(timeframe, value) {
      chartRanges[timeframe] = parseInt(value);
      const label = document.getElementById(`label-${timeframe}`);
      if (label) {
        label.textContent = `Last ${value} candles`;
      }
      
      if (charts[timeframe] && priceData.symbols && priceData.symbols[selectedSymbol]) {
        const info = priceData.symbols[selectedSymbol];
        if (info.ohlc && info.ohlc[timeframe]) {
          const data = info.ohlc[timeframe].slice(-value);
          const validOhlcData = data.filter(d => d.x && d.x > 0);
          const chart = charts[timeframe];
          
          // Apply scaling and update datasets using helper functions
          applyChartScaling(chart, validOhlcData);
          updateChartDatasets(chart, validOhlcData);
          
          chart.validOhlcData = validOhlcData;
        }
      }
    }
    
    function toggleDrawerSection(sectionName) {
      const section = document.getElementById(`${sectionName}-section-drawer`);
      if (!section) return;
      
      section.classList.toggle('collapsed');
      collapsedSections[sectionName] = section.classList.contains('collapsed');
      localStorage.setItem('collapsedSections', JSON.stringify(collapsedSections));
    }
    
    function selectSymbol(symbol) {
      selectedSymbol = symbol;
      localStorage.setItem('selectedSymbol', symbol);
      
      // Update active state in drawer
      document.querySelectorAll('.drawer-item').forEach(item => {
        item.classList.remove('active');
      });
      document.querySelectorAll('.drawer-item').forEach(item => {
        if (item.dataset.symbol === symbol) {
          item.classList.add('active');
        }
      });
      
      // Render the chart view
      renderChartView();
    }
    
    function renderChartView() {
      const chartView = document.getElementById('main-chart-view');
      if (!selectedSymbol || !priceData.symbols || !priceData.symbols[selectedSymbol]) {
        // Destroy existing charts before clearing
        Object.keys(charts).forEach(tf => {
          if (charts[tf]) {
            charts[tf].remove();
            charts[tf] = null;
          }
        });
        
        chartView.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">📈</div>
            <div class="empty-state-text">Select a symbol from the drawer to view its chart</div>
          </div>
        `;
        return;
      }
      
      // Destroy existing charts before re-rendering
      Object.keys(charts).forEach(tf => {
        if (charts[tf]) {
          charts[tf].remove();
          charts[tf] = null;
        }
      });
      
      // Reset lastCandles to force initial render
      lastCandles = { '1m': null, '15m': null, '1h': null, '4h': null };
      
      const info = priceData.symbols[selectedSymbol];
      const priceChange = info.change_pct >= 0 ? 'up' : 'down';
      const changeSymbol = info.change_pct >= 0 ? '▲' : '▼';
      
      chartView.innerHTML = `
        <div class="chart-view">
          <div class="chart-view-header">
            <div class="chart-view-title-group">
              <div class="chart-view-symbol">${selectedSymbol}</div>
              <div class="chart-view-name">${info.name}</div>
            </div>
            <div class="chart-view-price-group">
              <div class="chart-view-price">${formatCurrency(info.price)}</div>
              <div class="chart-view-change ${priceChange}">
                ${changeSymbol} ${Math.abs(info.change_pct).toFixed(2)}%
              </div>
            </div>
          </div>
          
          <div class="charts-grid">
            <div class="chart-card">
              <div class="chart-card-header">
                <div class="chart-card-title">1 Minute</div>
                <div class="chart-card-timeframe">1m</div>
              </div>
              <div class="chart-card-controls">
                <input type="range" class="chart-range-slider" id="range-1m" min="10" max="100" value="60" 
                       oninput="updateChartRange('1m', this.value)">
                <span class="chart-range-label" id="label-1m">Last 60 candles</span>
              </div>
              <div class="chart-card-body">
                <div id="chart-1m" style="width: 100%; height: 100%;"></div>
              </div>
            </div>
            
            <div class="chart-card">
              <div class="chart-card-header">
                <div class="chart-card-title">15 Minutes</div>
                <div class="chart-card-timeframe">15m</div>
              </div>
              <div class="chart-card-controls">
                <input type="range" class="chart-range-slider" id="range-15m" min="10" max="80" value="60" 
                       oninput="updateChartRange('15m', this.value)">
                <span class="chart-range-label" id="label-15m">Last 60 candles</span>
              </div>
              <div class="chart-card-body">
                <div id="chart-15m" style="width: 100%; height: 100%;"></div>
              </div>
            </div>
            
            <div class="chart-card">
              <div class="chart-card-header">
                <div class="chart-card-title">1 Hour</div>
                <div class="chart-card-timeframe">1h</div>
              </div>
              <div class="chart-card-controls">
                <input type="range" class="chart-range-slider" id="range-1h" min="10" max="100" value="60" 
                       oninput="updateChartRange('1h', this.value)">
                <span class="chart-range-label" id="label-1h">Last 60 candles</span>
              </div>
              <div class="chart-card-body">
                <div id="chart-1h" style="width: 100%; height: 100%;"></div>
              </div>
            </div>
            
            <div class="chart-card">
              <div class="chart-card-header">
                <div class="chart-card-title">4 Hours</div>
                <div class="chart-card-timeframe">4h</div>
              </div>
              <div class="chart-card-controls">
                <input type="range" class="chart-range-slider" id="range-4h" min="10" max="120" value="50" 
                       oninput="updateChartRange('4h', this.value)">
                <span class="chart-range-label" id="label-4h">Last 50 candles</span>
              </div>
              <div class="chart-card-body">
                <div id="chart-4h" style="width: 100%; height: 100%;"></div>
              </div>
            </div>
          </div>
          
          <div class="trade-panel">
            <div class="trade-panel-title">Trade ${selectedSymbol}</div>
            <div class="trade-controls">
              <input type="number" id="trade-qty" class="trade-input" placeholder="Quantity" value="10" min="1">
              <button class="btn btn-buy" onclick="trade('${selectedSymbol}', 'buy')">Buy</button>
              <button class="btn btn-sell" onclick="trade('${selectedSymbol}', 'sell')">Sell</button>
            </div>
          </div>
        </div>
      `;
      
      // Render all 4 charts - wait longer for DOM to be ready
      setTimeout(() => updateCharts(), 100);
    }
    
    function createCandlestickChart(canvasId, ohlcData, timeframe) {
      const chartDiv = document.getElementById(canvasId);
      if (!chartDiv) {
        console.error(`Chart div not found: ${canvasId}`);
        return null;
      }
      
      const validOhlcData = ohlcData.filter(d => d.x && d.x > 0);
      if (validOhlcData.length === 0) {
        console.warn(`No valid OHLC data for ${canvasId}`);
        return null;
      }
      
      // Create the chart
      const chart = LightweightCharts.createChart(chartDiv, {
        layout: {
          background: { color: '#1e1e1e' },
          textColor: '#888888'
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.1)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.1)' }
        },
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          borderColor: 'rgba(255, 255, 255, 0.1)'
        },
        rightPriceScale: {
          borderColor: 'rgba(255, 255, 255, 0.1)'
        }
      });
      
      // Add candlestick series
      const candlestickSeries = chart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderUpColor: '#26a69a',
        borderDownColor: '#ef5350',
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350'
      });
      
      // Convert data to lightweight-charts format
      const candleData = validOhlcData.map(d => ({
        time: Math.floor(d.x / 1000), // Convert ms to seconds
        open: d.o,
        high: d.h,
        low: d.l,
        close: d.c
      }));
      
      candlestickSeries.setData(candleData);
      
      // Fit content
      chart.timeScale().fitContent();
      
      // Store references
      chart.candlestickSeries = candlestickSeries;
      chart.validOhlcData = validOhlcData;
      
      return chart;
    }
    
    function updateChartViewHeader(info) {
      // Update price and change % in the chart view header
      const priceElement = document.querySelector('.chart-view-price');
      const changeElement = document.querySelector('.chart-view-change');
      
      if (priceElement && changeElement && info) {
        priceElement.textContent = formatCurrency(info.price);
        
        const priceChange = info.change_pct >= 0 ? 'up' : 'down';
        const changeSymbol = info.change_pct >= 0 ? '▲' : '▼';
        changeElement.className = `chart-view-change ${priceChange}`;
        changeElement.textContent = `${changeSymbol} ${Math.abs(info.change_pct).toFixed(2)}%`;
      }
    }
    
    function updateCharts() {
      const info = priceData.symbols[selectedSymbol];
      if (!info || !info.ohlc) return;
      
      // Update the price display in the header
      updateChartViewHeader(info);
      
      // Check each chart and only update if last candle timestamp changed
      Object.keys(chartRanges).forEach(tf => {
        const fullData = info.ohlc[tf] || [];
        
        // Ensure we have enough data to display
        if (fullData.length < 10) {
          return;
        }
        
        const rangeValue = chartRanges[tf];
        const data = fullData.slice(-rangeValue);
        const validOhlcData = data.filter(d => d.x && d.x > 0);
        
        if (validOhlcData.length === 0) return;
        
        const lastCandle = validOhlcData[validOhlcData.length - 1];
        const currentTimestamp = lastCandle.x;
        
        // Create chart if doesn't exist
        if (!charts[tf]) {
          charts[tf] = createCandlestickChart(`chart-${tf}`, validOhlcData, tf);
          lastCandles[tf] = currentTimestamp;
          return;
        }
        
        // Always update to show current candle changes
        const chart = charts[tf];
        const timestampChanged = (lastCandles[tf] !== currentTimestamp);
        
        if (timestampChanged) {
          // New candle arrived - update timestamp tracker and apply full scaling
          lastCandles[tf] = currentTimestamp;
          applyChartScaling(chart, validOhlcData);
        }

        updateChartDatasets(chart, validOhlcData);
      });
    }
    
    function updateDrawer(data) {
      priceData = data;
      
      const cryptoContent = document.getElementById('crypto-drawer-content');
      const indicesContent = document.getElementById('indices-drawer-content');
      const stocksContent = document.getElementById('stocks-drawer-content');
      
      // Group symbols
      const cryptos = [];
      const indices = [];
      const stocks = [];
      
      for (const [symbol, info] of Object.entries(data.symbols)) {
        if (info.type === 'crypto') cryptos.push({symbol, info});
        else if (info.type === 'index') indices.push({symbol, info});
        else stocks.push({symbol, info});
      }
      
      // Render drawer items
      function renderDrawerItems(container, items, type) {
        container.innerHTML = items.map(({symbol, info}) => {
          const priceChange = info.change_pct >= 0 ? 'up' : 'down';
          const changeSymbol = info.change_pct >= 0 ? '▲' : '▼';
          const isActive = symbol === selectedSymbol ? 'active' : '';
          
          return `
            <div class="drawer-item ${type} ${isActive}" data-symbol="${symbol}" onclick="selectSymbol('${symbol}')">
              <div class="drawer-item-left">
                <div class="drawer-item-symbol">${symbol}</div>
                <div class="drawer-item-name">${info.name}</div>
              </div>
              <div class="drawer-item-right">
                <div class="drawer-item-price">${formatCurrency(info.price)}</div>
                <div class="drawer-item-change ${priceChange}">${changeSymbol} ${Math.abs(info.change_pct).toFixed(2)}%</div>
              </div>
            </div>
          `;
        }).join('');
      }
      
      renderDrawerItems(cryptoContent, cryptos, 'crypto');
      renderDrawerItems(indicesContent, indices, 'index');
      renderDrawerItems(stocksContent, stocks, 'stock');
      
      // Apply collapsed state
      Object.keys(collapsedSections).forEach(sectionName => {
        const section = document.getElementById(`${sectionName}-section-drawer`);
        if (section && collapsedSections[sectionName]) {
          section.classList.add('collapsed');
        }
      });
      
      // Don't re-render charts - they update themselves
      // if (selectedSymbol) {
      //   renderChartView();
      // }
      
      // Initialize charts on first load if we have a selected symbol
      if (!chartsInitialized && selectedSymbol) {
        chartsInitialized = true;
        renderChartView();
      } else if (chartsInitialized && selectedSymbol) {
        updateCharts();
      }
    }
    
    async function trade(symbol, action) {
      const qty = parseInt(document.getElementById('trade-qty').value);
      if (!qty || qty < 1) {
        showAlert('Please enter a valid quantity', 'error');
        return;
      }
      
      const response = await fetch('/api/trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, symbol, action, quantity: qty })
      });
      
      const data = await response.json();
      if (data.success) {
        showAlert(`${action === 'buy' ? 'Bought' : 'Sold'} ${qty} ${symbol}`, 'success');
        fetchPortfolio();
      } else {
        showAlert(data.error, 'error');
      }
    }
    
    function updatePortfolio(data) {
      // Update the main portfolio section at the top
      const portfolioStats = document.getElementById('portfolio-stats');
      if (!portfolioStats) return;
      
      const totalValue = data.cash + Object.entries(data.holdings).reduce((sum, [symbol, qty]) => {
        return sum + (qty * (priceData.symbols[symbol]?.price || 0));
      }, 0);
      
      const profit = totalValue - 10000;
      const returnPct = (profit / 10000) * 100;
      const holdingsValue = totalValue - data.cash;
      
      portfolioStats.innerHTML = `
        <div class="portfolio-stat-card">
          <div class="portfolio-stat-label">Cash Available</div>
          <div class="portfolio-stat-value">${formatCurrency(data.cash)}</div>
        </div>
        <div class="portfolio-stat-card">
          <div class="portfolio-stat-label">Holdings Value</div>
          <div class="portfolio-stat-value">${formatCurrency(holdingsValue)}</div>
        </div>
        <div class="portfolio-stat-card">
          <div class="portfolio-stat-label">Total Value</div>
          <div class="portfolio-stat-value">${formatCurrency(totalValue)}</div>
        </div>
        <div class="portfolio-stat-card">
          <div class="portfolio-stat-label">Profit/Loss</div>
          <div class="portfolio-stat-value ${profit >= 0 ? '' : 'negative'}">${formatCurrency(profit)}</div>
        </div>
        <div class="portfolio-stat-card">
          <div class="portfolio-stat-label">Return %</div>
          <div class="portfolio-stat-value ${returnPct >= 0 ? '' : 'negative'}">${returnPct.toFixed(2)}%</div>
        </div>
      `;
    }
    
    function showAlert(message, type) {
      const container = document.getElementById('alert-container');
      const alert = document.createElement('div');
      alert.className = `alert alert-${type}`;
      alert.textContent = message;
      container.appendChild(alert);
      setTimeout(() => alert.remove(), 3000);
    }
    
    function formatCurrency(value) {
      return '$' + value.toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
    }
    
    async function fetchPrices() {
      const response = await fetch('/api/prices');
      const data = await response.json();
      updateDrawer(data);
      // Don't call updateCharts here - it runs on its own interval
    }
    
    async function fetchPortfolio() {
      const response = await fetch(`/api/portfolio/${userId}`);
      const data = await response.json();
      updatePortfolio(data);
    }
    
    // Initialize
    fetchPrices();
    fetchPortfolio();
    
    // Update prices every 2 seconds
    setInterval(fetchPrices, 2000);
    setInterval(fetchPortfolio, 2000);
    
    // Check for chart updates every 1 second (but only update if data changed)
    setInterval(() => {
      if (selectedSymbol && document.getElementById('chart-1m')) {
        updateCharts();
      }
    }, 1000);
  </script>
</body>
</html>
"""

# ----------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/prices')
def api_prices():
    """Get current prices and history"""
    update_stock_prices()
    
    # Ensure current candles are initialized for all symbols
    now = datetime.now()
    for symbol in ALL_SYMBOLS.keys():
        for tf in ['1m', '15m', '1h', '4h']:
            if current_candle[tf][symbol]['timestamp'] is None:
                # Initialize current candle with current time boundary
                if tf == '1m':
                    candle_time = now.replace(second=0, microsecond=0)
                elif tf == '15m':
                    candle_time = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
                elif tf == '1h':
                    candle_time = now.replace(minute=0, second=0, microsecond=0)
                else:  # 4h
                    candle_time = now.replace(hour=(now.hour // 4) * 4, minute=0, second=0, microsecond=0)
                
                # Get last historical candle's close as the open price
                if len(ohlc_data[tf][symbol]) > 0:
                    open_price = ohlc_data[tf][symbol][-1]['c']
                else:
                    open_price = current_prices.get(symbol, 100.0)
                
                current_candle[tf][symbol] = {
                    'open': open_price,
                    'high': open_price,
                    'low': open_price,
                    'close': open_price,
                    'volume': 0,
                    'timestamp': candle_time
                }
    
    symbols_data = {}
    max_candles = {'1m': 90, '15m': 90, '1h': 90, '4h': 80}
    for symbol, data in ALL_SYMBOLS.items():
        history = list(price_history[symbol])
        current = current_prices.get(symbol, 0)
        previous = history[-2]['price'] if len(history) > 1 else current
        change = current - previous
        change_pct = (change / previous) * 100 if previous != 0 else 0

        # Build OHLC data including current in-progress candle per timeframe
        ohlc_with_current = {}
        for tf in ['1m', '15m', '1h', '4h']:
            historical = list(ohlc_data[tf][symbol])[-max_candles[tf]:]
            current_tf_candle = current_candle[tf][symbol]

            if (
                current_tf_candle['timestamp'] is not None and
                current_tf_candle['open'] is not None and
                current_tf_candle['close'] is not None and
                current_tf_candle['high'] is not None and
                current_tf_candle['low'] is not None
            ):
                current_entry = {
                    'x': int(current_tf_candle['timestamp'].timestamp() * 1000),
                    'o': current_tf_candle['open'],
                    'h': current_tf_candle['high'],
                    'l': current_tf_candle['low'],
                    'c': current_tf_candle['close'],
                    'v': int(current_tf_candle['volume'])
                }
                ohlc_with_current[tf] = historical + [current_entry]
            else:
                ohlc_with_current[tf] = historical

        symbols_data[symbol] = {
            'name': data['name'],
            'type': data['type'],
            'price': current,
            'change': change,
            'change_pct': change_pct,
            'history': history[-50:],
            'ohlc': ohlc_with_current
        }

    return jsonify({'symbols': symbols_data})

@app.route('/api/portfolio/<user_id>')
def api_portfolio(user_id):
    """Get user portfolio"""
    portfolio = get_portfolio(user_id)
    total_value = calculate_portfolio_value(portfolio)
    
    return jsonify({
        'cash': portfolio['cash'],
        'holdings': portfolio['holdings'],
        'trades': portfolio['trades'],
        'total_value': total_value,
        'start_value': portfolio['start_value']
    })

@app.route('/api/trade', methods=['POST'])
def api_trade():
    """Execute a trade"""
    data = request.json
    user_id = data.get('user_id')
    symbol = data.get('symbol')
    action = data.get('action')
    quantity = int(data.get('quantity', 0))
    
    if symbol not in ALL_SYMBOLS:
        return jsonify({'success': False, 'error': 'Invalid symbol'})
    
    if action not in ['buy', 'sell']:
        return jsonify({'success': False, 'error': 'Invalid action'})
    
    if quantity <= 0:
        return jsonify({'success': False, 'error': 'Invalid quantity'})
    
    result = execute_trade(user_id, symbol, action, quantity)
    return jsonify(result)

@app.route('/api/reset/<user_id>', methods=['POST'])
def api_reset(user_id):
    """Reset user portfolio"""
    if 'portfolios' in session and user_id in session['portfolios']:
        del session['portfolios'][user_id]
        session.modified = True
    return jsonify({'success': True})

# ----------------------------------------------------------------------
# RUN
# ----------------------------------------------------------------------
if __name__ == '__main__':
    # Fetch real prices FIRST before generating historical data
    print("Fetching current prices from Yahoo Finance...")
    for symbol in ALL_SYMBOLS.keys():
        real_price = fetch_yahoo_price(symbol)
        if real_price and real_price > 0:
            current_prices[symbol] = real_price
            print(f"{symbol}: ${real_price:.2f}")
        else:
            print(f"{symbol}: Using default ${current_prices[symbol]:.2f}")
    
    # Generate initial historical data for all symbols using REAL Yahoo Finance data
    print("Fetching historical data from Yahoo Finance...")
    for symbol in ALL_SYMBOLS.keys():
        print(f"  Fetching {symbol}...")
        base_price = current_prices[symbol]
        
        # Generate realistic data ending at current price for 1m and 15m charts
        print(f"    Generating data for {symbol} 1m for initial load.")
        generated_1m = generate_historical_ohlc(symbol, base_price, '1m', 300)
        ohlc_data['1m'][symbol].extend(generated_1m)
        
        print(f"    Generating data for {symbol} 15m for initial load.")
        generated_15m = generate_historical_ohlc(symbol, base_price, '15m', 250)
        ohlc_data['15m'][symbol].extend(generated_15m)

        # Generate data for ALL timeframes to ensure consistency
        print(f"    Generating data for {symbol} 1h for initial load.")
        generated_1h = generate_historical_ohlc(symbol, base_price, '1h', 200)
        ohlc_data['1h'][symbol].extend(generated_1h)
        
        print(f"    Generating data for {symbol} 4h for initial load.")
        generated_4h = generate_historical_ohlc(symbol, base_price, '4h', 150)
        ohlc_data['4h'][symbol].extend(generated_4h)
        
        # Debug: Print first and last 3 timestamps to verify 4h intervals
        if symbol == 'BTC-USD':
            print(f"    DEBUG 4h timestamps for BTC-USD:")
            for i in [0, 1, 2, -3, -2, -1]:
                ts = generated_4h[i]['x']
                dt = datetime.fromtimestamp(ts / 1000)
                print(f"      [{i}] {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    
    print("Starting Flask server...")
    app.run(host='0.0.0.0', port=8081, threaded=True, debug=True, use_reloader=False)
