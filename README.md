# Polymarket Crypto Volatility Bot
### BTC / ETH / SOL Directional Position Bot

Automatically scans Polymarket for Bitcoin, Ethereum, and Solana price markets,
computes momentum-based probability estimates, and enters positions when the market
appears mispriced relative to live spot momentum.

---

## How It Works

```
CoinGecko (free)          Polymarket API
Live BTC/ETH/SOL   --->   Scan active BTC/ETH/SOL markets
spot prices               (15min up/down, price targets, hourly)
       |                           |
       v                           v
  Momentum Signal           Current YES price
  (short + medium term)     (what market thinks prob is)
       |                           |
       +-----------> EDGE <--------+
                  (our prob vs market price)
                        |
              EnsembleSignalGate (4/5 signals)
                        |
              VPIN Toxicity Check
                        |
                   Place Order
               BUY YES or BUY NO
```

**Market Types Traded:**
- `UPDOWN_SHORT` — "Will BTC be UP in 15 minutes?" (highest volume)
- `UPDOWN_LONG`  — "Will ETH be higher by end of day?"
- `PRICE_TARGET` — "Will SOL exceed $150 by March 31?"

---

## Quick Start

### 1. Install
```bash
git clone <your-repo>
cd polymarket-bot
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your wallet details
```

### 3. First-time Setup (generates API keys)
```bash
python main.py --setup
```
Follow the prompts to:
- Set up a Polygon wallet (MetaMask)
- Fund with USDC + MATIC
- Generate Polymarket CLOB API keys

### 4. Test with Paper Trading
```bash
python main.py --dry-run
```
Runs the full strategy with NO real money. Recommended for at least
a few hours before going live.

### 5. Scan Markets Without Trading
```bash
python main.py --scan
```
Shows current BTC/ETH/SOL opportunities ranked by score.

### 6. Go Live
```bash
python main.py --live
```
Requires confirmation. Real USDC will be used.

---

## Risk Settings (in .env)

| Setting | Default | Description |
|---|---|---|
| `MAX_POSITION_USDC` | 10 | Max $ per single position |
| `MAX_TOTAL_EXPOSURE_USDC` | 50 | Max $ deployed at once |
| `DAILY_LOSS_LIMIT_USDC` | 20 | Bot shuts down if you lose this |
| `ORDER_SIZE_USDC` | 5 | Base size per trade |
| `REFRESH_INTERVAL` | 60 | Seconds between cycles |
| `MIN_SPREAD_THRESHOLD` | 0.05 | Min spread to consider quoting |
| `MAX_ACTIVE_MARKETS` | 3 | Max simultaneous open positions |

**Start conservative.** Recommend $5 order size, $30 max exposure, $15 daily stop.

---

## Strategy Details

### Edge Detection
The bot compares its **momentum-based probability estimate** to the current
Polymarket YES price. If the gap exceeds the minimum edge threshold (6%), it
enters the position.

- Short momentum: last 3 price samples (~1 min)
- Medium momentum: last 10 price samples (~3-5 min)
- High volatility → probability compressed toward 50% (harder to call)

### Signal Gate (Research-Backed)
Before entering any trade, 4 of 5 signals must pass:
1. **Spread Width** — enough profit margin exists
2. **VPIN Toxicity** — informed traders not dominating flow
3. **Volume 24h** — market liquid enough (harder to manipulate)
4. **Roll Momentum** — market not in runaway momentum
5. **Price Boundary** — not near 0.0 or 1.0 (resolution boundary)

*Based on: Easley/O'Hara Cornell microstructure paper (2024) and
"How Manipulable Are Prediction Markets?" arXiv:2503.03312*

### Position Sizing by Confidence
| Confidence | Size Multiplier |
|---|---|
| HIGH (edge > 10%) | 100% of ORDER_SIZE_USDC |
| MEDIUM (6-10%) | 60% |
| LOW (<6%) | Skipped |

---

## Project Structure

```
polymarket-bot/
├── main.py              # Entry point — all CLI commands
├── config.py            # Settings loader from .env
├── requirements.txt
├── .env.example         # Copy to .env and fill in
├── bot/
│   ├── client.py        # Polymarket CLOB API wrapper
│   ├── scanner.py       # Finds/classifies BTC/ETH/SOL markets
│   ├── price_feed.py    # Live spot prices + momentum signals (CoinGecko)
│   ├── strategy.py      # Main trading logic + edge detection
│   ├── risk.py          # Position limits, daily loss stop, P&L tracking
│   ├── analytics.py     # VPIN, Roll measure, EnsembleSignalGate
│   └── display.py       # Terminal dashboard
└── bot.log              # Auto-generated trade log
```

---

## Important Notes

- **Polymarket runs on Polygon** — you need MATIC for gas fees (~$2-5/month)
- **15-minute markets have taker fees** (0.2–1.6%) — maker orders are free
- **Binary outcomes only** — YES pays $1, NO pays $1 at resolution
- **Markets expire** — positions are worthless if you're wrong at expiry
- **Not financial advice** — use responsibly, only risk what you can lose

---

## Academic Sources Used

1. Easley, O'Hara et al. — *Microstructure and Market Dynamics in Crypto Markets*
   Cornell/SSRN 2024 — https://ssrn.com/abstract=4814346
   → VPIN and Roll measure implementation

2. *How Manipulable Are Prediction Markets?* — arXiv:2503.03312 (2025)
   → Market quality scoring weights volume/trader count

3. Jabbar & Jalil — *ML Models for Algorithmic Bitcoin Trading*
   arXiv:2407.18334 (2024)
   → Ensemble/multi-signal gate design
