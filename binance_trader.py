"""
binance_trader.py
─────────────────
Every trade is logged with full transparency.
Every price is real — fetched from KuCoin live feed.
Every timestamp is real UTC time.
You can cross-check every number on Binance or TradingView.
"""

import ccxt
import pandas as pd
import time
from datetime import datetime, timezone


class BinanceTrader:

    def __init__(self, config):
        self.config   = config
        self.telegram = None
        self.exchange = ccxt.binance({
            "apiKey":  config.get("binance_key", ""),
            "secret":  config.get("binance_secret", ""),
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

    # ──────────────────────────────────────────────
    # CHECK OPEN TRADES — with full transparency log
    # ──────────────────────────────────────────────

    def check_outcomes(self, trades, symbol, df):
        for trade in trades:
            if trade.get("result") is not None:
                continue
            if trade["symbol"] != symbol:
                continue

            entry_time  = pd.Timestamp(trade["entry_time"])
            after_entry = df[df.index > entry_time]

            if len(after_entry) < 2:
                # Still open — print current status
                current_price = df["close"].iloc[-1]
                self._print_open_trade_status(trade, current_price, df)
                continue

            is_long = trade["direction"] == "BUY"

            for ts, row in after_entry.iterrows():
                if is_long:
                    if row["low"] <= trade["sl"]:
                        self._close_trade(
                            trade, trade["sl"], str(ts),
                            "LOSS", trades, row
                        )
                        break
                    if row["high"] >= trade["tp1"]:
                        self._close_trade(
                            trade, trade["tp1"], str(ts),
                            "WIN", trades, row
                        )
                        break
                else:
                    if row["high"] >= trade["sl"]:
                        self._close_trade(
                            trade, trade["sl"], str(ts),
                            "LOSS", trades, row
                        )
                        break
                    if row["low"] <= trade["tp1"]:
                        self._close_trade(
                            trade, trade["tp1"], str(ts),
                            "WIN", trades, row
                        )
                        break

    def _print_open_trade_status(self, trade, current_price, df):
        """Shows live status of open trade every scan — so you can verify on Binance."""
        is_long     = trade["direction"] == "BUY"
        entry_price = trade["entry_price"]
        sl          = trade["sl"]
        tp1         = trade["tp1"]
        pnl_now     = ((current_price - entry_price) / entry_price
                       * 100 * (1 if is_long else -1))
        sl_dist_pct = abs(current_price - sl) / entry_price * 100
        tp_dist_pct = abs(tp1 - current_price) / entry_price * 100
        direction   = "📈 LONG" if is_long else "📉 SHORT"
        pnl_icon    = "🟢" if pnl_now > 0 else "🔴"

        print(f"\n  ┌─ OPEN TRADE #{trade['id']} ─────────────────────────────")
        print(f"  │ Symbol    : {trade['symbol']}  [{direction}]")
        print(f"  │ Opened    : {trade['entry_time']}  ← CHECK THIS ON BINANCE")
        print(f"  │ Entry     : ${entry_price:>14,.4f}  ← REAL PRICE AT SIGNAL TIME")
        print(f"  │ Now       : ${current_price:>14,.4f}  ← CURRENT LIVE PRICE")
        print(f"  │ P&L now   : {pnl_now:>+.2f}%  {pnl_icon}")
        print(f"  │ Stop Loss : ${sl:>14,.4f}  ({sl_dist_pct:.2f}% away)")
        print(f"  │ Target TP1: ${tp1:>14,.4f}  ({tp_dist_pct:.2f}% away)")
        print(f"  └────────────────────────────────────────────────────")

    def _close_trade(self, trade, exit_price, exit_time, result, all_trades, candle_row):
        is_long  = trade["direction"] == "BUY"
        pnl      = ((exit_price - trade["entry_price"]) / trade["entry_price"]
                    * 100 * (1 if is_long else -1))
        duration = self._get_duration(trade["entry_time"], exit_time)

        trade["result"]      = result
        trade["exit_price"]  = round(exit_price, 6)
        trade["exit_time"]   = exit_time
        trade["pnl_pct"]     = round(pnl, 3)

        icon = "✅ WIN" if result == "WIN" else "❌ LOSS"
        signal_id = trade.get("id", "?")

        # Full transparency log — every number verifiable on Binance/TradingView
        print(f"\n  {'═'*55}")
        print(f"  {icon} TRADE #{signal_id} CLOSED — {trade['symbol']}")
        print(f"  {'═'*55}")
        print(f"  Direction      : {'LONG (BUY)' if is_long else 'SHORT (SELL)'}")
        print(f"  ─────────────────────────────────────────────────────")
        print(f"  ENTRY DETAILS:")
        print(f"    Time         : {trade['entry_time']}")
        print(f"    Price        : ${trade['entry_price']:>14,.6f}")
        print(f"    Timeframe    : {self.config.get('timeframe','15m')} candle")
        print(f"  ─────────────────────────────────────────────────────")
        print(f"  EXIT DETAILS:")
        print(f"    Time         : {exit_time}")
        print(f"    Price        : ${exit_price:>14,.6f}")
        print(f"    Exit reason  : {'TP1 hit' if result=='WIN' else 'SL hit'}")
        print(f"    Candle High  : ${candle_row['high']:>14,.6f}")
        print(f"    Candle Low   : ${candle_row['low']:>14,.6f}")
        print(f"  ─────────────────────────────────────────────────────")
        print(f"  RESULT:")
        print(f"    Outcome      : {result}")
        print(f"    P&L          : {pnl:>+.4f}%")
        print(f"    Duration     : {duration}")
        print(f"  ─────────────────────────────────────────────────────")
        print(f"  VERIFY ON TRADINGVIEW:")
        print(f"    Symbol       : {trade['symbol'].replace('/','')}")
        print(f"    Check candle : {exit_time[:16]}")
        print(f"    Should show  : {'high' if result=='WIN' and is_long else 'low'} of ${exit_price:,.4f}")
        print(f"  {'═'*55}")

        stats = self._get_stats(all_trades)

        if self.telegram:
            self._send_result_alert(trade, exit_price, pnl, duration, result, stats, candle_row)

        if stats["total"] > 0 and stats["total"] % 10 == 0:
            if self.telegram:
                self._send_report_alert(stats)

    def _get_duration(self, entry_time_str, exit_time_str):
        try:
            entry = pd.Timestamp(entry_time_str)
            exit_ = pd.Timestamp(exit_time_str)
            diff  = exit_ - entry
            hours = int(diff.total_seconds() // 3600)
            mins  = int((diff.total_seconds() % 3600) // 60)
            if hours > 0:
                return f"{hours}h {mins}m"
            return f"{mins}m"
        except Exception:
            return "unknown"

    def _get_stats(self, all_trades):
        closed = [t for t in all_trades if t.get("result")]
        total  = len(closed)
        wins   = [t for t in closed if t["result"] == "WIN"]
        losses = [t for t in closed if t["result"] == "LOSS"]
        wr     = len(wins) / total * 100 if total > 0 else 0
        gw     = sum(abs(t.get("pnl_pct", 0)) for t in wins)
        gl     = sum(abs(t.get("pnl_pct", 0)) for t in losses)
        pf     = round(gw / gl, 2) if gl > 0 else float("inf")
        net    = sum(t.get("pnl_pct", 0) for t in closed)
        last5  = closed[-5:] if len(closed) >= 5 else closed
        streak = "".join("✅" if t["result"]=="WIN" else "❌" for t in last5)
        return {
            "total":    total,
            "wins":     len(wins),
            "losses":   len(losses),
            "win_rate": round(wr, 1),
            "pf":       pf,
            "net_pnl":  round(net, 2),
            "streak":   streak,
        }

    def _send_result_alert(self, trade, exit_price, pnl, duration, result, stats, candle_row):
        symbol    = trade["symbol"]
        direction = trade["direction"]
        is_win    = result == "WIN"
        icon      = "✅" if is_win else "❌"
        header    = "WIN" if is_win else "LOSS"
        pnl_icon  = "📈" if pnl > 0 else "📉"
        wr        = stats["win_rate"]
        wr_icon   = "🟢" if wr >= 60 else "🟡" if wr >= 50 else "🔴"
        pf        = stats["pf"]
        pf_str    = f"{pf:.2f}" if pf != float("inf") else "∞"
        direction_str = "🟢 LONG" if direction=="BUY" else "🔴 SHORT"

        msg = (
            f"{icon} <b>{header} — {symbol}</b>\n"
            f"{direction_str} trade closed\n"
            f"🆔 Signal ID: <b>#{signal_id}</b> ← matches your signal message\n\n"

            f"📋 <b>ENTRY (verify on Binance)</b>\n"
            f"🕐 Time  : {trade['entry_time'][:19]}\n"
            f"💰 Price : <b>${trade['entry_price']:,.4f}</b>\n\n"

            f"📋 <b>EXIT (verify on Binance)</b>\n"
            f"🕐 Time  : {trade.get('exit_time','')[:19]}\n"
            f"🏁 Price : <b>${exit_price:,.4f}</b>\n"
            f"📊 Candle High : ${candle_row['high']:,.4f}\n"
            f"📊 Candle Low  : ${candle_row['low']:,.4f}\n\n"

            f"{pnl_icon} <b>P&L : {pnl:+.4f}%</b>\n"
            f"⏱ Duration : {duration}\n"
            f"🔍 Exit reason : {'TP1 hit' if result=='WIN' else 'SL hit'}\n\n"

            f"────────────────────\n"
            f"📊 <b>Running Stats</b>\n"
            f"{wr_icon} Win Rate     : <b>{wr}%</b> ({stats['wins']}W/{stats['losses']}L)\n"
            f"⚖️ Prof.Factor : {pf_str}\n"
            f"💹 Net P&L    : {stats['net_pnl']:+.2f}%\n"
            f"📋 Total      : {stats['total']} trades\n"
            f"🔥 Last 5     : {stats['streak']}\n"
        )

        if wr >= 60 and pf >= 1.5:
            msg += "\n✅ <i>Strategy performing well</i>"
        elif wr >= 50 and pf >= 1.0:
            msg += "\n⚠️ <i>Marginal — watch fees</i>"
        else:
            msg += "\n🔴 <i>Below target — review signals</i>"

        self.telegram.send(msg)
        print(f"    [Telegram] Result alert sent")

    def _send_report_alert(self, stats):
        wr     = stats["win_rate"]
        pf     = stats["pf"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        wr_icon = "🟢" if wr >= 60 else "🟡" if wr >= 50 else "🔴"

        if wr >= 60 and pf >= 1.5:
            verdict = "✅ Strategy working. Keep running."
        elif wr >= 50 and pf >= 1.0:
            verdict = "⚠️ Marginal. Watch fees."
        else:
            verdict = "🔴 Not profitable. Review entries."

        msg = (
            f"📊 <b>{stats['total']}-TRADE REPORT</b>\n\n"
            f"{wr_icon} Win Rate     : <b>{wr}%</b>\n"
            f"   Wins        : {stats['wins']}\n"
            f"   Losses      : {stats['losses']}\n"
            f"⚖️ Prof.Factor : {pf_str}\n"
            f"💹 Net P&L    : {stats['net_pnl']:+.2f}%\n"
            f"🔥 Last 5     : {stats['streak']}\n\n"
            f"<b>Verdict:</b> {verdict}"
        )
        self.telegram.send(msg)

    def place_order(self, symbol, direction, price, levels):
        if not self.config.get("auto_trade"):
            return
        if not self.config.get("binance_key"):
            print("    [Trader] No API key")
            return
        try:
            side    = "buy" if direction=="BUY" else "sell"
            sl_side = "sell" if side=="buy" else "buy"
            qty     = round(levels["position_usdt"] / price, 4)
            lev     = self.config.get("max_leverage", 3)
            self.exchange.set_leverage(lev, symbol)
            order = self.exchange.create_market_order(symbol, side, qty)
            print(f"    [Trader] ✅ ORDER: {side.upper()} {qty} {symbol}  ID:{order['id']}")
            time.sleep(0.5)
            self.exchange.create_order(symbol, "stop_market", sl_side, qty,
                params={"stopPrice": levels["sl"], "reduceOnly": True})
            self.exchange.create_order(symbol, "take_profit_market", sl_side, qty,
                params={"stopPrice": levels["tp1"], "reduceOnly": True})
        except ccxt.InsufficientFunds:
            print("    [Trader] ❌ Not enough balance")
        except ccxt.InvalidOrder as e:
            print(f"    [Trader] ❌ Invalid order: {e}")
        except ccxt.AuthenticationError:
            print("    [Trader] ❌ Wrong API key")
        except Exception as e:
            print(f"    [Trader] ❌ Failed: {e}")
