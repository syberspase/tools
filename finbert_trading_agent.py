#!/usr/bin/env python3
"""
FinBERT-Based AI Trading Agent for Real-Time Trading
Integrates with app_stock_sim.py Flask backend
"""

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
from typing import Dict, List, Tuple, Optional
import logging
from datetime import datetime
import json
import requests
from collections import deque
import threading
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FinBERTSentimentAnalyzer:
    """
    FinBERT model for financial sentiment analysis
    Model: ProsusAI/finbert (fine-tuned BERT for financial text)
    """
    
    def __init__(self, model_name: str = "ProsusAI/finbert"):
        logger.info(f"Loading FinBERT model: {model_name}")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Using device: {self.device}")
        
        # Load FinBERT model and tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()
        
        # Create sentiment analysis pipeline
        self.sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model=self.model,
            tokenizer=self.tokenizer,
            device=0 if torch.cuda.is_available() else -1
        )
        
        logger.info("FinBERT model loaded successfully")
    
    def analyze_text(self, text: str) -> Dict[str, float]:
        """
        Analyze sentiment of financial text
        Returns: {'positive': 0.0-1.0, 'negative': 0.0-1.0, 'neutral': 0.0-1.0, 'score': -1.0 to 1.0}
        """
        if not text or len(text.strip()) < 10:
            return {'positive': 0.33, 'negative': 0.33, 'neutral': 0.34, 'score': 0.0}
        
        try:
            # Truncate text to 512 tokens (BERT limit)
            result = self.sentiment_pipeline(text[:2000])[0]
            
            # FinBERT outputs: positive, negative, neutral
            label = result['label'].lower()
            confidence = result['score']
            
            # Convert to sentiment scores
            sentiment = {'positive': 0.0, 'negative': 0.0, 'neutral': 0.0}
            sentiment[label] = confidence
            
            # Calculate aggregate score (-1 to +1)
            if label == 'positive':
                score = confidence
            elif label == 'negative':
                score = -confidence
            else:
                score = 0.0
            
            sentiment['score'] = score
            return sentiment
            
        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            return {'positive': 0.33, 'negative': 0.33, 'neutral': 0.34, 'score': 0.0}
    
    def analyze_multiple(self, texts: List[str]) -> Dict[str, float]:
        """
        Analyze multiple texts and return aggregated sentiment
        """
        if not texts:
            return {'positive': 0.33, 'negative': 0.33, 'neutral': 0.34, 'score': 0.0}
        
        sentiments = [self.analyze_text(text) for text in texts]
        
        # Aggregate sentiments
        avg_positive = np.mean([s['positive'] for s in sentiments])
        avg_negative = np.mean([s['negative'] for s in sentiments])
        avg_neutral = np.mean([s['neutral'] for s in sentiments])
        avg_score = np.mean([s['score'] for s in sentiments])
        
        return {
            'positive': float(avg_positive),
            'negative': float(avg_negative),
            'neutral': float(avg_neutral),
            'score': float(avg_score)
        }


class TechnicalAnalyzer:
    """
    Technical indicator calculator for trading signals
    """
    
    @staticmethod
    def calculate_indicators(ohlcv_data: List[Dict]) -> Dict:
        """
        Calculate technical indicators from OHLCV data
        Input: [{'open': x, 'high': x, 'low': x, 'close': x, 'volume': x}, ...]
        """
        if len(ohlcv_data) < 50:
            return TechnicalAnalyzer._empty_indicators()
        
        closes = np.array([c['close'] for c in ohlcv_data])
        highs = np.array([c['high'] for c in ohlcv_data])
        lows = np.array([c['low'] for c in ohlcv_data])
        volumes = np.array([c['volume'] for c in ohlcv_data])
        
        indicators = {
            'rsi_14': TechnicalAnalyzer._rsi(closes, 14),
            'rsi_7': TechnicalAnalyzer._rsi(closes, 7),
            'macd': TechnicalAnalyzer._macd(closes),
            'bollinger': TechnicalAnalyzer._bollinger_bands(closes, 20, 2),
            'ema_12': TechnicalAnalyzer._ema(closes, 12),
            'ema_26': TechnicalAnalyzer._ema(closes, 26),
            'sma_20': TechnicalAnalyzer._sma(closes, 20),
            'sma_50': TechnicalAnalyzer._sma(closes, 50),
            'atr_14': TechnicalAnalyzer._atr(highs, lows, closes, 14),
            'volume_ratio': volumes[-1] / np.mean(volumes[-20:]) if len(volumes) >= 20 else 1.0,
            'current_price': float(closes[-1]),
            'price_change_1': float((closes[-1] - closes[-2]) / closes[-2] * 100),
            'price_change_5': float((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else 0.0,
            'price_change_20': float((closes[-1] - closes[-20]) / closes[-20] * 100) if len(closes) >= 20 else 0.0,
        }
        
        # Trend detection
        indicators['trend'] = TechnicalAnalyzer._detect_trend(closes)
        indicators['momentum'] = TechnicalAnalyzer._calculate_momentum(closes)
        indicators['volatility'] = TechnicalAnalyzer._calculate_volatility(closes)
        
        return indicators
    
    @staticmethod
    def _empty_indicators() -> Dict:
        return {
            'rsi_14': 50.0, 'rsi_7': 50.0, 'macd': {'line': 0, 'signal': 0, 'histogram': 0},
            'bollinger': {'upper': 0, 'middle': 0, 'lower': 0, 'position': 50},
            'ema_12': 0, 'ema_26': 0, 'sma_20': 0, 'sma_50': 0, 'atr_14': 0,
            'volume_ratio': 1.0, 'current_price': 0, 'price_change_1': 0,
            'price_change_5': 0, 'price_change_20': 0, 'trend': 'Unknown',
            'momentum': 'Neutral', 'volatility': 'Normal'
        }
    
    @staticmethod
    def _rsi(prices: np.ndarray, period: int = 14) -> float:
        """Relative Strength Index"""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)
    
    @staticmethod
    def _macd(prices: np.ndarray) -> Dict[str, float]:
        """Moving Average Convergence Divergence"""
        ema_12 = TechnicalAnalyzer._ema(prices, 12)
        ema_26 = TechnicalAnalyzer._ema(prices, 26)
        macd_line = ema_12 - ema_26
        
        # Signal line (9-period EMA of MACD)
        # Simplified: use last 9 MACD values
        signal_line = macd_line  # Placeholder
        histogram = macd_line - signal_line
        
        return {
            'line': float(macd_line),
            'signal': float(signal_line),
            'histogram': float(histogram)
        }
    
    @staticmethod
    def _ema(prices: np.ndarray, period: int) -> float:
        """Exponential Moving Average"""
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return float(ema)
    
    @staticmethod
    def _sma(prices: np.ndarray, period: int) -> float:
        """Simple Moving Average"""
        return float(np.mean(prices[-period:]))
    
    @staticmethod
    def _bollinger_bands(prices: np.ndarray, period: int = 20, std_dev: int = 2) -> Dict[str, float]:
        """Bollinger Bands"""
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        current = prices[-1]
        
        # Position within bands (0-100%)
        band_width = upper - lower
        position = ((current - lower) / band_width * 100) if band_width > 0 else 50
        
        return {
            'upper': float(upper),
            'middle': float(sma),
            'lower': float(lower),
            'position': float(np.clip(position, 0, 100))
        }
    
    @staticmethod
    def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Average True Range (volatility indicator)"""
        high_low = highs[1:] - lows[1:]
        high_close = np.abs(highs[1:] - closes[:-1])
        low_close = np.abs(lows[1:] - closes[:-1])
        
        true_range = np.maximum(high_low, high_close, low_close)
        atr = np.mean(true_range[-period:])
        return float(atr)
    
    @staticmethod
    def _detect_trend(prices: np.ndarray) -> str:
        """Detect current trend"""
        if len(prices) < 50:
            return "Unknown"
        
        sma_20 = np.mean(prices[-20:])
        sma_50 = np.mean(prices[-50:])
        current = prices[-1]
        
        if current > sma_20 > sma_50:
            return "Strong Uptrend"
        elif current > sma_20:
            return "Uptrend"
        elif current < sma_20 < sma_50:
            return "Strong Downtrend"
        elif current < sma_20:
            return "Downtrend"
        return "Sideways"
    
    @staticmethod
    def _calculate_momentum(prices: np.ndarray) -> str:
        """Calculate momentum"""
        if len(prices) < 10:
            return "Neutral"
        
        recent_change = (prices[-1] - prices[-10]) / prices[-10] * 100
        
        if recent_change > 2:
            return "Strong Positive"
        elif recent_change > 0.5:
            return "Positive"
        elif recent_change < -2:
            return "Strong Negative"
        elif recent_change < -0.5:
            return "Negative"
        return "Neutral"
    
    @staticmethod
    def _calculate_volatility(prices: np.ndarray) -> str:
        """Calculate volatility regime"""
        if len(prices) < 20:
            return "Normal"
        
        returns = np.diff(prices[-20:]) / prices[-21:-1]
        volatility = np.std(returns) * 100
        
        if volatility > 3:
            return "Very High"
        elif volatility > 2:
            return "High"
        elif volatility > 1:
            return "Normal"
        return "Low"


class FinBERTTradingAgent:
    """
    Main trading agent combining FinBERT sentiment + technical analysis
    """
    
    def __init__(self, flask_backend_url: str = "http://localhost:5000"):
        self.sentiment_analyzer = FinBERTSentimentAnalyzer()
        self.technical_analyzer = TechnicalAnalyzer()
        self.backend_url = flask_backend_url
        
        # Trading state
        self.active_positions = {}
        self.trade_history = deque(maxlen=1000)
        self.signal_history = deque(maxlen=100)
        
        # Configuration
        self.min_confidence = 0.65  # Minimum confidence to trade
        self.max_position_size = 0.15  # Max 15% of portfolio per position
        self.stop_loss_pct = 0.03  # 3% stop loss
        self.take_profit_pct = 0.05  # 5% take profit
        
        logger.info("FinBERT Trading Agent initialized")
    
    def generate_trading_signal(self, symbol: str, ohlcv_data: List[Dict], 
                                news_texts: List[str] = None) -> Dict:
        """
        Generate comprehensive trading signal
        
        Returns:
        {
            'action': 'BUY' | 'SELL' | 'HOLD',
            'confidence': 0.0-1.0,
            'position_size': 0.0-1.0 (fraction of portfolio),
            'stop_loss': price level,
            'take_profit': price level,
            'reasoning': detailed explanation,
            'sentiment': sentiment analysis results,
            'technicals': technical indicators
        }
        """
        logger.info(f"Generating signal for {symbol}")
        
        # 1. Technical Analysis
        technicals = self.technical_analyzer.calculate_indicators(ohlcv_data)
        current_price = technicals['current_price']
        
        # 2. Sentiment Analysis
        sentiment = {'score': 0.0, 'positive': 0.33, 'negative': 0.33, 'neutral': 0.34}
        if news_texts and len(news_texts) > 0:
            sentiment = self.sentiment_analyzer.analyze_multiple(news_texts)
        
        # 3. Generate synthetic market commentary for sentiment (if no news)
        if not news_texts:
            market_context = self._generate_market_context(symbol, technicals)
            sentiment = self.sentiment_analyzer.analyze_text(market_context)
        
        # 4. Combine signals
        signal = self._combine_signals(symbol, technicals, sentiment, current_price)
        
        # Store signal
        self.signal_history.append({
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'signal': signal
        })
        
        return signal
    
    def _generate_market_context(self, symbol: str, technicals: Dict) -> str:
        """Generate market context text for sentiment analysis"""
        trend = technicals['trend']
        momentum = technicals['momentum']
        rsi = technicals['rsi_14']
        price_change = technicals['price_change_1']
        
        # Create narrative
        contexts = []
        
        if price_change > 2:
            contexts.append(f"{symbol} surges higher with strong bullish momentum")
        elif price_change < -2:
            contexts.append(f"{symbol} drops sharply amid selling pressure")
        
        if rsi > 70:
            contexts.append(f"Technical indicators show {symbol} entering overbought territory")
        elif rsi < 30:
            contexts.append(f"{symbol} reaches oversold levels, potential reversal ahead")
        
        if trend == "Strong Uptrend":
            contexts.append(f"Analysts bullish on {symbol} as uptrend continues")
        elif trend == "Strong Downtrend":
            contexts.append(f"Bearish sentiment dominates {symbol} trading")
        
        if momentum == "Strong Positive":
            contexts.append(f"Strong buying interest drives {symbol} higher")
        elif momentum == "Strong Negative":
            contexts.append(f"Heavy selling hits {symbol} amid market concerns")
        
        # Combine
        if contexts:
            return ". ".join(contexts) + "."
        return f"{symbol} trading continues with moderate activity"
    
    def _combine_signals(self, symbol: str, technicals: Dict, 
                        sentiment: Dict, current_price: float) -> Dict:
        """
        Combine technical and sentiment signals into trading decision
        """
        # Technical score (-1 to +1)
        tech_score = self._calculate_technical_score(technicals)
        
        # Sentiment score (-1 to +1)
        sent_score = sentiment['score']
        
        # Weighted combination (60% technical, 40% sentiment)
        combined_score = (tech_score * 0.6) + (sent_score * 0.4)
        
        # Convert to action
        confidence = abs(combined_score)
        
        if combined_score > 0.3 and confidence >= self.min_confidence:
            action = "BUY"
            position_size = min(confidence * self.max_position_size, self.max_position_size)
            stop_loss = current_price * (1 - self.stop_loss_pct)
            take_profit = current_price * (1 + self.take_profit_pct)
            
        elif combined_score < -0.3 and confidence >= self.min_confidence:
            action = "SELL"
            position_size = min(confidence * self.max_position_size, self.max_position_size)
            stop_loss = current_price * (1 + self.stop_loss_pct)
            take_profit = current_price * (1 - self.take_profit_pct)
            
        else:
            action = "HOLD"
            position_size = 0.0
            stop_loss = None
            take_profit = None
        
        # Generate reasoning
        reasoning = self._generate_reasoning(action, tech_score, sent_score, technicals, sentiment)
        
        return {
            'action': action,
            'confidence': float(confidence),
            'position_size': float(position_size),
            'stop_loss': float(stop_loss) if stop_loss else None,
            'take_profit': float(take_profit) if take_profit else None,
            'reasoning': reasoning,
            'technical_score': float(tech_score),
            'sentiment_score': float(sent_score),
            'combined_score': float(combined_score),
            'sentiment': sentiment,
            'technicals': {
                'rsi_14': technicals['rsi_14'],
                'trend': technicals['trend'],
                'momentum': technicals['momentum'],
                'price': current_price
            }
        }
    
    def _calculate_technical_score(self, technicals: Dict) -> float:
        """
        Calculate technical analysis score (-1 to +1)
        """
        score = 0.0
        
        # RSI signals
        rsi = technicals['rsi_14']
        if rsi < 30:
            score += 0.3  # Oversold - bullish
        elif rsi > 70:
            score -= 0.3  # Overbought - bearish
        elif 40 < rsi < 60:
            score += 0.1  # Neutral zone
        
        # Trend signals
        trend = technicals['trend']
        if trend in ["Strong Uptrend", "Uptrend"]:
            score += 0.3
        elif trend in ["Strong Downtrend", "Downtrend"]:
            score -= 0.3
        
        # Momentum signals
        momentum = technicals['momentum']
        if momentum == "Strong Positive":
            score += 0.2
        elif momentum == "Positive":
            score += 0.1
        elif momentum == "Strong Negative":
            score -= 0.2
        elif momentum == "Negative":
            score -= 0.1
        
        # Bollinger Band position
        bb_position = technicals['bollinger']['position']
        if bb_position < 20:
            score += 0.2  # Near lower band - bullish
        elif bb_position > 80:
            score -= 0.2  # Near upper band - bearish
        
        # MACD
        macd_histogram = technicals['macd']['histogram']
        if macd_histogram > 0:
            score += 0.1
        else:
            score -= 0.1
        
        return np.clip(score, -1.0, 1.0)
    
    def _generate_reasoning(self, action: str, tech_score: float, sent_score: float,
                           technicals: Dict, sentiment: Dict) -> str:
        """Generate human-readable reasoning"""
        parts = []
        
        # Action
        parts.append(f"**{action} Signal**")
        
        # Technical reasoning
        tech_reasons = []
        rsi = technicals['rsi_14']
        if rsi < 30:
            tech_reasons.append(f"RSI({rsi:.1f}) oversold")
        elif rsi > 70:
            tech_reasons.append(f"RSI({rsi:.1f}) overbought")
        
        tech_reasons.append(f"Trend: {technicals['trend']}")
        tech_reasons.append(f"Momentum: {technicals['momentum']}")
        
        parts.append(f"Technical: {', '.join(tech_reasons)} (score: {tech_score:+.2f})")
        
        # Sentiment reasoning
        sent_label = "Positive" if sent_score > 0.2 else "Negative" if sent_score < -0.2 else "Neutral"
        parts.append(f"Sentiment: {sent_label} (score: {sent_score:+.2f})")
        
        return " | ".join(parts)
    
    def execute_trade(self, symbol: str, signal: Dict, portfolio_value: float) -> bool:
        """
        Execute trade via Flask backend API
        """
        if signal['action'] == 'HOLD':
            logger.info(f"{symbol}: HOLD signal, no action")
            return False
        
        action = signal['action']
        position_size_pct = signal['position_size']
        current_price = signal['technicals']['price']
        
        # Calculate shares
        position_value = portfolio_value * position_size_pct
        shares = int(position_value / current_price)
        
        if shares < 1:
            logger.warning(f"{symbol}: Insufficient capital for trade")
            return False
        
        try:
            # Call Flask API
            endpoint = f"{self.backend_url}/api/trade"
            payload = {
                'symbol': symbol,
                'action': action.lower(),  # 'buy' or 'sell'
                'shares': shares
            }
            
            response = requests.post(endpoint, json=payload, timeout=5)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    logger.info(f"✅ {action} {shares} shares of {symbol} at ${current_price:.2f}")
                    
                    # Track position
                    self.active_positions[symbol] = {
                        'action': action,
                        'shares': shares,
                        'entry_price': current_price,
                        'stop_loss': signal['stop_loss'],
                        'take_profit': signal['take_profit'],
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    # Log trade
                    self.trade_history.append({
                        'timestamp': datetime.now().isoformat(),
                        'symbol': symbol,
                        'action': action,
                        'shares': shares,
                        'price': current_price,
                        'signal': signal
                    })
                    
                    return True
                else:
                    logger.error(f"Trade failed: {result.get('message')}")
            else:
                logger.error(f"API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
        
        return False
    
    def get_ohlcv_from_backend(self, symbol: str, timeframe: str = '15m') -> List[Dict]:
        """
        Fetch OHLCV data from Flask backend
        """
        try:
            endpoint = f"{self.backend_url}/api/ohlc/{symbol}/{timeframe}"
            response = requests.get(endpoint, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('data', [])
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        
        return []
    
    def get_portfolio(self) -> Dict:
        """Get current portfolio from Flask backend"""
        try:
            endpoint = f"{self.backend_url}/api/portfolio/auto_trader"
            response = requests.get(endpoint, timeout=5)
            
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching portfolio: {e}")
        
        return {'cash': 0, 'total_value': 0}


class AutoTradingLoop:
    """
    Automated trading loop that runs continuously
    """
    
    def __init__(self, agent: FinBERTTradingAgent, symbols: List[str], 
                 interval_seconds: int = 60):
        self.agent = agent
        self.symbols = symbols
        self.interval = interval_seconds
        self.running = False
        self.thread = None
    
    def start(self):
        """Start trading loop in background thread"""
        if self.running:
            logger.warning("Trading loop already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"🚀 Auto-trading started for {len(self.symbols)} symbols")
    
    def stop(self):
        """Stop trading loop"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("⏹️ Auto-trading stopped")
    
    def _run_loop(self):
        """Main trading loop"""
        while self.running:
            try:
                # Get portfolio
                portfolio = self.agent.get_portfolio()
                portfolio_value = portfolio.get('total_value', 0)
                
                if portfolio_value < 1000:
                    logger.warning("Insufficient portfolio value, skipping cycle")
                    time.sleep(self.interval)
                    continue
                
                # Process each symbol
                for symbol in self.symbols:
                    if not self.running:
                        break
                    
                    try:
                        # Get OHLCV data
                        ohlcv_data = self.agent.get_ohlcv_from_backend(symbol, '15m')
                        
                        if len(ohlcv_data) < 50:
                            logger.warning(f"{symbol}: Insufficient data")
                            continue
                        
                        # Generate signal
                        signal = self.agent.generate_trading_signal(symbol, ohlcv_data)
                        
                        logger.info(f"{symbol}: {signal['action']} (confidence: {signal['confidence']:.2%}, "
                                  f"tech: {signal['technical_score']:+.2f}, sent: {signal['sentiment_score']:+.2f})")
                        
                        # Execute trade
                        if signal['action'] != 'HOLD':
                            self.agent.execute_trade(symbol, signal, portfolio_value)
                    
                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {e}")
                
                # Wait for next cycle
                time.sleep(self.interval)
                
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                time.sleep(self.interval)


def main():
    """
    Example usage
    """
    # Initialize agent
    agent = FinBERTTradingAgent(flask_backend_url="http://localhost:5000")
    
    # Symbols to trade
    symbols = ['AAPL', 'GOOGL', 'ORCL', 'BTC-USD', 'ETH-USD']
    
    # Start auto-trading
    trading_loop = AutoTradingLoop(agent, symbols, interval_seconds=60)
    trading_loop.start()
    
    # Keep running
    try:
        while True:
            time.sleep(10)
            
            # Print status
            portfolio = agent.get_portfolio()
            logger.info(f"Portfolio Value: ${portfolio.get('total_value', 0):,.2f}")
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        trading_loop.stop()


if __name__ == "__main__":
    main()
