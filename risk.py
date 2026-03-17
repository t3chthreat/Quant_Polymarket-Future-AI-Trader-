"""
bot/risk.py — Risk Manager
Tracks P&L, exposure limits, and enforces daily loss stops.
"""
import time
from dataclasses import dataclass, field
from typing import Dict
import config


@dataclass
class Position:
    token_id: str
    market_name: str
    buy_order_id: str = ""
    sell_order_id: str = ""
    buy_price: float = 0.0
    sell_price: float = 0.0
    size_usdc: float = 0.0
    realized_pnl: float = 0.0
    created_at: float = field(default_factory=time.time)


class RiskManager:
    """
    Enforces risk rules:
    - Max per-market position size
    - Max total exposure across all markets
    - Daily loss limit (bot shuts down if breached)
    - Spread quality filter
    """

    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.daily_pnl: float = 0.0
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.session_start: float = time.time()
        self._halted: bool = False
        self._halt_reason: str = ""

    # ── Guard Checks ──────────────────────────────────────────

    def is_halted(self) -> tuple[bool, str]:
        return self._halted, self._halt_reason

    def check_daily_loss(self) -> bool:
        """Returns True if we're still safe to trade."""
        if self.daily_pnl <= -abs(config.DAILY_LOSS_LIMIT_USDC):
            self._halt("Daily loss limit hit: "
                       f"${self.daily_pnl:.2f} / -${config.DAILY_LOSS_LIMIT_USDC:.2f}")
            return False
        return True

    def can_open_market(self, token_id: str) -> tuple[bool, str]:
        """Check if we're allowed to make markets on this token."""
        if self._halted:
            return False, f"Bot halted: {self._halt_reason}"

        if len(self.positions) >= config.MAX_ACTIVE_MARKETS:
            if token_id not in self.positions:
                return False, f"Max active markets reached ({config.MAX_ACTIVE_MARKETS})"

        if self.total_exposure() + config.ORDER_SIZE_USDC * 2 > config.MAX_TOTAL_EXPOSURE_USDC:
            return False, f"Total exposure limit: ${config.MAX_TOTAL_EXPOSURE_USDC:.2f}"

        return True, "ok"

    def spread_is_tradeable(self, spread: float) -> bool:
        """Is the spread wide enough to profitably market-make?"""
        return spread is not None and spread >= config.MIN_SPREAD_THRESHOLD

    # ── Position Tracking ─────────────────────────────────────

    def open_position(self, token_id: str, market_name: str) -> Position:
        pos = Position(
            token_id=token_id,
            market_name=market_name,
            size_usdc=config.ORDER_SIZE_USDC,
        )
        self.positions[token_id] = pos
        return pos

    def update_orders(self, token_id: str, buy_id: str, sell_id: str,
                      buy_price: float, sell_price: float):
        if token_id in self.positions:
            p = self.positions[token_id]
            p.buy_order_id = buy_id
            p.sell_order_id = sell_id
            p.buy_price = buy_price
            p.sell_price = sell_price

    def record_fill(self, token_id: str, filled_side: str, fill_price: float, size: float):
        """Record a fill and calculate realized P&L when both sides fill."""
        if token_id not in self.positions:
            return
        pos = self.positions[token_id]
        self.total_trades += 1

        if filled_side == "SELL" and pos.buy_price > 0:
            pnl = (fill_price - pos.buy_price) * size
            pos.realized_pnl += pnl
            self.daily_pnl += pnl
            if pnl > 0:
                self.winning_trades += 1

        self.check_daily_loss()

    def close_position(self, token_id: str):
        if token_id in self.positions:
            del self.positions[token_id]

    # ── Stats ─────────────────────────────────────────────────

    def total_exposure(self) -> float:
        return sum(p.size_usdc * 2 for p in self.positions.values())

    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100

    def session_duration(self) -> str:
        elapsed = int(time.time() - self.session_start)
        h, m = divmod(elapsed // 60, 60)
        s = elapsed % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def summary(self) -> dict:
        return {
            "daily_pnl": self.daily_pnl,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate(),
            "active_markets": len(self.positions),
            "total_exposure": self.total_exposure(),
            "session_duration": self.session_duration(),
            "halted": self._halted,
        }

    def _halt(self, reason: str):
        self._halted = True
        self._halt_reason = reason
