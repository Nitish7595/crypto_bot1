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
        self.exchange      = None
        self._candle_cache = {}   # {symbol_tf: (df, timestamp)}

    def get_candles(self, symbol, timeframe, limit=200):
        """
        Fetches OHLCV candles. Tries 4 sources in order:
        1. Alpha Vantage  — if ALPHA_VANTAGE_KEY set (500/day)
        2. Binance US     — public API, no geo blocks, no key needed
        3. Kraken         — public API, no key needed
        4. CoinGecko      — always works, ~96 candles
        """
        # Cache candles for 60 seconds to reduce API calls
        cache_key = f"{symbol}_{timeframe}"
        now       = time.time()
        if cache_key in self._candle_cache:
            cached_df, cached_at = self._candle_cache[cache_key]
            if now - cached_at < 60:
                return cached_df

        errors = []

        # Source 1 — Alpha Vantage (needs free key)
        if self.av_key:
            try:
                df = self._candles_alphavantage(symbol, timeframe, limit)
                if df is not None and len(df) >= 30:
                    self._candle_cache[cache_key] = (df, now)
                    return df
            except Exception as e:
                errors.append(f"AV:{str(e)[:40]}")

        # Source 2 — Binance US public API (no geo blocks)
        try:
            df = self._candles_binanceus(symbol, timeframe, limit)
            if df is not None and len(df) >= 30:
                self._candle_cache[cache_key] = (df, now)
                return df
        except Exception as e:
            errors.append(f"BinanceUS:{str(e)[:40]}")

        # Source 3 — Kraken
        try:
            df = self._candles_kraken(symbol, timeframe, limit)
            if df is not None and len(df) >= 30:
                self._candle_cache[cache_key] = (df, now)
                return df
        except Exception as e:
            errors.append(f"Kraken:{str(e)[:40]}")

        # Source 4 — CoinGecko (always works)
        try:
            df = self._candles_coingecko(symbol, timeframe, limit)
            if df is not None and len(df) >= 30:
                self._candle_cache[cache_key] = (df, now)
                return df
        except Exception as e:
            errors.append(f"CoinGecko:{str(e)[:40]}")

        print(f"    [Internet] All sources failed: {' | '.join(errors)}")
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

    def _candles_binanceus(self, symbol, timeframe, limit):
        """
        Binance US public REST API.
        No API key needed for candle data.
        No geo blocks — US-based, open to all servers.
        Full OHLCV data, up to 1000 candles per request.
        """
        # Binance US uses same format as Binance global
        coin = symbol.split("/")[0]
        pair = f"{coin}USDT"

        tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
        }
        interval = tf_map.get(timeframe)
        if not interval:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        r = requests.get(
            "https://api.binance.us/api/v3/klines",
            params={
                "symbol":    pair,
                "interval":  interval,
                "limit":     min(limit, 1000),
            },
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if r.status_code == 451:
            raise ValueError("Binance US geo-blocked from this server")
        if r.status_code != 200:
            raise ValueError(f"Binance US HTTP {r.status_code}")

        raw = r.json()
        if not raw or len(raw) < 10:
            raise ValueError(f"Only {len(raw)} candles from Binance US")

        # Binance format: [ts, open, high, low, close, volume, ...]
        df = pd.DataFrame(raw, columns=[
            "ts","open","high","low","close","volume",
            "close_ts","quote_vol","trades","taker_buy_base",
            "taker_buy_quote","ignore"
        ])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("ts")
        df = df[["open","high","low","close","volume"]].astype(float)
        print(f"    [Internet] Binance US: {len(df)} {timeframe} candles for {symbol}")
        return df

    def _candles_kraken(self, symbol, timeframe, limit):
        """Kraken public API — US exchange, no geo blocks on public data."""
        kraken_map = {
            "BTC/USDT": "XBTUSD", "ETH/USDT": "ETHUSD",
            "SOL/USDT": "SOLUSD", "BNB/USDT": "BNBUSD",
        }
        pair = kraken_map.get(symbol)
        if not pair:
            raise ValueError(f"No Kraken mapping for {symbol}")

        tf_map = {
            "1m": 1, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440,
        }
        interval = tf_map.get(timeframe)
        if not interval:
            raise ValueError(f"Unsupported timeframe for Kraken: {timeframe}")

        r = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval},
            timeout=15
        )
        if r.status_code != 200:
            raise ValueError(f"Kraken HTTP {r.status_code}")

        data = r.json()
        if data.get("error") and data["error"]:
            raise ValueError(f"Kraken error: {data['error']}")

        result = data.get("result", {})
        key    = [k for k in result if k != "last"]
        if not key:
            raise ValueError("No candle data from Kraken")

        raw = result[key[0]][-limit:]
        df  = pd.DataFrame(raw, columns=[
            "time","open","high","low","close","vwap","volume","count"
        ])
        df["ts"] = pd.to_datetime(df["time"].astype(int), unit="s")
        df = df.set_index("ts")
        df = df[["open","high","low","close","volume"]].astype(float)
        print(f"    [Internet] Kraken: {len(df)} {timeframe} candles for {symbol}")
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
        # Using more days to get enough candles
        # CoinGecko: 1 day = ~48 candles (30min), 2 days = ~96
        tf_days = {
            "5m":  2,   # ~96 candles
            "15m": 2,   # ~96 candles
            "30m": 2,   # ~96 candles
            "1h":  14,  # ~84 candles (4h resolution)
            "4h":  30,  # ~180 candles
            "1d":  90,  # daily candles
        }
        days = tf_days.get(timeframe, 2)

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
