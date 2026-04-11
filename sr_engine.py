"""
sr_engine.py
════════════
Professional Support & Resistance Engine

WHAT IT DOES:
  1. Fetches 1d, 1h, 30m, 15m candles from Kraken
  2. Finds key S/R levels on each timeframe
  3. Checks if current price is AT a key level
  4. Checks what PATTERN formed at that level
  5. Scores the setup based on:
     - How many timeframes confirm the level
     - What pattern formed
     - How many times price respected that level before
     - How strong the bounce/rejection was

WHY THIS WORKS:
  Price always remembers where it was rejected before
  Big players place orders at the same levels every time
  When price returns to that level, they defend it again
  Candle patterns show you HOW price is reacting to the level
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime


# ═══════════════════════════════════════════════════════
# LEVEL FINDER
# Finds significant S/R levels from candle data
# ═══════════════════════════════════════════════════════

class LevelFinder:
    """
    Finds support and resistance levels using:
    1. Swing highs and lows (most reliable)
    2. High volume zones
    3. Previous closes that acted as S/R
    """

    def find_swing_levels(self, df, lookback=5, min_touches=2):
        """
        Finds price levels where price reversed multiple times.
        A level is significant if price touched it at least min_touches times.

        Swing high = candle high higher than N candles on each side
        Swing low  = candle low  lower  than N candles on each side
        """
        highs     = df["high"].values
        lows      = df["low"].values
        closes    = df["close"].values
        price     = closes[-1]

        swing_highs = []
        swing_lows  = []

        for i in range(lookback, len(df) - lookback):
            # Swing high — higher than lookback candles on both sides
            if all(highs[i] >= highs[i-j] for j in range(1, lookback+1)) and \
               all(highs[i] >= highs[i+j] for j in range(1, lookback+1)):
                swing_highs.append(highs[i])

            # Swing low — lower than lookback candles on both sides
            if all(lows[i] <= lows[i-j] for j in range(1, lookback+1)) and \
               all(lows[i] <= lows[i+j] for j in range(1, lookback+1)):
                swing_lows.append(lows[i])

        # Cluster nearby levels together (within 0.3% of each other)
        resistance = self._cluster_levels(swing_highs, price, tolerance=0.003)
        support    = self._cluster_levels(swing_lows,  price, tolerance=0.003)

        # Count touches for each level
        resistance = self._count_touches(resistance, highs, lows, price)
        support    = self._count_touches(support,    highs, lows, price)

        # Filter: only levels touched at least min_touches times
        resistance = [l for l in resistance if l["touches"] >= min_touches]
        support    = [l for l in support    if l["touches"] >= min_touches]

        # Sort by proximity to current price
        resistance = sorted(resistance, key=lambda x: x["level"] - price)
        support    = sorted(support,    key=lambda x: price - x["level"])

        return support, resistance

    def _cluster_levels(self, levels, price, tolerance=0.003):
        """Groups nearby price levels into one cluster."""
        if not levels:
            return []

        levels  = sorted(levels)
        clusters = []
        current  = [levels[0]]

        for level in levels[1:]:
            if abs(level - current[-1]) / price < tolerance:
                current.append(level)
            else:
                clusters.append(sum(current) / len(current))
                current = [level]
        clusters.append(sum(current) / len(current))

        return [{"level": round(c, 6), "touches": 0} for c in clusters]

    def _count_touches(self, levels, highs, lows, price, zone=0.005):
        """Counts how many times price touched each level."""
        result = []
        for lvl in levels:
            l       = lvl["level"]
            zone_hi = l * (1 + zone)
            zone_lo = l * (1 - zone)
            touches = sum(
                1 for h, lo in zip(highs, lows)
                if lo <= zone_hi and h >= zone_lo
            )
            result.append({"level": l, "touches": touches})
        return result


# ═══════════════════════════════════════════════════════
# MULTI-TIMEFRAME S/R ENGINE
# Fetches 4 timeframes and finds confluent levels
# ═══════════════════════════════════════════════════════

class MultiTimeframeSR:

    TIMEFRAMES = {
        "1d":  {"interval": 1440, "label": "Daily",   "weight": 4, "candles": 60},
        "1h":  {"interval": 60,   "label": "1 Hour",  "weight": 3, "candles": 100},
        "30m": {"interval": 30,   "label": "30 Min",  "weight": 2, "candles": 100},
        "15m": {"interval": 15,   "label": "15 Min",  "weight": 1, "candles": 100},
    }

    COIN_MAP = {
        "BTC/USDT": "XBTUSD",
        "ETH/USDT": "ETHUSD",
        "SOL/USDT": "SOLUSD",
        "BNB/USDT": "BNBUSD",
    }

    def __init__(self):
        self.finder = LevelFinder()
        self.cache  = {}

    def _fetch_kraken(self, pair, interval, candles):
        r = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval},
            timeout=15
        )
        if r.status_code != 200:
            raise ValueError(f"Kraken HTTP {r.status_code}")
        data = r.json()
        if data.get("error"):
            raise ValueError(f"Kraken: {data['error']}")
        result  = data.get("result", {})
        key     = [k for k in result if k != "last"][0]
        raw     = result[key][-candles:]
        df      = pd.DataFrame(raw, columns=[
            "time","open","high","low","close","vwap","volume","count"
        ])
        df["ts"] = pd.to_datetime(df["time"].astype(int), unit="s")
        df = df.set_index("ts")
        df = df[["open","high","low","close","volume"]].astype(float)
        return df

    def get_all_levels(self, symbol):
        """
        Fetches S/R levels from all 4 timeframes.
        Returns dict with levels per timeframe.
        """
        pair    = self.COIN_MAP.get(symbol, f"{symbol.split('/')[0]}USD")
        all_tf  = {}

        for tf, config in self.TIMEFRAMES.items():
            try:
                df = self._fetch_kraken(pair, config["interval"], config["candles"])
                support, resistance = self.finder.find_swing_levels(
                    df,
                    lookback    = 5 if tf in ("15m","30m") else 3,
                    min_touches = 2
                )
                all_tf[tf] = {
                    "df":         df,
                    "support":    support[:5],     # top 5 nearest
                    "resistance": resistance[:5],  # top 5 nearest
                    "weight":     config["weight"],
                    "label":      config["label"],
                    "price":      df["close"].iloc[-1],
                }
            except Exception as e:
                print(f"    [S/R] {tf} fetch error: {e}")
                all_tf[tf] = None

        return all_tf

    def find_confluent_levels(self, symbol, current_price):
        """
        Finds S/R levels confirmed by multiple timeframes.
        A level is more significant if multiple timeframes see it.

        Returns:
          key_supports    - list of support levels with scores
          key_resistances - list of resistance levels with scores
          price_location  - where price is relative to levels
        """
        all_tf = self.get_all_levels(symbol)
        zone   = current_price * 0.005   # 0.5% zone for matching levels

        # Collect all levels with their timeframe weights
        all_supports    = []
        all_resistances = []

        for tf, data in all_tf.items():
            if data is None:
                continue
            weight = data["weight"]

            for s in data["support"]:
                all_supports.append({
                    "level":      s["level"],
                    "touches":    s["touches"],
                    "timeframe":  tf,
                    "weight":     weight,
                    "label":      data["label"],
                })

            for r in data["resistance"]:
                all_resistances.append({
                    "level":      r["level"],
                    "touches":    r["touches"],
                    "timeframe":  tf,
                    "weight":     weight,
                    "label":      data["label"],
                })

        # Find confluent support levels
        key_supports    = self._find_confluence(all_supports,    zone)
        key_resistances = self._find_confluence(all_resistances, zone)

        # Filter to only relevant levels
        key_supports    = [l for l in key_supports    if l["level"] < current_price]
        key_resistances = [l for l in key_resistances if l["level"] > current_price]

        # Sort by proximity
        key_supports    = sorted(key_supports,    key=lambda x: current_price - x["level"])[:5]
        key_resistances = sorted(key_resistances, key=lambda x: x["level"] - current_price)[:5]

        # Determine where price is
        at_support    = any(abs(current_price - l["level"]) <= zone * 2 for l in key_supports)
        at_resistance = any(abs(current_price - l["level"]) <= zone * 2 for l in key_resistances)

        if at_support:
            location = "AT_SUPPORT"
        elif at_resistance:
            location = "AT_RESISTANCE"
        else:
            location = "IN_RANGE"

        return key_supports, key_resistances, location, all_tf

    def _find_confluence(self, levels, zone):
        """
        Groups levels within zone of each other.
        Levels confirmed by more timeframes get higher scores.
        """
        if not levels:
            return []

        sorted_levels = sorted(levels, key=lambda x: x["level"])
        clusters      = []
        processed     = set()

        for i, lvl in enumerate(sorted_levels):
            if i in processed:
                continue

            cluster_levels  = [lvl]
            cluster_indices = {i}

            for j, other in enumerate(sorted_levels):
                if j != i and j not in processed:
                    if abs(lvl["level"] - other["level"]) <= zone:
                        cluster_levels.append(other)
                        cluster_indices.add(j)

            processed.update(cluster_indices)

            # Score = sum of timeframe weights × touches
            score       = sum(l["weight"] * min(l["touches"], 5) for l in cluster_levels)
            avg_level   = sum(l["level"] for l in cluster_levels) / len(cluster_levels)
            timeframes  = list(set(l["timeframe"] for l in cluster_levels))
            max_touches = max(l["touches"] for l in cluster_levels)

            clusters.append({
                "level":      round(avg_level, 6),
                "score":      score,
                "timeframes": timeframes,
                "touches":    max_touches,
                "tf_count":   len(timeframes),
                "confirmed_by": " + ".join(sorted(timeframes, key=lambda x: ["1d","1h","30m","15m"].index(x) if x in ["1d","1h","30m","15m"] else 99)),
            })

        return sorted(clusters, key=lambda x: -x["score"])


# ═══════════════════════════════════════════════════════
# PATTERN AT LEVEL DETECTOR
# Checks what candle pattern formed AT the S/R level
# ═══════════════════════════════════════════════════════

class PatternAtLevel:
    """
    The most important part of the strategy.
    Checks if a significant candle pattern formed
    exactly AT a key S/R level.

    Pattern + Level = high probability trade
    """

    def check(self, df_15m, support_levels, resistance_levels, current_price):
        """
        Looks at last 3 candles of 15m chart.
        Checks if any pattern formed at a key level.
        Returns signal with full explanation.
        """
        if df_15m is None or len(df_15m) < 5:
            return None

        c3 = df_15m.iloc[-1]   # latest candle
        c2 = df_15m.iloc[-2]   # previous
        c1 = df_15m.iloc[-3]   # two back

        o3,h3,l3,cl3 = c3["open"], c3["high"], c3["low"], c3["close"]
        o2,h2,l2,cl2 = c2["open"], c2["high"], c2["low"], c2["close"]
        o1,h1,l1,cl1 = c1["open"], c1["high"], c1["low"], c1["close"]

        zone = current_price * 0.004   # 0.4% touch zone

        signals = []

        # ── CHECK AT SUPPORT LEVELS ────────────────────────
        for sup in support_levels:
            level = sup["level"]
            dist  = abs(current_price - level)

            if dist > zone * 3:
                continue

            score      = sup["score"]
            tf_count   = sup["tf_count"]
            confirmed  = sup["confirmed_by"]
            touches    = sup["touches"]

            # Check bullish patterns at support
            patterns_found = []

            # 1. Price touching support (wick into support zone)
            if l3 <= level * 1.002 and cl3 > level:
                patterns_found.append(("Support touch + hold", 2))

            # 2. Hammer at support
            body3     = abs(cl3 - o3)
            lower_sh3 = min(o3, cl3) - l3
            upper_sh3 = h3 - max(o3, cl3)
            total3    = h3 - l3
            if total3 > 0 and lower_sh3 >= body3 * 2 and upper_sh3 <= body3 and l3 <= level * 1.003:
                patterns_found.append(("Hammer at support", 3))

            # 3. Bullish engulfing at support
            if cl2 < o2 and cl3 > o3 and o3 <= cl2 and cl3 >= o2 and l2 <= level * 1.005:
                patterns_found.append(("Bullish Engulfing at support", 4))

            # 4. Dragonfly doji at support
            if total3 > 0 and body3 <= total3 * 0.1 and lower_sh3 >= total3 * 0.7 and l3 <= level * 1.003:
                patterns_found.append(("Dragonfly Doji at support", 3))

            # 5. Morning star at support
            body1  = abs(cl1 - o1)
            body2  = abs(cl2 - o2)
            if cl1 < o1 and body2 < body1 * 0.3 and cl3 > o3 and l2 <= level * 1.005:
                patterns_found.append(("Morning Star at support", 4))

            # 6. Three bounces — price tested this level 3+ times
            if touches >= 3 and current_price <= level * 1.01:
                patterns_found.append((f"Triple+ tested support ({touches}x proven)", 3))

            if patterns_found:
                pattern_score = sum(w for _, w in patterns_found)
                # Multiply by S/R level strength
                total_score = pattern_score * min(score, 4)
                tf_bonus    = tf_count * 10   # +10 per confirming timeframe

                signals.append({
                    "direction":   "BUY",
                    "level":       level,
                    "level_type":  "SUPPORT",
                    "patterns":    patterns_found,
                    "confirmed_by": confirmed,
                    "tf_count":    tf_count,
                    "touches":     touches,
                    "score":       total_score,
                    "confidence":  min(90, 40 + tf_bonus + pattern_score * 5),
                    "reason":      f"{' + '.join(p for p,_ in patterns_found)} at {confirmed} support ${level:,.4f} ({touches} touches)",
                })

        # ── CHECK AT RESISTANCE LEVELS ─────────────────────
        for res in resistance_levels:
            level = res["level"]
            dist  = abs(current_price - level)

            if dist > zone * 3:
                continue

            score     = res["score"]
            tf_count  = res["tf_count"]
            confirmed = res["confirmed_by"]
            touches   = res["touches"]

            patterns_found = []

            # 1. Price touching resistance (wick into resistance zone)
            if h3 >= level * 0.998 and cl3 < level:
                patterns_found.append(("Resistance touch + reject", 2))

            # 2. Shooting star at resistance
            body3     = abs(cl3 - o3)
            lower_sh3 = min(o3, cl3) - l3
            upper_sh3 = h3 - max(o3, cl3)
            total3    = h3 - l3
            if total3 > 0 and upper_sh3 >= body3 * 2 and lower_sh3 <= body3 and h3 >= level * 0.997:
                patterns_found.append(("Shooting Star at resistance", 3))

            # 3. Bearish engulfing at resistance
            if cl2 > o2 and cl3 < o3 and o3 >= cl2 and cl3 <= o2 and h2 >= level * 0.995:
                patterns_found.append(("Bearish Engulfing at resistance", 4))

            # 4. Gravestone doji at resistance
            if total3 > 0 and body3 <= total3 * 0.1 and upper_sh3 >= total3 * 0.7 and h3 >= level * 0.997:
                patterns_found.append(("Gravestone Doji at resistance", 3))

            # 5. Evening star at resistance
            body1 = abs(cl1 - o1)
            body2 = abs(cl2 - o2)
            if cl1 > o1 and body2 < body1 * 0.3 and cl3 < o3 and h2 >= level * 0.995:
                patterns_found.append(("Evening Star at resistance", 4))

            # 6. Multiple rejections
            if touches >= 3 and current_price >= level * 0.99:
                patterns_found.append((f"Triple+ tested resistance ({touches}x proven)", 3))

            if patterns_found:
                pattern_score = sum(w for _, w in patterns_found)
                total_score   = pattern_score * min(score, 4)
                tf_bonus      = tf_count * 10

                signals.append({
                    "direction":   "SELL",
                    "level":       level,
                    "level_type":  "RESISTANCE",
                    "patterns":    patterns_found,
                    "confirmed_by": confirmed,
                    "tf_count":    tf_count,
                    "touches":     touches,
                    "score":       total_score,
                    "confidence":  min(90, 40 + tf_bonus + pattern_score * 5),
                    "reason":      f"{' + '.join(p for p,_ in patterns_found)} at {confirmed} resistance ${level:,.4f} ({touches} touches)",
                })

        if not signals:
            return None

        # Return highest scoring signal
        best = sorted(signals, key=lambda x: -x["score"])[0]
        return best


# ═══════════════════════════════════════════════════════
# MAIN SR AGENT — called by ai_council
# ═══════════════════════════════════════════════════════

class SRAgent:
    """
    Main entry point.
    Combines multi-timeframe S/R with pattern detection.
    Returns a vote for ai_council.
    """

    def __init__(self, config):
        self.config  = config
        self.mtf_sr  = MultiTimeframeSR()
        self.pattern = PatternAtLevel()

    def analyse(self, symbol, current_price):
        print(f"    [S/R Agent] Analysing {symbol} at ${current_price:,.4f}...")

        try:
            # Find all S/R levels across 4 timeframes
            supports, resistances, location, all_tf = \
                self.mtf_sr.find_confluent_levels(symbol, current_price)

            # Print key levels
            print(f"    [S/R Agent] Location: {location}")
            if supports:
                nearest_sup = supports[0]
                dist_pct    = (current_price - nearest_sup["level"]) / current_price * 100
                print(f"    [S/R Agent] Nearest support : ${nearest_sup['level']:,.4f} "
                      f"({dist_pct:.2f}% below) — {nearest_sup['confirmed_by']} — {nearest_sup['touches']} touches")
            if resistances:
                nearest_res = resistances[0]
                dist_pct    = (nearest_res["level"] - current_price) / current_price * 100
                print(f"    [S/R Agent] Nearest resist  : ${nearest_res['level']:,.4f} "
                      f"({dist_pct:.2f}% above) — {nearest_res['confirmed_by']} — {nearest_res['touches']} touches")

            # Get 15m df for pattern detection
            df_15m = all_tf.get("15m", {})
            df_15m = df_15m.get("df") if df_15m else None

            # Check for patterns at S/R levels
            signal = self.pattern.check(
                df_15m, supports, resistances, current_price
            )

            if not signal:
                # No pattern at level — still return location info
                return {
                    "agent":      "S/R Agent",
                    "vote":       "HOLD",
                    "confidence": 0,
                    "reason":     f"Price {location.replace('_',' ')} — no pattern at key level",
                    "location":   location,
                    "supports":   supports[:3],
                    "resistances": resistances[:3],
                }

            direction  = signal["direction"]
            confidence = signal["confidence"]

            print(f"    [S/R Agent] → {direction} ({confidence}%) — {signal['reason'][:60]}")

            return {
                "agent":       "S/R Agent",
                "vote":        direction,
                "confidence":  confidence,
                "reason":      signal["reason"],
                "location":    location,
                "level":       signal["level"],
                "level_type":  signal["level_type"],
                "tf_count":    signal["tf_count"],
                "confirmed_by": signal["confirmed_by"],
                "patterns":    signal["patterns"],
                "supports":    supports[:3],
                "resistances": resistances[:3],
            }

        except Exception as e:
            print(f"    [S/R Agent] Error: {e}")
            return None
