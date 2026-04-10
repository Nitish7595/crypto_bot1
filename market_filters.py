"""
market_filters.py
═════════════════
Three filters that prevent bad trades before they happen.

1. DAILY TREND FILTER
   Checks the 1d candle trend
   Only allows BUY in uptrend, SELL in downtrend
   Most important filter — stops trading against the market

2. FUNDING RATE FILTER
   Reads Binance public funding rate (no key needed)
   Extreme positive funding = too many longs = SHORT opportunity
   Extreme negative funding = too many shorts = BUY opportunity

3. SESSION TIMING FILTER
   Blocks signals during low-quality trading hours
   Asian session (00:00-07:00 UTC) = fakeouts, avoid
   London/NY open = highest quality signals
   Weekends = reduced position size
"""

import requests
import pandas as pd
import time
from datetime import datetime, timezone


class DailyTrendFilter:
    """
    Checks the daily (1d) candle trend.
    This is the master trend — all shorter timeframe
    signals must align with it.

    Returns:
      UP       → only allow BUY signals
      DOWN     → only allow SELL signals
      SIDEWAYS → allow both directions
    """

    def __init__(self):
        self.cache      = {}   # cache per coin, refreshed every 4 hours
        self.cache_time = {}

    def get_trend(self, symbol, df_daily=None):
        coin = symbol.split("/")[0]

        # Use cache if fresh (within 4 hours)
        if coin in self.cache_time:
            age_hours = (datetime.now() - self.cache_time[coin]).total_seconds() / 3600
            if age_hours < 4 and coin in self.cache:
                return self.cache[coin]

        try:
            # Use Kraken daily data
            pair_map = {
                "BTC": "XBTUSD",
                "ETH": "ETHUSD",
                "SOL": "SOLUSD",
                "BNB": "BNBUSD",
            }
            pair = pair_map.get(coin, f"{coin}USD")

            r = requests.get(
                "https://api.kraken.com/0/public/OHLC",
                params={"pair": pair, "interval": 1440},  # 1440 min = 1 day
                timeout=15
            )

            if r.status_code == 200:
                data = r.json()
                result = data.get("result", {})
                key = [k for k in result if k != "last"]
                if key:
                    candles = result[key[0]][-30:]  # last 30 days
                    closes  = [float(c[4]) for c in candles]
                    df      = pd.Series(closes)

                    # EMA 7 and EMA 21 on daily closes
                    ema7  = df.ewm(span=7).mean().iloc[-1]
                    ema21 = df.ewm(span=21).mean().iloc[-1]
                    price = closes[-1]

                    # Price change over last 7 days
                    change_7d = (closes[-1] - closes[-8]) / closes[-8] * 100 if len(closes) >= 8 else 0

                    if ema7 > ema21 and price > ema7 and change_7d > -2:
                        trend = "UP"
                    elif ema7 < ema21 and price < ema7 and change_7d < 2:
                        trend = "DOWN"
                    else:
                        trend = "SIDEWAYS"

                    self.cache[coin]      = (trend, ema7, ema21, price, change_7d)
                    self.cache_time[coin] = datetime.now()

                    print(f"    [Daily Trend] {coin}: {trend} | EMA7=${ema7:,.0f} EMA21=${ema21:,.0f} | 7d: {change_7d:+.1f}%")
                    return trend, ema7, ema21, price, change_7d

        except Exception as e:
            print(f"    [Daily Trend] Error: {e}")

        # Fallback — use passed df if available
        if df_daily is not None and len(df_daily) >= 10:
            closes  = df_daily["close"].values
            ema7    = pd.Series(closes).ewm(span=7).mean().iloc[-1]
            ema21   = pd.Series(closes).ewm(span=21).mean().iloc[-1]
            price   = closes[-1]
            change  = (closes[-1] - closes[-8]) / closes[-8] * 100 if len(closes) >= 8 else 0
            trend   = "UP" if ema7 > ema21 else "DOWN" if ema7 < ema21 else "SIDEWAYS"
            return trend, ema7, ema21, price, change

        return "SIDEWAYS", 0, 0, 0, 0

    def check(self, symbol, direction, df_daily=None):
        """
        Returns (allowed, reason)
        allowed = True  → signal can proceed
        allowed = False → signal blocked
        """
        result = self.get_trend(symbol, df_daily)
        trend  = result[0] if isinstance(result, tuple) else result
        change = result[4] if isinstance(result, tuple) and len(result) > 4 else 0

        if trend == "UP" and direction == "SELL":
            return False, f"Daily trend is UP ({change:+.1f}% 7d) — blocking SHORT signal"
        elif trend == "DOWN" and direction == "BUY":
            return False, f"Daily trend is DOWN ({change:+.1f}% 7d) — blocking LONG signal"
        elif trend == "SIDEWAYS":
            return True, f"Daily trend SIDEWAYS — allowing both directions"
        else:
            return True, f"Daily trend {trend} — signal direction matches"


class FundingRateFilter:
    """
    Reads Binance futures funding rate.
    No API key needed — public endpoint.

    Funding rate meaning:
      > +0.1%  = too many longs, market overleveraged
                 → SHORT signal gets confidence boost
                 → BUY signal gets penalty
      < -0.1%  = too many shorts, market overleveraged
                 → BUY signal gets confidence boost
                 → SHORT signal gets penalty
      Between  = neutral, no adjustment
    """

    def __init__(self):
        self.cache      = {}
        self.cache_time = {}

    def get_funding_rate(self, symbol):
        coin = symbol.split("/")[0]

        # Cache for 30 minutes (funding updates every 8 hours)
        if coin in self.cache_time:
            age_min = (datetime.now() - self.cache_time[coin]).total_seconds() / 60
            if age_min < 30 and coin in self.cache:
                return self.cache[coin]

        try:
            # Binance public funding rate endpoint
            binance_symbol = f"{coin}USDT"
            r = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": binance_symbol},
                timeout=10
            )

            if r.status_code == 200:
                data          = r.json()
                funding_rate  = float(data.get("lastFundingRate", 0))
                mark_price    = float(data.get("markPrice", 0))
                next_funding  = data.get("nextFundingTime", 0)

                result = {
                    "rate":         funding_rate,
                    "rate_pct":     funding_rate * 100,
                    "mark_price":   mark_price,
                    "next_funding": next_funding,
                    "symbol":       symbol,
                }
                self.cache[coin]      = result
                self.cache_time[coin] = datetime.now()
                return result

        except Exception as e:
            print(f"    [Funding] Error fetching rate: {e}")

        return None

    def check(self, symbol, direction):
        """
        Returns (score_adjustment, reason)
        score_adjustment: positive = boost, negative = penalty
        """
        data = self.get_funding_rate(symbol)
        if not data:
            return 0, "Funding rate unavailable — no adjustment"

        rate_pct = data["rate_pct"]

        print(f"    [Funding] {symbol}: {rate_pct:+.4f}% per 8h")

        # Extreme funding — strong signal
        if rate_pct > 0.1 and direction == "SELL":
            return +15, f"Funding {rate_pct:+.4f}% — overleveraged longs, SHORT confirmed"
        elif rate_pct > 0.1 and direction == "BUY":
            return -10, f"Funding {rate_pct:+.4f}% — overleveraged longs, risky to BUY"
        elif rate_pct < -0.1 and direction == "BUY":
            return +15, f"Funding {rate_pct:+.4f}% — overleveraged shorts, BUY confirmed"
        elif rate_pct < -0.1 and direction == "SELL":
            return -10, f"Funding {rate_pct:+.4f}% — overleveraged shorts, risky to SELL"

        # Moderate funding — mild signal
        elif rate_pct > 0.05 and direction == "SELL":
            return +5, f"Funding {rate_pct:+.4f}% — leaning short"
        elif rate_pct < -0.05 and direction == "BUY":
            return +5, f"Funding {rate_pct:+.4f}% — leaning long"

        return 0, f"Funding {rate_pct:+.4f}% — neutral, no adjustment"


class SessionFilter:
    """
    Filters signals based on trading session quality.

    Session schedule (UTC):
      00:00 - 07:00  Asian session    — low volume, many fakeouts
      07:00 - 09:00  Pre-London       — increasing volume
      08:00 - 12:00  London session   — high quality signals
      12:00 - 17:00  London + NY      — highest volume, best signals
      17:00 - 21:00  NY session       — good signals
      21:00 - 00:00  NY close/Asia    — decreasing volume
      Sat/Sun        Weekend          — low liquidity

    Returns:
      quality: PRIME / GOOD / POOR / AVOID
      adjustment: score modifier
    """

    SESSIONS = {
        # hour (UTC): (quality, score_adj, label)
        0:  ("AVOID", -20, "Asian session — high fakeout risk"),
        1:  ("AVOID", -20, "Asian session — high fakeout risk"),
        2:  ("AVOID", -20, "Asian session — high fakeout risk"),
        3:  ("AVOID", -20, "Asian session — high fakeout risk"),
        4:  ("AVOID", -15, "Asian session — low volume"),
        5:  ("AVOID", -15, "Asian session — low volume"),
        6:  ("AVOID", -10, "Late Asian — volume picking up"),
        7:  ("GOOD",   +0, "Pre-London open"),
        8:  ("PRIME", +15, "London open — high quality"),
        9:  ("PRIME", +15, "London session — strong"),
        10: ("PRIME", +10, "London session"),
        11: ("PRIME", +10, "London session"),
        12: ("PRIME", +15, "London + NY overlap — best time"),
        13: ("PRIME", +15, "NY open — highest volume"),
        14: ("PRIME", +15, "NY session — peak volume"),
        15: ("PRIME", +10, "NY session"),
        16: ("GOOD",  +5,  "NY session"),
        17: ("GOOD",  +5,  "NY session"),
        18: ("GOOD",  +0,  "NY mid session"),
        19: ("GOOD",  +0,  "NY session"),
        20: ("GOOD",  -5,  "NY closing"),
        21: ("POOR",  -10, "NY close — volume dropping"),
        22: ("POOR",  -10, "After NY — low volume"),
        23: ("AVOID", -15, "Pre-Asia — low liquidity"),
    }

    def check(self, direction=None):
        """
        Returns (quality, score_adjustment, reason, allowed)
        """
        now     = datetime.now(timezone.utc)
        hour    = now.hour
        weekday = now.weekday()   # 0=Mon 6=Sun

        is_weekend = weekday >= 5

        quality, adj, label = self.SESSIONS.get(hour, ("POOR", -5, "Unknown session"))

        if is_weekend:
            quality = "POOR"
            adj     = min(adj, -15)
            label   = f"Weekend — {label} (reduced liquidity)"

        # Never fully block — just adjust score
        # User can still trade weekends/Asian if they want
        # but confidence score will reflect lower quality
        allowed = quality != "AVOID" or adj > -20

        print(f"    [Session] {now.strftime('%H:%M')} UTC — {quality}: {label} ({adj:+d} score)")

        return quality, adj, label, allowed
