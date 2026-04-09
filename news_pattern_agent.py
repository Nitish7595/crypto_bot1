"""
news_pattern_agent.py
══════════════════════
News Pattern Recognition + Historical Correlation Engine

WHAT THIS ACTUALLY DOES:
  1. Fetches real news headlines every scan
  2. Classifies each headline into a category
     (macro policy, regulation, hack, adoption, etc)
  3. Searches memory for similar past news events
  4. Checks what price actually did after those events
  5. Predicts direction based on real historical patterns
  6. After each trade closes — saves the real outcome
     so the bot learns from actual results over time

HONEST LIMITS:
  - Starts with zero memory. Gets smarter after 20-30 events.
  - First week: predictions based on built-in base patterns
  - After 1 month: predictions based on YOUR real trade history
  - Still not 100% accurate — news can always surprise
  - Works best combined with technical signals

MEMORY FILE: news_pattern_memory.json
  Grows over time. Never delete it — it is the bot learning.
"""

import json
import os
import re
import requests
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════
# NEWS CATEGORIES
# Every headline gets classified into one of these
# ═══════════════════════════════════════════════════════

CATEGORIES = {

    # ── MACRO ECONOMIC ─────────────────────────────────
    "FED_RATE_HIKE": {
        "keywords": ["fed rate hike","interest rate hike","rate increase",
                     "federal reserve raise","tightening monetary"],
        "base_sentiment": "BEARISH",
        "base_impact":    -3.5,
        "description":    "Fed raises rates — historically bearish for crypto",
    },
    "FED_RATE_CUT": {
        "keywords": ["fed rate cut","interest rate cut","rate decrease",
                     "federal reserve cut","easing monetary","pivot"],
        "base_sentiment": "BULLISH",
        "base_impact":    +4.0,
        "description":    "Fed cuts rates — historically bullish for crypto",
    },
    "INFLATION_HIGH": {
        "keywords": ["inflation high","cpi above","inflation rose",
                     "price surge","inflation hits"],
        "base_sentiment": "BEARISH",
        "base_impact":    -2.0,
        "description":    "High inflation — uncertainty for risk assets",
    },
    "RECESSION_FEAR": {
        "keywords": ["recession","economic downturn","gdp falls",
                     "job losses","unemployment rises"],
        "base_sentiment": "BEARISH",
        "base_impact":    -3.0,
        "description":    "Recession fears — risk-off sentiment",
    },

    # ── REGULATION ─────────────────────────────────────
    "REGULATION_BAN": {
        "keywords": ["crypto ban","bitcoin ban","exchange shutdown",
                     "government ban","crypto illegal","crackdown"],
        "base_sentiment": "BEARISH",
        "base_impact":    -6.0,
        "description":    "Crypto ban news — strong bearish impact",
    },
    "REGULATION_POSITIVE": {
        "keywords": ["crypto regulation approved","legal framework",
                     "crypto legal","regulatory clarity","approved framework"],
        "base_sentiment": "BULLISH",
        "base_impact":    +3.5,
        "description":    "Positive regulation — institutional confidence",
    },
    "SEC_ACTION": {
        "keywords": ["sec lawsuit","sec charges","sec investigation",
                     "securities violation","sec enforcement"],
        "base_sentiment": "BEARISH",
        "base_impact":    -4.0,
        "description":    "SEC action — legal uncertainty bearish",
    },
    "ETF_APPROVAL": {
        "keywords": ["etf approved","etf launch","bitcoin etf","spot etf",
                     "etf filing approved","sec approves etf"],
        "base_sentiment": "BULLISH",
        "base_impact":    +8.0,
        "description":    "ETF approval — major institutional demand signal",
    },

    # ── EXCHANGE / MARKET ───────────────────────────────
    "EXCHANGE_HACK": {
        "keywords": ["exchange hacked","stolen crypto","security breach",
                     "funds stolen","exploit","hack attack"],
        "base_sentiment": "BEARISH",
        "base_impact":    -5.0,
        "description":    "Exchange hack — trust damage, panic selling",
    },
    "EXCHANGE_COLLAPSE": {
        "keywords": ["exchange bankrupt","exchange collapse","exchange insolvent",
                     "withdrawal frozen","exchange fails","ftx","celsius","blockfi"],
        "base_sentiment": "BEARISH",
        "base_impact":    -8.0,
        "description":    "Exchange collapse — systemic fear",
    },
    "EXCHANGE_LISTING": {
        "keywords": ["listed on binance","listed on coinbase","new listing",
                     "exchange listing","coinbase lists"],
        "base_sentiment": "BULLISH",
        "base_impact":    +5.0,
        "description":    "Major exchange listing — increased liquidity",
    },

    # ── INSTITUTIONAL ───────────────────────────────────
    "INSTITUTIONAL_BUY": {
        "keywords": ["buys bitcoin","adds bitcoin","invests in crypto",
                     "bitcoin treasury","institutional purchase",
                     "microstrategy","blackrock buys"],
        "base_sentiment": "BULLISH",
        "base_impact":    +4.5,
        "description":    "Institutional buying — strong demand signal",
    },
    "INSTITUTIONAL_SELL": {
        "keywords": ["sells bitcoin","dumps crypto","reduces holdings",
                     "bitcoin selloff","institutional selling"],
        "base_sentiment": "BEARISH",
        "base_impact":    -3.5,
        "description":    "Institutional selling — supply pressure",
    },
    "WHALE_MOVEMENT": {
        "keywords": ["whale moves","large transfer","billion moved",
                     "whale alert","large wallet"],
        "base_sentiment": "NEUTRAL",
        "base_impact":    -1.5,
        "description":    "Whale movement — potential sell pressure",
    },

    # ── TECHNOLOGY ──────────────────────────────────────
    "NETWORK_UPGRADE": {
        "keywords": ["network upgrade","hard fork","protocol upgrade",
                     "mainnet launch","major update","ethereum upgrade"],
        "base_sentiment": "BULLISH",
        "base_impact":    +3.0,
        "description":    "Network upgrade — positive development signal",
    },
    "NETWORK_ISSUE": {
        "keywords": ["network down","blockchain congestion","node failure",
                     "network attack","51% attack","congestion"],
        "base_sentiment": "BEARISH",
        "base_impact":    -4.0,
        "description":    "Network issue — trust and utility concern",
    },

    # ── MARKET SENTIMENT ───────────────────────────────
    "BULL_MARKET_SIGNAL": {
        "keywords": ["bull run","all time high","ath","new record",
                     "bitcoin rally","crypto surge","moon"],
        "base_sentiment": "BULLISH",
        "base_impact":    +2.5,
        "description":    "Bull market signals — momentum continuation",
    },
    "BEAR_MARKET_SIGNAL": {
        "keywords": ["bear market","crypto winter","market crash",
                     "bitcoin crash","sell off","bloodbath"],
        "base_sentiment": "BEARISH",
        "base_impact":    -3.0,
        "description":    "Bear market signals — momentum continuation",
    },
    "ADOPTION_NEWS": {
        "keywords": ["accepts bitcoin","crypto payment","adopts blockchain",
                     "partnership","integration","accepts crypto"],
        "base_sentiment": "BULLISH",
        "base_impact":    +2.0,
        "description":    "Adoption news — real world utility signal",
    },
}


# ═══════════════════════════════════════════════════════
# NEWS PATTERN AGENT
# ═══════════════════════════════════════════════════════

class NewsPatternAgent:

    def __init__(self, config):
        self.config      = config
        self.memory_file = "news_pattern_memory.json"
        self.memory      = self._load_memory()
        self.anthropic_key = config.get("anthropic_key", "")

    # ──────────────────────────────────────────────────
    # MEMORY — saves all news events + real outcomes
    # ──────────────────────────────────────────────────

    def _load_memory(self):
        if os.path.exists(self.memory_file):
            with open(self.memory_file) as f:
                return json.load(f)
        return {
            "events":      [],   # all past news events with outcomes
            "total_events": 0,
            "started":     str(datetime.now()),
        }

    def save_memory(self):
        with open(self.memory_file, "w") as f:
            json.dump(self.memory, f, indent=2)

    # ──────────────────────────────────────────────────
    # STEP 1 — FETCH REAL NEWS
    # ──────────────────────────────────────────────────

    def fetch_news(self, coin_name, hours_back=6):
        key = self.config.get("news_api_key", "")
        if not key:
            return []
        try:
            r = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q":        f"{coin_name} OR bitcoin OR crypto",
                    "sortBy":   "publishedAt",
                    "pageSize": 20,
                    "language": "en",
                    "from":     (datetime.now()-timedelta(hours=hours_back)
                                 ).strftime("%Y-%m-%dT%H:%M:%S"),
                    "apiKey":   key,
                },
                timeout=10
            )
            if r.status_code == 200:
                articles = r.json().get("articles", [])
                return [
                    {
                        "title":       a.get("title", ""),
                        "description": a.get("description", ""),
                        "source":      a.get("source", {}).get("name", ""),
                        "published":   a.get("publishedAt", ""),
                    }
                    for a in articles if a.get("title")
                ]
            return []
        except Exception as e:
            print(f"    [News] Fetch error: {e}")
            return []

    # ──────────────────────────────────────────────────
    # STEP 2 — CLASSIFY HEADLINE INTO CATEGORY
    # ──────────────────────────────────────────────────

    def classify_headline(self, headline):
        headline_lower = headline.lower()
        matches = []

        for cat_name, cat_data in CATEGORIES.items():
            for keyword in cat_data["keywords"]:
                if keyword in headline_lower:
                    matches.append((cat_name, cat_data))
                    break

        if not matches:
            return None, None

        # Return the most specific match (longest keyword match)
        return matches[0]

    def classify_with_ai(self, headlines_text):
        """Use Claude to classify news if API key available — more accurate."""
        if not self.anthropic_key:
            return None

        categories_list = "\n".join(
            f"  {name}: {data['description']}"
            for name, data in CATEGORIES.items()
        )

        prompt = f"""You are a crypto market news analyst.
Classify these news headlines into categories and predict market impact.

AVAILABLE CATEGORIES:
{categories_list}

HEADLINES:
{headlines_text}

For each headline respond with JSON only — no explanation:
[
  {{
    "headline": "first 50 chars of headline",
    "category": "CATEGORY_NAME or UNKNOWN",
    "sentiment": "BULLISH or BEARISH or NEUTRAL",
    "impact_score": number from -10 to +10,
    "confidence": 0-100
  }}
]"""

        try:
            import requests as req
            r = req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      "claude-haiku-4-5-20251001",
                    "max_tokens": 500,
                    "messages":   [{"role": "user", "content": prompt}]
                },
                timeout=20
            )
            if r.status_code == 200:
                text  = r.json()["content"][0]["text"].strip()
                start = text.find("[")
                end   = text.rfind("]") + 1
                if start != -1:
                    return json.loads(text[start:end])
        except Exception as e:
            print(f"    [News AI] Classification error: {e}")
        return None

    # ──────────────────────────────────────────────────
    # STEP 3 — SEARCH MEMORY FOR SIMILAR PAST EVENTS
    # ──────────────────────────────────────────────────

    def find_similar_events(self, category, symbol, lookback=50):
        """
        Searches past events with the same category and symbol.
        Returns events that have a recorded real outcome.
        """
        similar = [
            e for e in self.memory["events"]
            if e.get("category") == category
            and e.get("symbol") == symbol
            and e.get("real_outcome") is not None
        ]
        # Most recent first
        similar = sorted(similar, key=lambda e: e.get("timestamp",""), reverse=True)
        return similar[:lookback]

    # ──────────────────────────────────────────────────
    # STEP 4 — CALCULATE PATTERN FROM HISTORY
    # ──────────────────────────────────────────────────

    def calculate_pattern(self, similar_events, base_impact):
        """
        From past similar events, calculates:
        - How often the expected outcome happened (accuracy %)
        - Average price change when it did happen
        - Confidence based on number of data points
        """
        if not similar_events:
            # No history — use base pattern from category definition
            return {
                "source":       "BASE_PATTERN",
                "data_points":  0,
                "accuracy":     50,
                "avg_impact":   base_impact,
                "confidence":   30,   # low confidence — no real data
                "note":         "No historical data yet — using base pattern",
            }

        total      = len(similar_events)
        # Count how many times direction matched expected
        expected   = "positive" if base_impact > 0 else "negative"
        correct    = sum(
            1 for e in similar_events
            if (e["real_outcome"] > 0 and expected == "positive")
            or (e["real_outcome"] < 0 and expected == "negative")
        )
        accuracy   = round(correct / total * 100, 1)
        avg_impact = round(
            sum(e["real_outcome"] for e in similar_events) / total, 2
        )

        # Confidence grows with more data points
        # 5 events = 50% confidence, 20 events = 80% confidence, 50+ = 95%
        confidence = min(95, 30 + (total * 2.5))

        return {
            "source":       "HISTORICAL",
            "data_points":  total,
            "accuracy":     accuracy,
            "avg_impact":   avg_impact,
            "confidence":   round(confidence, 1),
            "note":         f"Based on {total} similar past events",
            "recent":       [
                {
                    "date":    e.get("timestamp","")[:10],
                    "outcome": f"{e['real_outcome']:+.2f}%"
                }
                for e in similar_events[:5]
            ],
        }

    # ──────────────────────────────────────────────────
    # STEP 5 — MAKE PREDICTION
    # ──────────────────────────────────────────────────

    def predict(self, pattern, category_data):
        """
        Converts pattern data into a trading prediction.
        """
        avg_impact = pattern["avg_impact"]
        confidence = pattern["confidence"]
        accuracy   = pattern["accuracy"]

        # Need at least 55% historical accuracy to signal
        if pattern["data_points"] >= 5 and accuracy < 45:
            return {
                "direction":  "HOLD",
                "confidence": confidence,
                "reason":     f"Historical accuracy only {accuracy}% — not reliable",
            }

        # Direction from average historical impact
        if avg_impact > 0.5:
            direction = "BUY"
            strength  = "STRONG" if avg_impact > 3 else "MODERATE"
        elif avg_impact < -0.5:
            direction = "SELL"
            strength  = "STRONG" if avg_impact < -3 else "MODERATE"
        else:
            direction = "HOLD"
            strength  = "WEAK"

        # Reduce confidence if accuracy is borderline
        if accuracy < 60 and pattern["data_points"] >= 5:
            confidence = confidence * 0.7

        return {
            "direction":      direction,
            "strength":       strength,
            "confidence":     round(confidence, 1),
            "expected_move":  avg_impact,
            "accuracy":       accuracy,
            "data_points":    pattern["data_points"],
            "source":         pattern["source"],
            "reason":         pattern["note"],
        }

    # ──────────────────────────────────────────────────
    # STEP 6 — SAVE EVENT TO MEMORY (without outcome yet)
    # ──────────────────────────────────────────────────

    def save_event(self, symbol, category, headline, prediction, price_at_event):
        event = {
            "id":              len(self.memory["events"]) + 1,
            "timestamp":       str(datetime.now()),
            "symbol":          symbol,
            "category":        category,
            "headline":        headline[:100],
            "prediction":      prediction["direction"],
            "confidence":      prediction["confidence"],
            "price_at_event":  price_at_event,
            "real_outcome":    None,   # filled in later by record_outcome()
            "outcome_time":    None,
        }
        self.memory["events"].append(event)
        self.memory["total_events"] = len(self.memory["events"])
        self.save_memory()
        return event["id"]

    # ──────────────────────────────────────────────────
    # STEP 7 — RECORD REAL OUTCOME AFTER TRADE CLOSES
    # This is how the bot learns over time
    # ──────────────────────────────────────────────────

    def record_outcome(self, event_id, price_now):
        """
        Called after a trade closes.
        Calculates real % change and saves to memory.
        Bot learns from this for future predictions.
        """
        for event in self.memory["events"]:
            if event["id"] == event_id and event["real_outcome"] is None:
                price_then   = event["price_at_event"]
                real_outcome = round(
                    (price_now - price_then) / price_then * 100, 3
                )
                event["real_outcome"] = real_outcome
                event["outcome_time"] = str(datetime.now())

                # Was prediction correct?
                predicted_bull = event["prediction"] == "BUY"
                outcome_bull   = real_outcome > 0
                correct        = predicted_bull == outcome_bull

                event["prediction_correct"] = correct
                self.save_memory()

                print(f"    [News Pattern] Event #{event_id} outcome recorded: {real_outcome:+.2f}%  Prediction {'✅ CORRECT' if correct else '❌ WRONG'}")
                return real_outcome
        return None

    # ──────────────────────────────────────────────────
    # MAIN ANALYSE — combines everything
    # ──────────────────────────────────────────────────

    def analyse(self, symbol, current_price):
        coin       = symbol.split("/")[0]
        coin_names = {"BTC":"Bitcoin","ETH":"Ethereum","SOL":"Solana","BNB":"BNB"}
        coin_name  = coin_names.get(coin, coin)

        print(f"    [News Pattern] Analysing news for {symbol}...")

        # Fetch real news
        articles = self.fetch_news(coin_name)
        if not articles:
            print(f"    [News Pattern] No news found — need NEWS_API_KEY")
            return None

        print(f"    [News Pattern] {len(articles)} articles fetched")

        # Try AI classification first
        headlines_text = "\n".join(
            f"- {a['title']}" for a in articles[:10]
        )
        ai_classifications = self.classify_with_ai(headlines_text)

        # Process each article
        significant_events = []

        for article in articles[:10]:
            headline = article["title"]

            # Use AI classification if available
            ai_class = None
            if ai_classifications:
                for ac in ai_classifications:
                    if ac.get("headline","") in headline[:50]:
                        ai_class = ac
                        break

            if ai_class and ai_class.get("category") != "UNKNOWN":
                cat_name   = ai_class["category"]
                cat_data   = CATEGORIES.get(cat_name)
                sentiment  = ai_class.get("sentiment", "NEUTRAL")
                confidence = ai_class.get("confidence", 50)
                if not cat_data:
                    continue
            else:
                # Fall back to keyword classification
                cat_name, cat_data = self.classify_headline(headline)
                if not cat_name:
                    continue
                sentiment  = cat_data["base_sentiment"]
                confidence = 60

            # Find historical patterns
            similar        = self.find_similar_events(cat_name, symbol)
            pattern        = self.calculate_pattern(similar, cat_data["base_impact"])
            prediction     = self.predict(pattern, cat_data)

            if prediction["direction"] == "HOLD":
                continue

            significant_events.append({
                "headline":    headline,
                "category":    cat_name,
                "description": cat_data["description"],
                "sentiment":   sentiment,
                "prediction":  prediction,
                "pattern":     pattern,
            })

            print(f"    [News Pattern] 📰 {cat_name}: {prediction['direction']} ({prediction['confidence']:.0f}% conf) — {pattern['note']}")

        if not significant_events:
            print(f"    [News Pattern] No significant news patterns found")
            return None

        # Aggregate all event predictions
        buy_score  = sum(
            e["prediction"]["confidence"]
            for e in significant_events
            if e["prediction"]["direction"] == "BUY"
        )
        sell_score = sum(
            e["prediction"]["confidence"]
            for e in significant_events
            if e["prediction"]["direction"] == "SELL"
        )

        total_score = buy_score + sell_score
        if total_score == 0:
            return None

        if buy_score > sell_score:
            final_direction = "BUY"
            final_confidence = round(buy_score / total_score * 100, 1)
        else:
            final_direction = "SELL"
            final_confidence = round(sell_score / total_score * 100, 1)

        # Save significant events to memory
        saved_ids = []
        for event in significant_events[:3]:
            event_id = self.save_event(
                symbol,
                event["category"],
                event["headline"],
                event["prediction"],
                current_price
            )
            saved_ids.append(event_id)

        # Build summary
        top_event   = significant_events[0]
        data_points = top_event["pattern"]["data_points"]
        accuracy    = top_event["pattern"]["accuracy"]

        result = {
            "agent":          "News Pattern",
            "vote":           final_direction,
            "confidence":     final_confidence,
            "reason":         f"{len(significant_events)} news events — {accuracy}% hist. accuracy on {data_points} past events",
            "events":         significant_events[:3],
            "saved_ids":      saved_ids,
            "buy_score":      buy_score,
            "sell_score":     sell_score,
        }

        print(f"    [News Pattern] → {final_direction} ({final_confidence:.0f}% confidence)")
        return result

    # ──────────────────────────────────────────────────
    # ACCURACY REPORT — how well news predictions worked
    # ──────────────────────────────────────────────────

    def get_accuracy_report(self):
        events_with_outcome = [
            e for e in self.memory["events"]
            if e.get("real_outcome") is not None
        ]
        total   = len(events_with_outcome)
        if total == 0:
            return None

        correct = sum(1 for e in events_with_outcome if e.get("prediction_correct"))
        accuracy = round(correct / total * 100, 1)

        # By category
        by_cat = {}
        for e in events_with_outcome:
            cat = e.get("category", "UNKNOWN")
            if cat not in by_cat:
                by_cat[cat] = {"correct": 0, "total": 0}
            by_cat[cat]["total"] += 1
            if e.get("prediction_correct"):
                by_cat[cat]["correct"] += 1

        best_cat = max(by_cat, key=lambda c: by_cat[c]["correct"]/by_cat[c]["total"])

        return {
            "total":    total,
            "correct":  correct,
            "accuracy": accuracy,
            "by_category": by_cat,
            "best_category": best_cat,
        }
