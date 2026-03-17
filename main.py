#!/usr/bin/env python3
"""
main.py — Polymarket Crypto Volatility Bot
Entry point with CLI arguments, setup wizard, and main trading loop.

Usage:
  python main.py --dry-run          # Paper trade (no real money)
  python main.py --live             # Live trading (requires .env)
  python main.py --setup            # Generate API keys from your wallet
  python main.py --scan             # Just scan markets, no trading
  python main.py --dry-run --fast   # Faster cycle for testing (15s)
"""
import sys
import time
import logging
import argparse

# ── Argument Parsing ──────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="Polymarket BTC/ETH/SOL Volatility Bot"
)
parser.add_argument("--dry-run",  action="store_true", help="Paper trade — no real money")
parser.add_argument("--live",     action="store_true", help="Enable live trading")
parser.add_argument("--setup",    action="store_true", help="Run API key setup wizard")
parser.add_argument("--scan",     action="store_true", help="Scan markets only, no orders")
parser.add_argument("--fast",     action="store_true", help="15s cycle instead of default")
parser.add_argument("--verbose",  action="store_true", help="Debug logging")
args = parser.parse_args()

# Require explicit mode
if not any([args.dry_run, args.live, args.setup, args.scan]):
    print("\n  Usage: python main.py --dry-run   (safe paper trading)")
    print("         python main.py --live      (real money, needs .env)")
    print("         python main.py --setup     (first-time API key setup)")
    print("         python main.py --scan      (scan markets only)\n")
    sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────────────

log_level = logging.DEBUG if args.verbose else logging.WARNING
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)]
    if args.verbose else [logging.FileHandler("bot.log")],
)

# ── Imports ───────────────────────────────────────────────────────────────────

try:
    import config
    from bot.client import PolymarketClient
    from bot.risk import RiskManager
    from bot.scanner import CryptoMarketScanner
    from bot.price_feed import PriceFeed
    from bot.strategy import CryptoVolatilityStrategy
    from bot.display import render_dashboard
except ImportError as e:
    print(f"\n[ERROR] Missing dependency: {e}")
    print("Run: pip install -r requirements.txt\n")
    sys.exit(1)


# ── Setup Wizard ──────────────────────────────────────────────────────────────

def run_setup():
    print("\n" + "=" * 60)
    print("  POLYMARKET BOT — FIRST TIME SETUP")
    print("=" * 60)
    print("""
  STEP 1 — Get a Polygon Wallet
  ─────────────────────────────
  • Install MetaMask: https://metamask.io
  • Switch to Polygon network (Chain ID: 137)
  • Fund with MATIC (for gas) + USDC (for trading)
    - Bridge USDC via: https://wallet.polygon.technology
    - Minimum recommended: $50 USDC + $5 MATIC

  STEP 2 — Enable Polymarket Trading
  ────────────────────────────────────
  • Go to https://polymarket.com and connect MetaMask
  • Complete KYC if required in your region
  • Deposit USDC into your Polymarket account

  STEP 3 — Set Your Private Key
  ──────────────────────────────
  • Copy your wallet private key from MetaMask:
    MetaMask > 3 dots > Account Details > Export Private Key
  • Add to .env file:
    PRIVATE_KEY=0xYOUR_KEY_HERE
    POLYGON_ADDRESS=0xYOUR_ADDRESS_HERE

  STEP 4 — Generate CLOB API Keys
  ────────────────────────────────
  Your private key must be set in .env before running this step.
""")

    pk = config.PRIVATE_KEY
    if not pk or pk == "0xYOUR_PRIVATE_KEY_HERE":
        print("  [!] PRIVATE_KEY not set in .env — skipping API key generation")
        print("  → Copy .env.example to .env and fill in your private key first\n")
        return

    print("  Generating API keys from your wallet...")
    try:
        client = PolymarketClient()
        keys = client.generate_api_key()
        print("\n  SUCCESS! Add these to your .env file:\n")
        print(f"  CLOB_API_KEY={keys['api_key']}")
        print(f"  CLOB_SECRET={keys['api_secret']}")
        print(f"  CLOB_PASSPHRASE={keys['api_passphrase']}")
        print("\n  STEP 5 — Configure Risk Settings in .env")
        print("  ──────────────────────────────────────────")
        print("  MAX_POSITION_USDC=10      # Max $ per position")
        print("  MAX_TOTAL_EXPOSURE_USDC=50 # Max total deployed")
        print("  DAILY_LOSS_LIMIT_USDC=20  # Bot stops if you lose this much")
        print("  ORDER_SIZE_USDC=5         # Size per trade")
        print("  REFRESH_INTERVAL=60       # Seconds between cycles\n")
        print("  Once .env is complete, run: python main.py --dry-run\n")
    except Exception as e:
        print(f"\n  [ERROR] Could not generate keys: {e}\n")


# ── Market Scan Only ──────────────────────────────────────────────────────────

def run_scan():
    print("\n  Scanning Polymarket for BTC / ETH / SOL markets...\n")
    scanner = CryptoMarketScanner()
    feed = PriceFeed()

    prices = feed.fetch()
    if prices:
        print(f"  Live prices — "
              f"BTC: ${prices.get('BTC', 0):,.0f}  "
              f"ETH: ${prices.get('ETH', 0):,.0f}  "
              f"SOL: ${prices.get('SOL', 0):,.2f}\n")

    opps = scanner.scan()
    if not opps:
        print("  No active BTC/ETH/SOL markets found. Polymarket API may be unavailable.\n")
        return

    print(f"  Found {len(opps)} tradeable markets:\n")
    from tabulate import tabulate
    rows = []
    for o in opps[:15]:
        rows.append([
            o["asset"],
            o["timeframe"],
            o["market_type"].replace("_", " "),
            f"{o['yes_price']:.3f}",
            f"${o['volume_24h']:,.0f}",
            f"{o['score']:.3f}",
            o["question"][:55],
        ])
    print(tabulate(rows,
        headers=["Asset", "TF", "Type", "YES", "Vol 24h", "Score", "Question"],
        tablefmt="grid"))
    print()


# ── Main Trading Loop ─────────────────────────────────────────────────────────

def run_bot(dry_run: bool):
    mode = "DRY RUN (paper trading)" if dry_run else "LIVE TRADING"
    print(f"\n  Starting Polymarket Crypto Bot — {mode}")

    if not dry_run and not config.CREDENTIALS_SET:
        print("\n  [ERROR] Live trading requires credentials in .env")
        print("  Run: python main.py --setup\n")
        sys.exit(1)

    # Initialize components
    client  = PolymarketClient(dry_run=dry_run)
    risk    = RiskManager()
    scanner = CryptoMarketScanner()
    feed    = PriceFeed()

    if not dry_run:
        print("  Connecting to Polymarket CLOB...")
        try:
            client.connect()
            balance = client.get_balance()
            print(f"  Connected. USDC Balance: ${balance:.2f}")
            if balance < 5:
                print("  [WARN] Low balance — bot needs at least $5 USDC to trade")
        except Exception as e:
            print(f"  [ERROR] Connection failed: {e}")
            print("  Run --setup to configure credentials\n")
            sys.exit(1)
    else:
        print("  Dry run mode — no real orders will be placed\n")

    strategy = CryptoVolatilityStrategy(
        client=client,
        risk=risk,
        scanner=scanner,
        feed=feed,
        dry_run=dry_run,
    )

    interval = 15 if args.fast else config.REFRESH_INTERVAL

    print(f"  Cycle interval: {interval}s  |  Press Ctrl+C to stop\n")
    print("  Warming up price feed (collecting initial data)...")

    # Warm up — collect a few price samples before trading
    for i in range(3):
        feed.fetch()
        time.sleep(3)

    print("  Ready. Starting main loop...\n")
    time.sleep(1)

    try:
        while True:
            # Run strategy cycle
            strategy.run_cycle()

            # Get feed summary for display
            feed_summary = feed.summary()

            # Render dashboard
            render_dashboard(
                risk=risk,
                strategy=strategy,
                feed_summary=feed_summary,
                dry_run=dry_run,
                refresh_interval=interval,
            )

            # Check halt condition
            halted, reason = risk.is_halted()
            if halted:
                print(f"\n  BOT HALTED: {reason}")
                print("  All positions should be manually reviewed.\n")
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n  Stopping bot...")
        if not dry_run:
            print("  Cancelling all open orders...")
            try:
                client.cancel_all_orders()
                print("  Orders cancelled.")
            except Exception:
                print("  [WARN] Could not auto-cancel orders — check Polymarket manually.")

        s = risk.summary()
        print(f"\n  Session Summary")
        print(f"  ───────────────")
        print(f"  Duration  : {s['session_duration']}")
        print(f"  Trades    : {s['total_trades']}")
        print(f"  Win Rate  : {s['win_rate']:.1f}%")
        print(f"  PnL       : ${s['daily_pnl']:+.4f}")
        print(f"  Exposure  : ${s['total_exposure']:.2f}")
        print("\n  Goodbye.\n")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if args.setup:
        run_setup()
    elif args.scan:
        run_scan()
    elif args.dry_run:
        run_bot(dry_run=True)
    elif args.live:
        print("\n  WARNING: Live trading mode uses real money.")
        confirm = input("  Type 'YES' to confirm: ").strip()
        if confirm == "YES":
            run_bot(dry_run=False)
        else:
            print("  Cancelled.\n")
