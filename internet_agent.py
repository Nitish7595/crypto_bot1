"""
internet_agent.py
─────────────────
NOTE: Using KuCoin instead of Binance.
Reason: Railway servers are in USA — Binance blocks USA IPs (error 451)
KuCoin works from any location — same real market prices.
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange


class InternetAgent:

    def __init__(self, config):
        self.config = config
        # Alpha Vantage — free crypto OHLCV API
        # 500 requests/day free, no geo restrictions
        # Get free key at: alphavantage.co/support/#api-key
        # Add as ALPHA_VANTAGE_KEY in Railway Variables
        self.av_key  = config.get("alpha_vantage_key", "")
        self.av_base = "https://www.alphavantage.co/query"

        # CoinGecko as fallback (confirmed working)
        self.coin_map = {
            "BTC/USDT": {"cg": "bitcoin",      "av": "BTC"},
            "ETH/USDT": {"cg": "ethereum",     "av": "ETH"},
            "SOL/USDT": {"cg": "solana",       "av": "SOL"},
            "BNB/USDT": {"cg": "binancecoin",  "av": "BNB"},
        }
        self.exchange = None

    def get_candles(self, symbol, timeframe, limit=200):
        """
        Fetches OHLCV candles.
        1. Alpha Vantage (500 req/day free, full OHLCV)
        2. CoinGecko OHLC (confirmed working, fallback)
        """
        # Try Alpha Vantage first if key is set
        if self.av_key:
            try:
                df = self._candles_alphavantage(symbol, timeframe, limit)
                if df is not None and len(df) >= 50:
                    return df
            except Exception as e:
                print(f"    [Internet] Alpha Vantage failed: {str(e)[:60]} — trying CoinGecko")

        # Fall back to CoinGecko
        try:
            df = self._candles_coingecko(symbol, timeframe, limit)
            if df is not None and len(df) >= 50:
                return df
        except Exception as e:
            print(f"    [Internet] CoinGecko OHLC failed: {str(e)[:60]}")

        raise ConnectionError(f"All price sources failed for {symbol}")

    def _candles_alphavantage(self, symbol, timeframe, limit):
        """
        Alpha Vantage crypto OHLCV API.
        500 requests/day free. No geo restrictions.
        Get key at: alphavantage.co/support/#api-key
        """
        coins = self.coin_map.get(symbol, {})
        coin  = coins.get("av", symbol.split("/")[0])

        # Alpha Vantage function names
        tf_map = {
            "1m":  ("CRYPTO_INTRADAY", "1min"),
            "5m":  ("CRYPTO_INTRADAY", "5min"),
            "15m": ("CRYPTO_INTRADAY", "15min"),
            "30m": ("CRYPTO_INTRADAY", "30min"),
            "1h":  ("CRYPTO_INTRADAY", "60min"),
            "1d":  ("DIGITAL_CURRENCY_DAILY", None),
        }

        if timeframe not in tf_map:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        func, interval = tf_map[timeframe]

        params = {
            "function":   func,
            "symbol":     coin,
            "market":     "USD",
            "apikey":     self.av_key,
            "outputsize": "full",
        }
        if interval:
            params["interval"] = interval

        r = requests.get(self.av_base, params=params, timeout=20)
        if r.status_code != 200:
            raise ValueError(f"Alpha Vantage HTTP {r.status_code}")

        data = r.json()

        # Check for error or rate limit
        if "Note" in data:
            raise ValueError("Alpha Vantage rate limit — 5 requests/min, 500/day")
        if "Error Message" in data:
            raise ValueError(f"Alpha Vantage error: {data['Error Message'][:60]}")
        if "Information" in data:
            raise ValueError("Alpha Vantage: " + data["Information"][:80])

        # Find the time series key
        ts_key = [k for k in data if "Time Series" in k]
        if not ts_key:
            raise ValueError("No time series in Alpha Vantage response")

        ts = data[ts_key[0]]
        rows = []
        for ts_str, vals in ts.items():
            try:
                # AV keys vary: "1. open", "1a. open (USD)", etc
                o = float(next(v for k,v in vals.items() if "open"   in k.lower()))
                h = float(next(v for k,v in vals.items() if "high"   in k.lower()))
                l = float(next(v for k,v in vals.items() if "low"    in k.lower()))
                c = float(next(v for k,v in vals.items() if "close"  in k.lower()))
                v = float(next((v for k,v in vals.items() if "volume" in k.lower()), 0))
                rows.append({"ts": pd.Timestamp(ts_str), "open": o, "high": h, "low": l, "close": c, "volume": v})
            except Exception:
                continue

        if not rows:
            raise ValueError("Could not parse Alpha Vantage candles")

        df = pd.DataFrame(rows).set_index("ts").sort_index()
        df = df.tail(limit)
        print(f"    [Internet] Alpha Vantage: {len(df)} {timeframe} candles for {symbol}")
        return df

    def _candles_coingecko(self, symbol, timeframe, limit):
        """CoinGecko OHLC — confirmed working on Railway."""
        coins   = self.coin_map.get(symbol, {})
        cg_id   = coins.get("cg")
        if not cg_id:
            raise ValueError(f"No CoinGecko mapping for {symbol}")

        # CoinGecko days → candle size:
        # days=1  → 30min candles
        # days=7+ → 4h candles
        # days=90+→ daily candles
        # We need ~200 candles so:
        # For 15m/5m → use days=1 (30min, ~48 candles) — fewer but works
        # For 1h     → use days=14 (4h, ~84 candles)
        # For 4h     → use days=30 (4h, ~180 candles)
        tf_days = {
            "5m": 1, "15m": 1, "30m": 1,
            "1h": 14, "4h": 30, "1d": 90,
        }
        days = tf_days.get(timeframe, 1)

        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc",
            params={"vs_currency": "usd", "days": days},
            timeout=15
        )
        if r.status_code != 200:
            raise ValueError(f"CoinGecko HTTP {r.status_code}")

        raw = r.json()
        if not raw or len(raw) < 10:
            raise ValueError(f"Only {len(raw)} candles from CoinGecko")

        # CoinGecko format: [timestamp_ms, open, high, low, close]
        df = pd.DataFrame(raw, columns=["ts","open","high","low","close"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("ts")
        df["volume"] = 0.0   # CoinGecko OHLC has no volume — use 0
        df = df[["open","high","low","close","volume"]].astype(float)
        df = df.tail(limit)
        print(f"    [Internet] CoinGecko: {len(df)} candles for {symbol} (no volume data)")
        return df

    def calculate_indicators(self, df):
        c = df["close"]
        h = df["high"]
        l = df["low"]
        rsi       = RSIIndicator(close=c, window=14).rsi()
        macd_obj  = MACD(close=c, window_slow=26, window_fast=12, window_sign=9)
        macd_hist = macd_obj.macd_diff()
        ema50     = EMAIndicator(close=c, window=50).ema_indicator()
        ema200    = EMAIndicator(close=c, window=200).ema_indicator()
        bb        = BollingerBands(close=c, window=20, window_dev=2)
        bb_pct    = bb.bollinger_pband()
        atr       = AverageTrueRange(high=h, low=l, close=c, window=14).average_true_range()
        vol_avg   = df["volume"].rolling(20).mean()
        vol_ratio = df["volume"].iloc[-1] / vol_avg.iloc[-1]
        return {
            "price":          c.iloc[-1],
            "rsi":            rsi.iloc[-1],
            "rsi_prev":       rsi.iloc[-2],
            "macd_hist":      macd_hist.iloc[-1],
            "macd_hist_prev": macd_hist.iloc[-2],
            "ema50":          ema50.iloc[-1],
            "ema200":         ema200.iloc[-1],
            "bb_pct":         bb_pct.iloc[-1],
            "atr":            atr.iloc[-1],
            "vol_ratio":      vol_ratio,
        }

    def get_fear_greed(self):
        try:
            r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
            if r.status_code == 200:
                data = r.json()["data"][0]
                return {"value": int(data["value"]), "label": data["value_classification"]}
            return None
        except Exception as e:
            print(f"    [Internet] Fear/Greed error: {e}")
            return None

    def get_coingecko_data(self, coin):
        coin_ids = {"BTC":"bitcoin","ETH":"ethereum","SOL":"solana","BNB":"binancecoin"}
        coin_id  = coin_ids.get(coin)
        if not coin_id:
            return None
        try:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={"localization":"false","tickers":"false","community_data":"false"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                md   = data.get("market_data", {})
                return {
                    "price_change_24h": md.get("price_change_percentage_24h", 0),
                    "market_cap_rank":  data.get("market_cap_rank", 0),
                }
            return None
        except Exception as e:
            print(f"    [Internet] CoinGecko error: {e}")
            return None

    def get_news(self, coin_name):
        """
        Fetches news from Currents API (600 req/day free)
        Falls back to NewsAPI if Currents key not set.

        Get Currents API key free at:
        https://currentsapi.services/en/register
        Add as CURRENTS_API_KEY in Railway Variables

        NewsAPI key → NEWS_API_KEY  (100/day, backup)
        Currents key → CURRENTS_API_KEY (600/day, recommended)
        """
        # Try Currents API first (600/day free)
        currents_key = self.config.get("currents_api_key", "")
        if currents_key:
            try:
                r = requests.get(
                    "https://api.currentsapi.services/v1/search",
                    params={
                        "keywords":  f"{coin_name} crypto",
                        "language":  "en",
                        "apiKey":    currents_key,
                    },
                    timeout=10
                )
                if r.status_code == 200:
                    news = r.json().get("news", [])
                    headlines = [a["title"] for a in news if a.get("title")]
                    if headlines:
                        print(f"    [Internet] Currents API: {len(headlines)} headlines")
                        return headlines
                elif r.status_code == 429:
                    print("    [Internet] Currents API rate limited today")
                else:
                    print(f"    [Internet] Currents API error: {r.status_code}")
            except Exception as e:
                print(f"    [Internet] Currents API error: {e}")

        # Fall back to NewsAPI (100/day)
        news_key = self.config.get("news_api_key", "")
        if not news_key:
            return []
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q":        f"{coin_name} crypto",
                    "sortBy":   "publishedAt",
                    "pageSize": 10,
                    "language": "en",
                    "from":     (datetime.now()-timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S"),
                    "apiKey":   news_key,
                },
                timeout=10
            )
            if r.status_code == 200:
                articles = r.json().get("articles", [])
                headlines = [a["title"] for a in articles if a.get("title")]
                if headlines:
                    print(f"    [Internet] NewsAPI: {len(headlines)} headlines")
                return headlines
            return []
        except Exception as e:
            print(f"    [Internet] NewsAPI error: {e}")
            return []

    def get_market_data(self, symbol, timeframe):
        try:
            coin       = symbol.split("/")[0]
            coin_names = {"BTC":"Bitcoin","ETH":"Ethereum","SOL":"Solana","BNB":"BNB"}
            df         = self.get_candles(symbol, timeframe)
            ind        = self.calculate_indicators(df)
            news       = self.get_news(coin_names.get(coin, coin))
            fg         = self.get_fear_greed()
            cg_data    = self.get_coingecko_data(coin)
            if fg:
                print(f"    [Internet] Fear & Greed: {fg['value']} ({fg['label']})")
            if cg_data:
                print(f"    [Internet] 24h change: {cg_data['price_change_24h']:+.2f}%")
            if news:
                print(f"    [Internet] {len(news)} news headlines fetched")
            return {
                "symbol": symbol, "price": ind["price"],
                "ind": ind, "df": df, "news": news,
                "fear_greed": fg, "cg_data": cg_data,
            }
        except ConnectionError as e:
            print(f"    [Internet] {e}")
            return None
        except Exception as e:
            print(f"    [Internet] Unexpected error: {e}")
            return None
