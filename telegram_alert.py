"""
telegram_alert.py
─────────────────
Sends real trade signals to your Telegram phone.

SETUP (takes 2 minutes):
  1. Open Telegram app
  2. Search for @BotFather
  3. Send: /newbot
  4. Follow steps — get your BOT TOKEN
  5. Search for @userinfobot — get your CHAT ID
  6. Put both in CONFIG in main_agent.py
"""

import requests
import time


class TelegramAlert:

    def __init__(self, config):
        self.token   = config.get("telegram_token", "")
        self.chat_id = config.get("telegram_chat", "")
        self.enabled = bool(self.token and self.chat_id)

        if self.enabled:
            print("    [Telegram] Alert system ready")
        else:
            print("    [Telegram] No token/chat_id set — alerts disabled")

    def send(self, message):
        """
        Sends message and retries 3 times if it fails.
        Returns True if delivered, False if all attempts failed.
        This is critical — if False, trade must NOT be saved to memory.
        """
        if not self.enabled:
            return True  # not enabled = skip silently, not a failure

        for attempt in range(3):
            try:
                url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                r   = requests.post(url, json={
                    "chat_id":    self.chat_id,
                    "text":       message,
                    "parse_mode": "HTML",
                }, timeout=10)

                if r.status_code == 200:
                    return True  # delivered successfully

                print(f"    [Telegram] Send failed {r.status_code} attempt {attempt+1}/3")
                time.sleep(5)

            except Exception as e:
                print(f"    [Telegram] Error attempt {attempt+1}/3: {e}")
                time.sleep(5)

        print(f"    [Telegram] ALL 3 ATTEMPTS FAILED — trade will NOT be saved to memory")
        return False  # caller must not save trade if this returns False

    def send_signal(self, symbol, decision):
        if not self.enabled:
            return

        action  = decision["action"]
        levels  = decision.get("levels", {})
        icon    = "🟢" if action == "BUY" else "🔴"
        conf    = decision.get("confidence", 0)
        regime  = decision.get("regime", "")
        confl   = decision.get("confluence", "")
        sr_zone = decision.get("sr_zone", "")

        votes_text = ""
        for v in decision.get("votes", []):
            bullet = "✅" if v["vote"] == action else "⚪"
            votes_text += f"\n{bullet} {v['agent']}: {v['vote']}"

        # Top signals
        sig_key  = "bull_signals" if action=="BUY" else "bear_signals"
        signals  = decision.get(sig_key, [])
        sig_text = ""
        for name, w, reason in signals[:3]:
            sig_text += f"\n  {'★'*w} {reason[:45]}"

        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if action == "BUY":
            direction_note = "Price must RISE to hit TP"
            sl_note        = "Exit if price DROPS here"
        else:
            direction_note = "Price must FALL to hit TP"
            sl_note        = "Exit if price RISES here"

        # All conditions that fired
        sig_key  = "bull_signals" if action=="BUY" else "bear_signals"
        all_sigs = decision.get(sig_key, [])
        cond_text = ""
        for name, weight, reason in all_sigs[:6]:
            stars = "★" * weight
            cond_text += f"\n✅ {stars} [{name}] {reason[:40]}"
        if not cond_text:
            cond_text = "\nNo conditions logged"

        msg = f"""{icon} <b>{action} — {symbol}</b>
{direction_note}

🕐 <b>Signal Time: {now_str}</b>
   ← verify this candle on Binance/TradingView

📊 Confidence : {conf:.0f}/100
⏱ Timeframes : {confl}
📈 Market     : {regime}
📍 S/R Zone   : {sr_zone}
────────────────────────
💰 Entry Price: <b>${levels.get('entry', 0):,.6f}</b>
   ← This is the LIVE price right now
🛑 Stop Loss  : ${levels.get('sl', 0):,.6f}
   ← {sl_note}
────────────────────────
🎯 TP1 (safe) : ${levels.get('tp1', 0):,.6f}  R:R {levels.get('rr1','?')}:1
🎯 TP2 (mid)  : ${levels.get('tp2', 0):,.6f}  R:R {levels.get('rr2','?')}:1
🎯 TP3 (full) : ${levels.get('tp3', 0):,.6f}  R:R {levels.get('rr3','?')}:1
────────────────────────
💼 Position   : ${levels.get('position_usdt', 0):,.0f} USDT
⚠️ Max Risk   : ${levels.get('risk_usdt', 0):,.2f} USDT
🔧 Leverage   : {levels.get('leverage',1)}x

<b>Conditions that fired:</b>{cond_text}

<b>AI Votes:</b>{votes_text}"""

        # Add news pattern context if available
        news_votes = [v for v in decision.get("votes",[]) if v.get("agent") == "News Pattern"]
        if news_votes:
            nv       = news_votes[0]
            events   = decision.get("news_result", {}).get("events", [])
            news_txt = f"\n\n📰 <b>News Pattern ({nv['confidence']:.0f}% conf):</b>"
            for ev in events[:2]:
                news_txt += f"\n  • [{ev['category']}] {ev['headline'][:55]}"
                p = ev.get('pattern', {})
                if p.get('data_points', 0) > 0:
                    news_txt += f"\n    📊 {p['data_points']} similar events — {p['accuracy']}% accurate"
            msg += news_txt

        # Add candle pattern context
        candle_votes = [v for v in decision.get("votes",[]) if v.get("agent") == "Candle Pattern"]
        if candle_votes:
            cv = candle_votes[0]
            msg += f"\n\n🕯 <b>Candle Patterns ({cv['confidence']:.0f}% conf):</b>"
            msg += f"\n  {cv['reason']}"

        # Add news pattern context
        news_votes = [v for v in decision.get("votes",[]) if v.get("agent") == "News Pattern"]
        if news_votes:
            nv = news_votes[0]
            msg += f"\n\n📰 <b>News Pattern ({nv['confidence']:.0f}% conf):</b>"
            msg += f"\n  {nv['reason']}"

        # Add candle patterns section
        candle_votes = [v for v in decision.get("votes",[]) if v.get("agent")=="Candle Patterns"]
        if candle_votes:
            cv = candle_votes[0]
            patterns = decision.get("candle_result", {}).get("patterns", [])
            top = sorted(patterns, key=lambda x: x["strength"], reverse=True)[:3] if patterns else []
            pat_txt = f"\n\n🕯 <b>Candle Patterns ({cv['confidence']:.0f}% conf):</b>"
            for p in top:
                icon = "🟢" if p["signal"]=="BUY" else "🔴" if p["signal"]=="SELL" else "🟡"
                stars = "★" * p["strength"]
                hist  = f" ({p['historical_accuracy']}% acc)" if p.get("historical_accuracy") else ""
                pat_txt += f"\n  {icon} {stars} {p['name']}{hist}"
                pat_txt += f"\n     {p['desc'][:55]}"
            msg += pat_txt

        self.send(msg)
        print(f"    [Telegram] Signal sent to your phone")

    def send_signal_with_id(self, symbol, decision, signal_id):
        """
        Sends signal with unique ID.
        Returns True if delivered, False if failed.
        Caller must NOT save trade to memory if this returns False.
        """
        if not self.enabled:
            return True

        action  = decision["action"]
        levels  = decision.get("levels", {})
        icon    = "🟢" if action == "BUY" else "🔴"
        conf    = decision.get("confidence", 0)
        regime  = decision.get("regime", "")
        confl   = decision.get("confluence", "")
        sr_zone = decision.get("sr_zone", "")

        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if action == "BUY":
            direction_note = "Price must RISE to hit TP"
            sl_note        = "Exit if price DROPS here"
        else:
            direction_note = "Price must FALL to hit TP"
            sl_note        = "Exit if price RISES here"

        votes_text = ""
        for v in decision.get("votes", []):
            bullet = "✅" if v["vote"] == action else "❌"
            votes_text += f"\n{bullet} {v['agent']}: {v['vote']}"

        sig_key  = "bull_signals" if action=="BUY" else "bear_signals"
        all_sigs = decision.get(sig_key, [])
        cond_text = ""
        for name, weight, reason in all_sigs[:6]:
            stars = "★" * weight
            cond_text += f"\n✅ {stars} [{name}] {reason[:40]}"
        if not cond_text:
            cond_text = "\nNo conditions logged"

        # Fear & Greed context
        fg    = decision.get("fear_greed") or {}
        fg_val = fg.get("value", "N/A")
        fg_lbl = fg.get("label", "")
        if isinstance(fg_val, int):
            if fg_val <= 25:
                fg_icon = "😱"
            elif fg_val <= 45:
                fg_icon = "😨"
            elif fg_val <= 55:
                fg_icon = "😐"
            elif fg_val <= 75:
                fg_icon = "😊"
            else:
                fg_icon = "🤑"
        else:
            fg_icon = "📊"

        msg = (
            f"{icon} <b>{action} SIGNAL #{signal_id} — {symbol}</b>\n"
            f"{direction_note}\n\n"
            f"🆔 Signal ID: <b>#{signal_id}</b>\n"
            f"   Match this ID to the result message\n\n"
            f"{fg_icon} Fear & Greed: <b>{fg_val} ({fg_lbl})</b>\n"
            f"   ← This signal passed the sentiment filter\n\n"
            f"🕐 <b>Signal Time: {now_str}</b>\n"
            f"   Verify this candle on Binance/TradingView\n\n"
            f"📊 Confidence : {conf:.0f}/100\n"
            f"⏱ Timeframes : {confl}\n"
            f"📈 Market     : {regime}\n"
            f"📍 S/R Zone   : {sr_zone}\n"
            f"────────────────────────\n"
            f"💰 Entry Price: <b>${levels.get('entry', 0):,.6f}</b>\n"
            f"   ← Live price right now\n"
            f"🛑 Stop Loss  : ${levels.get('sl', 0):,.6f}\n"
            f"   ← {sl_note}\n"
            f"────────────────────────\n"
            f"🎯 TP1 (safe) : ${levels.get('tp1', 0):,.6f}  R:R {levels.get('rr1','?')}:1\n"
            f"🎯 TP2 (mid)  : ${levels.get('tp2', 0):,.6f}  R:R {levels.get('rr2','?')}:1\n"
            f"🎯 TP3 (full) : ${levels.get('tp3', 0):,.6f}  R:R {levels.get('rr3','?')}:1\n"
            f"────────────────────────\n"
            f"💼 Position   : ${levels.get('position_usdt', 0):,.0f} USDT\n"
            f"⚠️ Max Risk   : ${levels.get('risk_usdt', 0):,.2f} USDT\n"
            f"🔧 Leverage   : {levels.get('leverage',1)}x\n\n"
            f"<b>Conditions fired:</b>{cond_text}\n\n"
            f"<b>AI Votes:</b>{votes_text}"
        )

        delivered = self.send(msg)
        if delivered:
            print(f"    [Telegram] Signal #{signal_id} confirmed delivered to your phone")
        return delivered

    def send_result(self, symbol, result, pnl_pct):
        if not self.enabled:
            return
        icon = "✅" if result == "WIN" else "❌"
        msg  = f"{icon} <b>{result} — {symbol}</b>\nP&L: {pnl_pct:+.2f}%"
        self.send(msg)

    def send_report(self, win_rate, pf, wins, losses):
        if not self.enabled:
            return
        icon = "📊"
        msg  = f"""{icon} <b>10-Trade Report</b>

Win Rate: {win_rate:.0f}%  ({wins}W / {losses}L)
Profit Factor: {pf:.2f}
{'✅ Strategy working' if win_rate >= 55 else '⚠️ Needs review'}"""
        self.send(msg)
