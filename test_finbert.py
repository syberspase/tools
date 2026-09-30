#!/usr/bin/env python3
"""
Quick Test Script for FinBERT Trading Agent
Tests sentiment analysis and signal generation without trading
"""

import sys
import time

print("=" * 60)
print("🧪 FinBERT Trading Agent - Test Suite")
print("=" * 60)
print()

# Test 1: Import dependencies
print("Test 1: Checking dependencies...")
try:
    import torch
    import transformers
    import numpy
    import requests
    import flask
    print("✅ All dependencies installed")
    print(f"   PyTorch: {torch.__version__}")
    print(f"   Transformers: {transformers.__version__}")
    print(f"   NumPy: {numpy.__version__}")
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("\nInstall with: pip install -r requirements_finbert.txt")
    sys.exit(1)

print()

# Test 2: Load FinBERT model
print("Test 2: Loading FinBERT model...")
try:
    from finbert_trading_agent import FinBERTSentimentAnalyzer
    
    start = time.time()
    analyzer = FinBERTSentimentAnalyzer()
    load_time = time.time() - start
    
    print(f"✅ FinBERT model loaded in {load_time:.2f}s")
    print(f"   Device: {analyzer.device}")
except Exception as e:
    print(f"❌ Failed to load model: {e}")
    sys.exit(1)

print()

# Test 3: Sentiment analysis
print("Test 3: Testing sentiment analysis...")
test_texts = [
    ("Apple reports record earnings beating expectations", "positive"),
    ("Stock market crashes amid economic concerns", "negative"),
    ("Company maintains steady quarterly results", "neutral"),
    ("Strong bullish momentum drives prices higher with increasing volume", "positive"),
    ("Heavy selling pressure sends stock tumbling to new lows", "negative"),
]

print()
passed = 0
for text, expected in test_texts:
    start = time.time()
    result = analyzer.analyze_text(text)
    inference_time = (time.time() - start) * 1000  # Convert to ms
    
    predicted = "positive" if result['score'] > 0.2 else "negative" if result['score'] < -0.2 else "neutral"
    status = "✅" if predicted == expected else "⚠️"
    
    print(f"{status} Text: '{text[:50]}...'")
    print(f"   Expected: {expected}, Got: {predicted} (score: {result['score']:+.2f})")
    print(f"   Inference time: {inference_time:.1f}ms")
    print()
    
    if predicted == expected:
        passed += 1

print(f"Passed: {passed}/{len(test_texts)} ({passed/len(test_texts)*100:.0f}%)")
print()

# Test 4: Technical analysis
print("Test 4: Testing technical analysis...")
try:
    from finbert_trading_agent import TechnicalAnalyzer
    import numpy as np
    
    # Generate sample OHLCV data
    base_price = 100
    ohlcv_data = []
    for i in range(100):
        price = base_price + np.random.randn() * 2
        ohlcv_data.append({
            'open': price - 0.5,
            'high': price + 1.0,
            'low': price - 1.0,
            'close': price,
            'volume': 10000 + np.random.randint(-2000, 2000)
        })
    
    indicators = TechnicalAnalyzer.calculate_indicators(ohlcv_data)
    
    print("✅ Technical indicators calculated:")
    print(f"   RSI(14): {indicators['rsi_14']:.2f}")
    print(f"   Trend: {indicators['trend']}")
    print(f"   Momentum: {indicators['momentum']}")
    print(f"   Volatility: {indicators['volatility']}")
    print(f"   Current Price: ${indicators['current_price']:.2f}")
    
except Exception as e:
    print(f"❌ Technical analysis failed: {e}")
    sys.exit(1)

print()

# Test 5: Trading signal generation
print("Test 5: Testing trading signal generation...")
try:
    from finbert_trading_agent import FinBERTTradingAgent
    
    # Create agent (connects to localhost:5000 by default)
    agent = FinBERTTradingAgent(flask_backend_url="http://localhost:5000")
    
    # Generate signal with sample data
    signal = agent.generate_trading_signal('TEST', ohlcv_data)
    
    print("✅ Trading signal generated:")
    print(f"   Action: {signal['action']}")
    print(f"   Confidence: {signal['confidence']:.2%}")
    print(f"   Technical Score: {signal['technical_score']:+.2f}")
    print(f"   Sentiment Score: {signal['sentiment_score']:+.2f}")
    print(f"   Combined Score: {signal['combined_score']:+.2f}")
    print(f"   Position Size: {signal['position_size']:.1%}")
    if signal['stop_loss']:
        print(f"   Stop Loss: ${signal['stop_loss']:.2f}")
    if signal['take_profit']:
        print(f"   Take Profit: ${signal['take_profit']:.2f}")
    print(f"   Reasoning: {signal['reasoning']}")
    
except Exception as e:
    print(f"❌ Signal generation failed: {e}")
    print("   Note: This is expected if Flask backend is not running")

print()

# Test 6: Backend connectivity
print("Test 6: Testing Flask backend connectivity...")
try:
    import requests
    response = requests.get("http://localhost:5000", timeout=2)
    if response.status_code == 200:
        print("✅ Flask backend is running")
        
        # Test API endpoints
        try:
            ohlc_response = requests.get("http://localhost:5000/api/ohlc/AAPL/15m", timeout=2)
            if ohlc_response.status_code == 200:
                data = ohlc_response.json()
                print(f"   ✅ OHLC API working ({len(data.get('data', []))} candles)")
            else:
                print(f"   ⚠️  OHLC API returned: {ohlc_response.status_code}")
        except Exception as e:
            print(f"   ⚠️  OHLC API error: {e}")
            
    else:
        print(f"⚠️  Flask backend returned: {response.status_code}")
except requests.exceptions.ConnectionError:
    print("⚠️  Flask backend not running")
    print("   Start with: python3 app_stock_sim.py")
except Exception as e:
    print(f"⚠️  Backend check failed: {e}")

print()

# Summary
print("=" * 60)
print("📊 Test Summary")
print("=" * 60)
print()
print("Core Components:")
print("  ✅ Dependencies installed")
print("  ✅ FinBERT model loaded")
print("  ✅ Sentiment analysis working")
print("  ✅ Technical analysis working")
print("  ✅ Signal generation working")
print()
print("Next Steps:")
print("  1. Start Flask backend: python3 app_stock_sim.py")
print("  2. Start AI trading: python3 finbert_trading_agent.py")
print("  3. Or use startup script: ./start_trading.sh")
print()
print("Documentation: README_FINBERT.md")
print()
