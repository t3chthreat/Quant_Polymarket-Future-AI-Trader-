"""
bot/price_feed.py — Live Crypto Price Feed (CoinGecko — Free, No API Key)

Fetches real-time BTC, ETH, SOL spot prices to:
  1. Calculate momentum signals (is price trending up or down?)
  2. Calibrate our YES/NO probability estimate vs Polymarket's current odds
  3. Detect divergence between Polymarket price and true probability
     → Divergence = edge → take the position the market is mispricing
"""
import time
import statistics
import requests
from typing import Optional

# CoinGecko free API — no key needed, rate limit ~30 req/min
COINGECKO_URL = "https://api.coingecko.com/api/v3"

ASSET_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}

# How many price samples to keep per asset for momentum calculation
HISTORY_LIMIT = 30


class PriceFeed:
    """
    Fetches and caches live spot prices for BTC, ETH, SOL.
    Computes momentum, volatility, and divergence signals.
    """

    def __init__(self):
        self._prices: dict[str, list[float]] = {a: [] for a in ASSET_IDS}
        self._last_fetch: float = 0
        self._fetch_interval: int = 20   # seconds between API calls
        self._last_prices: dict[str, float] = {}

    # ── Data Fetching ─────────────────────────────────────────────────────────

    def fetch(self) -> dict[str, float]:
        """
        Fetch current prices for all three assets in one API call.
        Returns dict like: {'BTC': 84200.0, 'ETH': 1950.0, 'SOL': 115.0}
        """
        ids = ",".join(ASSET_IDS.values())
        try:
            r = requests.get(
                f"{COINGECKO_URL}/simple/price",
                params={"ids": ids, "vs_currencies": "usd"},
                timeout=8,
            )
            r.raise_for_status()
            data = r.json()

            prices = {}
            for symbol, cg_id in ASSET_IDS.items():
                price = data.get(cg_id, {}).get("usd")
                if price:
                    prices[symbol] = float(price)
                    self._prices[symbol].append(float(price))
                    if len(self._prices[symbol]) > HISTORY_LIMIT:
                        self._prices[symbol].pop(0)

            self._last_prices = prices
            self._last_fetch = time.time()
            return prices

        except Exception as e:
            # Return cached prices if fetch fails
            return self._last_prices

    def get_prices(self) -> dict[str, float]:
        """Return prices, fetching fresh data if cache is stale."""
        if time.time() - self._last_fetch > self._fetch_interval:
            return self.fetch()
        return self._last_prices

    # ── Momentum Signals ──────────────────────────────────────────────────────

    def momentum(self, symbol: str, lookback: int = 5) -> float:
        """
        Simple price momentum over last N samples.
        Returns: positive = bullish, negative = bearish
        Range roughly -1.0 to +1.0
        """
        hist = self._prices.get(symbol, [])
        if len(hist) < lookback + 1:
            return 0.0

        recent = hist[-lookback:]
        first = recent[0]
        last = recent[-1]
        if first == 0:
            return 0.0

        return (last - first) / first   # % change as decimal

    def short_momentum(self, symbol: str) -> float:
        """Last 3 samples — captures very recent move."""
        return self.momentum(symbol, lookback=3)

    def medium_momentum(self, symbol: str) -> float:
        """Last 10 samples — medium-term trend."""
        return self.momentum(symbol, lookback=10)

    def volatility(self, symbol: str) -> float:
        """
        Realized volatility from recent price history.
        Higher = more volatile = wider Polymarket spreads expected.
        """
        hist = self._prices.get(symbol, [])
        if len(hist) < 5:
            return 0.0
        changes = [
            abs(hist[i] - hist[i - 1]) / hist[i - 1]
            for i in range(1, len(hist))
            if hist[i - 1] > 0
        ]
        return statistics.mean(changes) if changes else 0.0

    # ── Polymarket Edge Detection ─────────────────────────────────────────────

    def estimate_up_probability(self, symbol: str, timeframe: str = "15min") -> float:
        """
        Estimate the TRUE probability that price will be UP in given timeframe,
        based on momentum signals. This is our edge vs. Polymarket's quoted price.

        Timeframes: '5min', '15min', '1hr', '1day'

        Returns probability 0.0–1.0 that price ends UP.
        Base is 0.50 (coin flip), adjusted by momentum signals.
        """
        short_mom = self.short_momentum(symbol)
        med_mom = self.medium_momentum(symbol)
        vol = self.volatility(symbol)

        # Momentum influence — caps at ±0.20 adjustment
        # Short-term momentum has more weight for 5/15min markets
        if timeframe in ("5min", "15min"):
            mom_signal = (short_mom * 0.7 + med_mom * 0.3)
            mom_weight = 0.20
        elif timeframe == "1hr":
            mom_signal = (short_mom * 0.3 + med_mom * 0.7)
            mom_weight = 0.15
        else:  # 1day+
            mom_signal = med_mom
            mom_weight = 0.10

        # Scale momentum to probability adjustment (-0.20 to +0.20)
        adjustment = max(-mom_weight, min(mom_weight, mom_signal * 2.0))

        prob = 0.50 + adjustment

        # High volatility pushes toward 50% (harder to predict)
        if vol > 0.002:
            prob = 0.50 + (prob - 0.50) * 0.7

        return round(max(0.20, min(0.80, prob)), 4)

    def edge_vs_market(
        self,
        symbol: str,
        market_yes_price: float,
        timeframe: str = "15min",
    ) -> dict:
        """
        Compare our probability estimate to Polymarket's current YES price.
        Returns the edge, direction, and position recommendation.

        If market says YES = 0.52 but we estimate 0.65 → buy YES
        If market says YES = 0.48 but we estimate 0.30 → buy NO
        """
        our_prob = self.estimate_up_probability(symbol, timeframe)
        edge = our_prob - market_yes_price
        edge_pct = abs(edge)

        if edge_pct < 0.04:
            direction = "NEUTRAL"
            action = "SKIP"
            confidence = "LOW"
        elif edge > 0:
            direction = "UP"
            action = "BUY YES"
            confidence = "HIGH" if edge_pct > 0.10 else "MEDIUM"
        else:
            direction = "DOWN"
            action = "BUY NO"
            confidence = "HIGH" if edge_pct > 0.10 else "MEDIUM"

        return {
            "symbol":           symbol,
            "timeframe":        timeframe,
            "our_probability":  our_prob,
            "market_price":     market_yes_price,
            "edge":             round(edge, 4),
            "edge_pct":         round(edge_pct, 4),
            "direction":        direction,
            "action":           action,
            "confidence":       confidence,
            "short_momentum":   round(self.short_momentum(symbol), 6),
            "medium_momentum":  round(self.medium_momentum(symbol), 6),
            "volatility":       round(self.volatility(symbol), 6),
        }

    def summary(self) -> dict[str, dict]:
        """Return full price + signal summary for all 3 assets."""
        prices = self.get_prices()
        result = {}
        for symbol in ASSET_IDS:
            p = prices.get(symbol, 0.0)
            result[symbol] = {
                "price":            p,
                "short_momentum":   self.short_momentum(symbol),
                "medium_momentum":  self.medium_momentum(symbol),
                "volatility":       self.volatility(symbol),
                "samples":          len(self._prices[symbol]),
            }
        return result
