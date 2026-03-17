"""
bot/analytics.py — Research-Backed Market Analytics

Implements microstructure metrics from academic research:

1. VPIN (Volume-Synchronized Probability of Informed Trading)
   Source: Easley, O'Hara et al. — "Microstructure and Market Dynamics in Crypto Markets"
   Cornell/SSRN 2024 — https://ssrn.com/abstract=4814346
   
   Key finding: High VPIN = toxic order flow = informed traders are active.
   For market makers, high VPIN means adverse selection risk is elevated —
   widen spreads or stop quoting entirely.

2. Roll Measure
   Source: Same Cornell paper.
   Key finding: High Roll = strong serial autocorrelation = momentum in prices.
   When Roll is elevated, re-quote more aggressively to avoid being stale.

3. Market Quality Score
   Source: "How Manipulable Are Prediction Markets?" — arXiv 2503.03312
   Key finding: Markets with MORE traders and HIGHER volume are harder to 
   manipulate and more suitable for market making. We weight volume and 
   trader count heavily in market selection.

4. Ensemble Signal Gate
   Source: "ML Models for Algorithmic Bitcoin Trading" — arXiv 2407.18334
   Key finding: Random Forest / ensemble approaches outperform single 
   indicators. We simulate this by requiring MULTIPLE favorable signals 
   before quoting — spread is wide AND VPIN is low AND volume is sufficient.
"""

import math
import statistics
from typing import Optional


# ── VPIN Toxicity Score ────────────────────────────────────────────────────────

def compute_vpin(trades: list[dict], bucket_size: int = 50) -> float:
    """
    Estimate VPIN (Volume-Synchronized Probability of Informed Trading).

    VPIN measures the probability that a trade comes from an informed
    (directional) trader vs. an uninformed (noise) trader.

    High VPIN (>0.5) = toxic flow, adverse selection risk is HIGH
    Low VPIN (<0.3)  = safe to quote, mostly noise traders

    Args:
        trades: list of dicts with keys: 'price', 'size', 'side' ('buy'/'sell')
        bucket_size: volume per bucket (lower = more sensitive)

    Returns:
        VPIN score between 0.0 and 1.0
    """
    if not trades or len(trades) < bucket_size:
        return 0.35  # Default to moderate — not enough data

    # Group trades into volume buckets
    buckets = []
    current_buy = 0.0
    current_sell = 0.0
    current_vol = 0.0

    for trade in trades:
        size = float(trade.get("size", 0))
        side = trade.get("side", "buy").lower()

        if side == "buy":
            current_buy += size
        else:
            current_sell += size
        current_vol += size

        if current_vol >= bucket_size:
            order_imbalance = abs(current_buy - current_sell) / current_vol
            buckets.append(order_imbalance)
            current_buy = 0.0
            current_sell = 0.0
            current_vol = 0.0

    if not buckets:
        return 0.35

    return min(statistics.mean(buckets), 1.0)


def classify_vpin(vpin: float) -> tuple[str, str]:
    """
    Classify VPIN into trading zones.
    Returns (zone, action_recommendation)
    """
    if vpin < 0.30:
        return "LOW", "Safe to quote — uninformed flow dominates"
    elif vpin < 0.45:
        return "MODERATE", "Quote with normal spreads"
    elif vpin < 0.60:
        return "ELEVATED", "Widen spreads by 50% — informed traders present"
    else:
        return "TOXIC", "Do not quote — high adverse selection risk"


# ── Roll Measure (Price Autocorrelation / Momentum) ───────────────────────────

def compute_roll_measure(prices: list[float]) -> float:
    """
    Compute the Roll Measure — captures serial autocorrelation in price changes.

    From Cornell paper: High Roll = strong momentum = market makers must
    re-quote more frequently to avoid stale prices.

    Formula: Roll = 2 * sqrt(max(-cov(dp_t, dp_{t-1}), 0))

    Args:
        prices: list of recent trade prices (at least 10 needed)

    Returns:
        Roll measure (>0.02 = significant momentum present)
    """
    if len(prices) < 10:
        return 0.0

    # Compute price changes
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    if len(changes) < 2:
        return 0.0

    # Compute covariance between consecutive changes
    n = len(changes) - 1
    mean1 = statistics.mean(changes[:-1])
    mean2 = statistics.mean(changes[1:])

    cov = sum(
        (changes[i] - mean1) * (changes[i + 1] - mean2)
        for i in range(n)
    ) / n

    # Roll measure = 2 * sqrt(-cov) when cov is negative
    if cov < 0:
        return 2.0 * math.sqrt(-cov)
    return 0.0


def spread_adjustment_from_roll(roll: float, base_spread: float) -> float:
    """
    Adjust quote aggression based on Roll measure momentum signal.
    High Roll = fast-moving market = be less aggressive (wider quotes).
    """
    if roll > 0.03:
        return base_spread * 1.5   # Widen — high momentum, stale risk
    elif roll > 0.015:
        return base_spread * 1.2   # Slightly wider
    return base_spread             # Normal


# ── Ensemble Signal Gate (inspired by ML paper findings) ─────────────────────

class EnsembleSignalGate:
    """
    Multi-signal gate before quoting — inspired by the finding that
    ensemble/multi-condition approaches outperform single indicators.

    Requires MULTIPLE green lights before placing orders:
      1. Spread is wide enough (profit opportunity exists)
      2. VPIN is below threshold (flow is not toxic)
      3. Volume is sufficient (market is liquid enough)
      4. Roll measure is not too high (market not in runaway momentum)
      5. Price is not near resolution boundary (avoid 0.01 or 0.99)
    """

    def __init__(
        self,
        min_spread: float = 0.04,
        max_vpin: float = 0.55,
        min_volume_24h: float = 500.0,
        max_roll: float = 0.05,
        boundary_buffer: float = 0.06,
        required_signals: int = 4,   # out of 5 must pass
    ):
        self.min_spread = min_spread
        self.max_vpin = max_vpin
        self.min_volume_24h = min_volume_24h
        self.max_roll = max_roll
        self.boundary_buffer = boundary_buffer
        self.required_signals = required_signals

    def evaluate(
        self,
        spread: float,
        mid_price: float,
        vpin: float,
        volume_24h: float,
        roll: float,
    ) -> tuple[bool, list[dict]]:
        """
        Run all 5 signals. Returns (go/no-go, signal report).
        """
        signals = [
            {
                "name": "Spread Width",
                "pass": spread >= self.min_spread,
                "value": f"{spread:.2%}",
                "threshold": f">= {self.min_spread:.2%}",
                "weight": "Profit exists in the spread",
            },
            {
                "name": "VPIN Toxicity",
                "pass": vpin <= self.max_vpin,
                "value": f"{vpin:.3f}",
                "threshold": f"<= {self.max_vpin:.3f}",
                "weight": "Flow is not adversely informed",
            },
            {
                "name": "Volume (24h)",
                "pass": volume_24h >= self.min_volume_24h,
                "value": f"${volume_24h:,.0f}",
                "threshold": f">= ${self.min_volume_24h:,.0f}",
                "weight": "Market is liquid enough",
            },
            {
                "name": "Roll Momentum",
                "pass": roll <= self.max_roll,
                "value": f"{roll:.4f}",
                "threshold": f"<= {self.max_roll:.4f}",
                "weight": "Market not in runaway momentum",
            },
            {
                "name": "Price Boundary",
                "pass": self.boundary_buffer < mid_price < (1.0 - self.boundary_buffer),
                "value": f"{mid_price:.4f}",
                "threshold": f"{self.boundary_buffer:.2f} < p < {1 - self.boundary_buffer:.2f}",
                "weight": "Not near resolution edge (0 or 1)",
            },
        ]

        passed = sum(1 for s in signals if s["pass"])
        go = passed >= self.required_signals

        return go, signals

    def vpin_spread_multiplier(self, vpin: float) -> float:
        """
        Scale spread width based on VPIN toxicity level.
        As VPIN rises, we demand a wider spread to compensate for adverse selection.
        """
        if vpin < 0.30:
            return 1.0    # Normal
        elif vpin < 0.45:
            return 1.25   # Widen 25%
        elif vpin < 0.55:
            return 1.60   # Widen 60%
        else:
            return 999.0  # Effectively block quoting


# ── Market Quality Score ───────────────────────────────────────────────────────

def market_quality_score(
    spread: float,
    mid_price: float,
    volume_24h: float,
    num_traders: int = 0,
    vpin: float = 0.35,
    roll: float = 0.0,
) -> float:
    """
    Composite market quality score for ranking candidate markets.

    Factors (weighted by research importance):
      - Spread width:       40% — direct profit opportunity
      - Volume / liquidity: 25% — harder-to-manipulate markets (arXiv 2503.03312)
      - Proximity to 0.5:  20% — maximum uncertainty = most activity
      - VPIN (inverted):   10% — lower toxicity = safer for MM
      - Roll (inverted):    5% — lower momentum = more stable quotes

    Returns score 0.0–1.0 (higher = better market making opportunity)
    """
    # Spread score (capped at 15% spread = 1.0)
    spread_score = min(spread / 0.15, 1.0)

    # Volume score (capped at $5k daily = 1.0)
    volume_score = min(volume_24h / 5000.0, 1.0)

    # Proximity to 50% probability
    proximity_score = 1.0 - abs(mid_price - 0.5) * 2.0
    proximity_score = max(proximity_score, 0.0)

    # VPIN inverted (lower VPIN = higher score)
    vpin_score = max(1.0 - (vpin / 0.6), 0.0)

    # Roll inverted (lower momentum = higher score)
    roll_score = max(1.0 - (roll / 0.05), 0.0)

    score = (
        spread_score   * 0.40 +
        volume_score   * 0.25 +
        proximity_score * 0.20 +
        vpin_score     * 0.10 +
        roll_score     * 0.05
    )

    return round(min(score, 1.0), 4)


# ── Price History Tracker ──────────────────────────────────────────────────────

class PriceTracker:
    """
    Lightweight rolling price history for computing Roll measure and VPIN.
    """

    def __init__(self, window: int = 100):
        self.window = window
        self._prices: list[float] = []
        self._trades: list[dict] = []

    def add_price(self, price: float):
        self._prices.append(price)
        if len(self._prices) > self.window:
            self._prices.pop(0)

    def add_trade(self, price: float, size: float, side: str):
        self._trades.append({"price": price, "size": size, "side": side})
        if len(self._trades) > self.window * 2:
            self._trades.pop(0)

    @property
    def roll(self) -> float:
        return compute_roll_measure(self._prices)

    @property
    def vpin(self) -> float:
        return compute_vpin(self._trades)

    @property
    def has_data(self) -> bool:
        return len(self._prices) >= 5
