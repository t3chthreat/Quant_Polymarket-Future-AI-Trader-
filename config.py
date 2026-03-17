"""
config.py — Loads and validates all environment settings
"""
import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"\n[CONFIG ERROR] Missing required env var: {key}\n"
            f"  → Copy .env.example to .env and fill in your values.\n"
            f"  → Run:  cp .env.example .env"
        )
    return val

def _float(key: str, default: float) -> float:
    return float(os.getenv(key, default))

def _int(key: str, default: int) -> int:
    return int(os.getenv(key, default))

# ── Credentials ─────────────────────────────────────────────
PRIVATE_KEY         = os.getenv("PRIVATE_KEY", "")
CLOB_API_KEY        = os.getenv("CLOB_API_KEY", "")
CLOB_SECRET         = os.getenv("CLOB_SECRET", "")
CLOB_PASSPHRASE     = os.getenv("CLOB_PASSPHRASE", "")
POLYGON_ADDRESS     = os.getenv("POLYGON_ADDRESS", "")

# ── Risk Settings ────────────────────────────────────────────
MAX_POSITION_USDC       = _float("MAX_POSITION_USDC", 10.0)
MAX_TOTAL_EXPOSURE_USDC = _float("MAX_TOTAL_EXPOSURE_USDC", 50.0)
DAILY_LOSS_LIMIT_USDC   = _float("DAILY_LOSS_LIMIT_USDC", 20.0)
MIN_SPREAD_THRESHOLD    = _float("MIN_SPREAD_THRESHOLD", 0.05)
MAX_ACTIVE_MARKETS      = _int("MAX_ACTIVE_MARKETS", 3)
ORDER_SIZE_USDC         = _float("ORDER_SIZE_USDC", 5.0)
REFRESH_INTERVAL        = _int("REFRESH_INTERVAL", 30)

# ── API Endpoints ────────────────────────────────────────────
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

CREDENTIALS_SET = all([PRIVATE_KEY, CLOB_API_KEY, CLOB_SECRET, CLOB_PASSPHRASE])
