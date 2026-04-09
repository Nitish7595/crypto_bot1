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
        # Price sources confirmed working on Railway:
        # 1. Kraken public API — US exchange, no geo blocks
        # 2. CoinGecko OHLC   — already confirmed working above
        self.coin_map = {
            "BTC/USDT": {"kraken": "XBTUSD",  "cg": "bitcoin"},
            "ETH/USDT": {"kraken": "ETHUSD",  "cg": "ethereum"},
            "SOL/USDT": {"kraken": "SOLUSD",  "cg": "solana"},
            "BNB/USDT": {"kraken": "BNBUSD",  "cg": "binancecoin"},
        }
        self.exchange = None

    def get_candles(self, symbol, timeframe, limit=200):
        """
        Fetches OHLCV candles. Tries Kraken first, then CoinGecko.
        Both confirmed to work from Railway USA servers.
        """
        # Try Kraken first
        try:
            df = self._candles_kraken(symbol, timeframe, limit)
            if df is not None and len(df) >= 50:
                return df
        except Exception as e:
            print(f"    [Internet] Kraken failed: {str(e)[:60]} — trying CoinGecko")

        # Fall back to CoinGecko
        try:
            df = self._candles_coingecko(symbol, timeframe, limit)
            if df is not None and len(df) >= 50:
                return df
        except Exception as e:
            print(f"    [Internet] CoinGecko failed: {str(e)[:60]}")

        raise ConnectionError(f"All price sources failed for {symbol}")

    def _candles_kraken(self, symbol, timeframe, limit):
        """Kraken public OHLC API — US exchange, no geo restrictions."""
        coins  = self.coin_map.get(symbol, {})
        pair   = coins.get("kraken")
        if not pair:
            raise ValueError(f"No Kraken mapping for {symbol}")

        # Kraken interval in minutes
        tf_map = {
            "1m": 1, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440,
        }
        interval = tf_map.get(timeframe)
        if not interval:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        r = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval},
            timeout=15
        )
        if r.status_code != 200:
            raise ValueError(f"Kraken HTTP {r.status_code}")

        data = r.json()
        if data.get("error"):
            raise ValueError(f"Kraken error: {data['error']}")

        # Result key is the pair name (may differ slightly)
        result = data.get("result", {})
        candle_key = [k for k in result.keys() if k != "last"]
        if not candle_key:
            raise ValueError("No candle data in Kraken response")

        raw = result[candle_key[0]]
        # Kraken format: [time, open, high, low, close, vwap, volume, count]
        df = pd.DataFrame(raw, columns=[
            "time","open","high","low","close","vwap","volume","count"
        ])
        df["ts"] = pd.to_datetime(df["time"].astype(int), unit="s")
        df = df.set_index("ts")
        df = df[["open","high","low","close","volume"]].astype(float)
        df = df.tail(limit)
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
        key = self.config.get("news_api_key", "")
        if not key:
            return []
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": f"{coin_name} crypto", "sortBy": "publishedAt",
                    "pageSize": 10, "language": "en",
                    "from": (datetime.now()-timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S"),
                    "apiKey": key,
                },
                timeout=10
            )
            if r.status_code == 200:
                return [a["title"] for a in r.json().get("articles",[]) if a.get("title")]
            return []
        except Exception as e:
            print(f"    [Internet] News error: {e}")
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
