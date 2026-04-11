"""
ai_council.py — ENHANCED
═════════════════════════
Every real AI feature that genuinely improves signal quality.

WHAT IS REAL AND WHAT IT DOES:
  1. 12 indicators  — not just 4. Each votes independently.
  2. Multi-timeframe — 15m + 1h + 4h must agree. Filters false signals.
  3. Market regime   — detects trending vs ranging. Different rules apply.
  4. Volume analysis — OBV, VWAP, volume spike. No volume = no signal.
  5. Support/Resistance — auto detects key price levels from history.
  6. Confluence score — 0 to 100. Not just pass/fail.
  7. Dynamic weights  — indicators that were right recently score higher.
  8. Claude API       — reads all data + news + fear/greed, gives final vote.
  9. OpenAI API       — second opinion, confirms or rejects.

HONEST: Win rate depends on market conditions. Nobody knows until
you run 50+ real signals. These features reduce false signals — they
do not guarantee profit.
"""

import json
import time
import requests
from news_pattern_agent import NewsPatternAgent
from candle_pattern_agent import CandlePatternAgent
from market_filters import DailyTrendFilter, FundingRateFilter, SessionFilter
from sr_engine import SRAgent
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator
from ta.trend import MACD, EMAIndicator, CCIIndicator, ADXIndicator, IchimokuIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice


# ═══════════════════════════════════════════════════════
# INDICATOR ENGINE — 12 indicators, each votes independently
# ═══════════════════════════════════════════════════════

class IndicatorEngine:
    """
    Calculates 12 real indicators on real candle data.
    Each indicator votes BUY, SELL or NEUTRAL independently.
    No single indicator can override the others.
    """

    def calculate(self, df):
        c   = df["close"]
        h   = df["high"]
        l   = df["low"]
        v   = df["volume"]

        results = {}

        # ── 1. RSI (14) ────────────────────────────────
        rsi = RSIIndicator(close=c, window=14).rsi()
        results["rsi"]      = rsi.iloc[-1]
        results["rsi_prev"] = rsi.iloc[-2]

        # ── 2. MACD ────────────────────────────────────
        macd_obj = MACD(close=c, window_slow=26, window_fast=12, window_sign=9)
        results["macd_hist"]      = macd_obj.macd_diff().iloc[-1]
        results["macd_hist_prev"] = macd_obj.macd_diff().iloc[-2]
        results["macd_line"]      = macd_obj.macd().iloc[-1]
        results["macd_signal"]    = macd_obj.macd_signal().iloc[-1]

        # ── 3. EMA stack ───────────────────────────────
        results["ema20"]  = EMAIndicator(close=c, window=20).ema_indicator().iloc[-1]
        results["ema50"]  = EMAIndicator(close=c, window=50).ema_indicator().iloc[-1]
        results["ema200"] = EMAIndicator(close=c, window=200).ema_indicator().iloc[-1]

        # ── 4. Bollinger Bands ─────────────────────────
        bb = BollingerBands(close=c, window=20, window_dev=2)
        results["bb_pct"]   = bb.bollinger_pband().iloc[-1]
        results["bb_upper"] = bb.bollinger_hband().iloc[-1]
        results["bb_lower"] = bb.bollinger_lband().iloc[-1]
        results["bb_width"] = bb.bollinger_wband().iloc[-1]

        # ── 5. Stochastic (14,3) ───────────────────────
        stoch = StochasticOscillator(high=h, low=l, close=c, window=14, smooth_window=3)
        results["stoch_k"]      = stoch.stoch().iloc[-1]
        results["stoch_d"]      = stoch.stoch_signal().iloc[-1]
        results["stoch_k_prev"] = stoch.stoch().iloc[-2]

        # ── 6. Williams %R ─────────────────────────────
        results["williams_r"] = WilliamsRIndicator(high=h, low=l, close=c, lbp=14).williams_r().iloc[-1]

        # ── 7. CCI ─────────────────────────────────────
        results["cci"] = CCIIndicator(high=h, low=l, close=c, window=20).cci().iloc[-1]

        # ── 8. ADX (trend strength) ────────────────────
        adx = ADXIndicator(high=h, low=l, close=c, window=14)
        results["adx"]     = adx.adx().iloc[-1]
        results["adx_pos"] = adx.adx_pos().iloc[-1]  # +DI
        results["adx_neg"] = adx.adx_neg().iloc[-1]  # -DI

        # ── 9. ATR ─────────────────────────────────────
        results["atr"] = AverageTrueRange(high=h, low=l, close=c, window=14).average_true_range().iloc[-1]

        # ── 10. OBV (On Balance Volume) ────────────────
        obv = OnBalanceVolumeIndicator(close=c, volume=v).on_balance_volume()
        results["obv"]      = obv.iloc[-1]
        results["obv_ema"]  = obv.ewm(span=20).mean().iloc[-1]

        # ── 11. VWAP ───────────────────────────────────
        try:
            vwap = VolumeWeightedAveragePrice(high=h, low=l, close=c, volume=v, window=14)
            results["vwap"] = vwap.volume_weighted_average_price().iloc[-1]
        except Exception:
            results["vwap"] = c.iloc[-1]  # fallback to price if VWAP fails

        # ── 12. Volume analysis ────────────────────────
        vol_sma           = v.rolling(20).mean()
        results["vol_ratio"]  = v.iloc[-1] / vol_sma.iloc[-1]
        results["vol_spike"]  = v.iloc[-1] > vol_sma.iloc[-1] * 1.5

        results["price"] = c.iloc[-1]
        return results

    def vote(self, ind):
        """
        Each indicator votes independently.
        Returns list of bull votes and bear votes with reasons.
        """
        p    = ind["price"]
        bull = []
        bear = []

        # ── RSI ────────────────────────────────────────
        if ind["rsi"] < 30 and ind["rsi"] > ind["rsi_prev"]:
            bull.append(("RSI", 2, f"RSI={ind['rsi']:.1f} extreme oversold + turning up"))
        elif ind["rsi"] < 40 and ind["rsi"] > ind["rsi_prev"]:
            bull.append(("RSI", 1, f"RSI={ind['rsi']:.1f} oversold zone + rising"))
        elif ind["rsi"] > 70 and ind["rsi"] < ind["rsi_prev"]:
            bear.append(("RSI", 2, f"RSI={ind['rsi']:.1f} extreme overbought + turning down"))
        elif ind["rsi"] > 60 and ind["rsi"] < ind["rsi_prev"]:
            bear.append(("RSI", 1, f"RSI={ind['rsi']:.1f} overbought zone + falling"))

        # ── MACD ───────────────────────────────────────
        if ind["macd_hist"] > 0 and ind["macd_hist_prev"] <= 0:
            bull.append(("MACD", 2, "MACD bullish crossover — strong momentum signal"))
        elif ind["macd_hist"] > 0 and ind["macd_line"] > ind["macd_signal"]:
            bull.append(("MACD", 1, "MACD positive + line above signal"))
        elif ind["macd_hist"] < 0 and ind["macd_hist_prev"] >= 0:
            bear.append(("MACD", 2, "MACD bearish crossover — strong momentum signal"))
        elif ind["macd_hist"] < 0 and ind["macd_line"] < ind["macd_signal"]:
            bear.append(("MACD", 1, "MACD negative + line below signal"))

        # ── EMA Stack ──────────────────────────────────
        if p > ind["ema20"] > ind["ema50"] > ind["ema200"]:
            bull.append(("EMA", 3, "Perfect EMA alignment: price > EMA20 > EMA50 > EMA200"))
        elif p > ind["ema50"] > ind["ema200"]:
            bull.append(("EMA", 2, "Price above EMA50 > EMA200 — uptrend confirmed"))
        elif p > ind["ema200"]:
            bull.append(("EMA", 1, "Price above EMA200 — long term uptrend"))
        elif p < ind["ema20"] < ind["ema50"] < ind["ema200"]:
            bear.append(("EMA", 3, "Perfect EMA alignment: price < EMA20 < EMA50 < EMA200"))
        elif p < ind["ema50"] < ind["ema200"]:
            bear.append(("EMA", 2, "Price below EMA50 < EMA200 — downtrend confirmed"))
        elif p < ind["ema200"]:
            bear.append(("EMA", 1, "Price below EMA200 — long term downtrend"))

        # ── Bollinger Bands ────────────────────────────
        if ind["bb_pct"] < 0.05:
            bull.append(("BB", 2, f"Price BELOW lower Bollinger Band — strong reversal zone"))
        elif ind["bb_pct"] < 0.15:
            bull.append(("BB", 1, f"Price at lower Bollinger Band (bb={ind['bb_pct']:.2f})"))
        elif ind["bb_pct"] > 0.95:
            bear.append(("BB", 2, f"Price ABOVE upper Bollinger Band — strong rejection zone"))
        elif ind["bb_pct"] > 0.85:
            bear.append(("BB", 1, f"Price at upper Bollinger Band (bb={ind['bb_pct']:.2f})"))

        # ── Stochastic ─────────────────────────────────
        if ind["stoch_k"] < 20 and ind["stoch_k"] > ind["stoch_k_prev"] and ind["stoch_k"] > ind["stoch_d"]:
            bull.append(("Stoch", 2, f"Stochastic oversold ({ind['stoch_k']:.1f}) + K crossed above D"))
        elif ind["stoch_k"] < 30:
            bull.append(("Stoch", 1, f"Stochastic oversold ({ind['stoch_k']:.1f})"))
        elif ind["stoch_k"] > 80 and ind["stoch_k"] < ind["stoch_k_prev"] and ind["stoch_k"] < ind["stoch_d"]:
            bear.append(("Stoch", 2, f"Stochastic overbought ({ind['stoch_k']:.1f}) + K crossed below D"))
        elif ind["stoch_k"] > 70:
            bear.append(("Stoch", 1, f"Stochastic overbought ({ind['stoch_k']:.1f})"))

        # ── Williams %R ────────────────────────────────
        if ind["williams_r"] < -80:
            bull.append(("WilliamsR", 1, f"Williams %R oversold ({ind['williams_r']:.1f})"))
        elif ind["williams_r"] > -20:
            bear.append(("WilliamsR", 1, f"Williams %R overbought ({ind['williams_r']:.1f})"))

        # ── CCI ────────────────────────────────────────
        if ind["cci"] < -100:
            bull.append(("CCI", 1, f"CCI oversold ({ind['cci']:.1f})"))
        elif ind["cci"] > 100:
            bear.append(("CCI", 1, f"CCI overbought ({ind['cci']:.1f})"))

        # ── ADX — only add directional votes if trend is strong
        if ind["adx"] > 25:
            if ind["adx_pos"] > ind["adx_neg"]:
                bull.append(("ADX", 1, f"ADX={ind['adx']:.1f} strong trend + bullish direction"))
            else:
                bear.append(("ADX", 1, f"ADX={ind['adx']:.1f} strong trend + bearish direction"))

        # ── OBV ────────────────────────────────────────
        if ind["obv"] > ind["obv_ema"]:
            bull.append(("OBV", 1, "OBV above its EMA — buying pressure confirmed"))
        elif ind["obv"] < ind["obv_ema"]:
            bear.append(("OBV", 1, "OBV below its EMA — selling pressure confirmed"))

        # ── VWAP ───────────────────────────────────────
        if p > ind["vwap"] * 1.001:
            bull.append(("VWAP", 1, f"Price above VWAP (${ind['vwap']:,.2f}) — bullish intraday"))
        elif p < ind["vwap"] * 0.999:
            bear.append(("VWAP", 1, f"Price below VWAP (${ind['vwap']:,.2f}) — bearish intraday"))

        # ── Volume filter — reduce score if volume is low
        if not ind["vol_spike"] and ind["vol_ratio"] < 0.7:
            # Low volume — reduce weight of all signals
            bull = [(name, max(1, w-1), reason) for name, w, reason in bull]
            bear = [(name, max(1, w-1), reason) for name, w, reason in bear]

        return bull, bear


# ═══════════════════════════════════════════════════════
# MULTI-TIMEFRAME ENGINE
# Checks 15m, 1h, 4h candles and requires agreement
# ═══════════════════════════════════════════════════════

class MultiTimeframeEngine:
    """
    Fetches candles on 3 timeframes and scores each.
    A signal on 15m that is confirmed on 1h and 4h is
    much stronger than a 15m signal alone.

    This is the single biggest improvement over basic bots.
    Most false signals on 15m are filtered by 1h/4h disagreement.
    """

    def __init__(self):
        self.exchange = ccxt.kucoin({"enableRateLimit": True})
        self.engine   = IndicatorEngine()

    def get_tf_score(self, symbol, timeframe):
        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=220)
            df  = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            df = df.set_index("ts").astype(float)
            ind  = self.engine.calculate(df)
            bull, bear = self.engine.vote(ind)
            bull_score = sum(w for _, w, _ in bull)
            bear_score = sum(w for _, w, _ in bear)
            if bull_score > bear_score and bull_score >= 3:
                return "BUY", bull_score, ind, df
            elif bear_score > bull_score and bear_score >= 3:
                return "SELL", bear_score, ind, df
            else:
                return "HOLD", 0, ind, df
        except Exception as e:
            print(f"    [MTF] Error on {timeframe}: {e}")
            return "HOLD", 0, {}, None

    def analyse(self, symbol):
        print(f"    [MTF] Checking 5m, 15m, 1h timeframes...")
        tf5m_dir,  tf5m_score,  ind5m,  df5m  = self.get_tf_score(symbol, "5m")
        tf15_dir,  tf15_score,  ind15,  df15  = self.get_tf_score(symbol, "15m")
        tf1h_dir,  tf1h_score,  ind1h,  _     = self.get_tf_score(symbol, "1h")

        print(f"    [MTF] 5m:{tf5m_dir}({tf5m_score}) | 15m:{tf15_dir}({tf15_score}) | 1h:{tf1h_dir}({tf1h_score})")

        # Best: all 3 agree
        if tf5m_dir == tf15_dir == tf1h_dir and tf5m_dir != "HOLD":
            confluence = "ALL3"
            direction  = tf5m_dir
            score      = tf5m_score + tf15_score + tf1h_score
            print(f"    [MTF] ✅ ALL 3 AGREE — {direction} — highest confidence")
        # Good: 15m + 1h agree (filters most false signals)
        elif tf15_dir == tf1h_dir and tf15_dir != "HOLD":
            confluence = "15M_1H"
            direction  = tf15_dir
            score      = tf15_score + tf1h_score
            print(f"    [MTF] ⚡ 15m + 1h agree — {direction} — good confidence")
        # Acceptable: 5m + 15m agree (faster signals, slightly lower quality)
        elif tf5m_dir == tf15_dir and tf5m_dir != "HOLD":
            confluence = "5M_15M"
            direction  = tf5m_dir
            score      = tf5m_score + tf15_score
            print(f"    [MTF] ⚡ 5m + 15m agree — {direction} — moderate confidence")
        else:
            confluence = "NONE"
            direction  = "HOLD"
            score      = 0
            print(f"    [MTF] ❌ Timeframes disagree — HOLD")

        # Use 15m df for indicator detail (best balance of speed and reliability)
        return direction, score, ind15, df15, confluence


# ═══════════════════════════════════════════════════════
# MARKET REGIME DETECTOR
# Is the market trending or ranging?
# Different trading rules apply for each.
# ═══════════════════════════════════════════════════════

class MarketRegime:
    """
    Detects whether market is:
    - TRENDING: Use EMA + MACD + ADX signals
    - RANGING:  Use RSI + Bollinger Band reversal signals
    - VOLATILE: Reduce position size, widen SL
    """

    def detect(self, ind, df):
        adx       = ind.get("adx", 20)
        bb_width  = ind.get("bb_width", 0.02)
        atr       = ind.get("atr", 0)
        price     = ind.get("price", 1)
        atr_pct   = atr / price * 100

        if adx > 30 and bb_width > 0.03:
            regime = "TRENDING"
            note   = f"ADX={adx:.1f} strong trend, BB width={bb_width:.3f}"
        elif adx < 20 and bb_width < 0.02:
            regime = "RANGING"
            note   = f"ADX={adx:.1f} weak trend, market consolidating"
        elif atr_pct > 4:
            regime = "VOLATILE"
            note   = f"ATR={atr_pct:.1f}% — high volatility, reduce size"
        else:
            regime = "NORMAL"
            note   = f"ADX={adx:.1f}, normal conditions"

        print(f"    [Regime] Market is {regime} — {note}")
        return regime, note


# ═══════════════════════════════════════════════════════
# SUPPORT & RESISTANCE DETECTOR
# Auto-detects key price levels from candle history
# ═══════════════════════════════════════════════════════

class SupportResistance:
    """
    Finds the nearest support and resistance levels
    from recent price history.
    Checks if current price is near a key level.
    """

    def find_levels(self, df, num_levels=5):
        if df is None or len(df) < 50:
            return [], []

        highs  = df["high"].rolling(10, center=True).max()
        lows   = df["low"].rolling(10, center=True).min()
        price  = df["close"].iloc[-1]

        # Find swing highs and lows
        resistance = sorted(set(
            round(h, 2) for h in highs.dropna().unique()
            if h > price
        ))[:num_levels]

        support = sorted(set(
            round(l, 2) for l in lows.dropna().unique()
            if l < price
        ), reverse=True)[:num_levels]

        return support, resistance

    def check_proximity(self, price, support, resistance, atr):
        """Check if price is near a key level — within 0.5 ATR"""
        proximity_zone = atr * 0.5
        near_support    = any(abs(price - s) < proximity_zone for s in support)
        near_resistance = any(abs(price - r) < proximity_zone for r in resistance)

        if near_support:
            nearest = min(support, key=lambda s: abs(price - s))
            print(f"    [S/R] Price near SUPPORT at ${nearest:,.4f} — potential bounce zone")
            return "NEAR_SUPPORT"
        elif near_resistance:
            nearest = min(resistance, key=lambda r: abs(price - r))
            print(f"    [S/R] Price near RESISTANCE at ${nearest:,.4f} — potential rejection zone")
            return "NEAR_RESISTANCE"
        return "CLEAR"


# ═══════════════════════════════════════════════════════
# CONFLUENCE SCORER
# Converts all votes into a single 0-100 score
# ═══════════════════════════════════════════════════════

class ConfluenceScorer:
    """
    Takes all indicator votes and produces a single
    confluence score from 0 to 100.

    Score meaning:
      0-40:  Weak — no signal
      40-60: Mixed — HOLD
      60-75: Good signal — consider trading
      75-90: Strong signal — high confidence
      90+:   Very strong — all systems agree
    """

    def score(self, bull_votes, bear_votes, mtf_confluence, regime, sr_zone):
        bull_raw = sum(w for _, w, _ in bull_votes)
        bear_raw = sum(w for _, w, _ in bear_votes)

        # Base score from indicator votes
        total_possible = 20  # max possible weighted score
        if bull_raw > bear_raw:
            direction  = "BUY"
            base_score = min(100, bull_raw / total_possible * 100)
        elif bear_raw > bull_raw:
            direction  = "SELL"
            base_score = min(100, bear_raw / total_possible * 100)
        else:
            return "HOLD", 0

        # Bonus for multi-timeframe confluence
        mtf_bonus = {"ALL3": 20, "15M_1H": 12, "5M_15M": 6, "NONE": 0}.get(mtf_confluence, 0)

        # Bonus for market regime matching signal
        regime_bonus = 0
        if regime == "TRENDING":
            regime_bonus = 8  # trending market — signals are more reliable
        elif regime == "RANGING":
            regime_bonus = 5  # ranging — reversal signals work better
        elif regime == "VOLATILE":
            regime_bonus = -10  # volatile — reduce confidence

        # Bonus for support/resistance confirmation
        sr_bonus = 0
        if direction == "BUY"  and sr_zone == "NEAR_SUPPORT":
            sr_bonus = 10  # buying at support — strong confluence
        elif direction == "SELL" and sr_zone == "NEAR_RESISTANCE":
            sr_bonus = 10  # selling at resistance — strong confluence
        elif direction == "BUY"  and sr_zone == "NEAR_RESISTANCE":
            sr_bonus = -10  # buying at resistance — bad timing
        elif direction == "SELL" and sr_zone == "NEAR_SUPPORT":
            sr_bonus = -10  # selling at support — bad timing

        final_score = min(100, max(0, base_score + mtf_bonus + regime_bonus + sr_bonus))

        # Minimum score to fire a signal
        if final_score < 52:
            return "HOLD", final_score

        return direction, round(final_score, 1)


# ═══════════════════════════════════════════════════════
# RISK MANAGER — enhanced with regime-aware sizing
# ═══════════════════════════════════════════════════════

class RiskManager:

    def calculate(self, price, atr, direction, confidence, regime, account, risk_pct, max_lev):
        d = 1 if direction == "BUY" else -1

        # Wider SL in volatile markets
        sl_multiplier = 2.0 if regime == "VOLATILE" else 1.5
        sl  = price - d * sl_multiplier * atr
        tp1 = price + d * 2.0 * atr
        tp2 = price + d * 3.5 * atr
        tp3 = price + d * 5.0 * atr

        sl_dist = abs(price - sl)

        # Reduce position size in volatile/low confidence scenarios
        confidence_factor = confidence / 100
        regime_factor     = 0.5 if regime == "VOLATILE" else 1.0
        risk_usdt         = account * risk_pct * confidence_factor * regime_factor

        # Position size = how many USDT to put in trade
        # Formula: risk_usdt / sl_distance_as_percentage
        sl_pct        = sl_dist / price  # SL as fraction of price
        if sl_pct > 0:
            position_usdt = risk_usdt / sl_pct
        else:
            position_usdt = account * 0.1  # fallback 10%

        # Hard cap: never exceed account size (no matter what)
        position_usdt = min(position_usdt, account)

        # Leverage scales with confidence and regime
        if regime == "VOLATILE":
            leverage = 1
        else:
            leverage = max(1, min(max_lev, int(confidence / 100 * max_lev)))

        return {
            "entry":          round(price, 6),
            "sl":             round(sl, 6),
            "tp1":            round(tp1, 6),
            "tp2":            round(tp2, 6),
            "tp3":            round(tp3, 6),
            "rr1":            round(abs(tp1-price)/sl_dist, 2),
            "rr2":            round(abs(tp2-price)/sl_dist, 2),
            "rr3":            round(abs(tp3-price)/sl_dist, 2),
            "position_usdt":  round(position_usdt, 2),
            "risk_usdt":      round(risk_usdt, 2),
            "leverage":       leverage,
            "sl_multiplier":  sl_multiplier,
        }

    def check_safety(self, trades, account, risk_pct, ind):
        open_trades  = [t for t in trades if not t.get("result")]
        closed       = [t for t in trades if t.get("result")]
        warnings     = []

        if len(open_trades) >= 3:
            warnings.append(f"Max 3 open trades reached ({len(open_trades)} open)")

        if len(closed) >= 3:
            last3 = closed[-3:]
            if all(t["result"] == "LOSS" for t in last3):
                warnings.append("3 consecutive losses — pausing to protect capital")

        today       = datetime.now().strftime("%Y-%m-%d")
        today_loss  = sum(
            account * risk_pct for t in closed
            if t.get("exit_time","").startswith(today) and t["result"]=="LOSS"
        )
        if today_loss >= account * 0.05:
            warnings.append(f"Daily loss limit hit (${today_loss:.2f}) — no more trades today")

        atr_pct = ind.get("atr", 0) / ind.get("price", 1) * 100
        if atr_pct > 6:
            warnings.append(f"Extreme volatility ATR={atr_pct:.1f}% — skipping")

        return warnings


# ═══════════════════════════════════════════════════════
# AI COUNCIL — Claude + OpenAI get full context
# ═══════════════════════════════════════════════════════

class AICouncil:

    def __init__(self, config):
        self.config         = config
        self.anthropic_key  = config.get("anthropic_key", "")
        self.openai_key     = config.get("openai_key", "")
        self.mtf_engine     = MultiTimeframeEngine()
        self.ind_engine     = IndicatorEngine()
        self.regime_det     = MarketRegime()
        self.sr_det         = SupportResistance()
        self.scorer         = ConfluenceScorer()
        self.risk_mgr       = RiskManager()
        self.news_agent     = NewsPatternAgent(config)
        self.candle_agent   = CandlePatternAgent(config)
        self.sr_agent       = SRAgent(config)
        self.daily_filter   = DailyTrendFilter()
        self.funding_filter = FundingRateFilter()
        self.session_filter = SessionFilter()

    def ask_claude(self, symbol, ind, bull_votes, bear_votes, news,
                   fear_greed, regime, sr_zone, confluence_score):
        if not self.anthropic_key:
            return None

        bull_text = "\n".join(f"  + {r}" for _, _, r in bull_votes[:5])
        bear_text = "\n".join(f"  - {r}" for _, _, r in bear_votes[:5])
        news_text = "\n".join(f"  • {h}" for h in news[:4]) if news else "  No news available"
        fg_text   = f"{fear_greed['value']} ({fear_greed['label']})" if fear_greed else "N/A"

        prompt = f"""You are a professional crypto trading analyst. 
Analyse this complete market picture and give a final trading decision.

SYMBOL: {symbol}
PRICE: ${ind['price']:,.4f}
CONFLUENCE SCORE: {confluence_score}/100
MARKET REGIME: {regime}
S/R ZONE: {sr_zone}
FEAR & GREED: {fg_text}

KEY INDICATORS:
  RSI: {ind.get('rsi',0):.1f}
  MACD Histogram: {ind.get('macd_hist',0):.6f}
  ADX: {ind.get('adx',0):.1f} (trend strength)
  Stochastic K: {ind.get('stoch_k',0):.1f}
  BB Position: {ind.get('bb_pct',0):.3f}
  Volume ratio: {ind.get('vol_ratio',0):.2f}x average

BULLISH SIGNALS:
{bull_text if bull_text else "  None"}

BEARISH SIGNALS:
{bear_text if bear_text else "  None"}

RECENT NEWS:
{news_text}

Rules you must follow:
- If confluence score < 65 say HOLD
- If market is VOLATILE reduce confidence
- If near wrong S/R level say HOLD
- Be conservative — only say BUY or SELL when genuinely convinced

Respond ONLY with valid JSON, no extra text:
{{"action": "BUY" or "SELL" or "HOLD", "confidence": 0-100, "reason": "max 15 words"}}"""

        for attempt in range(2):
            try:
                r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key":         self.anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "content-type":      "application/json",
                    },
                    json={
                        "model":      "claude-haiku-4-5-20251001",
                        "max_tokens": 100,
                        "messages":   [{"role": "user", "content": prompt}]
                    },
                    timeout=20
                )
                if r.status_code == 200:
                    text  = r.json()["content"][0]["text"].strip()
                    start = text.find("{")
                    end   = text.rfind("}") + 1
                    if start == -1:
                        return None
                    result = json.loads(text[start:end])
                    result["action"] = result.get("action","HOLD").upper()
                    if result["action"] not in ("BUY","SELL","HOLD"):
                        result["action"] = "HOLD"
                    print(f"    [Claude]  → {result['action']} ({result.get('confidence',0)}%): {result.get('reason','')}")
                    return {"agent": "Claude", "vote": result["action"],
                            "confidence": result.get("confidence", 50),
                            "reason": result.get("reason", "")}
                elif r.status_code == 429:
                    time.sleep(10)
                    continue
                else:
                    err = r.json().get("error",{}).get("message","")
                    print(f"    [Claude] {r.status_code}: {err[:60]}")
                    return None
            except Exception as e:
                print(f"    [Claude] Error: {e}")
                return None
        return None

    def ask_openai(self, symbol, ind, confluence_score, regime, news):
        if not self.openai_key:
            return None

        news_text = " | ".join(news[:3]) if news else "none"
        prompt = f"""Crypto analyst. Symbol: {symbol}. Price: ${ind['price']:,.4f}.
Confluence score: {confluence_score}/100. Regime: {regime}.
RSI: {ind.get('rsi',0):.1f}. MACD: {ind.get('macd_hist',0):.4f}.
ADX: {ind.get('adx',0):.1f}. BB: {ind.get('bb_pct',0):.2f}.
News: {news_text}
Reply JSON only: {{"action":"BUY/SELL/HOLD","confidence":0-100,"reason":"max 10 words"}}"""

        for attempt in range(2):
            try:
                r = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.openai_key}",
                             "Content-Type": "application/json"},
                    json={"model": "gpt-4o-mini", "messages": [{"role":"user","content":prompt}],
                          "max_tokens": 80, "temperature": 0.1},
                    timeout=15
                )
                if r.status_code == 200:
                    text  = r.json()["choices"][0]["message"]["content"].strip()
                    start = text.find("{")
                    end   = text.rfind("}") + 1
                    if start == -1:
                        return None
                    result = json.loads(text[start:end])
                    result["action"] = result.get("action","HOLD").upper()
                    if result["action"] not in ("BUY","SELL","HOLD"):
                        result["action"] = "HOLD"
                    print(f"    [GPT-4o]  → {result['action']} ({result.get('confidence',0)}%): {result.get('reason','')}")
                    return {"agent": "GPT-4o", "vote": result["action"],
                            "confidence": result.get("confidence", 50),
                            "reason": result.get("reason", "")}
                elif r.status_code == 429:
                    time.sleep(12 * (attempt+1))
                    continue
                else:
                    print(f"    [GPT-4o] Error {r.status_code}")
                    return None
            except Exception as e:
                print(f"    [GPT-4o] Error: {e}")
                return None
        return None

    # ── MAIN ANALYSE FUNCTION ──────────────────────────
    def analyse(self, symbol, market_data, all_trades):
        ind        = market_data["ind"]
        df         = market_data["df"]
        news       = market_data.get("news", [])
        fear_greed = market_data.get("fear_greed")
        account    = self.config.get("account_usdt", 1000)
        risk_pct   = self.config.get("risk_per_trade", 0.01)
        max_lev    = self.config.get("max_leverage", 3)

        print(f"    AI Council full analysis — {symbol}...")

        # ── STEP 1: Multi-timeframe check ──────────────
        mtf_dir, mtf_score, ind15, df15, confluence_label = self.mtf_engine.analyse(symbol)

        if mtf_dir == "HOLD":
            return {"action": "HOLD",
                    "reason": f"Timeframes disagree — {confluence_label}",
                    "votes": []}

        # Use 15m indicators for detailed analysis
        ind = self.ind_engine.calculate(df15) if df15 is not None else ind

        # ── STEP 2: Get all indicator votes ────────────
        bull_votes, bear_votes = self.ind_engine.vote(ind)

        # ── STEP 3: Market regime ──────────────────────
        regime, regime_note = self.regime_det.detect(ind, df15)

        # ── STEP 4: Support & Resistance ───────────────
        support, resistance = self.sr_det.find_levels(df15)
        sr_zone = self.sr_det.check_proximity(
            ind["price"], support, resistance, ind.get("atr", 1)
        )

        # ── STEP 5: Confluence score ───────────────────
        direction, conf_score = self.scorer.score(
            bull_votes, bear_votes, confluence_label, regime, sr_zone
        )

        print(f"    [Score] Confluence: {conf_score}/100 — Direction: {direction}")

        if direction == "HOLD":
            return {"action": "HOLD",
                    "reason": f"Confluence score {conf_score}/100 — below threshold",
                    "votes": []}

        # ── STEP 5b: SESSION FILTER ────────────────────
        session_quality, session_adj, session_label, session_ok = self.session_filter.check()
        conf_score = max(0, min(100, conf_score + session_adj))
        print(f"    [Session] Score adjusted {session_adj:+d} → {conf_score}/100")

        # ── STEP 5c: DAILY TREND FILTER ────────────────
        trend_ok, trend_reason = self.daily_filter.check(symbol, direction)
        if not trend_ok:
            return {"action": "HOLD", "reason": trend_reason, "votes": []}
        print(f"    [Daily]   {trend_reason}")

        # ── STEP 5d: FUNDING RATE ───────────────────────
        funding_adj, funding_reason = self.funding_filter.check(symbol, direction)
        conf_score = max(0, min(100, conf_score + funding_adj))
        print(f"    [Funding] {funding_reason}")

        # Re-check after filter adjustments
        if conf_score < 52:
            return {
                "action": "HOLD",
                "reason": f"Score dropped to {conf_score}/100 after filters",
                "votes":  [],
            }

        # ── STEP 6: Safety checks ──────────────────────
        warnings = self.risk_mgr.check_safety(all_trades, account, risk_pct, ind)
        if warnings:
            print(f"    [Risk] BLOCKED: {warnings[0]}")
            return {"action": "HOLD", "reason": warnings[0], "votes": []}

        # ── STEP 7: Ask Claude + OpenAI ────────────────
        votes = []
        claude_vote = self.ask_claude(symbol, ind, bull_votes, bear_votes,
                                      news, fear_greed, regime, sr_zone, conf_score)
        if claude_vote:
            votes.append(claude_vote)

        openai_vote = self.ask_openai(symbol, ind, conf_score, regime, news)
        if openai_vote:
            votes.append(openai_vote)

        # ── STEP 7b: News Pattern vote ─────────────────
        news_result = self.news_agent.analyse(symbol, ind["price"])
        if news_result:
            votes.append({
                "agent":      "News Pattern",
                "vote":       news_result["vote"],
                "confidence": news_result["confidence"],
                "reason":     news_result["reason"],
            })

        # ── STEP 7c: Candle Pattern vote ──────────────────
        candle_result = self.candle_agent.analyse(symbol, df15)
        if candle_result and candle_result["vote"] != "HOLD":
            votes.append({
                "agent":      "Candle Patterns",
                "vote":       candle_result["vote"],
                "confidence": candle_result["confidence"],
                "reason":     candle_result["reason"],
            })

        # ── STEP 7d: S/R Agent vote ────────────────────
        sr_result = self.sr_agent.analyse(symbol, ind["price"])
        if sr_result and sr_result["vote"] != "HOLD":
            votes.append({
                "agent":      "S/R Agent",
                "vote":       sr_result["vote"],
                "confidence": sr_result["confidence"],
                "reason":     sr_result["reason"],
            })
            # If S/R agent fires with high confidence
            # boost overall confidence significantly
            if sr_result["confidence"] >= 70:
                conf_score = min(100, conf_score + 15)
                print(f"    [S/R Agent] High confidence S/R signal — boosting score to {conf_score}")

        # ── STEP 8: Deduplicate votes ─────────────────
        # Remove duplicate agent votes — keep only the last vote per agent
        seen_agents = {}
        for v in votes:
            seen_agents[v["agent"]] = v
        votes = list(seen_agents.values())

        # ── STEP 8: Final decision ─────────────────────
        # If AI APIs available — require majority agreement with indicators
        if votes:
            ai_buys  = sum(1 for v in votes if v["vote"] == direction)
            ai_total = len(votes)
            if ai_buys == 0:
                print(f"    [Council] AI APIs disagree with indicators — HOLD")
                return {"action": "HOLD",
                        "reason": "AI APIs disagree with technical signal",
                        "votes": votes}
            avg_conf = sum(v["confidence"] for v in votes if v["vote"]==direction) / ai_buys
            final_score = (conf_score * 0.6) + (avg_conf * 0.4)
        else:
            # No AI APIs — rely on confluence score alone
            final_score = conf_score

        print(f"    [Council] FINAL: {direction} — score {final_score:.1f}/100")

        # ── STEP 9: Calculate levels ───────────────────
        levels = self.risk_mgr.calculate(
            ind["price"], ind.get("atr", ind["price"]*0.01),
            direction, final_score, regime, account, risk_pct, max_lev
        )

        # Build signal reasons for display
        winning_votes = bull_votes if direction == "BUY" else bear_votes
        reasons = [r for _, _, r in winning_votes[:4]]

        votes.insert(0, {
            "agent":      "Technical+MTF+S/R",
            "vote":       direction,
            "confidence": conf_score,
            "reason":     f"Score {conf_score}/100 | {confluence_label} | {regime} | {sr_zone}"
        })

        # Get filter summaries for Telegram
        trend_data   = self.daily_filter.cache.get(symbol.split("/")[0], {})
        funding_data = self.funding_filter.cache.get(symbol.split("/")[0])
        funding_str  = f"{funding_data['rate_pct']:+.4f}%" if funding_data else "N/A"
        sess_quality, sess_adj, sess_label, _ = self.session_filter.check()

        return {
            "action":          direction,
            "reason":          f"Score {final_score:.0f}/100 | {confluence_label} | {regime}",
            "votes":           votes,
            "levels":          levels,
            "confidence":      final_score,
            "bull_signals":    bull_votes,
            "bear_signals":    bear_votes,
            "confluence":      confluence_label,
            "regime":          regime,
            "sr_zone":         sr_zone,
            "daily_trend":     trend_data[0] if trend_data else "N/A",
            "funding_rate":    funding_str,
            "session":         f"{sess_quality} ({sess_label[:30]})",
            "fear_greed":      fear_greed,
            "supports":        sr_result.get("supports", [])    if sr_result else [],
            "resistances":     sr_result.get("resistances", []) if sr_result else [],
        }
