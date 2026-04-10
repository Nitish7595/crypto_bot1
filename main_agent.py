"""
=================================================================
  AUTONOMOUS AI AGENT — MAIN BRAIN
  Runs on YOUR computer. Controls browser. Has internet.
  Talks to multiple AIs. Trades on Binance. Alerts your phone.
=================================================================

INSTALL EVERYTHING (run once):
  pip install ccxt pandas numpy ta requests anthropic
  pip install pyautogui selenium webdriver-manager
  pip install python-telegram-bot schedule

FOLDER STRUCTURE:
  autonomous_agent/
  ├── main_agent.py         ← YOU ARE HERE — run this
  ├── internet_agent.py     ← fetches live data from internet
  ├── ai_council.py         ← talks to Claude + OpenAI APIs
  ├── computer_use.py       ← controls your browser/computer
  ├── binance_trader.py     ← places real trades
  ├── telegram_alert.py     ← sends alerts to your phone
  └── agent_memory.json     ← agent saves memory here

RUN:
  python main_agent.py

WHAT IT HONESTLY DOES:
  Every 60 seconds:
  1. Fetches real crypto prices from Binance (internet_agent)
  2. Fetches real news headlines (internet_agent)
  3. Sends data to AI council for analysis (ai_council)
  4. Risk agent checks if trade is safe (ai_council)
  5. If all AIs agree — prints signal + sends Telegram alert
  6. If AUTO_TRADE=True — opens browser and places order
  7. Tracks every real outcome and reports win/loss honestly
=================================================================
"""

import time
import json
import os
import schedule
from datetime import datetime

# Import our modules
from internet_agent  import InternetAgent
from ai_council      import AICouncil
from binance_trader  import BinanceTrader
from telegram_alert  import TelegramAlert
from computer_use    import ComputerUse


# ═══════════════════════════════════════════════════════
# YOUR SETTINGS — fill these in
# ═══════════════════════════════════════════════════════

import os

CONFIG = {
    # Coins to watch
    "symbols":        ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "timeframe":      "15m",
    "scan_every":     300,       # 5 minutes — good for Railway free tier

    # Your account
    "account_usdt":   1000,
    "risk_per_trade": 0.01,      # 1% per trade
    "max_leverage":   3,

    # API Keys — loaded from Railway environment variables
    # Set these in Railway dashboard → Variables tab
    # NEVER paste real keys directly in code — keeps them safe
    "binance_key":    os.environ.get("BINANCE_KEY",    ""),
    "binance_secret": os.environ.get("BINANCE_SECRET", ""),
    "anthropic_key":  os.environ.get("ANTHROPIC_KEY",  ""),
    "openai_key":     os.environ.get("OPENAI_KEY",     ""),
    "news_api_key":   os.environ.get("NEWS_API_KEY",   ""),
    "telegram_token": os.environ.get("TELEGRAM_TOKEN", ""),
    "telegram_chat":  os.environ.get("TELEGRAM_CHAT",  ""),

    # Trade mode
    "auto_trade":     False,
    "use_browser":    False,
    "memory_file":    "agent_memory.json",
}


# ═══════════════════════════════════════════════════════
# AGENT MEMORY — persists between restarts
# ═══════════════════════════════════════════════════════

def load_memory():
    if os.path.exists(CONFIG["memory_file"]):
        with open(CONFIG["memory_file"]) as f:
            return json.load(f)
    return {
        "trades":        [],    # all signals + outcomes
        "scans":         0,     # how many scans done
        "started":       str(datetime.now()),
        "agent_notes":   [],    # agent writes notes to itself
    }

def save_memory(mem):
    with open(CONFIG["memory_file"], "w") as f:
        json.dump(mem, f, indent=2)


# ═══════════════════════════════════════════════════════
# REPORT — real numbers every 10 trades
# ═══════════════════════════════════════════════════════

def print_report(memory):
    closed = [t for t in memory["trades"] if t.get("result")]
    total  = len(closed)

    if total == 0 or total % 10 != 0:
        return

    batch = closed[-10:]
    wins  = [t for t in batch if t["result"] == "WIN"]
    losses= [t for t in batch if t["result"] == "LOSS"]
    wr    = len(wins) / 10 * 100

    gw = sum(abs(t.get("pnl_pct", 0)) for t in wins)
    gl = sum(abs(t.get("pnl_pct", 0)) for t in losses)
    pf = round(gw / gl, 2) if gl > 0 else float("inf")

    print()
    print("╔═══════════════════════════════════════════════════╗")
    print(f"║  10-TRADE REPORT — trades #{total-9} to #{total}")
    print("╠═══════════════════════════════════════════════════╣")
    print(f"║  Win Rate      : {wr:.0f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"║  Profit Factor : {pf}")
    if wins:
        print(f"║  Avg Win       : +{gw/len(wins):.2f}%")
    if losses:
        print(f"║  Avg Loss      : -{gl/len(losses):.2f}%")
    print("╠═══════════════════════════════════════════════════╣")

    if wr >= 60 and pf >= 1.5:
        verdict = "Working well. Keep running."
    elif wr >= 50 and pf >= 1.0:
        verdict = "Marginal. Watch fees."
    else:
        verdict = "Not profitable yet. Review signals."

    print(f"║  Verdict : {verdict}")
    print("╚═══════════════════════════════════════════════════╝")

    # Agent writes a note to itself about performance
    note = f"Batch {total//10}: WR={wr:.0f}% PF={pf} — {verdict}"
    memory["agent_notes"].append(note)
    save_memory(memory)


# ═══════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════

def run():
    memory   = load_memory()

    # Initialise all modules
    internet = InternetAgent(CONFIG)
    council  = AICouncil(CONFIG)
    trader   = BinanceTrader(CONFIG)
    telegram = TelegramAlert(CONFIG)
    computer = ComputerUse(CONFIG)
    # Give trader access to telegram so it can send WIN/LOSS alerts
    trader.telegram = telegram

    last_signal = {s: None for s in CONFIG["symbols"]}


    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         AUTONOMOUS AI AGENT — ONLINE                    ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  internet_agent  : fetches live prices + news           ║")
    print("║  ai_council      : Claude + OpenAI analyse together     ║")
    print("║  binance_trader  : places real orders via API           ║")
    print("║  telegram_alert  : sends signals to your phone          ║")
    print("║  computer_use    : can control browser if needed        ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Coins       : {', '.join(s.split('/')[0] for s in CONFIG['symbols']):<44}║")
    print(f"║  Auto-trade  : {'YES — placing real orders' if CONFIG['auto_trade'] else 'NO — you trade manually':<44}║")
    print(f"║  Browser use : {'YES' if CONFIG['use_browser'] else 'NO':<44}║")
    print(f"║  Telegram    : {'Connected' if CONFIG['telegram_token'] else 'Not set':<44}║")
    print(f"║  Claude API  : {'Connected' if CONFIG['anthropic_key'] else 'Not set — using indicators only':<44}║")
    print(f"║  Past trades : {len([t for t in memory['trades'] if t.get('result')])} closed, {len([t for t in memory['trades'] if not t.get('result')])} open{'':<26}║")
    print("╚══════════════════════════════════════════════════════════╝")

    if memory["agent_notes"]:
        print("\n  Agent memory (what it learned):")
        for note in memory["agent_notes"][-3:]:
            print(f"    • {note}")

    print()

    # ── STARTUP DIAGNOSTICS ───────────────────────────────
    # Tests every API and reports clearly in Railway logs
    # and sends full status to your Telegram
    print()
    print("  Running startup diagnostics...")
    print("  " + "─" * 50)

    diag = {}

    # Test 1 — Price data (Kraken → CoinGecko fallback)
    try:
        test_df = internet.get_candles("BTC/USDT", "15m", limit=10)
        if test_df is not None and len(test_df) > 0:
            diag["kucoin"] = f"✅ Working — BTC ${test_df['close'].iloc[-1]:,.2f}"
        else:
            diag["kucoin"] = "❌ No data returned"
    except Exception as e:
        diag["kucoin"] = f"❌ Failed — {str(e)[:60]}"
    print(f"  Price data    : {diag['kucoin']}")

    # Test 2 — Fear & Greed
    try:
        fg_test = internet.get_fear_greed()
        if fg_test:
            diag["fear_greed"] = f"✅ Working — {fg_test['value']} ({fg_test['label']})"
        else:
            diag["fear_greed"] = "❌ No data returned"
    except Exception as e:
        diag["fear_greed"] = f"❌ Failed — {str(e)[:50]}"
    print(f"  Fear & Greed  : {diag['fear_greed']}")

    # Test 3 — CoinGecko
    try:
        cg_test = internet.get_coingecko_data("BTC")
        if cg_test:
            diag["coingecko"] = f"✅ Working — 24h change {cg_test['price_change_24h']:+.2f}%"
        else:
            diag["coingecko"] = "❌ No data returned"
    except Exception as e:
        diag["coingecko"] = f"❌ Failed — {str(e)[:50]}"
    print(f"  CoinGecko     : {diag['coingecko']}")

    # Test 4 — News API
    news_key = CONFIG.get("news_api_key", "")
    if not news_key:
        diag["news"] = "⚠️  NOT SET — add NEWS_API_KEY in Railway Variables"
        diag["news_detail"] = "Get free key at newsapi.org"
    else:
        try:
            import requests as req
            r = req.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": "bitcoin", "pageSize": 3,
                    "language": "en", "apiKey": news_key
                },
                timeout=10
            )
            if r.status_code == 200:
                articles = r.json().get("articles", [])
                diag["news"] = f"✅ Working — {len(articles)} articles returned"
                diag["news_detail"] = articles[0]["title"][:60] if articles else "no articles"
            elif r.status_code == 401:
                diag["news"] = "❌ WRONG KEY — go to newsapi.org → your account → API Key"
                diag["news_detail"] = "Copy the key exactly, no spaces"
            elif r.status_code == 426:
                diag["news"] = "❌ Free tier expired — newsapi.org free = dev only (localhost)"
                diag["news_detail"] = "Railway is a server — needs paid plan OR use gnews.io free alternative"
            elif r.status_code == 429:
                diag["news"] = "⚠️  Rate limited — 100 req/day on free tier"
                diag["news_detail"] = "Key works — just too many requests today"
            else:
                diag["news"] = f"❌ Error {r.status_code} — {r.text[:60]}"
                diag["news_detail"] = ""
        except Exception as e:
            diag["news"] = f"❌ Failed — {str(e)[:50]}"
            diag["news_detail"] = ""
    print(f"  News API      : {diag['news']}")
    if diag.get("news_detail"):
        print(f"                  {diag['news_detail']}")

    # Test 5 — Claude API
    claude_key = CONFIG.get("anthropic_key", "")
    if not claude_key:
        diag["claude"] = "⚠️  NOT SET — signals use indicators only"
    else:
        try:
            import requests as req
            r = req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": claude_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "Say OK"}]
                },
                timeout=10
            )
            if r.status_code == 200:
                diag["claude"] = "✅ Working"
            elif r.status_code == 401:
                diag["claude"] = "❌ Invalid API key"
            elif "credit" in r.text.lower():
                diag["claude"] = "❌ No credits — add credits at console.anthropic.com"
            else:
                diag["claude"] = f"❌ Error {r.status_code}"
        except Exception as e:
            diag["claude"] = f"❌ Failed — {str(e)[:50]}"
    print(f"  Claude API    : {diag['claude']}")

    # Test 6 — OpenAI API
    openai_key = CONFIG.get("openai_key", "")
    if not openai_key:
        diag["openai"] = "⚠️  NOT SET — optional"
    else:
        try:
            import requests as req
            r = req.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 5},
                timeout=10
            )
            if r.status_code == 200:
                diag["openai"] = "✅ Working"
            elif r.status_code == 401:
                diag["openai"] = "❌ Invalid API key"
            else:
                diag["openai"] = f"❌ Error {r.status_code}"
        except Exception as e:
            diag["openai"] = f"❌ Failed — {str(e)[:50]}"
    print(f"  OpenAI API    : {diag['openai']}")

    print("  " + "─" * 50)
    print()

    # ── STARTUP TEST MESSAGE ──────────────────────────────
    # Sends a Telegram message immediately when bot starts
    # So you can confirm your phone receives alerts
    telegram.send(
        "✅ <b>Bot is ONLINE on Railway</b>\n\n"
        "📡 <b>API Status:</b>\n"
        f"  KuCoin prices : {diag.get('kucoin','?')[:40]}\n"
        f"  Fear & Greed  : {diag.get('fear_greed','?')[:40]}\n"
        f"  CoinGecko     : {diag.get('coingecko','?')[:40]}\n"
        f"  News API      : {diag.get('news','?')[:40]}\n"
        f"  Claude API    : {diag.get('claude','?')[:40]}\n"
        f"  OpenAI API    : {diag.get('openai','?')[:40]}\n\n"
        "Scanning BTC, ETH, SOL every 5 minutes.\n"
        "<i>No action needed — wait for signals.</i>"
    )
    print("  ✅ Startup test message sent to Telegram")

    scan = 0

    while True:
        scan += 1
        memory["scans"] = scan
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] Scan #{scan}")
        print("─" * 55)

        for symbol in CONFIG["symbols"]:
            print(f"\n  [{symbol}] Starting analysis...")

            try:
                # ── STEP 1: Get real live data ──────────────────
                market_data = internet.get_market_data(symbol, CONFIG["timeframe"])
                if not market_data:
                    print(f"  [{symbol}] Could not fetch data — skipping")
                    continue

                print(f"  [{symbol}] Price: ${market_data['price']:,.4f}")

                # ── STEP 2: Check open trade outcomes ───────────
                trader.check_outcomes(memory["trades"], symbol, market_data["df"])
                save_memory(memory)
                print_report(memory)

                # ── STEP 3: Send to AI council for analysis ─────
                decision = council.analyse(symbol, market_data, memory["trades"])

                if decision["action"] == "HOLD":
                    print(f"  [{symbol}] AI Council: HOLD — {decision['reason']}")
                    continue

                # ── STEP 4: No duplicate signals ────────────────
                sig_key = f"{symbol}_{decision['action']}"
                if last_signal[symbol] == sig_key:
                    print(f"  [{symbol}] Same signal as last scan — skip")
                    continue
                last_signal[symbol] = sig_key

                # ── STEP 5: Print signal clearly ────────────────
                print_signal(symbol, decision)

                # ── STEP 6: Send Telegram alert to your phone ───
                telegram.send_signal(symbol, decision)

                # ── STEP 7: Save to memory ───────────────────────
                record = {
                    "id":          len(memory["trades"]) + 1,
                    "symbol":      symbol,
                    "direction":   decision["action"],
                    "entry_price": market_data["price"],
                    "sl":          decision["levels"]["sl"],
                    "tp1":         decision["levels"]["tp1"],
                    "tp2":         decision["levels"]["tp2"],
                    "entry_time":  str(market_data["df"].index[-1]),
                    "result":      None,
                    "exit_price":  None,
                    "exit_time":   None,
                    "pnl_pct":     None,
                    "ai_votes":    decision["votes"],
                }
                memory["trades"].append(record)
                save_memory(memory)

                # ── STEP 8: Place order ──────────────────────────
                if CONFIG["auto_trade"]:
                    if CONFIG["use_browser"]:
                        # Use browser to place trade on Binance website
                        computer.place_trade_on_binance(
                            symbol,
                            decision["action"],
                            decision["levels"]
                        )
                    else:
                        # Use API directly
                        trader.place_order(
                            symbol,
                            decision["action"],
                            market_data["price"],
                            decision["levels"]
                        )

            except ConnectionError as e:
                print(f"  [{symbol}] Connection error: {e}")
            except Exception as e:
                print(f"  [{symbol}] Error: {e}")

        save_memory(memory)
        print(f"\n  Waiting {CONFIG['scan_every']}s... (Ctrl+C to stop)\n")
        time.sleep(CONFIG["scan_every"])


def print_signal(symbol, decision):
    action   = decision["action"]
    levels   = decision["levels"]
    is_long  = action == "BUY"
    icon     = "🟢 LONG  (BUY)" if is_long else "🔴 SHORT (SELL)"
    now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    conf     = decision.get("confidence", 0)
    regime   = decision.get("regime", "UNKNOWN")
    sr_zone  = decision.get("sr_zone", "UNKNOWN")
    confl    = decision.get("confluence", "UNKNOWN")
    bar_len  = int(conf / 5)
    conf_bar = "█" * bar_len + "░" * (20 - bar_len)

    print()
    print("═" * 65)
    print(f"  {icon}  —  {symbol}")
    print(f"  SIGNAL TIME : {now}  ← TIMESTAMP FOR VERIFICATION")
    print("═" * 65)

    # Confidence and conditions
    print(f"  Confidence   : [{conf_bar}] {conf:.0f}/100")
    print(f"  Timeframes   : {confl}")
    print(f"  Market Regime: {regime}")
    print(f"  S/R Zone     : {sr_zone}")
    print("─" * 65)

    # Price levels — all verifiable on Binance/TradingView
    print(f"  PRICE LEVELS (verify on Binance):")
    print(f"  Entry Price  : ${levels['entry']:>14,.6f}  ← LIVE PRICE RIGHT NOW")
    if is_long:
        print(f"  Stop Loss    : ${levels['sl']:>14,.6f}  ← EXIT IF PRICE DROPS HERE")
        print(f"  TP1 (safe)   : ${levels['tp1']:>14,.6f}  R:R {levels['rr1']}:1  ← FIRST TARGET")
        print(f"  TP2 (mid)    : ${levels['tp2']:>14,.6f}  R:R {levels['rr2']}:1")
        print(f"  TP3 (full)   : ${levels['tp3']:>14,.6f}  R:R {levels['rr3']}:1")
    else:
        print(f"  Stop Loss    : ${levels['sl']:>14,.6f}  ← EXIT IF PRICE RISES HERE")
        print(f"  TP1 (safe)   : ${levels['tp1']:>14,.6f}  R:R {levels['rr1']}:1  ← FIRST TARGET")
        print(f"  TP2 (mid)    : ${levels['tp2']:>14,.6f}  R:R {levels['rr2']}:1")
        print(f"  TP3 (full)   : ${levels['tp3']:>14,.6f}  R:R {levels['rr3']}:1")
    print(f"  Leverage     : {levels.get('leverage',1)}x")
    print(f"  Position     : ${levels['position_usdt']:>10,.2f} USDT")
    print(f"  Max Risk     : ${levels['risk_usdt']:>10,.2f} USDT")
    print("─" * 65)

    # Every condition that fired — fully transparent
    sig_key = "bull_signals" if is_long else "bear_signals"
    signals = decision.get(sig_key, [])
    print(f"  CONDITIONS ACTIVE ({len(signals)} fired):")
    if signals:
        for name, weight, reason in signals:
            stars  = "★" * weight
            status = "✅ PASS"
            print(f"    {status}  {stars:<3} [{name:<12}] {reason[:48]}")
    else:
        print("    No conditions logged")

    # Conditions that did NOT fire
    all_indicators = ["RSI","MACD","EMA","BB","Stoch","WilliamsR","CCI","ADX","OBV","VWAP"]
    active_names   = [name for name, _, _ in signals]
    inactive       = [i for i in all_indicators if i not in active_names]
    if inactive:
        print(f"  CONDITIONS NOT MET:")
        for name in inactive:
            print(f"    ⚪ SKIP  [{name:<12}] not in signal zone")
    print("─" * 65)

    # AI votes
    print("  AI VOTES:")
    for vote in decision.get("votes", []):
        bullet = "✅" if vote["vote"] == action else "❌"
        print(f"    {bullet} {vote['agent']:<28}: {vote['vote']} — {vote.get('reason','')[:40]}")
    print("─" * 65)

    # Plain English summary
    if is_long:
        print(f"  SUMMARY: BUY {symbol} at ${levels['entry']:,.4f}")
        print(f"    Price needs to RISE {levels['rr1']}x the risk to hit TP1")
        print(f"    Exit immediately if price drops to ${levels['sl']:,.4f}")
    else:
        print(f"  SUMMARY: SHORT {symbol} at ${levels['entry']:,.4f}")
        print(f"    Price needs to FALL {levels['rr1']}x the risk to hit TP1")
        print(f"    Exit immediately if price rises to ${levels['sl']:,.4f}")
    print("═" * 65)
    print()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nAgent stopped. Memory saved.")
