"""
bot/scanner.py — Crypto Market Scanner

Scans Polymarket for BTC, ETH, SOL volatility/direction markets.
Classifies each market by:
  - Asset (BTC / ETH / SOL)
  - Type: UP/DOWN (15min), Price Target (will X exceed $Y?), Range
  - Timeframe: 5min, 15min, 1hr, 1day, longer
  - Current YES/NO prices
  - Volume and liquidity
"""
import re
import requests
from typing import Optional
import config

# Keywords to identify each asset in market questions
ASSET_KEYWORDS = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth", "ether"],
    "SOL": ["solana", "sol"],
}

# Keywords that indicate a directional up/down market
UP_KEYWORDS   = ["above", "exceed", "higher", "up", "over", "bull", "rise", "gain"]
DOWN_KEYWORDS = ["below", "under", "lower", "down", "fall", "drop", "crash", "bear"]

# Timeframe detection patterns
TIMEFRAME_PATTERNS = [
    (r"\b5[\s-]?min",    "5min"),
    (r"\b15[\s-]?min",   "15min"),
    (r"\b1[\s-]?hr?\b",  "1hr"),
    (r"\b24[\s-]?hr?",   "1day"),
    (r"\bend of day\b",  "1day"),
    (r"\bweek\b",        "1week"),
    (r"\bmonth\b",       "1month"),
    (r"\bquarter\b",     "3month"),
    (r"\byear\b",        "1year"),
]

# Market types we want to trade
TRADEABLE_TYPES = {"UPDOWN_SHORT", "UPDOWN_LONG", "PRICE_TARGET"}


def detect_asset(question: str) -> Optional[str]:
    q = question.lower()
    for asset, keywords in ASSET_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return asset
    return None


def detect_timeframe(question: str) -> str:
    q = question.lower()
    for pattern, label in TIMEFRAME_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            return label
    return "unknown"


def detect_market_type(question: str, timeframe: str) -> str:
    """
    Classify the market into a type:
      UPDOWN_SHORT  — 5min/15min up or down (high frequency)
      UPDOWN_LONG   — daily/weekly directional
      PRICE_TARGET  — will asset hit $X by date?
      RANGE         — will asset stay between $X–$Y?
      UNKNOWN
    """
    q = question.lower()

    # Check for price target pattern (e.g. "Will BTC exceed $90k")
    if re.search(r'\$[\d,]+[k]?', q) or re.search(r'\d{4,}', q):
        if any(kw in q for kw in UP_KEYWORDS + DOWN_KEYWORDS):
            return "PRICE_TARGET"

    # Short timeframe up/down
    if timeframe in ("5min", "15min"):
        return "UPDOWN_SHORT"

    # Longer timeframe directional
    if timeframe in ("1hr", "1day", "1week"):
        if any(kw in q for kw in UP_KEYWORDS + DOWN_KEYWORDS):
            return "UPDOWN_LONG"

    return "UNKNOWN"


def extract_price_target(question: str) -> Optional[float]:
    """Extract the numeric price target from a market question."""
    # Match patterns like $90,000 / $90k / $90K / 90000
    match = re.search(r'\$?([\d,]+)([kK])?', question)
    if match:
        num = match.group(1).replace(",", "")
        try:
            val = float(num)
            if match.group(2):
                val *= 1000
            # Sanity check: BTC > 1000, ETH > 100, SOL > 1
            if val > 1:
                return val
        except ValueError:
            pass
    return None


def parse_outcome_prices(market: dict) -> tuple[float, float]:
    """Parse YES and NO prices from market data."""
    raw = market.get("outcomePrices", "")
    if isinstance(raw, str):
        try:
            import json
            prices = json.loads(raw)
            if len(prices) >= 2:
                return float(prices[0]), float(prices[1])
        except Exception:
            pass

    # Fallback to bestBid/bestAsk
    yes = float(market.get("bestAsk") or market.get("lastTradePrice") or 0.5)
    no = round(1.0 - yes, 4)
    return yes, no


class CryptoMarketScanner:
    """
    Scans Polymarket for BTC/ETH/SOL volatility and directional markets.
    Returns structured, ranked opportunities.
    """

    def __init__(self):
        self.last_markets: list[dict] = []

    def fetch_raw_markets(self, limit: int = 200) -> list[dict]:
        """Pull active markets from Gamma API."""
        try:
            r = requests.get(
                f"{config.GAMMA_API}/markets",
                params={
                    "limit": limit,
                    "active": "true",
                    "closed": "false",
                    "archived": "false",
                },
                timeout=12,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return []

    def scan(self) -> list[dict]:
        """
        Fetch all markets, filter to BTC/ETH/SOL, classify, and rank.
        Returns list of opportunity dicts sorted by score.
        """
        raw = self.fetch_raw_markets()
        opportunities = []

        for m in raw:
            question = m.get("question", "") or m.get("title", "")
            if not question:
                continue

            asset = detect_asset(question)
            if not asset:
                continue

            timeframe = detect_timeframe(question)
            mtype = detect_market_type(question, timeframe)

            if mtype not in TRADEABLE_TYPES:
                continue

            yes_price, no_price = parse_outcome_prices(m)
            if yes_price <= 0 or yes_price >= 1:
                continue

            volume_24h = float(m.get("volume24hr") or m.get("volume") or 0)
            liquidity  = float(m.get("liquidity") or 0)

            # Get token IDs for trading
            tokens = m.get("tokens") or m.get("clobTokenIds") or []
            yes_token_id = None
            no_token_id = None

            if isinstance(tokens, list) and tokens:
                if isinstance(tokens[0], dict):
                    for t in tokens:
                        outcome = t.get("outcome", "").upper()
                        if outcome == "YES":
                            yes_token_id = t.get("token_id") or t.get("id")
                        elif outcome == "NO":
                            no_token_id = t.get("token_id") or t.get("id")
                elif isinstance(tokens[0], str):
                    yes_token_id = tokens[0]
                    no_token_id = tokens[1] if len(tokens) > 1 else None

            # Score for ranking (higher volume = more liquid = better)
            score = self._score(
                mtype=mtype,
                timeframe=timeframe,
                yes_price=yes_price,
                volume_24h=volume_24h,
                liquidity=liquidity,
            )

            opp = {
                "market_id":       m.get("id", ""),
                "question":        question,
                "asset":           asset,
                "timeframe":       timeframe,
                "market_type":     mtype,
                "yes_price":       yes_price,
                "no_price":        no_price,
                "yes_token_id":    yes_token_id,
                "no_token_id":     no_token_id,
                "volume_24h":      volume_24h,
                "liquidity":       liquidity,
                "price_target":    extract_price_target(question),
                "end_date":        m.get("endDate", ""),
                "score":           score,
                "raw":             m,
            }
            opportunities.append(opp)

        opportunities.sort(key=lambda x: x["score"], reverse=True)
        self.last_markets = opportunities
        return opportunities

    def _score(
        self,
        mtype: str,
        timeframe: str,
        yes_price: float,
        volume_24h: float,
        liquidity: float,
    ) -> float:
        """
        Rank markets by trading attractiveness.
        Based on research: higher volume = harder to manipulate = better.
        """
        # Volume score (log scale — $50k daily = 1.0)
        import math
        vol_score = min(math.log10(max(volume_24h, 1)) / math.log10(50000), 1.0)

        # Liquidity score
        liq_score = min(liquidity / 10000, 1.0)

        # Uncertainty score — markets near 50% are most interesting
        uncertainty = 1.0 - abs(yes_price - 0.5) * 2.0

        # Type preference: short-term up/down markets are most active
        type_weight = {
            "UPDOWN_SHORT": 1.0,
            "UPDOWN_LONG": 0.8,
            "PRICE_TARGET": 0.7,
        }.get(mtype, 0.5)

        # Timeframe preference: 15min and 1hr most active
        tf_weight = {
            "5min": 0.9,
            "15min": 1.0,
            "1hr": 0.85,
            "1day": 0.70,
            "1week": 0.55,
        }.get(timeframe, 0.4)

        score = (
            vol_score    * 0.35 +
            liq_score    * 0.20 +
            uncertainty  * 0.25 +
            type_weight  * 0.10 +
            tf_weight    * 0.10
        )
        return round(score, 4)

    def by_asset(self, asset: str) -> list[dict]:
        """Filter last scan results by asset (BTC/ETH/SOL)."""
        return [m for m in self.last_markets if m["asset"] == asset]

    def by_type(self, mtype: str) -> list[dict]:
        """Filter by market type."""
        return [m for m in self.last_markets if m["market_type"] == mtype]

    def top(self, n: int = 10) -> list[dict]:
        """Return top N opportunities across all assets."""
        return self.last_markets[:n]
