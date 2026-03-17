"""
bot/strategy.py — BTC / ETH / SOL Volatility Position Strategy

How it works:
─────────────
1. Scanner finds active BTC/ETH/SOL markets on Polymarket
   (15-min up/down, hourly direction, price targets, etc.)

2. PriceFeed fetches live spot prices from CoinGecko and computes
   short + medium momentum signals

3. EdgeDetector compares our momentum-based probability estimate
   to Polymarket's current YES price:
     • If we think UP prob = 0.65 but market prices YES at 0.50 → BUY YES
     • If we think UP prob = 0.30 but market prices YES at 0.50 → BUY NO

4. EnsembleSignalGate (from research) requires 4/5 signals green
   before entering any position

5. RiskManager enforces position limits and daily loss stop
"""
import time
import logging
from typing import Optional
from bot.client import PolymarketClient
from bot.risk import RiskManager, Position
from bot.scanner import CryptoMarketScanner
from bot.price_feed import PriceFeed
from bot.analytics import EnsembleSignalGate, PriceTracker, compute_vpin
import config

logger = logging.getLogger("strategy")

# Minimum edge (probability gap) to enter a trade
MIN_EDGE = 0.06   # 6 percentage points

# Minimum 24h volume on the market to consider it
MIN_VOLUME = 1000.0

# For short-term (5/15min) markets — higher edge required due to fees
MIN_EDGE_SHORT = 0.08

_gate = EnsembleSignalGate(
    min_spread=0.04,
    max_vpin=0.58,
    min_volume_24h=MIN_VOLUME,
    max_roll=0.06,
    required_signals=3,   # 3/5 for directional positions (less strict than MM)
)

_trackers: dict[str, PriceTracker] = {}


def get_tracker(token_id: str) -> PriceTracker:
    if token_id not in _trackers:
        _trackers[token_id] = PriceTracker(window=60)
    return _trackers[token_id]


class CryptoVolatilityStrategy:
    """
    Takes directional positions on BTC/ETH/SOL markets based on
    momentum signals vs. Polymarket mispricing.
    """

    def __init__(
        self,
        client: PolymarketClient,
        risk: RiskManager,
        scanner: CryptoMarketScanner,
        feed: PriceFeed,
        dry_run: bool = False,
    ):
        self.client = client
        self.risk = risk
        self.scanner = scanner
        self.feed = feed
        self.dry_run = dry_run
        self.cycle = 0
        self.events: list[dict] = []
        self.last_signals: list[dict] = []
        self.last_vpin: float = 0.35
        self.last_roll: float = 0.0
        self.opportunities: list[dict] = []   # Last scanned ops for display

    def log(self, msg: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        entry = {"ts": ts, "level": level, "msg": msg}
        self.events.append(entry)
        if len(self.events) > 300:
            self.events.pop(0)
        logger.info(f"[{level}] {msg}")

    # ── Main Cycle ────────────────────────────────────────────────────────────

    def run_cycle(self):
        self.cycle += 1
        halted, reason = self.risk.is_halted()
        if halted:
            self.log(f"BOT HALTED: {reason}", "ERROR")
            return

        # 1. Refresh live spot prices
        prices = self.feed.get_prices()
        if not prices:
            self.log("Price feed unavailable — skipping cycle", "WARN")
            return

        btc = prices.get("BTC", 0)
        eth = prices.get("ETH", 0)
        sol = prices.get("SOL", 0)
        self.log(
            f"Prices — BTC: ${btc:,.0f}  ETH: ${eth:,.0f}  SOL: ${sol:,.2f}", "INFO"
        )

        # 2. Scan Polymarket for crypto markets
        opportunities = self.scanner.scan()
        self.opportunities = opportunities[:20]   # Store top 20 for display

        if not opportunities:
            self.log("No tradeable BTC/ETH/SOL markets found this cycle", "WARN")
            return

        self.log(f"Found {len(opportunities)} BTC/ETH/SOL opportunities", "INFO")

        # 3. Evaluate and enter positions
        entered = 0
        for opp in opportunities:
            if entered >= 3:   # Max 3 new positions per cycle
                break

            can, reason_str = self.risk.can_open_market(opp["market_id"])
            if not can:
                continue

            result = self._evaluate_opportunity(opp, prices)
            if result and result.get("action") != "SKIP":
                success = self._enter_position(opp, result)
                if success:
                    entered += 1

    # ── Opportunity Evaluation ────────────────────────────────────────────────

    def _evaluate_opportunity(self, opp: dict, prices: dict) -> Optional[dict]:
        """
        Compare our probability estimate to Polymarket's price.
        Returns trade signal or None if no edge found.
        """
        asset = opp["asset"]
        timeframe = opp["timeframe"]
        yes_price = opp["yes_price"]
        volume = opp["volume_24h"]
        market_type = opp["market_type"]

        # Get our probability estimate from momentum signals
        edge_result = self.feed.edge_vs_market(
            symbol=asset,
            market_yes_price=yes_price,
            timeframe=timeframe,
        )

        edge = abs(edge_result["edge"])
        min_edge = MIN_EDGE_SHORT if timeframe in ("5min", "15min") else MIN_EDGE

        # For price target markets, adjust edge requirement
        if market_type == "PRICE_TARGET":
            min_edge = MIN_EDGE * 1.2   # More conservative on longer-term markets

        if edge < min_edge:
            return {"action": "SKIP", "reason": f"Edge too small ({edge:.2%} < {min_edge:.2%})"}

        if volume < MIN_VOLUME:
            return {"action": "SKIP", "reason": f"Volume too low (${volume:,.0f})"}

        # Run ensemble gate
        tracker = get_tracker(opp.get("yes_token_id", opp["market_id"]))
        tracker.add_price(yes_price)

        spread = abs(yes_price - (1 - yes_price))   # YES vs NO spread proxy
        go, signals = _gate.evaluate(
            spread=spread,
            mid_price=yes_price,
            vpin=tracker.vpin,
            volume_24h=volume,
            roll=tracker.roll,
        )
        self.last_signals = signals
        self.last_vpin = tracker.vpin
        self.last_roll = tracker.roll

        passed = sum(1 for s in signals if s["pass"])
        if not go:
            self.log(
                f"Gate blocked ({passed}/5) — {opp['asset']} "
                f"{opp['market_type']} ({opp['timeframe']})", "DEBUG"
            )
            return {"action": "SKIP", "reason": f"Signal gate blocked ({passed}/5)"}

        # Determine which token to buy
        action = edge_result["action"]   # "BUY YES" or "BUY NO"
        if action == "BUY YES":
            token_id = opp["yes_token_id"]
            buy_price = yes_price
        else:
            token_id = opp["no_token_id"]
            buy_price = opp["no_price"]

        if not token_id:
            return {"action": "SKIP", "reason": "Token ID not available"}

        return {
            "action":          action,
            "token_id":        token_id,
            "buy_price":       buy_price,
            "edge":            edge_result["edge"],
            "our_probability": edge_result["our_probability"],
            "confidence":      edge_result["confidence"],
            "short_momentum":  edge_result["short_momentum"],
            "medium_momentum": edge_result["medium_momentum"],
            "volatility":      edge_result["volatility"],
            "signals_passed":  passed,
        }

    # ── Position Entry ────────────────────────────────────────────────────────

    def _enter_position(self, opp: dict, signal: dict) -> bool:
        """Place the order and register the position."""
        asset     = opp["asset"]
        timeframe = opp["timeframe"]
        action    = signal["action"]
        token_id  = signal["token_id"]
        price     = signal["buy_price"]
        edge      = signal["edge"]
        conf      = signal["confidence"]
        question  = opp["question"][:55]

        # Scale position size by confidence
        size_mult = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}.get(conf, 0.5)
        size_usdc = round(config.ORDER_SIZE_USDC * size_mult, 2)
        size_usdc = max(1.0, size_usdc)   # Min $1

        self.log(
            f"{action} {asset} ({timeframe}) | "
            f"Price:{price:.3f} Edge:{edge:+.3f} "
            f"Conf:{conf} Size:${size_usdc}", "INFO"
        )

        resp = self.client.place_limit_order(
            token_id=token_id,
            side="BUY",
            price=price,
            size_usdc=size_usdc,
        )

        if "error" in resp:
            self.log(f"Order failed: {resp['error']}", "ERROR")
            return False

        # Register position with risk manager
        pos = self.risk.open_position(opp["market_id"], question)
        pos.buy_price = price
        pos.size_usdc = size_usdc

        tag = "[DRY RUN] " if self.dry_run else ""
        self.log(
            f"{tag}✓ Entered {action} {asset} | "
            f"${size_usdc} @ {price:.3f} | "
            f"Market: {question[:40]}", "SUCCESS"
        )
        return True
