"""
candle_pattern_agent.py
═══════════════════════
Real candlestick pattern recognition on real OHLCV data.
No library — patterns calculated directly from candle math.

Each pattern is calculated from real open/high/low/close values.
Every condition is written out explicitly so you can verify it.

BULLISH PATTERNS (vote BUY):
  Hammer, Inverted Hammer, Bullish Engulfing,
  Morning Star, Piercing Line, Three White Soldiers,
  Dragonfly Doji, Bullish Harami

BEARISH PATTERNS (vote SELL):
  Shooting Star, Hanging Man, Bearish Engulfing,
  Evening Star, Dark Cloud Cover, Three Black Crows,
  Gravestone Doji, Bearish Harami

HOW IT VOTES:
  Finds all patterns in last 3 candles
  Counts bullish vs bearish patterns
  If majority agree → votes BUY or SELL
  Confidence based on number of patterns + their strength
"""

import pandas as pd
import numpy as np


class CandlePatternAgent:

    def __init__(self, config):
        self.config = config

    # ──────────────────────────────────────────────────
    # CANDLE MATH HELPERS
    # ──────────────────────────────────────────────────

    def _body(self, o, c):
        """Absolute size of candle body"""
        return abs(c - o)

    def _upper_shadow(self, o, c, h):
        """Upper shadow length"""
        return h - max(o, c)

    def _lower_shadow(self, o, c, l):
        """Lower shadow length"""
        return min(o, c) - l

    def _is_bullish(self, o, c):
        return c > o

    def _is_bearish(self, o, c):
        return c < o

    def _range(self, h, l):
        return h - l

    # ──────────────────────────────────────────────────
    # SINGLE CANDLE PATTERNS
    # ──────────────────────────────────────────────────

    def _hammer(self, o, h, l, c):
        """
        Hammer — bullish reversal after downtrend
        Condition:
          - Small body in upper third of range
          - Lower shadow at least 2x body size
          - Upper shadow very small (less than body)
        """
        body        = self._body(o, c)
        lower_sh    = self._lower_shadow(o, c, l)
        upper_sh    = self._upper_shadow(o, c, h)
        total_range = self._range(h, l)

        if total_range == 0:
            return False

        body_small    = body <= total_range * 0.35
        long_lower    = lower_sh >= body * 2.0
        short_upper   = upper_sh <= body * 0.5
        body_at_top   = min(o, c) >= l + total_range * 0.55

        return body_small and long_lower and short_upper and body_at_top

    def _inverted_hammer(self, o, h, l, c):
        """
        Inverted Hammer — bullish reversal
        Condition:
          - Small body in lower third of range
          - Upper shadow at least 2x body size
          - Lower shadow very small
        """
        body        = self._body(o, c)
        lower_sh    = self._lower_shadow(o, c, l)
        upper_sh    = self._upper_shadow(o, c, h)
        total_range = self._range(h, l)

        if total_range == 0:
            return False

        body_small   = body <= total_range * 0.35
        long_upper   = upper_sh >= body * 2.0
        short_lower  = lower_sh <= body * 0.5
        body_at_bot  = max(o, c) <= l + total_range * 0.45

        return body_small and long_upper and short_lower and body_at_bot

    def _shooting_star(self, o, h, l, c):
        """
        Shooting Star — bearish reversal after uptrend
        Condition:
          - Small body in lower third of range
          - Upper shadow at least 2x body size
          - Lower shadow very small
          - (Same shape as inverted hammer but in uptrend)
        """
        return self._inverted_hammer(o, h, l, c)

    def _hanging_man(self, o, h, l, c):
        """
        Hanging Man — bearish reversal after uptrend
        Same shape as hammer but appears after uptrend
        Context (uptrend) is checked in analyse()
        """
        return self._hammer(o, h, l, c)

    def _doji(self, o, h, l, c):
        """
        Doji — indecision, open ≈ close
        Body is very small relative to total range
        """
        body        = self._body(o, c)
        total_range = self._range(h, l)
        if total_range == 0:
            return False
        return body <= total_range * 0.1

    def _dragonfly_doji(self, o, h, l, c):
        """
        Dragonfly Doji — bullish
        Open ≈ Close ≈ High, long lower shadow
        """
        body        = self._body(o, c)
        upper_sh    = self._upper_shadow(o, c, h)
        lower_sh    = self._lower_shadow(o, c, l)
        total_range = self._range(h, l)

        if total_range == 0:
            return False

        return (
            body     <= total_range * 0.1 and
            upper_sh <= total_range * 0.1 and
            lower_sh >= total_range * 0.7
        )

    def _gravestone_doji(self, o, h, l, c):
        """
        Gravestone Doji — bearish
        Open ≈ Close ≈ Low, long upper shadow
        """
        body        = self._body(o, c)
        upper_sh    = self._upper_shadow(o, c, h)
        lower_sh    = self._lower_shadow(o, c, l)
        total_range = self._range(h, l)

        if total_range == 0:
            return False

        return (
            body     <= total_range * 0.1 and
            lower_sh <= total_range * 0.1 and
            upper_sh >= total_range * 0.7
        )

    # ──────────────────────────────────────────────────
    # TWO CANDLE PATTERNS
    # ──────────────────────────────────────────────────

    def _bullish_engulfing(self, o1, c1, o2, c2):
        """
        Bullish Engulfing — strong bullish reversal
        Candle 1: bearish (red)
        Candle 2: bullish (green), body fully engulfs candle 1 body
        """
        candle1_bearish = self._is_bearish(o1, c1)
        candle2_bullish = self._is_bullish(o2, c2)
        engulfs         = o2 <= c1 and c2 >= o1

        return candle1_bearish and candle2_bullish and engulfs

    def _bearish_engulfing(self, o1, c1, o2, c2):
        """
        Bearish Engulfing — strong bearish reversal
        Candle 1: bullish (green)
        Candle 2: bearish (red), body fully engulfs candle 1 body
        """
        candle1_bullish = self._is_bullish(o1, c1)
        candle2_bearish = self._is_bearish(o2, c2)
        engulfs         = o2 >= c1 and c2 <= o1

        return candle1_bullish and candle2_bearish and engulfs

    def _bullish_harami(self, o1, h1, l1, c1, o2, h2, l2, c2):
        """
        Bullish Harami — bullish reversal
        Candle 1: large bearish candle
        Candle 2: small bullish candle inside candle 1 body
        """
        large_bearish = self._is_bearish(o1, c1) and self._body(o1, c1) > self._range(h1, l1) * 0.5
        small_bullish = self._is_bullish(o2, c2) and self._body(o2, c2) < self._body(o1, c1) * 0.5
        inside        = o2 > c1 and c2 < o1

        return large_bearish and small_bullish and inside

    def _bearish_harami(self, o1, h1, l1, c1, o2, h2, l2, c2):
        """
        Bearish Harami — bearish reversal
        Candle 1: large bullish candle
        Candle 2: small bearish candle inside candle 1 body
        """
        large_bullish = self._is_bullish(o1, c1) and self._body(o1, c1) > self._range(h1, l1) * 0.5
        small_bearish = self._is_bearish(o2, c2) and self._body(o2, c2) < self._body(o1, c1) * 0.5
        inside        = o2 < c1 and c2 > o1

        return large_bullish and small_bearish and inside

    def _piercing_line(self, o1, c1, o2, c2):
        """
        Piercing Line — bullish reversal
        Candle 1: bearish
        Candle 2: bullish, opens below candle 1 low, closes above midpoint of candle 1
        """
        candle1_bearish = self._is_bearish(o1, c1)
        candle2_bullish = self._is_bullish(o2, c2)
        opens_below     = o2 < c1
        closes_above_mid = c2 > (o1 + c1) / 2 and c2 < o1

        return candle1_bearish and candle2_bullish and opens_below and closes_above_mid

    def _dark_cloud_cover(self, o1, c1, o2, c2):
        """
        Dark Cloud Cover — bearish reversal
        Candle 1: bullish
        Candle 2: bearish, opens above candle 1 high, closes below midpoint of candle 1
        """
        candle1_bullish  = self._is_bullish(o1, c1)
        candle2_bearish  = self._is_bearish(o2, c2)
        opens_above      = o2 > c1
        closes_below_mid = c2 < (o1 + c1) / 2 and c2 > o1

        return candle1_bullish and candle2_bearish and opens_above and closes_below_mid

    # ──────────────────────────────────────────────────
    # THREE CANDLE PATTERNS
    # ──────────────────────────────────────────────────

    def _morning_star(self, o1, c1, o2, h2, l2, c2, o3, c3):
        """
        Morning Star — strong bullish reversal
        Candle 1: large bearish
        Candle 2: small body (star) — gaps down
        Candle 3: large bullish, closes above midpoint of candle 1
        """
        large_bearish  = self._is_bearish(o1, c1) and self._body(o1, c1) > 0
        small_star     = self._body(o2, c2) < self._body(o1, c1) * 0.3
        large_bullish  = self._is_bullish(o3, c3) and self._body(o3, c3) > 0
        closes_high    = c3 > (o1 + c1) / 2

        return large_bearish and small_star and large_bullish and closes_high

    def _evening_star(self, o1, c1, o2, h2, l2, c2, o3, c3):
        """
        Evening Star — strong bearish reversal
        Candle 1: large bullish
        Candle 2: small body (star) — gaps up
        Candle 3: large bearish, closes below midpoint of candle 1
        """
        large_bullish  = self._is_bullish(o1, c1) and self._body(o1, c1) > 0
        small_star     = self._body(o2, c2) < self._body(o1, c1) * 0.3
        large_bearish  = self._is_bearish(o3, c3) and self._body(o3, c3) > 0
        closes_low     = c3 < (o1 + c1) / 2

        return large_bullish and small_star and large_bearish and closes_low

    def _three_white_soldiers(self, o1, c1, o2, c2, o3, c3):
        """
        Three White Soldiers — strong bullish continuation
        Three consecutive bullish candles each closing higher
        Each opens within previous candle body
        """
        all_bullish  = self._is_bullish(o1,c1) and self._is_bullish(o2,c2) and self._is_bullish(o3,c3)
        higher_close = c1 < c2 < c3
        inside_open  = o2 > o1 and o2 < c1 and o3 > o2 and o3 < c2

        return all_bullish and higher_close and inside_open

    def _three_black_crows(self, o1, c1, o2, c2, o3, c3):
        """
        Three Black Crows — strong bearish continuation
        Three consecutive bearish candles each closing lower
        Each opens within previous candle body
        """
        all_bearish  = self._is_bearish(o1,c1) and self._is_bearish(o2,c2) and self._is_bearish(o3,c3)
        lower_close  = c1 > c2 > c3
        inside_open  = o2 < o1 and o2 > c1 and o3 < o2 and o3 > c2

        return all_bearish and lower_close and inside_open

    # ──────────────────────────────────────────────────
    # TREND CONTEXT
    # ──────────────────────────────────────────────────

    def _recent_trend(self, df, lookback=10):
        """
        Checks price direction over last N candles.
        Returns: UP, DOWN, or SIDEWAYS
        """
        if len(df) < lookback:
            return "SIDEWAYS"

        recent = df["close"].tail(lookback)
        start  = recent.iloc[0]
        end    = recent.iloc[-1]
        change = (end - start) / start * 100

        if change > 1.5:
            return "UP"
        elif change < -1.5:
            return "DOWN"
        return "SIDEWAYS"

    # ──────────────────────────────────────────────────
    # MAIN ANALYSE FUNCTION
    # ──────────────────────────────────────────────────

    def analyse(self, symbol, df):
        """
        Scans the last 3 candles for all patterns.
        Returns vote with confidence and list of patterns found.
        """
        if df is None or len(df) < 5:
            return None

        try:
            # Get last 3 candles
            c  = df.tail(3)
            o1,h1,l1,c1 = c.iloc[0]["open"], c.iloc[0]["high"], c.iloc[0]["low"],  c.iloc[0]["close"]
            o2,h2,l2,c2 = c.iloc[1]["open"], c.iloc[1]["high"], c.iloc[1]["low"],  c.iloc[1]["close"]
            o3,h3,l3,c3 = c.iloc[2]["open"], c.iloc[2]["high"], c.iloc[2]["low"],  c.iloc[2]["close"]

            trend = self._recent_trend(df)

            bull_patterns = []
            bear_patterns = []

            # ── Single candle patterns on latest candle ──
            if self._hammer(o3, h3, l3, c3) and trend == "DOWN":
                bull_patterns.append(("Hammer", 2))

            if self._inverted_hammer(o3, h3, l3, c3) and trend == "DOWN":
                bull_patterns.append(("Inverted Hammer", 1))

            if self._shooting_star(o3, h3, l3, c3) and trend == "UP":
                bear_patterns.append(("Shooting Star", 2))

            if self._hanging_man(o3, h3, l3, c3) and trend == "UP":
                bear_patterns.append(("Hanging Man", 2))

            if self._dragonfly_doji(o3, h3, l3, c3):
                bull_patterns.append(("Dragonfly Doji", 1))

            if self._gravestone_doji(o3, h3, l3, c3):
                bear_patterns.append(("Gravestone Doji", 1))

            # ── Two candle patterns (candle 2 + 3) ──────
            if self._bullish_engulfing(o2, c2, o3, c3):
                bull_patterns.append(("Bullish Engulfing", 3))

            if self._bearish_engulfing(o2, c2, o3, c3):
                bear_patterns.append(("Bearish Engulfing", 3))

            if self._bullish_harami(o2,h2,l2,c2, o3,h3,l3,c3):
                bull_patterns.append(("Bullish Harami", 2))

            if self._bearish_harami(o2,h2,l2,c2, o3,h3,l3,c3):
                bear_patterns.append(("Bearish Harami", 2))

            if self._piercing_line(o2, c2, o3, c3):
                bull_patterns.append(("Piercing Line", 2))

            if self._dark_cloud_cover(o2, c2, o3, c3):
                bear_patterns.append(("Dark Cloud Cover", 2))

            # ── Three candle patterns ───────────────────
            if self._morning_star(o1,c1, o2,h2,l2,c2, o3,c3):
                bull_patterns.append(("Morning Star", 3))

            if self._evening_star(o1,c1, o2,h2,l2,c2, o3,c3):
                bear_patterns.append(("Evening Star", 3))

            if self._three_white_soldiers(o1,c1, o2,c2, o3,c3):
                bull_patterns.append(("Three White Soldiers", 3))

            if self._three_black_crows(o1,c1, o2,c2, o3,c3):
                bear_patterns.append(("Three Black Crows", 3))

            # ── Score and decide ────────────────────────
            bull_score = sum(w for _, w in bull_patterns)
            bear_score = sum(w for _, w in bear_patterns)

            total_patterns = len(bull_patterns) + len(bear_patterns)

            if total_patterns == 0:
                return {
                    "agent":      "Candle Patterns",
                    "vote":       "HOLD",
                    "confidence": 0,
                    "reason":     "No patterns detected in last 3 candles",
                    "patterns":   [],
                }

            # Confidence based on score and number of patterns
            if bull_score > bear_score:
                direction  = "BUY"
                score      = bull_score
                patterns   = bull_patterns
            elif bear_score > bull_score:
                direction  = "SELL"
                score      = bear_score
                patterns   = bear_patterns
            else:
                return {
                    "agent":      "Candle Patterns",
                    "vote":       "HOLD",
                    "confidence": 30,
                    "reason":     f"Bull/Bear patterns tied — {bull_score} each",
                    "patterns":   bull_patterns + bear_patterns,
                }

            # Confidence formula:
            # 1 pattern weight 1 = 40%
            # 1 pattern weight 3 = 70%
            # Multiple patterns = higher confidence
            confidence = min(90, 35 + (score * 12))

            pattern_names = " + ".join(name for name, _ in patterns)
            trend_note    = f"in {trend} trend"

            print(f"    [Candle] {direction} — {pattern_names} ({trend_note}) — {confidence}% conf")

            return {
                "agent":      "Candle Patterns",
                "vote":       direction,
                "confidence": confidence,
                "reason":     f"{pattern_names} {trend_note}",
                "patterns":   patterns,
            }

        except Exception as e:
            print(f"    [Candle] Error: {e}")
            return None
