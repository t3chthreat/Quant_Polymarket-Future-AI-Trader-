"""
bot/client.py — Polymarket CLOB API wrapper
Handles authentication, market data, and order management.
"""
import time
import requests
from typing import Optional
import config

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        ApiCreds, OrderArgs, OrderType, Side, BookParams
    )
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False


class PolymarketClient:
    """Wraps the Polymarket CLOB client with helper methods."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.client: Optional[object] = None
        self._connected = False

    def connect(self) -> bool:
        """Initialize and authenticate the CLOB client."""
        if not CLOB_AVAILABLE:
            raise ImportError(
                "py-clob-client not installed.\n"
                "Run: pip install py-clob-client"
            )

        if not config.CREDENTIALS_SET:
            raise EnvironmentError(
                "API credentials not set. Run with --setup first."
            )

        try:
            creds = ApiCreds(
                api_key=config.CLOB_API_KEY,
                api_secret=config.CLOB_SECRET,
                api_passphrase=config.CLOB_PASSPHRASE,
            )
            self.client = ClobClient(
                host=config.CLOB_HOST,
                key=config.PRIVATE_KEY,
                chain_id=137,  # Polygon mainnet
                creds=creds,
            )
            self._connected = True
            return True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Polymarket: {e}")

    def generate_api_key(self) -> dict:
        """Generate a new CLOB API key from your wallet (used in --setup)."""
        if not CLOB_AVAILABLE:
            raise ImportError("py-clob-client not installed.")

        tmp_client = ClobClient(
            host=config.CLOB_HOST,
            key=config.PRIVATE_KEY,
            chain_id=137,
        )
        resp = tmp_client.create_or_derive_api_creds()
        return {
            "api_key": resp.api_key,
            "api_secret": resp.api_secret,
            "api_passphrase": resp.api_passphrase,
        }

    # ── Market Data ───────────────────────────────────────────

    def get_markets(self, limit: int = 50, active_only: bool = True) -> list:
        """Fetch available markets from the Gamma API."""
        params = {
            "limit": limit,
            "active": "true" if active_only else "false",
            "closed": "false",
            "archived": "false",
        }
        try:
            r = requests.get(
                f"{config.GAMMA_API}/markets",
                params=params,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise ConnectionError(f"Failed to fetch markets: {e}")

    def get_orderbook(self, token_id: str) -> dict:
        """Get live order book for a market token."""
        self._assert_connected()
        try:
            book = self.client.get_order_book(token_id)
            return {
                "bids": [(float(b.price), float(b.size)) for b in (book.bids or [])],
                "asks": [(float(a.price), float(a.size)) for a in (book.asks or [])],
            }
        except Exception as e:
            return {"bids": [], "asks": [], "error": str(e)}

    def get_spread(self, token_id: str) -> Optional[float]:
        """Return current bid-ask spread as a percentage."""
        book = self.get_orderbook(token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if not bids or not asks:
            return None
        best_bid = max(b[0] for b in bids)
        best_ask = min(a[0] for a in asks)
        if best_ask <= 0:
            return None
        return (best_ask - best_bid) / best_ask

    def get_mid_price(self, token_id: str) -> Optional[float]:
        """Return midpoint price between best bid and ask."""
        book = self.get_orderbook(token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if not bids or not asks:
            return None
        best_bid = max(b[0] for b in bids)
        best_ask = min(a[0] for a in asks)
        return (best_bid + best_ask) / 2

    # ── Order Management ──────────────────────────────────────

    def place_limit_order(
        self,
        token_id: str,
        side: str,       # "BUY" or "SELL"
        price: float,
        size_usdc: float,
    ) -> dict:
        """Place a limit order. Returns order ID or dry-run confirmation."""
        side_const = BUY if side == "BUY" else SELL
        size = round(size_usdc / price, 2) if price > 0 else 0

        if self.dry_run:
            return {
                "dry_run": True,
                "token_id": token_id,
                "side": side,
                "price": price,
                "size": size,
                "order_id": f"DRY-{int(time.time())}",
            }

        self._assert_connected()
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side_const,
            )
            resp = self.client.create_and_post_order(order_args)
            return {"order_id": resp.orderID, "status": resp.status}
        except Exception as e:
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by ID."""
        if self.dry_run:
            return True
        self._assert_connected()
        try:
            self.client.cancel(order_id)
            return True
        except Exception:
            return False

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if self.dry_run:
            return True
        self._assert_connected()
        try:
            self.client.cancel_all()
            return True
        except Exception:
            return False

    def get_open_orders(self) -> list:
        """Get all currently open orders."""
        if not self._connected:
            return []
        try:
            orders = self.client.get_orders()
            return orders or []
        except Exception:
            return []

    def get_balance(self) -> float:
        """Get USDC balance available for trading."""
        self._assert_connected()
        try:
            balance = self.client.get_balance()
            return float(balance)
        except Exception:
            return 0.0

    def _assert_connected(self):
        if not self._connected:
            raise RuntimeError("Client not connected. Call connect() first.")
